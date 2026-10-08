# Agent Workflow (deterministic state machine)

The workflow is **data** (`agent/orchestrator/transitions.py`/YAML) executed by a small engine. State functions are idempotent and resumable. LLM calls happen only in `UNDERSTAND_INTENT` and `GENERATE_PLAN`.

## States
| State | Does | LLM? | Audit event |
|---|---|---|---|
| RECEIVE_REQUEST | Authenticate requester, create `request_id`, build `PolicyActor` from Knowledge identity | no | REQUEST_RECEIVED |
| UNDERSTAND_INTENT | Classify intent + extract entities (structured) | **yes** | INTENT_CLASSIFIED |
| DISCOVER_IAM_OBJECTS | Resolve people, systems, entitlements via Knowledge search | no | IAM_OBJECTS_DISCOVERED |
| LOAD_CURRENT_KNOWLEDGE | Pin `knowledge_version`; load details, `check_entitlement_usable`, dependencies, conflicts, schemas; derive attributes | no | KNOWLEDGE_RETRIEVED |
| LOAD_RELEVANT_MEMORY | `memory_search` (degrades gracefully) | no | MEMORY_RETRIEVED |
| EVALUATE_POLICY | Policy MCP `evaluate_policy` | no | POLICY_EVALUATED |
| GENERATE_PLAN | Draft plan as structured JSON using only resolved ids | **yes** | PLAN_GENERATED |
| VALIDATE_PLAN | Checks V1–V14 (`docs/provisioning.md`) incl. dry-run and `evaluate_plan` | no | PLAN_VALIDATED |
| WAIT_FOR_APPROVAL | Create approval, notify, persist and stop; resume on decision | no | APPROVAL_REQUESTED / APPROVAL_DECIDED |
| EXECUTE | Mint grants, run actions in order, retry, compensate | no | EXECUTION_STARTED, ACTION_EXECUTED, PROVISIONING_FAILED, COMPENSATION_STARTED |
| VERIFY_STATE | Read back actual state, compare with desired | no | STATE_VERIFIED |
| UPDATE_KNOWLEDGE | Propose + apply FACT_REGISTRATION changes with verification evidence | no | KNOWLEDGE_UPDATED |
| WRITE_AUDIT | Final audit, learning hand-off, notification | no | MEMORY_UPDATED (async), REQUEST_COMPLETED |
| DONE | Terminal success | | |
Side states: **WAITING_FOR_CLARIFICATION**. Terminals: **REFUSED, FAILED, EXPIRED, CANCELLED**. Every terminal passes through WRITE_AUDIT exactly once (the terminal is stored as `pending_terminal`, WRITE_AUDIT then moves to it).

## Transitions
| From | On | To |
|---|---|---|
| RECEIVE_REQUEST | ok | UNDERSTAND_INTENT |
| UNDERSTAND_INTENT | intent supported, confidence ≥ threshold | DISCOVER_IAM_OBJECTS |
| UNDERSTAND_INTENT | low confidence | WAITING_FOR_CLARIFICATION |
| UNDERSTAND_INTENT | unsupported / injection detected | REFUSED |
| DISCOVER_IAM_OBJECTS | every object `EXACT` | LOAD_CURRENT_KNOWLEDGE |
| DISCOVER_IAM_OBJECTS | any `AMBIGUOUS` | WAITING_FOR_CLARIFICATION |
| DISCOVER_IAM_OBJECTS | any `NONE` | REFUSED (with suggestions) |
| WAITING_FOR_CLARIFICATION | answer (max 3 rounds) | DISCOVER_IAM_OBJECTS |
| WAITING_FOR_CLARIFICATION | timeout / user cancel | EXPIRED / CANCELLED |
| LOAD_CURRENT_KNOWLEDGE | all USABLE, deps resolvable, no HARD conflict | LOAD_RELEVANT_MEMORY |
| LOAD_CURRENT_KNOWLEDGE | any non-USABLE (assign), unresolvable dep, HARD conflict | REFUSED (reasons + replacement; UI offers "request replacement instead" as a **new** request with `parent_request_id`) |
| LOAD_RELEVANT_MEMORY | ok or degraded | EVALUATE_POLICY |
| EVALUATE_POLICY | ALLOW or APPROVAL_REQUIRED | GENERATE_PLAN |
| EVALUATE_POLICY | DENY | REFUSED |
| GENERATE_PLAN | valid structured plan | VALIDATE_PLAN |
| GENERATE_PLAN | invalid after one repair | FAILED |
| VALIDATE_PLAN | valid, approval required | WAIT_FOR_APPROVAL |
| VALIDATE_PLAN | valid, no human approval needed | EXECUTE (policy-auto approval created first) |
| VALIDATE_PLAN | invalid and fixable (max 2 re-plans, validator feedback to LLM) | GENERATE_PLAN |
| VALIDATE_PLAN | policy DENY on plan, or still invalid | REFUSED / FAILED |
| WAIT_FOR_APPROVAL | APPROVED and plan not stale | EXECUTE |
| WAIT_FOR_APPROVAL | APPROVED but stale (knowledge head moved and verdicts changed) | EVALUATE_POLICY (new pin, new plan hash, new approval) |
| WAIT_FOR_APPROVAL | REJECTED / EXPIRED / cancelled | REFUSED / EXPIRED / CANCELLED |
| EXECUTE | all actions success | VERIFY_STATE |
| EXECUTE | failed or blocked action | compensate completed actions, then FAILED |
| VERIFY_STATE | VERIFIED | UPDATE_KNOWLEDGE |
| VERIFY_STATE | DRIFT or UNKNOWN | FAILED (`VERIFICATION_DRIFT`/`UNVERIFIED`), incident-recovery skill suggests next step |
| UPDATE_KNOWLEDGE | applied, or failed | WRITE_AUDIT (failure ⇒ result carries `warnings=["KNOWLEDGE_SYNC_PENDING"]`; reconciliation will register it) |

