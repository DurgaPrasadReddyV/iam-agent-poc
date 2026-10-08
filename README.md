# AI-Native IAM Provisioning Agent: POC repo pack

Repo-ready content for building the POC with GitHub Copilot: coding-agent instructions, MCP tool contracts (inputs and outputs), architecture and workflow docs, nine agent skills, evals, and a phase plan with paste-in prompts.

> **The LLM proposes. Deterministic code validates, authorizes, executes and verifies.**

## Start here
1. Create the repo, copy this folder in, commit. Copilot reads `.github/copilot-instructions.md` (repo-wide), `.github/instructions/*.instructions.md` (path-specific, via `applyTo`) and `AGENTS.md` (the nearest file wins) automatically.
2. Open the repo in VS Code with Copilot **Agent mode**.
3. Open `docs/implementation-plan.md`, paste the **Phase 0** prompt, review, run `make lint type arch test`, merge. Then one phase per branch, in order, only after the exit criteria pass.
4. **You build Phase 1** (AD, SQL, Linux, App servers) from `docs/contracts/provisioning-mcp.md`. The per-server prompt is in the plan, and Copilot can assist.
5. When you ask Copilot for a component, attach its contract file (drag it into the chat or use `#file`). Contracts are the source of truth. If code and contract disagree, change one deliberately, never silently; the snapshot tests catch drift.
6. Keep sessions small: one tool group or one module per prompt.

## Contents
| Path | What |
|---|---|
| `AGENTS.md`, `.github/` | coding-agent rules, path-specific instructions, CI |
| `docs/contracts/00-conventions.md` | shared types, error codes, outcomes, idempotency, governance flags, execution grants, manifest, capability tags |
| `docs/contracts/provisioning-mcp.md` | **AD, SQL, Linux, App servers**: every tool with inputs, outputs, behavior, examples, acceptance checklist |
| `docs/contracts/knowledge-mcp.md` | **Knowledge MCP**: architecture, temporal model, models, all tools with inputs and outputs, change pipeline, seed loader, layout |
| `docs/contracts/platform-mcps.md` | Policy, Memory, Approval, Audit, Notification |
| `docs/architecture.md`, `agent-workflow.md`, `provisioning.md`, `memory.md`, `security.md`, `mcp.md` | design, workflow state machine, plan/validate/execute/verify, discovery and registry |
| `docs/knowledge-model.md` | seed dataset: systems, identities, entitlements, policies, seed profiles |
| `docs/implementation-plan.md` | phases 0 to 6 with Copilot prompts |
| `docs/evaluation.md` | 48 deterministic evals, 9 demo scenarios, final acceptance test |
| `skills/` | nine skills and `README.md` (intent mapping, format, composition) |
| `libs/`, `agent/`, `mcp/`, `knowledge/`, `memory/`, `docker/`, `tests/` | skeleton with a short `AGENTS.md` per component |

## Quickstart (after Phase 0)
```
cp .env.example .env
make setup && make up && make seed && make smoke
make demo SCENARIO=1
make eval && make acceptance
```
`tests/skills` already runs today: `pip install pytest pyyaml && pytest tests/skills`.

## Additions beyond your spec (marked ★ in the docs)
* Shared `libs/iam_contracts` and `libs/mcp_common`; two extra servers, `mcp/app-server` (APP_X/APP_Y) and `mcp/notification-server`.
* `import-linter` rule: `agent` may not import server packages.
* Identity tools in Knowledge; `check_entitlement_usable`; `derive_account_attributes` and `validate_*` tools; `simulate_policy_change`.
* Knowledge change pipeline: proposals, approval, grant-gated `apply_knowledge_change`, change classes, lifecycle tables.
* `llm_exposed` governance flag so deterministic-only tools are hidden from the LLM.
* Execution grants bound to `plan_hash` and per-call `args_hash`.
* Neutral capability tags bound to tools through the registry; `x-iam-ref` check (invented ids rejected).
* Common provider contract (`health_check`, `get_account_state`) so verification and reconciliation are provider-agnostic.
* Extra audit event types; `SEED_PROFILE` for the live-change acceptance test.

## Check against your spec
* **Audit event names** mirror the workflow states. If your spec names them differently, change the one `Literal` in `libs/iam_contracts/audit.py`.
* **Demo scenarios**: 1, 6 and 7 follow the contract examples; 2 to 5, 8 and 9 are defined in `docs/evaluation.md`. Renumber to match your spec if needed.
* **Workflow states**: the spec's separate dry-run state is folded into `VALIDATE_PLAN` (decision D7 in `docs/architecture.md`); `WAITING_FOR_CLARIFICATION` and the terminals `REFUSED`, `FAILED`, `EXPIRED`, `CANCELLED` are added.
* **Seed names** (Alice, `FIN_READ`, `APP_X_ADMIN`, policy ids) are chosen for the demos. Rename freely in `knowledge/`.
