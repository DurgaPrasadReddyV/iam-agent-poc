# AGENTS.md: approval MCP server

Port **8121** · package `approval_server` (`mcp/approval-server/src/approval_server`) · Phase 3
Contract: `docs/contracts/platform-mcps.md (section 3)`

## Specific rules
* The only service that mints execution grants (`issue_execution_grant`, CRITICAL, `llm_exposed=false`). Key from `GRANT_SIGNING_KEY`.
* Approvals bind to `subject_hash`; enforce requester != approver; auto-approval only through the policy-auto path with verified evidence.
* A deterministic sweeper expires approvals (`expire_approvals`).

## Common rules
* `docs/contracts/00-conventions.md` (C1 to C9) applies. Tool names, inputs and outputs match the contract exactly; change the contract and its snapshot test first.
* Use `FastMCP`, Streamable HTTP at `/mcp`. Tools stay thin; logic lives in `domain/` or the `Provider`.
* Publish governance as MCP annotations and in the manifest (`iam://server/manifest`).
* Never import `agent` or another server package; share code through `libs/`.
* Definition of done: the contract's acceptance checklist is fully ticked and `make lint type arch test` is green.
