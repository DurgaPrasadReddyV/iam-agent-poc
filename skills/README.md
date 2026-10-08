# Skills

Skills are procedural playbooks the engine loads for a request: instructions for the LLM's two steps (intent, plan), an allowlist of tools and capabilities, and input/output schemas. Selection is **deterministic** (intent to skill table below), never chosen by the LLM.

## Intent to skill
| Intent | Skill | Spec area |
|---|---|---|
| `QUERY` | `iam-discovery` | discovery |
| `CREATE_ACCOUNT`, `UPDATE_ACCOUNT`, `DISABLE_ACCOUNT` | `account-provisioning` | account provisioning |
| `ASSIGN_ENTITLEMENT`, `REMOVE_ENTITLEMENT` | `entitlement-provisioning` | entitlement assignment |
| `CREATE_ENTITLEMENT`, `DEPRECATE_ENTITLEMENT`, `RETIRE_ENTITLEMENT`, `BLOCK_ENTITLEMENT`, `UNBLOCK_ENTITLEMENT`, `PROPOSE_REPLACEMENT` | `entitlement-lifecycle` | entitlement creation / lifecycle |
| `PROPOSE_POLICY_CHANGE`, `EXPLAIN_DECISION` | `policy-evaluation` | policy change proposals |
| `RECONCILE` | `reconciliation` | reconciliation |
| `RECOVER_REQUEST` | `incident-recovery` | recovery |
| workflow step DISCOVER_IAM_OBJECTS | `iam-discovery` | |
| workflow step WAIT_FOR_APPROVAL | `approval-management` | |
| workflow step VERIFY_STATE | `verification` | |

Risk levels: LOW `iam-discovery`, `verification` · MEDIUM `policy-evaluation`, `approval-management` · HIGH `account-provisioning`, `entitlement-provisioning`, `entitlement-lifecycle`, `reconciliation`, `incident-recovery`.

## Composition
One request can carry several intents ("create an account and give her Finance read"). The planner receives the **union** of the matched skills' tools and capabilities, plan risk = the highest skill risk, and actions are ordered account, then entitlements (dependencies first).

## Format
* Frontmatter keys exactly: `name`, `description`, `risk_level`, `required_context`, `allowed_tools`, `input_schema`, `output_schema`.
* `allowed_tools`: `server.tool` for platform servers, `"capability:<tag>"` for provider operations. Semantics in `docs/mcp.md` (LLM sees `server.tool` read-only, `llm_exposed=true` entries only; capabilities constrain the plan).
* `required_context`: named blocks the engine must supply before the skill runs: `requester`, `subject_identity`, `resolved_objects`, `knowledge_pin`, `held_entitlements`, `actual_state`, `system_schema`, `account_schema`, `policy_decision`, `plan`, `execution_results`, `desired_state`, `approval`, `audit_timeline`, `scope`. A missing block ⇒ the engine does not run the skill.
* `input_schema` / `output_schema`: JSON Schema. `x-model: <module.Class>` names the Pydantic model the loader validates against (models live in `libs/iam_contracts`).
* The registry fails startup if a skill names an unknown tool or capability.
