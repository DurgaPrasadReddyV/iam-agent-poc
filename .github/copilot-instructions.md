# Copilot instructions — IAM Agent POC

Read `AGENTS.md` first. It is the source of truth for rules, import boundaries and the working loop.

Core principle: the LLM proposes; deterministic code validates, authorizes, executes and verifies.

Where things are:
- MCP contracts (inputs and outputs of every tool): `docs/contracts/` — `00-conventions.md`, `provisioning-mcp.md`, `knowledge-mcp.md`, `platform-mcps.md`.
- Architecture and workflow: `docs/architecture.md`, `docs/agent-workflow.md`.
- Phase plan with prompts: `docs/implementation-plan.md`. Work one phase at a time.
- Skills: `skills/*/SKILL.md`. Evals: `docs/evaluation.md`.

Always:
- Implement tools exactly as named and typed in the contracts. Do not rename or add tools without updating the contract and its snapshot test.
- Use Python 3.12, Pydantic v2, type hints, `ruff`, `mypy --strict`. Write tests with the code.
- Use the injected `Clock`. Never call `datetime.now()` in domain code.
- Never let LLM text become a tool name or argument without validation. Never invent entitlement ids.
- Never put secrets in code, logs or audit.
- Ask for the contract section when a requirement is unclear instead of guessing.
