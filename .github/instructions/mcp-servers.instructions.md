---
applyTo: "mcp/**"
---
# MCP server rules
- Contract source of truth: `docs/contracts/` (conventions C1–C9 apply to every server). Tool names, inputs and outputs must match exactly.
- Use `from mcp.server.fastmcp import FastMCP`. Serve Streamable HTTP at `/mcp`. Keep tool functions thin: validate input, call a domain/provider function, return the Pydantic output model.
- One Pydantic input and one output model per tool. Return structured output, never free text. Errors in-band via `ToolError`.
- Publish governance twice: MCP annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`) and the `iam://server/manifest` resource.
- Writes: verify the execution grant with `libs/mcp_common/grants.py`, honor `dry_run`, store idempotency keys, return `EXISTS`/`NO_CHANGE` instead of mutating on create.
- Provisioners implement `health_check` and `get_account_state`. Keep the mock behind a `Provider` interface so a real backend can replace it.
- Never import `agent` or another server package. Shared code goes in `libs/`.
- Every tool needs: success, idempotent replay, dry-run, missing-grant and error-path tests, plus the contract snapshot test.
