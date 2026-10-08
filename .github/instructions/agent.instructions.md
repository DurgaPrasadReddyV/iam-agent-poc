---
applyTo: "agent/**"
---
# Agent rules
- The workflow is a deterministic state machine defined as data (`docs/agent-workflow.md`). The LLM is used only inside UNDERSTAND_INTENT and GENERATE_PLAN, with structured output.
- Never import server packages. Call servers through the MCP client and the capability registry. Plans use neutral capability tags, not tool names.
- Filter tools by `llm_exposed` and by the active skill's `allowed_tools` in code.
- Pin `knowledge_version` once at LOAD_CURRENT_KNOWLEDGE and pass it on every later read. If `head_version` moved before EXECUTE, re-plan.
- Plan validation must check: referenced ids resolved this run, entitlements usable, dependencies ordered, conflicts absent, policy ALLOW, dry-run equals expected, capabilities available.
- Execute only with grants. Retry only `RETRYABLE` + idempotent. Compensate only via declared `compensating_tool`, in reverse order, only for `CREATED`/`UPDATED` actions.
- Report success only after VERIFY_STATE. All terminal states pass through WRITE_AUDIT.
- Persist every transition to `workflow_runs` so a run can resume after approval or a crash.
- Inject `Clock`, `IdGenerator` and `LLMProvider`. Tests use mock cassettes.
