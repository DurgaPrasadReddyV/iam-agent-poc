# AGENTS.md: audit MCP server

Port **8122** · package `audit_server` (`mcp/audit-server/src/audit_server`) · Phase 3
Contract: `docs/contracts/platform-mcps.md (section 4)`

## Specific rules
* Append-only hash chain under a single writer lock; DB triggers forbid UPDATE/DELETE.
* Reject secret-looking payload keys. `reconstruct_decision` must answer from audit alone.
* No update or delete tool may exist.

## Common rules
* `docs/contracts/00-conventions.md` (C1 to C9) applies. Tool names, inputs and outputs match the contract exactly; change the contract and its snapshot test first.
* Use `FastMCP`, Streamable HTTP at `/mcp`. Tools stay thin; logic lives in `domain/` or the `Provider`.
* Publish governance as MCP annotations and in the manifest (`iam://server/manifest`).
* Never import `agent` or another server package; share code through `libs/`.
* Definition of done: the contract's acceptance checklist is fully ticked and `make lint type arch test` is green.
