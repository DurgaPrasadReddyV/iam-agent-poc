---
name: account-provisioning
description: "Plan the creation, update or disabling of an account for a person in a target system (AD user, SQL login, Linux user, application account). Used for new-hire, \"give X an account\" and leaver-disable requests."
risk_level: HIGH
required_context: [requester, subject_identity, resolved_objects, system_schema, account_schema, policy_decision, knowledge_pin]
allowed_tools: [
  knowledge.get_identity, knowledge.get_system_schema, knowledge.get_account_schema, knowledge.search_accounts,
  knowledge.get_account, knowledge.derive_account_attributes, knowledge.validate_account_attributes,
  policy.evaluate_policy, memory.memory_search,
  "capability:account.create", "capability:account.read", "capability:account.update",
  "capability:account.disable", "capability:account.set_attribute", "capability:account.state"]
input_schema: {type: object, required: [identity_id, system_id, operation], properties: {identity_id: {type: string}, system_id: {type: string}, account_type: {type: string}, operation: {enum: [CREATE, UPDATE, DISABLE]}, attribute_overrides: {type: object}}}
output_schema: {type: object, x-model: iam_contracts.plan.ProvisioningPlan}
---
# Account Provisioning

## Purpose
Produce a validated-able plan that creates, updates or disables one account per target system, with attributes derived from the schema, not invented.

## Use when
Intents `CREATE_ACCOUNT`, `UPDATE_ACCOUNT`, `DISABLE_ACCOUNT`. Combined requests ("create an account and give her Finance read") compose this skill with `entitlement-provisioning` (see README, skill composition).

## Procedure
1. Load identity, system schema and account schema. `search_accounts` to see whether Knowledge already records an account.
2. `derive_account_attributes` (naming, OU, defaults). The LLM may supply only attributes the schema marks `INPUT` **and** the request or identity provides. Missing required attributes ⇒ ask for clarification.
3. `validate_account_attributes` (`CREATE` or `UPDATE`). Fix or ask; never override a validation error.
4. `evaluate_policy` for the operation (`CREATE_ACCOUNT`, `UPDATE_ACCOUNT`, `DISABLE_ACCOUNT`).
5. Draft the plan: `account.create` with `credential_mode=GENERATE_AND_ESCROW` (CREATE); `account.update` only for differences the request asks for; `account.disable` for leavers (group removals are separate, explicit, destructive actions that need policy ALLOW and approval).
6. Set `expected_outcome` (`CREATED` when no account is recorded; `EXISTS`/`UPDATED` per the dry-run) and a `compensation` (`account.disable`) for each create.

## Guardrails
Attribute names only from the schema. Never set protected attributes. No credentials in the plan (`credential_ref` only). Provider `EXISTS` is success-with-drift, not an error. `NATURAL_KEY_CONFLICT` ⇒ stop and ask. One account per system per action.

## Output
`ProvisioningPlan` (neutral capability tags; `rationale` per action).

## Failure handling
Policy DENY ⇒ REFUSED with reason codes. Capability unavailable ⇒ `CAPABILITY_UNAVAILABLE`. Invalid plan after 2 re-plans ⇒ FAILED.

## Example
"Create an AD account for Alice Smith" ⇒ one `account.create` on `ACTIVE_DIRECTORY` with derived `sam_account_name=asmith`, OU from department, `expected_outcome=CREATED`.
