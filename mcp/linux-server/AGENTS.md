# AGENTS.md: linux MCP server

Port **8113** · package `linux_server` (`mcp/linux-server/src/linux_server`) · Phase 1
Contract: `docs/contracts/provisioning-mcp.md (Linux section)`

## Specific rules
* Host-scoped: every tool takes a `host`. Users, groups, sudo rules per host in SQLite.
* Sudo rules are structured entries; never accept raw sudoers text.

## Common rules
* `docs/contracts/00-conventions.md` (C1 to C9) applies. Tool names, inputs and outputs match the contract exactly; change the contract and its snapshot test first.
* Use `FastMCP`, Streamable HTTP at `/mcp`. Tools stay thin; logic lives in `domain/` or the `Provider`.
* Publish governance as MCP annotations and in the manifest (`iam://server/manifest`).
* Never import `agent` or another server package; share code through `libs/`.
* Definition of done: the contract's acceptance checklist is fully ticked and `make lint type arch test` is green.
