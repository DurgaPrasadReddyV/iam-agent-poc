---
name: entitlement-provisioning
description: "Plan the assignment or removal of existing entitlements (AD groups, SQL roles and permissions, Linux groups and sudo rules, application roles) for an account. Handles usability, replacement, dependency ordering and conflicts."
risk_level: HIGH
required_context: [requester, subject_identity, resolved_objects, held_entitlements, actual_state, policy_decision, knowledge_pin]
allowed_tools: [
  knowledge.get_identity, knowledge.get_account, knowledge.search_accounts, knowledge.get_entitlement,
  knowledge.check_entitlement_usable, knowledge.find_entitlement_replacement,
  knowledge.find_entitlement_dependencies, knowledge.find_entitlement_conflicts,
  policy.evaluate_policy, memory.memory_search,
  "capability:group.add_member", "capability:group.remove_member", "capability:group.read_members",
  "capability:group.create", "capability:role.add_member", "capability:role.remove_member",
  "capability:role.create", "capability:permission.grant", "capability:permission.revoke",
  "capability:privilege.sudo.grant", "capability:privilege.sudo.revoke", "capability:account.state"]
input_schema: {type: object, required: [identity_id, operation, entitlement_ids], properties: {identity_id: {type: string}, operation: {enum: [ASSIGN, REMOVE]}, entitlement_ids: {type: array, items: {type: string}}, expires_at: {type: string, format: date-time}, justification: {type: string}}}
output_schema: {type: object, x-model: iam_contracts.plan.ProvisioningPlan}
---
# Entitlement Provisioning (Entitlement Assignment)

## Purpose
Grant or remove access that already exists in the catalog, safely: only usable entitlements, dependencies first, no conflicts, nothing removed that was not asked for.

## Use when
Intents `ASSIGN_ENTITLEMENT`, `REMOVE_ENTITLEMENT`.

## Procedure
1. Inputs are ids from discovery (never names). Load the subject's recorded assignments (`get_account`) and, via `account.state`, the **actual** held entitlements.
2. Gate every entitlement with `check_entitlement_usable` (operation `ASSIGN` or `REMOVE`). Any non-`USABLE` assignment ⇒ stop; report the verdict and the replacement. **Never substitute silently**: the user must request the replacement explicitly.
3. `find_entitlement_dependencies` (pass held ids) ⇒ add the missing closure **in the returned order**; an unresolvable HARD dependency ⇒ stop. `find_entitlement_conflicts` (within the request and against held) ⇒ any HARD conflict ⇒ stop.
4. `evaluate_policy` (`ASSIGN_ENTITLEMENT`/`REMOVE_ENTITLEMENT`) with `held_entitlement_ids`.
5. Draft actions per entitlement type: GROUP ⇒ `group.add_member`; ROLE/APP_ROLE ⇒ `role.add_member`; PERMISSION ⇒ `permission.grant`; SUDO_RULE ⇒ `privilege.sudo.grant`. Removal ⇒ the inverse, `destructive=true`. If the provider lacks the native group or role although Knowledge lists it ACTIVE, add `group.create`/`role.create` first.
6. Each action gets its inverse as `compensation` (not for removals) and `expected_outcome` (`CREATED` for a new membership, `NO_CHANGE` if already held).

## Guardrails
Removals only when the request says so, with explicit policy ALLOW and approval. Do not touch entitlements outside the request (drift is reported, not fixed). Respect `expires_at`. HIGH/CRITICAL entitlements always carry their approval requirements from policy.

## Output
`ProvisioningPlan`.

## Failure handling
REFUSED with reasons: `DEPRECATED`/`RETIRED`/`BLOCKED`/`NOT_YET_EFFECTIVE`/`NOT_REQUESTABLE`, `CONFLICT`, `UNRESOLVABLE_DEPENDENCY`, policy DENY.

## Example
"Give Alice read access to FinanceDB" ⇒ `FIN_READ` (AD group) first, then `SQL_FIN_READER` (SQL role) because of the HARD dependency.
