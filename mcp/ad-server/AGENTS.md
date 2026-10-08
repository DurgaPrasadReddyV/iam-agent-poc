# AGENTS.md: ad MCP server

Port **8111** · package `ad_server` (`mcp/ad-server/src/ad_server`) · Phase 1
Contract: `docs/contracts/provisioning-mcp.md (AD section)`

## Specific rules
* Mock directory in SQLite: users, groups, memberships, attributes. `sam_account_name` is the natural key; the DN is derived from the OU.
* Protected attributes (`objectSid`, `adminCount`, `userAccountControl`) are never writable.
* Generate credentials in the mock vault and return only `credential_ref`.

## Common rules
* `docs/contracts/00-conventions.md` (C1 to C9) applies. Tool names, inputs and outputs match the contract exactly; change the contract and its snapshot test first.
* Use `FastMCP`, Streamable HTTP at `/mcp`. Tools stay thin; logic lives in `domain/` or the `Provider`.
* Publish governance as MCP annotations and in the manifest (`iam://server/manifest`).
* Never import `agent` or another server package; share code through `libs/`.
* Definition of done: the contract's acceptance checklist is fully ticked and `make lint type arch test` is green.
