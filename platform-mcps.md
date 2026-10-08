# Platform MCP Contracts — Policy · Memory · Approval · Audit · Notification

Read `00-conventions.md` first. Policy documents and `Condition`, `PolicyVersion`, `ApproverSpec`, `Obligation`, `TemporalSelector` are defined in `knowledge-mcp.md §3`.
Notation as in the other contract docs: every input also has `context: ToolContext`; `*` = required.

| Server | `kind` | Port | Package | Calls (as MCP client) |
|---|---|---|---|---|
| `policy` | POLICY | 8103 | `policy_server` | Knowledge: `list_policies`, `get_policy`, `get_entitlement` |
| `memory` | MEMORY | 8102 | `memory_server` | none |
| `approval` | APPROVAL | 8121 | `approval_server` | Policy: `explain_decision`. Audit: `get_event` (evidence check) |
| `audit` | AUDIT | 8122 | `audit_server` | none |
| `notification` | NOTIFICATION | 8123 | `notification_server` | none |

Governance exceptions to conventions C5 (grants): only **provisioners** and `knowledge.apply_knowledge_change` need an execution grant. Platform writes (`append_event`, `memory_*`, `create_approval_request`, `send_notification`, …) are deterministic-service calls identified by `context.actor="system:*"`/`agent:*`; the LLM can never reach them (`llm_exposed=false`).

---

## 1. Policy MCP

Pure, deterministic decision engine. No LLM, no side effects on IAM state. Reads policy documents from Knowledge at the request's selector and caches them by `knowledge_version`.

### 1.1 Evaluation semantics
1. **Select** policy versions resolved at `(as_of, pinned knowledge_version)` whose `scope` matches (axes AND-ed, empty list = no restriction).
2. **Evaluate** every rule of every in-scope policy (per entitlement when several are requested).
3. Any matching `DENY` ⇒ `DENY` (collect all DENY reasons). No DENY and ≥ 1 matching `ALLOW` ⇒ ALLOW candidate. No matching ALLOW ⇒ `DENY` with reason `DEFAULT_DENY`. (**Deny-overrides, default-deny.**)
4. ALLOW candidate + ≥ 1 matching `approval_rule` ⇒ `APPROVAL_REQUIRED`. One `ApprovalRequirement` per matching rule (identical approver sets de-duplicated; strictest SLA). `auto_approve` is true only if **all** matching approval rules set it.
5. Obligations are collected from the matching ALLOW policies.
6. **Three-valued conditions.** A missing input ⇒ `UNKNOWN`. Fail closed: UNKNOWN in a DENY rule counts as a match (reason `INPUT_MISSING:<ref>`); in an ALLOW rule as no match; in an approval rule as a match.
7. Decision = pure function of `(input, policy set)`. `decision_id = "PD-" + sha256(inputs_hash + policy_set_version)[:16]`.
8. Aggregate across entitlements: most restrictive wins (`DENY` > `APPROVAL_REQUIRED` > `ALLOW`); per-entitlement results stay in `items`.

