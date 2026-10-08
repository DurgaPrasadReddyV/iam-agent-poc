# AGENTS.md: policy MCP server

Port **8103** · package `policy_server` (`mcp/policy-server/src/policy_server`) · Phase 3
Contract: `docs/contracts/platform-mcps.md (section 1)`

## Specific rules
* The engine (`engine/`) is pure functions: three-valued conditions, deny-overrides, default-deny, deterministic `decision_id`.
* Policies come from the Knowledge MCP (MCP client), cached by `knowledge_version`.
* No LLM, no clock reads inside the engine (use `evaluated_at` or the injected Clock).

## Common rules
* `docs/contracts/00-conventions.md` (C1 to C9) applies. Tool names, inputs and outputs match the contract exactly; change the contract and its snapshot test first.
* Use `FastMCP`, Streamable HTTP at `/mcp`. Tools stay thin; logic lives in `domain/` or the `Provider`.
* Publish governance as MCP annotations and in the manifest (`iam://server/manifest`).
* Never import `agent` or another server package; share code through `libs/`.
* Definition of done: the contract's acceptance checklist is fully ticked and `make lint type arch test` is green.
