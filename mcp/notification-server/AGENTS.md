# AGENTS.md: notification MCP server

Port **8123** · package `notification_server` (`mcp/notification-server/src/notification_server`) · Phase 3
Contract: `docs/contracts/platform-mcps.md (section 5)`

## Specific rules
* Templates and parameters only. Never send free-form LLM text. Outbox table + UI view; duplicates suppressed by `dedupe_key`.

## Common rules
* `docs/contracts/00-conventions.md` (C1 to C9) applies. Tool names, inputs and outputs match the contract exactly; change the contract and its snapshot test first.
* Use `FastMCP`, Streamable HTTP at `/mcp`. Tools stay thin; logic lives in `domain/` or the `Provider`.
* Publish governance as MCP annotations and in the manifest (`iam://server/manifest`).
* Never import `agent` or another server package; share code through `libs/`.
* Definition of done: the contract's acceptance checklist is fully ticked and `make lint type arch test` is green.
