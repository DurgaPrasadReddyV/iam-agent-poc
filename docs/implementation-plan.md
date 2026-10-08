# Implementation Plan (7 phases) with Copilot prompts

Work **one phase per branch**. Do not start the next phase until the exit criteria pass. Use Copilot Agent mode, attach the referenced files (or reference them by path), and start each session with:

> Follow AGENTS.md. Work only on Phase N below. First list the files you will create or change. Write tests with the code. When done run `make lint type arch test` and fix every failure. Do not change docs/contracts unless I say so.

| Phase | Theme | Who |
|---|---|---|
| 0 | Scaffold, shared libs, CI | Copilot |
| 1 | Provisioning MCP servers (AD, SQL, Linux, App) | **You** (Copilot assists) |
| 2 | Knowledge MCP | Copilot |
| 3 | Platform MCPs: Policy, Approval, Audit, Memory, Notification | Copilot |
| 4 | Agent core: registry, workflow, plan/validate/execute/verify, skills | Copilot |
| 5 | Reconciliation, change pipeline flows, memory learning, UI | Copilot |
| 6 | Evals, scenarios, hardening, docker, demo | Copilot |

## Phase 0 — Scaffold
**Deliver:** monorepo tooling; `libs/iam_contracts/common.py` exactly as `00-conventions.md §2`; `libs/mcp_common` (`grants.py` HS256 sign/verify with canonical `args_hash`, `idempotency.py`, `manifest.py`, `clock.py`, `client.py`); one package skeleton per `mcp/<server>` exposing only manifest + `health_check`; Makefile targets from AGENTS.md; import-linter contracts; `.env.example`; `docker/docker-compose.yml` with healthchecks; CI already in `.github/workflows/ci.yml`.
**Exit:** `make lint type arch test` green; `make up` shows 10 healthy services; `make smoke` lists every manifest.
**Prompt:**
> Implement Phase 0 using AGENTS.md, docs/architecture.md and docs/contracts/00-conventions.md. Create libs/iam_contracts/common.py verbatim from §2, libs/mcp_common (grant sign/verify per §5 including the approval_id rule, idempotency store, manifest builder, injectable Clock, MCP client with timeouts), a FastMCP skeleton for each server under mcp/<name>/src/<pkg> that serves /mcp and the manifest resource, the Makefile targets, import-linter config enforcing the boundaries in AGENTS.md, .env.example and a docker compose file with healthchecks on ports from docs/mcp.md. Add unit tests for grants (valid, expired, wrong args_hash, wrong tool, missing approval_id when required) and for the idempotency store.

## Phase 1 — Provisioning servers (you build; use this prompt per server)
**Deliver:** `ad`, `sql`, `linux`, `app` per `provisioning-mcp.md`, SQLite-backed mock `Provider` each, plus `health_check` and `get_account_state`.
**Exit:** each server's acceptance checklist (end of `provisioning-mcp.md`) passes; snapshot tests committed; `docker/seed/*.json` loadable.
**Prompt:**
> Implement mcp/<server>-server per docs/contracts/provisioning-mcp.md §<n> and docs/contracts/00-conventions.md. Create the Pydantic models and one tool per row of the tool table with exactly those names and inputs. Put behavior in a Provider interface with a SQLite mock implementation; keep tools thin. Implement outcomes per conventions §3 (CREATED/EXISTS+drift/NO_CHANGE/NATURAL_KEY_CONFLICT), dry_run, execution-grant verification, idempotency keys, governance flags + MCP annotations + manifest. Add tests: success, EXISTS/NO_CHANGE, dry-run has no side effect, missing/invalid grant, retryable error, replay, plus the contract snapshot. Finish by ticking every item of the acceptance checklist.

## Phase 2 — Knowledge MCP
**Deliver:** everything in `knowledge-mcp.md`, seed per `knowledge-model.md`.
**Exit:** acceptance checklist §9 passes; temporal worked example passes at four query points; `make seed` idempotent.
**Prompt:**
> Implement mcp/knowledge-server per docs/contracts/knowledge-mcp.md in this order, one commit each: (1) SQLAlchemy models, Alembic migration, append-only triggers, commit counter; (2) domain/temporal.py resolution + hypothesis property tests; (3) seed loader with relative dates and the dataset in docs/knowledge-model.md; (4) normalization, scoring and EXACT/AMBIGUOUS/NONE resolution; (5) entitlement search/get/history, provisionable computation, check_entitlement_usable; (6) replacement, dependency closure (topological, cycle-safe), conflicts; (7) policy documents, state snapshots, version info; (8) restricted expression parser (no eval), derive/validate tools; (9) proposal store, lifecycle tables in §6.2, impact preview, apply with grant verification. Keep tools thin and logic in domain/.

