# AGENTS.md: app MCP server

Port **8114** · package `app_server` (`mcp/app-server/src/app_server`) · Phase 1
Contract: `docs/contracts/provisioning-mcp.md (App section)`

## Specific rules
* SCIM-shaped accounts and roles for `APP_X` and `APP_Y`, scoped by `app_id`.

## Common rules
* `docs/contracts/00-conventions.md` (C1 to C9) applies. Tool names, inputs and outputs match the contract exactly; change the contract and its snapshot test first.
* Use `FastMCP`, Streamable HTTP at `/mcp`. Tools stay thin; logic lives in `domain/` or the `Provider`.
* Publish governance as MCP annotations and in the manifest (`iam://server/manifest`).
* Never import `agent` or another server package; share code through `libs/`.
* Definition of done: the contract's acceptance checklist is fully ticked and `make lint type arch test` is green.