### 1.2 Models
```python
PolicyOperation = Literal["CREATE_ACCOUNT","UPDATE_ACCOUNT","DISABLE_ACCOUNT","ASSIGN_ENTITLEMENT","REMOVE_ENTITLEMENT",
                          "CREATE_ENTITLEMENT","CHANGE_ENTITLEMENT_STATUS","PUBLISH_POLICY"]
Decision = Literal["ALLOW","DENY","APPROVAL_REQUIRED"]

class PolicyActor(BaseModel):
    identity_id: str; department: str | None = None; title: str | None = None; manager_id: str | None = None
    employment_status: str | None = None; roles: list[str] = []; attributes: dict[str, AttrValue] = {}

class PolicyEvaluationInput(ReadInput):
    operation: PolicyOperation; requester: PolicyActor; subject: PolicyActor | None = None
    system_id: str | None = None; entitlement_ids: list[str] = []; held_entitlement_ids: list[str] = []
    justification: str | None = None; attributes: dict[str, AttrValue] = {}     # extra request.* inputs
    evaluated_at: datetime | None = None; selector: TemporalSelector | None = None

class ApprovalRequirement(BaseModel):
    rule_id: str; policy_id: str; policy_version: int
    approvers: list[ApproverSpec]; mode: Literal["ANY_ONE","ALL","SEQUENTIAL"]; sla_hours: int; auto_approve: bool

class ReasonItem(BaseModel): code: str; message: str; policy_id: str | None = None; policy_version: int | None = None; rule_id: str | None = None
class PolicyRef(BaseModel): policy_id: str; version: int
class RuleTraceEntry(BaseModel):
    policy_id: str; policy_version: int; rule_id: str; kind: Literal["RULE","APPROVAL_RULE"]
    effect: Literal["ALLOW","DENY","APPROVAL"]; result: Literal["MATCH","NO_MATCH","UNKNOWN"]; detail: str

class EntitlementDecision(BaseModel):
    entitlement_id: str; decision: Decision; reason_codes: list[str]
    approvals: list[ApprovalRequirement] = []; obligations: list[Obligation] = []

class PolicyDecision(BaseModel):
    decision_id: str; decision: Decision; reasons: list[ReasonItem]
    approvals: list[ApprovalRequirement]; obligations: list[Obligation]; items: list[EntitlementDecision]
    matched_policies: list[PolicyRef]; policy_set_version: str       # "PS-" + hash of the exact policy versions used
    knowledge_version: int; evaluated_at: datetime
    rule_trace: list[RuleTraceEntry]; inputs_hash: str; plan_hash: str | None = None

class PolicyPlanAction(BaseModel):
    action_id: str; operation: PolicyOperation; system_id: str; entitlement_ids: list[str] = []
    destructive: bool = False; tool_risk: RiskLevel = "LOW"
class EvaluatePlanInput(ReadInput):
    plan_id: str; plan_hash: str; requester: PolicyActor; subject: PolicyActor | None = None
    justification: str | None = None; actions: list[PolicyPlanAction]
    held_entitlement_ids: list[str] = []; selector: TemporalSelector | None = None
class ActionDecision(BaseModel): action_id: str; decision: Decision; reason_codes: list[str]
class PlanPolicyDecision(PolicyDecision): plan_id: str; per_action: list[ActionDecision]
```

### 1.3 Tools
| Tool | In → Out | Notes |
|---|---|---|
| `evaluate_policy` | `PolicyEvaluationInput` → `PolicyDecision` | Request-level check (state EVALUATE_POLICY). |
| `evaluate_plan` | `EvaluatePlanInput` → `PlanPolicyDecision` | Re-checks the **final** plan (after dependency expansion and removals). Every `destructive`/`REMOVE_ENTITLEMENT` action needs an explicit matching ALLOW. `plan_hash` is stored in the decision so Approval can bind to it. |
| `explain_decision` | `decision_id*` → `DecisionExplanation{decision, summary, policies: list[PolicySummary], rule_trace}` | `summary` is a deterministic template. Reads the decision log. |
| `get_policy_set_version` | `selector?` → `{policy_set_version, policies: list[PolicyRef], knowledge_version}` | |
| `simulate_policy_change` ★ | `draft*: PolicyDraft`, `samples*: list[PolicyEvaluationInput]` → `list[{input_hash, before: Decision, after: Decision, changed: bool, reasons_after}]` | Impact preview for the "policy change" scenario. Evaluates against the draft layered on the current set. Not persisted. |

Governance: all `read_only=true`, LOW, idempotent, `llm_exposed=true`. `evaluate_*` append the decision to an idempotent decision log (same `decision_id` ⇒ one row); this mutates no IAM state.

---

## 2. Memory MCP

**Non-authoritative** operational memory: preferences, past decisions, observed quirks. Memory can *suggest*, never *decide*. It never influences policy, approval or plan validity. Knowledge wins every conflict.

