# MCP Servers, Discovery and the Capability Registry

## Server catalog
| Server | Port | Kind | Package (`mcp/<dir>/src/<pkg>`) | Contract |
|---|---|---|---|---|
| knowledge | 8101 | KNOWLEDGE | `knowledge-server` / `knowledge_server` | `contracts/knowledge-mcp.md` |
| memory | 8102 | MEMORY | `memory-server` / `memory_server` | `contracts/platform-mcps.md §2` |
| policy | 8103 | POLICY | `policy-server` / `policy_server` | `contracts/platform-mcps.md §1` |
| ad | 8111 | PROVISIONER | `ad-server` / `ad_server` | `contracts/provisioning-mcp.md §1` |
| sql | 8112 | PROVISIONER | `sql-server` / `sql_server` | `contracts/provisioning-mcp.md §2` |
| linux | 8113 | PROVISIONER | `linux-server` / `linux_server` | `contracts/provisioning-mcp.md §3` |
| app | 8114 | PROVISIONER | `app-server` / `app_server` | `contracts/provisioning-mcp.md §4` |
| approval | 8121 | APPROVAL | `approval-server` / `approval_server` | `contracts/platform-mcps.md §3` |
| audit | 8122 | AUDIT | `audit-server` / `audit_server` | `contracts/platform-mcps.md §4` |
| notification | 8123 | NOTIFICATION | `notification-server` / `notification_server` | `contracts/platform-mcps.md §5` |

Transport: Streamable HTTP at `/mcp` in Docker, in-memory/stdio in tests. Each server exposes `iam://server/manifest` (conventions §6).

## Discovery (startup, then every 60 s)
1. For each URL in config: `initialize`, `tools/list`, `resources/list`, read the manifest.
2. Verify `contract_version` is compatible and each tool's input/output schema hash equals the pinned snapshot in `tests/mcp/snapshots/` (drift ⇒ tool disabled + `CAPABILITY_UNAVAILABLE`).
3. Call `health_check` on provisioners. `DOWN` ⇒ its capabilities are unavailable until healthy.
4. Build the registry:
```python
class CapabilityBinding(BaseModel):
    capability: str; system_id: str; object_type: str | None
    server: str; tool: str; governance: ToolGovernance; input_schema: dict; healthy: bool

class CapabilityRegistry(Protocol):
    def bind(self, capability: str, system_id: str, object_type: str | None = None) -> CapabilityBinding | None: ...
    def tools_for_llm(self, skill: SkillSpec) -> list[ToolDef]: ...   # allowlist ∩ llm_exposed, schemas included
    def governance(self, server: str, tool: str) -> ToolGovernance: ...
```
`bind` returns `None` ⇒ `CAPABILITY_UNAVAILABLE` (audited, refused before planning). Two tools sharing one capability on a system (SQL `create_login` vs `create_database_user`) are separated by `object_type`.

## Which tools the LLM can see
A skill's `allowed_tools` lists everything its steps may invoke: `server.tool` entries for platform servers and `capability:<tag>` entries for provider operations.
* **LLM-callable tools** = `server.tool` entries **∩** `llm_exposed=true` **∩** `read_only=true`. Provisioner tools are never given to the LLM in the POC: the LLM drafts a plan, the executor calls them.
* `capability:<tag>` entries constrain the **plan**: the validator rejects any action whose capability is not listed, and the executor will only run listed capabilities for that skill.
* Deterministic steps of the skill (for example `approval.create_approval_request`) may call listed tools that have `llm_exposed=false`.
* Engine infrastructure is not skill-scoped: audit append, grant minting, notifications, workflow persistence.
* Every call carries its skill context; a call outside the allowed set is rejected and audited as `SAFETY_BLOCKED`.

## MCP client rules (`libs/mcp_common/client.py`)
Timeouts per call · automatic retry only for read tools · OpenTelemetry span per call with `request_id` · inject `ToolContext` centrally (never built by the LLM) · reject responses that do not validate against the output model.

## Adding a new target system (checklist)
1. Add `system_id`, account schema and naming rules to `knowledge/seed/*.yaml` (and entitlements).
2. Implement a provisioner server from the template: the common provider contract (`health_check`, `get_account_state`) plus system tools.
3. Publish the manifest with capability tags from conventions §7 (add new tags to the conventions first).
4. Add `agent/execution/bindings/<system>.yaml` mapping tags → tools and neutral args → tool args.
5. Add contract snapshot + acceptance tests; add one eval case per supported operation.
6. No change to orchestrator, planner or validator code. If you needed one, the abstraction leaked: fix the abstraction.
