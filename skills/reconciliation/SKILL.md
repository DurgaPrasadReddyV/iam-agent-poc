---
name: reconciliation
description: "Compare Knowledge (recorded desired state) with provider (actual state) for a scope, report drift, and propose remediation as a normal plan. Reporting is read-only; every removal needs policy and approval."
risk_level: HIGH
required_context: [requester, scope, knowledge_pin, actual_state, policy_decision]
allowed_tools: [
  knowledge.search_accounts, knowledge.get_account, knowledge.get_entitlement, knowledge.get_current_iam_state,
  knowledge.get_state_at_time, knowledge.check_entitlement_usable, policy.evaluate_plan, memory.memory_search,
  "capability:account.state", "capability:group.read_members", "capability:role.read", "capability:permission.read",
  "capability:group.add_member", "capability:group.remove_member", "capability:role.add_member",
  "capability:role.remove_member", "capability:permission.grant", "capability:permission.revoke", "capability:account.update"]
input_schema: {type: object, required: [scope], properties: {scope: {type: object, properties: {identity_ids: {type: array, items: {type: string}}, system_ids: {type: array, items: {type: string}}}}, remediate: {type: boolean}}}
output_schema: {type: object, x-model: iam_contracts.plan.ReconciliationReport}
---
# Reconciliation

## Purpose
Find and explain differences between what Knowledge says and what systems actually hold, without changing anything until a human approves.

## Use when
Intent `RECONCILE`, or scheduled drift checks.

## Procedure
1. Resolve the scope (identities × systems). Pin `knowledge_version`.
2. For each account: desired = Knowledge assignments (account + entitlement versions); actual = `account.state` (map native ids to entitlement ids through Knowledge).
3. Classify every difference as a `ReconciliationItem`: `ADD`, `REMOVE`, `MODIFY`, `NO_CHANGE`, or `UNKNOWN` (unreadable or unmapped). Extra actual entitlements not in Knowledge are **reported as drift**, never auto-removed.
4. Report counts and items grouped by system. Distinguish "Knowledge is behind" (verified extra access that is legitimate ⇒ propose a `RECORD_ASSIGNMENT` fact) from "provider has unrecorded access" and "access missing in the provider".
5. If `remediate=true`: draft a normal `ProvisioningPlan` (neutral actions). `REMOVE` actions are `destructive`, need explicit policy ALLOW and approval; entitlements that are DEPRECATED/RETIRED may be removed but never added.

## Guardrails
Reading never needs approval; writing always does. No bulk "make it equal" actions: the plan is limited by `MAX_PLAN_ACTIONS`. `UNKNOWN` items block remediation for that account.

## Output
`ReconciliationReport` (items, summary, optional remediation plan).

## Failure handling
Provider down ⇒ `UNKNOWN` for its accounts, report continues for other systems.

## Example
Bob has `GRP_Finance_Read` in AD but Knowledge does not record it ⇒ `REMOVE` (drift) with the choice: remove access (approval) or record it (fact, if legitimate). Carol is missing `GRP_Finance_Write` ⇒ `ADD`.