### 2.1 Models
```python
MemoryType = Literal["EPISODIC","SEMANTIC","PREFERENCE","DECISION","EXPERIENCE","OBSERVATION"]
class MemoryRef(BaseModel): kind: Literal["SYSTEM","ENTITLEMENT","POLICY","IDENTITY","SKILL","REQUEST"]; id: str
class KnowledgeConflictFlag(BaseModel): knowledge_ref: str; detail: str; detected_at: datetime; knowledge_version: int

class MemoryRecord(BaseModel):
    memory_id: str; type: MemoryType; title: str; content: str              # content ≤ 1000 chars, no secrets
    subject_refs: list[MemoryRef] = []; tags: list[str] = []
    confidence: float; reinforcement_count: int                              # confidence 0..1
    source: Literal["AGENT_LEARNING","HUMAN","IMPORT"]; source_request_id: str | None = None
    status: Literal["ACTIVE","SUPERSEDED","FORGOTTEN"]; superseded_by: str | None = None
    authoritative: Literal[False] = False                                    # constant
    knowledge_version_at_write: int | None = None
    conflicts_with_knowledge: KnowledgeConflictFlag | None = None
    created_at: datetime; last_reinforced_at: datetime | None = None; last_used_at: datetime | None = None
    expires_at: datetime | None = None

class ScoreParts(BaseModel): lexical: float; semantic: float | None = None; recency: float; reinforcement: float; confidence: float; subject_boost: float
class ScoredMemory(BaseModel): record: MemoryRecord; score: float; parts: ScoreParts
class MemorySearchResult(BaseModel): items: list[ScoredMemory]; total: int; excluded_conflicted: int
```

### 2.2 Tools
| Tool | In → Out | Behavior |
|---|---|---|
| `memory_search` | `query*`, `types?`, `subject_refs?`, `tags?`, `min_confidence=0.3`, `include_conflicted=false`, `limit=5` → `MemorySearchResult` | **Hybrid ranking:** lexical BM25 + optional embedding (`semantic`, off in POC) + recency (half-life 90 d) + `log(1+reinforcement)` + confidence + exact `subject_refs` boost. Excludes `SUPERSEDED`, `FORGOTTEN`, expired, and (default) conflicted records. Marks `last_used_at`. |
| `memory_get` | `memory_id*` → `ReadResult[MemoryRecord]` | |
| `memory_list` | `status?`, `type?`, `subject_ref?`, `limit=50`, `page_token?` → `Page[MemoryRecord]` | |
| `memory_write` | `type*`, `title*`, `content*`, `subject_refs=[]`, `tags=[]`, `confidence=0.5`, `source*`, `source_request_id?`, `expires_at?`, `knowledge_version?` → `{record, outcome: CREATED/MERGED_DUPLICATE, duplicate_of?}` | **Dedupe:** same `(type, subject_refs, normalized content hash)` or similarity ≥ 0.9 ⇒ reinforce the existing record, return `MERGED_DUPLICATE`. Rejects secrets/credential patterns and content > 1000 chars (`VALIDATION_ERROR`). |
| `memory_reinforce` | `memory_id*`, `request_id*`, `outcome*` (`HELPFUL`/`NEUTRAL`/`UNHELPFUL`) → `MemoryRecord` | HELPFUL: count+1, `confidence += 0.1·(1−c)`. UNHELPFUL: `confidence −= 0.2·c`. |
| `memory_supersede` | `old_memory_id*`, `new*: MemoryWrite` → `{old, new}` | Old → `SUPERSEDED`, `superseded_by` set. Never edits in place. |
| `memory_flag_conflict` | `memory_id*`, `knowledge_ref*`, `detail*`, `knowledge_version*` → `MemoryRecord` | Sets `conflicts_with_knowledge`. Flagged records leave planning context. |
| `memory_forget` | `memory_id*`, `reason*`, `hard=false` → `{memory_id, status}` | Soft: `FORGOTTEN` and excluded. `hard=true` (physical delete of content) only when `actor` starts with `user:`. |

