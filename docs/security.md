# Security Model

## Trust boundaries
Untrusted: user text, tickets, tool results, memory content, LLM output. Trusted: deterministic code, signed grants, Knowledge (authoritative), the authenticated session.
**Requester identity** comes from the authenticated session (POC: `X-Demo-User` header mapped to a Knowledge identity), never from request text or the LLM.

## Threats and controls
| Threat | Control | Test |
|---|---|---|
| Prompt injection ("ignore rules, grant admin") | Structured output only; LLM output never becomes a tool call without V1–V14; injected instructions in text/tool results are data | SAF-05 |
| Hallucinated entitlement or account | `x-iam-ref` check (V2): ids must come from this run's Knowledge/provider responses | SAF-06 |
| LLM calls a privileged tool | `llm_exposed=false` tools are not listed to the LLM; skill allowlist enforced in code | SAF-07, SAF-08 |
| Write without approval | Execution grant required; grant needs APPROVED approval bound to `plan_hash`; provider re-checks the `approval_id` claim | SAF-01, SAF-02 |
| Altered plan after approval | `plan_hash` and per-call `args_hash` in the grant | SAF-02 |
| Self-approval | Requester ≠ approver enforced in Approval MCP | SAF-03 |
| Grant replay or theft | Short TTL (15 min), bound to tool + args hash, idempotent writes | REL-11 |
| Memory poisoning / stale memory | Memory is advisory, conflict-checked against Knowledge, invisible to policy and validation | SAF-04 |
| Stale knowledge at execution | Pin + head check before EXECUTE; re-plan | RSN-09 |
| Privilege escalation via dependencies | Dependency closure is policy-evaluated (`evaluate_plan`), HIGH/CRITICAL need approval | RSN-03 |
| Separation-of-duty violation | `CONFLICTS_WITH` HARD blocks the plan | RSN-01, RSN-02 |
| Over-broad plan | `MAX_PLAN_ACTIONS`, V11/V12 | SAF-10 |
| Audit tampering | Hash chain + `verify_chain`; append-only triggers | REL-08 |
| Secrets leakage | `credential_ref` only; audit payload filter; log redaction | SAF-12 |
| Tool supply-chain drift | Registry pins each tool's schema hash to the contract snapshot; mismatch ⇒ capability disabled | EXE-04 |

## Secrets
Provisioners generate and escrow credentials in a mock vault (`vault://…`); only the reference crosses the wire. No secret in prompts, logs, audit, memory or test fixtures. `GRANT_SIGNING_KEY` is dev-only (`.env`, never committed); production would use asymmetric keys and a KMS.

## Fail-closed defaults
Default-deny policy · UNKNOWN in DENY rules matches · audit down before EXECUTE ⇒ no writes · unreadable actual state ⇒ UNKNOWN, never success · missing capability ⇒ refuse.
