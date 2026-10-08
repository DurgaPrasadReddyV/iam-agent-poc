# AGENTS.md: memory MCP server

Port **8102** · package `memory_server` (`mcp/memory-server/src/memory_server`) · Phase 3
Contract: `docs/contracts/platform-mcps.md (section 2)`

## Specific rules
* Memory is non-authoritative. Write tools are `llm_exposed=false`; only `agent/memory/learner.py` writes.
* Hybrid ranking (lexical + recency + reinforcement + confidence + subject boost); embeddings optional and off by default.
* Reject secrets and content over 1000 characters.

## Common rules
* `docs/contracts/00-conventions.md` (C1 to C9) applies. Tool names, inputs and outputs match the contract exactly; change the contract and its snapshot test first.
* Use `FastMCP`, Streamable HTTP at `/mcp`. Tools stay thin; logic lives in `domain/` or the `Provider`.
* Publish governance as MCP annotations and in the manifest (`iam://server/manifest`).
* Never import `agent` or another server package; share code through `libs/`.
* Definition of done: the contract's acceptance checklist is fully ticked and `make lint type arch test` is green.