Governance: `memory_search`, `memory_get`, `memory_list` = read-only, LOW, `llm_exposed=true`. All writes = LOW, idempotent, **`llm_exposed=false`**: the LLM may read memory but only the deterministic learning pipeline (`agent/memory/learner.py`, post-run, async) writes it.

### 2.3 Rules
* The agent wraps every retrieved memory as untrusted data (`<memory authoritative="false" id=…>`), and the plan validator ignores memory entirely.
* **Conflict check:** before writing, and when retrieving memories about entitlements/policies, the pipeline compares them with Knowledge at the pinned version. Conflict ⇒ `memory_flag_conflict` and the record is not used.
* **Failure:** Memory MCP down ⇒ state LOAD_RELEVANT_MEMORY returns an empty context with `degraded=true`, audit a note, continue. Never block a request on memory.
* What to learn (examples): successful resolution patterns ("`FinanceReader` requests usually also need X"), approver response patterns, recurring clarification outcomes. Never learn credentials, personal data beyond ids, or "facts" that Knowledge owns.

---

## 3. Approval MCP

Owns approval requests, decisions, and the **execution grants** that gate every write. Approvals are bound to a `subject_hash` (`plan_hash` for plans, `change_hash` for Knowledge proposals): a re-planned (changed) plan can never reuse an old approval.

### 3.1 Models
```python
ApprovalStatus = Literal["PENDING","APPROVED","REJECTED","EXPIRED","CANCELLED"]
ApprovalSubject = Literal["PROVISIONING_PLAN","KNOWLEDGE_PROPOSAL"]

class ApprovalDecisionRecord(BaseModel):
    approver_id: str; decision: Literal["APPROVE","REJECT"]; comment: str | None = None
    decided_at: datetime; requirement_rule_id: str | None = None

class ApprovalRequest(BaseModel):
    approval_id: str; subject_type: ApprovalSubject; subject_id: str; subject_hash: str
    request_id: str; requester_id: str; summary: str; risk_level: RiskLevel
    requirements: list[ApprovalRequirement]; resolved_approvers: dict[str, list[str]]     # rule_id → identity_ids
    decisions: list[ApprovalDecisionRecord]; status: ApprovalStatus
    policy_decision_id: str; auto_approved: bool = False; supersedes_approval_id: str | None = None
    created_at: datetime; sla_due_at: datetime; expires_at: datetime; resolved_at: datetime | None = None

class GrantActionSpec(BaseModel):
    action_id: str; server: str; tool: str; args_hash: str
    requires_approval: bool                          # the tool's governance floor, from the capability registry

class ExecutionGrant(BaseModel): action_id: str; grant_id: str; token: str; expires_at: datetime
class GrantVerification(BaseModel): valid: bool; reason: str | None = None; claims: dict[str, Any] | None = None
```