## Phase 3 — Platform MCPs
**Deliver:** policy, approval, audit, memory, notification per `platform-mcps.md`.
**Exit:** §6 checklist passes; FinanceReader v1 vs v2 decisions differ; audit tamper test passes.
**Prompt:**
> Implement the five servers in docs/contracts/platform-mcps.md. Start with the Policy engine as pure functions (three-valued conditions, deny-overrides, default-deny, approval merge, deterministic decision_id) with exhaustive table-driven tests, then the MCP wrappers reading policies from the Knowledge MCP via libs/mcp_common/client. Then Approval (requests, separation of duties, issue_execution_grant with the preconditions in §3.2), Audit (hash chain, timeline completeness, reconstruct_decision, verify_chain), Memory (hybrid ranking, dedupe, conflict flags; write tools llm_exposed=false), Notification (templates only).

## Phase 4 — Agent core
**Deliver:** capability registry + discovery, LLM abstraction with mock cassettes, workflow engine as data, all state implementations, plan model, validator V1–V14, executor with retry and compensation, verifier, skills loader (frontmatter parsed, allowlist enforced).
**Exit:** scenarios 1, 2, 3, 6 run end-to-end against the mock servers with the mock LLM; eval categories RET, RSN, EXE pass.
**Prompt:**
> Implement Phase 4 under agent/ following docs/agent-workflow.md, docs/provisioning.md and docs/mcp.md. Build in this order: registry + discovery with schema pinning; LLMProvider interface and MockCassetteProvider; workflow engine driven by a transition table with workflow_runs persistence and resume; states RECEIVE_REQUEST→DONE; plan models and plan_hash; validator checks V1–V14 as separate functions with tests; executor (grants, idempotency keys, tenacity retry for RETRYABLE+idempotent, compensation in reverse order); verifier; skills loader that enforces allowed_tools ∩ llm_exposed. The agent must not import any server package (make arch).

## Phase 5 — Reconciliation, change pipeline, learning, UI
**Deliver:** reconciliation request type and drift report; Knowledge change flows (deprecate entitlement, publish policy version) through proposal → approval → grant → apply; incident-recovery suggestions; memory learner; minimal UI (request box, run timeline from audit, approvals inbox, knowledge version/diff view).
**Exit:** scenarios 4, 5, 7 pass; UI shows a run timeline from `get_request_timeline`.
**Prompt:**
> Implement Phase 5. Add the reconciliation flow from docs/provisioning.md §2 (report drift between Knowledge and provider state; remediation as a normal plan, REMOVE needs policy and approval). Wire the Knowledge change pipeline (docs/contracts/knowledge-mcp.md §6) into the agent for DEPRECATE_ENTITLEMENT and PUBLISH_POLICY_VERSION including simulate_policy_change. Implement agent/memory/learner.py per docs/memory.md. Build a static HTML/JS UI served by agent-api: submit request, live timeline, approve/reject inbox (authenticated demo user), knowledge version and diff.

## Phase 6 — Evals, scenarios, hardening
**Deliver:** all eval cases in `docs/evaluation.md` as YAML + runner, nine demo scenarios, final acceptance test, docker compose end-to-end, README quickstart, CI green.
**Exit:** `make eval` 100% on deterministic cases; `make demo SCENARIO=1..9` works; `make acceptance` passes from a clean `docker compose up`.
**Prompt:**
> Implement the eval runner and every case in docs/evaluation.md as data under tests/end-to-end/evals/cases, asserting on structured results and audit events only. Add `make demo` and `make acceptance` (final acceptance test, `SEED_PROFILE=acceptance`). Run the whole suite from a clean compose environment, fix flakiness (no real clock, no network), and update README quickstart and docs for anything that changed.