```mermaid
stateDiagram-v2
  [*] --> RECEIVE_REQUEST --> UNDERSTAND_INTENT --> DISCOVER_IAM_OBJECTS --> LOAD_CURRENT_KNOWLEDGE
  LOAD_CURRENT_KNOWLEDGE --> LOAD_RELEVANT_MEMORY --> EVALUATE_POLICY --> GENERATE_PLAN --> VALIDATE_PLAN
  VALIDATE_PLAN --> GENERATE_PLAN: re-plan (max 2)
  VALIDATE_PLAN --> WAIT_FOR_APPROVAL
  VALIDATE_PLAN --> EXECUTE
  WAIT_FOR_APPROVAL --> EXECUTE
  WAIT_FOR_APPROVAL --> EVALUATE_POLICY: stale
  EXECUTE --> VERIFY_STATE --> UPDATE_KNOWLEDGE --> WRITE_AUDIT
  DISCOVER_IAM_OBJECTS --> WAITING_FOR_CLARIFICATION
  WAITING_FOR_CLARIFICATION --> DISCOVER_IAM_OBJECTS
  WRITE_AUDIT --> DONE
  WRITE_AUDIT --> REFUSED
  WRITE_AUDIT --> FAILED
  WRITE_AUDIT --> EXPIRED
  WRITE_AUDIT --> CANCELLED
```
(Any state may jump to WRITE_AUDIT with a `pending_terminal`.)

## Invariants (each has a test)
1. EXECUTE is reachable only from VALIDATE_PLAN (valid) or WAIT_FOR_APPROVAL (APPROVED, not stale).
2. EXECUTE needs a grant for every write action. No grant ⇒ no call.
3. UPDATE_KNOWLEDGE runs only after VERIFIED.
4. Every terminal passes WRITE_AUDIT once. If Audit MCP is unavailable **before** EXECUTE ⇒ FAILED, no writes. After EXECUTE, audit events are buffered locally and flushed with retry.
5. LLM calls only in the two states above. The user-facing message is rendered from structured results by templates.
6. At most 2 re-plans and 3 clarification rounds.
7. `knowledge_version` is pinned at LOAD_CURRENT_KNOWLEDGE and passed on every later read.
8. Resume is safe: each state function is idempotent; `workflow_runs` stores `state`, `pending_terminal`, `pin`, `plan_id`, `plan_hash`, `approval_id`, `attempt`, `checkpoint_json`, timestamps.

## Degradation
Memory down → continue (`degraded=true`). Notification down → warn. Provider down for an action → `RETRYABLE` rules; capability marked unavailable ⇒ `CAPABILITY_UNAVAILABLE` (REFUSED before planning when known). Knowledge or Policy down → FAILED (never guess).