### 3.2 Tools
| Tool | In → Out | Behavior / errors |
|---|---|---|
| `create_approval_request` | `subject_type*`, `subject_id*`, `subject_hash*`, `request_id*`, `requester_id*`, `summary*`, `risk_level*`, `requirements*: list[ApprovalRequirement]`, `policy_decision_id*`, `evidence=[]: list[EvidenceRef]`, `ttl_hours=72` → `ApprovalRequest` | Resolves approvers (`MANAGER`, `ENTITLEMENT_OWNER`, … via Knowledge identities). **Auto path:** if `requirements` is empty and `explain_decision(policy_decision_id)` is `ALLOW` bound to this `subject_hash`, or all requirements have `auto_approve` and `evidence` verifies in the Audit MCP (`STATE_VERIFIED` event with `state=VERIFIED`), status becomes `APPROVED`, `auto_approved=true`, decision by `system:policy-auto`. Otherwise `PENDING` and a notification is requested. Idempotent per `(subject_type, subject_hash)`. |
| `get_approval` | `approval_id*` → `ReadResult[ApprovalRequest]` | |
| `list_approvals` | `status?`, `approver_id?`, `request_id?`, `subject_id?`, `limit=25` → `Page[ApprovalRequest]` | The UI's "my pending approvals". |
| `record_approval_decision` | `approval_id*`, `approver_id*`, `decision*`, `comment?` → `ApprovalRequest` | `actor` must be `user:<approver_id>`. Errors: approver not in `resolved_approvers` ⇒ `PERMISSION_DENIED`; **requester = approver ⇒ `PERMISSION_DENIED` (separation of duties)**; not `PENDING` ⇒ `PRECONDITION_FAILED`. Semantics: any `REJECT` ⇒ `REJECTED`; `ANY_ONE` first APPROVE satisfies the requirement; `ALL` needs every approver; `SEQUENTIAL` needs them in order; the request is `APPROVED` when **every** requirement is satisfied. |
| `cancel_approval` | `approval_id*`, `reason*` → `ApprovalRequest` | Only `PENDING`. Requester or system. |
| `expire_approvals` | `now?` → `{expired: list[str]}` | Deterministic sweeper (scheduler, 1/min). Emits `APPROVAL_EXPIRED` audit events. |
| `issue_execution_grant` | `plan_id*`, `plan_hash*`, `request_id*`, `policy_decision_id*`, `approval_id?`, `actions*: list[GrantActionSpec]`, `ttl_minutes=15` → `list[ExecutionGrant]` | **Preconditions (all must hold, else `PRECONDITION_FAILED` + audit `SAFETY_BLOCKED`):** `approval.status=APPROVED` **and** `approval.subject_hash == plan_hash` **and** not expired; if any action has `requires_approval=true`, an APPROVED approval (human or policy-auto) is mandatory; the policy decision is not `DENY`. One signed token per action (claims in conventions §5). |
| `verify_execution_grant` | `token*`, `server*`, `tool*`, `args_hash*` → `GrantVerification` | Diagnostics and tests. Providers verify locally with `libs/mcp_common/grants.py`. |

Governance: `get_approval`, `list_approvals`, `verify_execution_grant` read-only LOW (`llm_exposed` true, true, false). `create_approval_request` MEDIUM, `cancel_approval` MEDIUM, `expire_approvals` LOW: all `llm_exposed=false`. `record_approval_decision` HIGH, `llm_exposed=false` (reachable only through agent-api for an authenticated approver). `issue_execution_grant` **CRITICAL**, `llm_exposed=false`.

Rules: an approval covers exactly one `subject_hash`; changing the plan ⇒ new request with `supersedes_approval_id` and the old one is `CANCELLED`. Grants are short-lived (default 15 min), per action and per `args_hash`; replaying the same call with the same grant is safe because writes are idempotent. Provisioners additionally require a non-null `approval_id` claim when their **own** tool has `requires_approval=true` (policy-auto approvals count).

---

## 4. Audit MCP

Append-only, hash-chained, queryable record of everything the system decided and did. It must be possible to reconstruct *why* from the audit alone.

### 4.1 Models
```python
AuditEventType = Literal[
  # the 13 workflow events
  "REQUEST_RECEIVED","IAM_OBJECTS_DISCOVERED","KNOWLEDGE_RETRIEVED","MEMORY_RETRIEVED","POLICY_EVALUATED",
  "PLAN_GENERATED","APPROVAL_REQUESTED","APPROVAL_DECIDED","EXECUTION_STARTED","ACTION_EXECUTED",
  "STATE_VERIFIED","KNOWLEDGE_UPDATED","MEMORY_UPDATED",
  # additions ★
  "INTENT_CLASSIFIED","PLAN_VALIDATED","PROVISIONING_FAILED","COMPENSATION_STARTED","REQUEST_COMPLETED",
  "CAPABILITY_UNAVAILABLE","APPROVAL_EXPIRED","SAFETY_BLOCKED",
]
class AuditEvent(BaseModel):
    event_id: str; seq: int; ts: datetime; type: AuditEventType
    request_id: str; plan_id: str | None = None; action_id: str | None = None
    actor: str; state: str | None = None; agent_model: str | None = None; trace_id: str | None = None
    knowledge_version: int | None = None; policy_set_version: str | None = None
    summary: str                                   # ≤ 300 chars
    payload: dict[str, Any]                        # redacted: ids, hashes, versions, outcomes. No secrets, no grant tokens.
    payload_hash: str; prev_hash: str; event_hash: str      # event_hash = sha256(canonical(event without event_hash) + prev_hash)
```
> The event names above mirror the workflow states. If your spec names them differently, change the `Literal` once in `libs/iam_contracts/audit.py`; nothing else depends on the strings.

