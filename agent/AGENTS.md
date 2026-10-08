# AGENTS.md: agent (orchestrator, planner, validator, executor, verifier)

Serves `agent-api` on port **8000** (HTTP API and the static UI) · Phases 4 and 5
Docs: `docs/agent-workflow.md`, `docs/provisioning.md`, `docs/mcp.md`, `docs/memory.md`, `docs/security.md`

## Layout
`orchestrator/` engine and transition table · `planning/` intent, plan generation, LLM abstraction · `validation/` checks V1 to V14 · `approval/` approval and grant handling · `execution/` executor, retry, compensation, capability bindings · `verification/` verifier and reconciliation · `memory/` learner.

## Rules
* **Never import a server package** (`make arch`). Talk to servers only through `libs/mcp_common/client.py` and the capability registry.
* The LLM runs only in UNDERSTAND_INTENT and GENERATE_PLAN, through `LLMProvider` with structured output and one repair attempt.
* Plans carry neutral capability tags; bindings are data (`execution/bindings/*.yaml`).
* The workflow is a transition table (data) executed by a small engine; every state function is idempotent and persisted in `workflow_runs`.
* Pin `knowledge_version` once; compare `head_version` before EXECUTE.
* Inject `Clock`, `IdGenerator`, `LLMProvider`. Tests use mock cassettes.
* Definition of done: the Phase 4 or 5 exit criteria in `docs/implementation-plan.md` and the matching eval categories pass.
