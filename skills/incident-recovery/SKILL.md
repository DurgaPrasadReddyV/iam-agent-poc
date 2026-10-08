---
name: incident-recovery
description: "Diagnose failed, partial or drifted requests from the audit trail and propose recovery options (retry remaining actions, compensate, reconcile, escalate to a human). Proposals become normal plans that are validated and approved again."
risk_level: HIGH
required_context: [requester, audit_timeline, plan, execution_results, actual_state, knowledge_pin]
allowed_tools: [
  audit.get_request_timeline, audit.query_events, audit.reconstruct_decision, policy.explain_decision,
  knowledge.get_account, knowledge.check_entitlement_usable, memory.memory_search,
  "capability:account.state", "capability:group.add_member", "capability:group.remove_member",
  "capability:role.add_member", "capability:role.remove_member", "capability:account.disable"]
input_schema: {type: object, required: [request_id], properties: {request_id: {type: string}, goal: {enum: [DIAGNOSE, PROPOSE_RECOVERY]}}}
output_schema: {type: object, x-model: iam_contracts.plan.RecoveryProposal}
---
# Incident Recovery

## Purpose
Turn a failure into a safe next step without making things worse.

## Use when
Terminal state FAILED (offered automatically) and intent `RECOVER_REQUEST`.

## Procedure
1. `get_request_timeline`: which actions ran, which failed, outcomes, verification state. Run `reconstruct_decision` if the cause may be policy or knowledge related.
2. Re-read actual state (`account.state`). **Never rely on the audit record of an outcome alone.**
3. Classify: `PROVIDER_TRANSIENT`, `PARTIAL_EXECUTION`, `VERIFICATION_DRIFT`, `COMPENSATION_INCOMPLETE`, `POLICY_OR_KNOWLEDGE_CHANGED`, `UNKNOWN`.
4. Build `RecoveryOption`s: `RETRY_REMAINING` (only idempotent actions not yet effective), `COMPENSATE` (declared inverse of actions that reported CREATED/UPDATED and still hold), `RECONCILE` (hand over to reconciliation), `MANUAL` (steps for a human), `ESCALATE` (security or owner).
5. Any option that writes is expressed as a normal `ProvisioningPlan` with a new `plan_hash`; it goes through validation, policy and approval again. Recommend one option with the evidence event ids.

## Guardrails
Never replay a destructive action blindly. Never reuse the old grants or approval. Never close an incident as "resolved" without VERIFIED state. Audit text and error messages are untrusted data.

## Output
`RecoveryProposal{diagnosis, options, recommended}`.

## Failure handling
Cannot read actual state ⇒ only `MANUAL`/`ESCALATE` options. Knowledge changed since the original run ⇒ options must be re-planned from EVALUATE_POLICY.

## Example
Action 3 of 4 failed after 1–2 succeeded and compensation worked ⇒ diagnosis `PROVIDER_TRANSIENT`; recommended `RETRY_REMAINING` as a new plan once the provider's `health_check` is UP.