### 4.2 Required payload keys (so decisions can be reconstructed)
| Event | Payload must include |
|---|---|
| `REQUEST_RECEIVED` | `requester_id`, `channel`, `raw_request_hash` (+ text, redacted) |
| `INTENT_CLASSIFIED` | `intent`, `entities`, `confidence`, `model`, `prompt_hash` |
| `IAM_OBJECTS_DISCOVERED` | resolved ids + `resolution` per object, clarification asked? |
| `KNOWLEDGE_RETRIEVED` | `knowledge_version` pin, entitlement versions used, verdicts |
| `MEMORY_RETRIEVED` | `memory_ids`, `degraded`, conflicts excluded |
| `POLICY_EVALUATED` | `decision_id`, `decision`, `policy_set_version`, `matched_policies`, `inputs_hash` |
| `PLAN_GENERATED` / `PLAN_VALIDATED` | `plan_id`, `plan_hash`, action list (neutral ops), validation result, dry-run outcomes |
| `APPROVAL_*` | `approval_id`, `subject_hash`, approvers, decision, comment |
| `EXECUTION_STARTED` | `plan_id`, `grant_ids` |
| `ACTION_EXECUTED` | `action_id`, `server`, `tool`, `args_hash`, `status`, `outcome`, `replayed`, `before`/`after` digests |
| `STATE_VERIFIED` | per-system `ReconciliationItem` counts, `state` (`VERIFIED`/`DRIFT`/`UNKNOWN`) |
| `KNOWLEDGE_UPDATED` | `proposal_id`, `new_knowledge_version`, `rows_written` |
| `REQUEST_COMPLETED` | terminal state, outcome summary |

### 4.3 Tools
| Tool | In → Out | Notes |
|---|---|---|
| `append_event` | `type*`, `request_id*`, `actor*`, `summary*`, `payload={}`, `plan_id?`, `action_id?`, `state?`, `knowledge_version?`, `policy_set_version?`, `dedupe_key?` → `{event: AuditEvent}` | Serialised under one writer lock. `dedupe_key` replay returns the existing event. Rejects payload keys matching `password/secret/token/credential` (except `credential_ref`) with `VALIDATION_ERROR`. |
| `get_event` | `event_id*` → `ReadResult[AuditEvent]` | |
| `query_events` | `request_id?`, `types?`, `actor?`, `system_id?`, `entity_id?`, `since?`, `until?`, `after_seq?`, `limit=100` → `Page[AuditEvent]` | |
| `get_request_timeline` | `request_id*` → `RequestTimeline` | Ordered events + `states_visited`, `terminal_state`, durations, **completeness checks**. |
| `reconstruct_decision` | `request_id*` or `decision_id*` → `DecisionReconstruction` | Answers "why did the agent do this?" from audit alone: request, intent, knowledge version and entitlement versions used, policy decision, memory used (flagged non-authoritative), plan hash, approval, executed actions, verification, plus a deterministic `narrative: list[str]`. |
| `verify_chain` | `from_seq?`, `to_seq?` → `ChainVerification{valid, checked, first_invalid_seq?, expected_hash?, actual_hash?}` | Recomputes hashes. Any tamper ⇒ `valid=false` at the first bad `seq`. |

