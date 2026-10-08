# AGENTS.md: sql MCP server

Port **8112** · package `sql_server` (`mcp/sql-server/src/sql_server`) · Phase 1
Contract: `docs/contracts/provisioning-mcp.md (SQL section)`

## Specific rules
* Mock: logins, database users, roles, role members, permissions. `login_name` is the natural key; grants are per database.
* `create_login` on an existing login returns `EXISTS` plus drift (scenario 6), never a duplicate or an overwrite.

## Common rules
* `docs/contracts/00-conventions.md` (C1 to C9) applies. Tool names, inputs and outputs match the contract exactly; change the contract and its snapshot test first.
* Use `FastMCP`, Streamable HTTP at `/mcp`. Tools stay thin; logic lives in `domain/` or the `Provider`.
* Publish governance as MCP annotations and in the manifest (`iam://server/manifest`).
* Never import `agent` or another server package; share code through `libs/`.
* Definition of done: the contract's acceptance checklist is fully ticked and `make lint type arch test` is green.
