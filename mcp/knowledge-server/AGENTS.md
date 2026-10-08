# AGENTS.md: knowledge MCP server

Port **8101** · package `knowledge_server` (`mcp/knowledge-server/src/knowledge_server`) · Phase 2
Contract: `docs/contracts/knowledge-mcp.md`

## Specific rules
* Read section 2 (temporal model) before writing any query. Resolution lives in `domain/temporal.py` as pure functions with property tests.
* Rows are append-only: never UPDATE or DELETE (triggers enforce it). `valid_to`, `superseded_by`, `updated_at` are computed at read time.
* `apply_knowledge_change` is the only tool that writes knowledge; it requires an execution grant and is `llm_exposed=false`.
* Seed through the same append path (`seed/loader.py`); data lives in `knowledge/`.

## Common rules
* `docs/contracts/00-conventions.md` (C1 to C9) applies. Tool names, inputs and outputs match the contract exactly; change the contract and its snapshot test first.
* Use `FastMCP`, Streamable HTTP at `/mcp`. Tools stay thin; logic lives in `domain/` or the `Provider`.
* Publish governance as MCP annotations and in the manifest (`iam://server/manifest`).
* Never import `agent` or another server package; share code through `libs/`.
* Definition of done: the contract's acceptance checklist is fully ticked and `make lint type arch test` is green.