```python
class CompletenessCheck(BaseModel): rule: str; passed: bool; detail: str | None = None
class RequestTimeline(BaseModel):
    request_id: str; events: list[AuditEvent]; states_visited: list[str]; terminal_state: str | None
    started_at: datetime; ended_at: datetime | None; duration_ms: int | None
    checks: list[CompletenessCheck]; complete: bool
```
Completeness rules: has `REQUEST_RECEIVED` and `REQUEST_COMPLETED`; every `ACTION_EXECUTED` is preceded by `EXECUTION_STARTED` and a `PLAN_VALIDATED`; every write action has an `APPROVAL_DECIDED` (human or policy-auto) or an ALLOW `POLICY_EVALUATED` in the same request; every `REFUSED`/`FAILED` terminal still has `REQUEST_COMPLETED`.

Governance: `append_event` LOW, idempotent via `dedupe_key`, `llm_exposed=false`. All others read-only LOW, `llm_exposed=true` except `verify_chain` (true, it is harmless). **No update or delete tool exists**; DB triggers forbid UPDATE/DELETE on `audit_events`.

---

## 5. Notification MCP

Mock delivery: messages are written to an `outbox` table and shown in the UI. **Template + parameters only.** Free-form text from the LLM is never sent.

```python
NotificationTemplate = Literal["APPROVAL_REQUESTED","APPROVAL_REMINDER","APPROVAL_DECIDED","REQUEST_COMPLETED",
                               "REQUEST_REFUSED","REQUEST_FAILED","CLARIFICATION_NEEDED","KNOWLEDGE_CHANGE_APPLIED","RECONCILIATION_DRIFT"]
class Recipient(BaseModel): kind: Literal["USER","ROLE","ADDRESS"]; ref: str
class NotificationResult(BaseModel):
    notification_id: str; status: Literal["QUEUED","SENT","FAILED","SUPPRESSED"]
    delivered_to: list[str]; outbox_ref: str | None = None; error: ToolError | None = None
class NotificationStatus(BaseModel):
    notification_id: str; status: Literal["QUEUED","SENT","FAILED","SUPPRESSED"]; attempts: int
    created_at: datetime; sent_at: datetime | None = None; template: NotificationTemplate; request_id: str
```
| Tool | In → Out | Behavior |
|---|---|---|
| `send_notification` | `channel*` (`UI`/`EMAIL`/`CHAT`/`WEBHOOK`), `recipients*: list[Recipient]`, `template*`, `params={}`, `request_id*`, `dedupe_key?` → `NotificationResult` | Params validated per template and sanitised (no secrets, ≤ 200 chars per value). Same `dedupe_key` ⇒ `SUPPRESSED`, no duplicate. Delivery failure never fails the request; the orchestrator logs a warning. |
| `get_notification_status` | `notification_id*` → `ReadResult[NotificationStatus]` | |

Governance: `send_notification` LOW, idempotent via `dedupe_key`, `llm_exposed=false`. `get_notification_status` read-only LOW.

---

## 6. Acceptance checklist

- [ ] **Policy:** deny-overrides, default-deny, UNKNOWN fail-closed rules each have a test; FinanceReader v1 vs v2 produce different `approvals`; same input + same set ⇒ same `decision_id`; `evaluate_plan` denies a REMOVE with no explicit ALLOW.
- [ ] **Memory:** hybrid ranking order test; dedupe returns `MERGED_DUPLICATE`; conflicted record excluded by default; secrets rejected; the LLM-visible tool list has no write tools.
- [ ] **Approval:** requester ≠ approver enforced; grant refused when `subject_hash != plan_hash`; grant refused for an unapproved `requires_approval` tool; expired approvals sweep; re-plan creates a new request and cancels the old one.
- [ ] **Audit:** UPDATE/DELETE blocked; `verify_chain` detects a tampered row at the right `seq`; timeline completeness catches a missing event; `reconstruct_decision` output contains knowledge version, policy decision id, plan hash and approval id.
- [ ] **Notification:** unknown template or secret-looking param rejected; duplicate `dedupe_key` suppressed.
- [ ] Manifest governance of every server matches this document (snapshot test).
