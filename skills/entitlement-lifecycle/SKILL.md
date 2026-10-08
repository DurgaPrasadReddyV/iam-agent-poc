---
name: entitlement-lifecycle
description: "Create new entitlements and change an entitlement's lifecycle (register, activate, update, deprecate with replacement, retire, block, unblock, relationships) through the Knowledge change pipeline, creating the native group or role when needed. Never edits Knowledge directly."
risk_level: HIGH
required_context: [requester, resolved_objects, policy_decision, knowledge_pin]
allowed_tools: [
  knowledge.search_entitlements, knowledge.get_entitlement, knowledge.get_entitlement_history,
  knowledge.find_entitlement_replacement, knowledge.find_entitlement_dependencies,
  knowledge.validate_entitlement_definition, knowledge.propose_knowledge_change,
  knowledge.get_knowledge_proposal, knowledge.list_knowledge_proposals, knowledge.withdraw_knowledge_proposal,
  policy.evaluate_policy, memory.memory_search,
  "capability:group.create", "capability:role.create", "capability:group.read", "capability:role.read",
  "capability:account.state"]
input_schema: {type: object, required: [operation], properties: {operation: {enum: [CREATE, ACTIVATE, UPDATE, DEPRECATE, RETIRE, BLOCK, UNBLOCK, PROPOSE_REPLACEMENT]}, entitlement_id: {type: string}, definition: {type: object}, replacement_ids: {type: array, items: {type: string}}, retire_at: {type: string, format: date-time}, reason: {type: string}}}
output_schema: {type: object, required: [proposals], properties: {proposals: {type: array, items: {type: object, x-model: iam_contracts.knowledge.KnowledgeProposal}}, plan: {type: object, x-model: iam_contracts.plan.ProvisioningPlan}}}
---
# Entitlement Lifecycle (Entitlement Creation and Change)

## Purpose
Keep the catalog truthful: add entitlements, retire old ones, always with history, replacement and approval.

## Use when
Intents `CREATE_ENTITLEMENT`, `DEPRECATE_ENTITLEMENT`, `RETIRE_ENTITLEMENT`, `BLOCK_ENTITLEMENT`, `UNBLOCK_ENTITLEMENT`, `PROPOSE_REPLACEMENT`.

## Procedure
1. `search_entitlements` for duplicates and near-duplicates (`AMBIGUOUS` ⇒ ask). `get_entitlement` for current status.
2. **Create:** `validate_entitlement_definition`; `evaluate_policy` (`CREATE_ENTITLEMENT`); propose `REGISTER_ENTITLEMENT(initial_status=PROPOSED)` (CATALOG_CHANGE ⇒ human approval). After it is applied, plan native object creation (`group.create`/`role.create`) as a normal provisioning plan; after VERIFIED, propose `ACTIVATE_ENTITLEMENT` with the verification evidence (auto-approvable).
3. **Deprecate:** require `replacement_ids` unless the reason says none exists; each replacement must be ACTIVE. Propose `DEPRECATE_ENTITLEMENT(retire_at=…)`; include the `impact` preview (assignments affected) in the approval summary. Later `RETIRE_ENTITLEMENT` follows the lifecycle table in `knowledge-mcp.md §6.2`; direct ACTIVE→RETIRED is illegal.
4. **Block/unblock:** `evaluate_policy` (`CHANGE_ENTITLEMENT_STATUS`), propose the change with `reason`.
5. Submit with `propose_knowledge_change`; the workflow (not the LLM) creates the approval, mints the grant and applies.

## Guardrails
Only `propose_*` is available: the LLM can never apply a change. Do not remove access as part of deprecation: existing assignments stay until separately requested (migration is its own request). Never invent a replacement id.

## Output
One or more `KnowledgeProposal`s, plus a `ProvisioningPlan` when a native object must be created.

## Failure handling
`VALIDATION_FAILED` ⇒ show the issues and offer to re-propose. Rejected or expired approval ⇒ REFUSED/EXPIRED, nothing applied.

## Example
"Deprecate APP_X_ADMIN, replace with APP_X_PLATFORM_ADMIN, retire in 60 days" ⇒ `DEPRECATE_ENTITLEMENT` with `replacement_ids=[APP_X_PLATFORM_ADMIN]`, `retire_at=+60d`; impact: 1 assignment (Bob).
