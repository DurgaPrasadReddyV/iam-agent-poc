---
name: verification
description: "Read back actual state from the providers after execution and decide whether the result matches the desired state of the touched scope (VERIFIED, DRIFT, UNKNOWN). Fully deterministic; success may only be reported after this passes."
risk_level: LOW
required_context: [plan, execution_results, desired_state, knowledge_pin]
allowed_tools: [
  knowledge.get_entitlement, knowledge.get_account,
  "capability:account.state", "capability:account.read", "capability:account.read_attributes",
  "capability:group.read_members", "capability:role.read", "capability:permission.read"]
input_schema: {type: object, required: [plan_id, touched], properties: {plan_id: {type: string}, touched: {type: array, items: {type: object, required: [system_id, account_id], properties: {system_id: {type: string}, account_id: {type: string}, scope: {type: object}}}}}}
output_schema: {type: object, x-model: iam_contracts.plan.VerificationReport}
---
# Verification

## Purpose
Prove the outcome. A write result says what the provider reported; verification says what is true now.

## Use when
State VERIFY_STATE (always after EXECUTE) and after recovery actions.

## Procedure
1. For each touched account call `account.state` (use the specific read capabilities only if the state lacks detail).
2. Map native entitlement ids to Knowledge ids. Compare **only the touched scope** with the desired state: account exists/status/attributes, and every entitlement the plan added or removed.
3. Produce `ReconciliationItem`s. `VERIFIED` = all items `NO_CHANGE`; `DRIFT` = any mismatch; `UNKNOWN` = any read failed or unmapped.
4. Include `observed_at` per system.

## Guardrails
Read-only. No LLM involvement; no tolerance for "close enough". Never infer success from `WriteResult` alone. A provider read that is older than the last write is rejected (compare `observed_at` with `executed_at`).

## Output
`VerificationReport{state, items, observed_at, systems_checked}`.

## Failure handling
`DRIFT` ⇒ request FAILED (`VERIFICATION_DRIFT`), no Knowledge update, incident-recovery suggested. `UNKNOWN` ⇒ FAILED (`UNVERIFIED`) unless a retry of the read succeeds (max 3).

## Example
After adding Alice to `GRP_Finance_Read`: `account.state(asmith)` lists the group ⇒ item `ENTITLEMENT FIN_READ NO_CHANGE` ⇒ `VERIFIED`.
