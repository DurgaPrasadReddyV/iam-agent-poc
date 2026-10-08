# 00 · MCP Contract Conventions

Applies to **every** MCP server in this repo: `knowledge`, `policy`, `memory`, `approval`, `audit`, `notification`, `ad`, `sql`, `linux`, `app` and any future target system.
Contract version `1.0.0` · Python 3.12 · Pydantic v2 · official `mcp` Python SDK (`from mcp.server.fastmcp import FastMCP`) · transport: Streamable HTTP at `/mcp` in Docker, stdio in unit tests. The Pydantic contracts must NOT depend on the SDK, so the SDK (or the standalone `fastmcp` package) can be swapped.

## 1. Rules

| # | Rule |
|---|---|
| C1 | One Pydantic input model and one Pydantic output model per tool. Return structured output (the SDK publishes `outputSchema` + `structuredContent`). Never return free text. |
| C2 | Tool names are `snake_case` and exactly as written in the contract docs. Do not rename or add tools without updating the contract + tests. |
| C3 | Timestamps are tz-aware ISO-8601 UTC. Dates are `YYYY-MM-DD` (= 00:00:00Z; start inclusive, end exclusive). |
| C4 | No secrets in inputs, outputs, logs or audit. Use `credential_ref` (vault reference). |
| C5 | Write tools: idempotent, support `dry_run`, never mutate an existing object on `create_*`, and reject calls without a valid `execution_grant` (`STRICT_GRANTS=true` by default). |
| C6 | Read tools are side-effect free. Actual-state reads stamp `observed_at`. |
| C7 | Errors are returned in-band (`error: ToolError`). Raise MCP protocol errors only for malformed calls. |
| C8 | Every server publishes the manifest resource `iam://server/manifest` (§6). |
| C9 | The agent never imports server code. Only `libs/iam_contracts` is shared between agent and servers. |

Notation used in the contract docs: every tool input implicitly contains `context: ToolContext`; write tools also contain `dry_run: bool = False`. `field*` = required, `field=value` = default.

## 2. Shared types (`libs/iam_contracts/common.py`)

```python
from datetime import datetime
from typing import Any, Generic, Literal, TypeVar
from pydantic import BaseModel, Field

T = TypeVar("T")
SystemId = str   # "ACTIVE_DIRECTORY" | "SQL_SERVER" | "LINUX" | "APP_X" | "APP_Y" | ...  (data-driven, NOT an Enum)
AttrValue = str | int | float | bool | list[str] | None
RiskLevel = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
ExecutionStatus = Literal["SUCCESS", "PARTIAL_SUCCESS", "FAILED", "RETRYABLE", "BLOCKED"]
Outcome = Literal["CREATED", "UPDATED", "DELETED", "EXISTS", "NO_CHANGE", "DRY_RUN"]
ErrorCode = Literal[
    "VALIDATION_ERROR", "NOT_FOUND", "PRECONDITION_FAILED", "PROTECTED_OBJECT", "PROTECTED_ATTRIBUTE",
    "UNSUPPORTED_OPERATION", "NATURAL_KEY_CONFLICT", "GRANT_REQUIRED", "GRANT_INVALID",
    "PERMISSION_DENIED", "CONCURRENT_MODIFICATION", "RATE_LIMITED", "TIMEOUT",
    "PROVIDER_UNAVAILABLE", "INTERNAL_ERROR",
]

class ToolContext(BaseModel):
    request_id: str
    plan_id: str | None = None
    action_id: str | None = None
    actor: str                                # "agent:iam-orchestrator" | "user:<id>" | "system:<svc>"
    agent_model: str | None = None            # model that proposed the plan (audit)
    trace_id: str | None = None
    knowledge_version: int | None = None
    policy_set_version: str | None = None
    idempotency_key: str | None = None        # sha256(plan_id + ":" + action_id), set by the executor
    execution_grant: str | None = None        # signed token, see §5

class ReadInput(BaseModel):
    context: ToolContext

class WriteInput(ReadInput):
    dry_run: bool = False

class ToolError(BaseModel):
    code: ErrorCode
    message: str
    retryable: bool = False
    details: dict[str, Any] = {}

class ResourceRef(BaseModel):
    system_id: SystemId
    object_type: str                          # USER | GROUP | LOGIN | DB_USER | ROLE | PERMISSION | SUDO_RULE | MEMBERSHIP ...
    native_id: str
    scope: dict[str, str] = {}                # {"host": "lx-prod-01"} | {"database": "FinanceDB"}

class FieldChange(BaseModel):
    field: str
    before: AttrValue = None
    after: AttrValue = None

class AttributeChange(BaseModel):
    attribute: str
    op: Literal["SET", "CLEAR", "ADD_VALUE", "REMOVE_VALUE"] = "SET"
    value: AttrValue = None

class ReadResult(BaseModel, Generic[T]):
    found: bool
    data: T | None = None
    observed_at: datetime
    error: ToolError | None = None

class WriteResult(BaseModel, Generic[T]):
    status: ExecutionStatus
    outcome: Outcome | None = None            # None when FAILED / BLOCKED / RETRYABLE
    predicted_outcome: Outcome | None = None  # only when dry_run=True
    target: ResourceRef
    before: T | None = None
    after: T | None = None                    # state READ BACK from the provider after the write
    changes: list[FieldChange] = []           # applied (or predicted) changes
    drift: list[FieldChange] = []             # create_* returned EXISTS: requested-vs-existing differences
    replayed: bool = False                    # served from the idempotency store
    provider_ref: str | None = None
    executed_at: datetime
    error: ToolError | None = None
```

Define a named subclass per tool for readable schemas, e.g. `class CreateGroupResult(WriteResult[ADGroup]): ...`.

## 3. Outcome & idempotency semantics (all provisioners)

| Situation | `status` | `outcome` / error |
|---|---|---|
| `create_*`, object absent | SUCCESS | `CREATED` |
| `create_*`, object already exists | SUCCESS | `EXISTS` + `after`=current state + `drift`=diff vs request. **Never modifies.** The agent decides whether an update is needed. |
| `create_*`, natural keys match **different** objects | BLOCKED | `NATURAL_KEY_CONFLICT` (do not guess) |
| update / set / add / grant, values differ | SUCCESS | `UPDATED` (or `CREATED` for a new membership/grant) |
| update / set / add / grant, already in desired state | SUCCESS | `NO_CHANGE` |
| remove / revoke / delete / disable, already absent/revoked | SUCCESS | `NO_CHANGE` |
| mutate, target not found | FAILED | `NOT_FOUND` |
| `dry_run=true` | SUCCESS | `DRY_RUN` + `predicted_outcome` + `changes`; no side effect; consumes no idempotency key |
| missing / invalid grant | BLOCKED | `GRANT_REQUIRED` / `GRANT_INVALID` |
| protected object/attribute, blocked privileged permission | BLOCKED | `PROTECTED_OBJECT` / `PROTECTED_ATTRIBUTE` |
| transient: `RATE_LIMITED`, `TIMEOUT`, `PROVIDER_UNAVAILABLE`, `CONCURRENT_MODIFICATION` | RETRYABLE | `retryable=true` |
| multi-step write inside one tool partly done | PARTIAL_SUCCESS | `details.completed_steps` |
| anything else | FAILED | `VALIDATION_ERROR`, `PRECONDITION_FAILED`, `PERMISSION_DENIED`, `INTERNAL_ERROR` |

**Idempotency-key store:** servers keep `idempotency_key → WriteResult` for ≥ 24 h. A replay returns the stored result with `replayed=true` and performs no side effect.
**Retry rule (executor):** retry only when `status=RETRYABLE` and `idempotent=true`. If `destructive=true`, re-read actual state first and retry only if the effect has not already happened. Never blind-retry destructive operations.
**Compensation:** only via the tool's declared `compensating_tool`, in reverse order, only for actions that reported `CREATED`/`UPDATED` (never for `EXISTS`/`NO_CHANGE`).

## 4. Tool governance declaration

```python
class ToolGovernance(BaseModel):
    tool: str
    capability: str | None            # neutral tag from §7, e.g. "group.add_member"
    read_only: bool
    requires_approval: bool           # FLOOR: an APPROVED approval (human or policy-auto) must back the grant
    risk_level: RiskLevel
    idempotent: bool
    supports_dry_run: bool
    destructive: bool = False         # removes/reduces access or deletes objects
    compensating_tool: str | None = None
    llm_exposed: bool = True          # False => only deterministic services may call it (hidden from the LLM)
    object_type: str | None = None    # e.g. LOGIN vs DB_USER when two tools share a capability
```

Publish governance in **two** places: (a) standard MCP tool annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`), (b) the manifest resource (§6) for the custom flags. Do not rely on clients preserving custom fields.
Example (from the spec): `{"tool":"create_group","read_only":false,"requires_approval":true,"risk_level":"HIGH","idempotent":true,"supports_dry_run":true}`.
Policy can only make things **stricter** than the tool flags, never looser.

## 5. Execution grant (deterministic write gate)

Every write must carry `context.execution_grant`, minted by the Approval MCP (`issue_execution_grant`, deterministic service only) after `VALIDATE_PLAN` + policy ALLOW or approval APPROVED. Signed (HS256 for POC; asymmetric later). Claims:

```json
{"grant_id":"G-…","request_id":"REQ-123","plan_id":"PLAN-9","plan_hash":"sha256:…","action_id":"A-3",
 "server":"ad","tool":"add_group_member","args_hash":"sha256:…","approval_id":"APR-7|null",
 "policy_decision_id":"PD-…","iat":"…","exp":"+15min","nonce":"…"}
```
`args_hash` = sha256 of canonical JSON of the tool arguments **excluding** `context` and `dry_run`. Providers verify signature, `exp`, `tool`, `args_hash` (shared lib `libs/mcp_common/grants.py`) and return `GRANT_INVALID` otherwise. If the provider's **own** tool has `requires_approval=true`, it also requires a non-null `approval_id` claim (policy-auto approvals count). Result: even a hallucinating LLM cannot execute anything that was not validated (and approved) as exactly those arguments.

## 6. Server manifest (discovery)

Resource `iam://server/manifest` on every server:

```python
class ServerManifest(BaseModel):
    server_name: str                          # "ad"
    server_version: str
    contract_version: str = "1.0.0"
    kind: Literal["PROVISIONER", "KNOWLEDGE", "POLICY", "MEMORY", "APPROVAL", "AUDIT", "NOTIFICATION"]
    system_ids: list[SystemId] = []           # PROVISIONER only
    mock: bool
    capabilities: dict[str, Any] = {}         # {"supports_expiry": false, "object_types": ["USER","GROUP"], ...}
    tools: list[ToolGovernance]
    resources: list[str]
```
The agent's startup discovery = `tools/list` + `resources/list` + manifest → **capability registry** (`docs/mcp.md`). Missing capability ⇒ `CAPABILITY_UNAVAILABLE`.

## 7. Capability tags (neutral operation names)

`account.create` `account.read` `account.update` `account.disable` `account.set_attribute` `account.read_attributes` `account.state`
`group.create` `group.read` `group.delete` `group.add_member` `group.remove_member` `group.read_members`
`role.create` `role.read` `role.add_member` `role.remove_member`
`permission.grant` `permission.revoke` `permission.read`
`privilege.sudo.grant` `privilege.sudo.revoke`
Provisioning plans use these neutral tags; the registry binds tag + `system_id` → `(server, tool)`. Core agent code never contains `"create_group"`-style literals.

## 8. Common provider contract (EVERY provisioner implements)

Beyond its system-specific tools, every provisioning server MUST expose these two tools so reconciliation/verification are provider-agnostic.

```python
class HealthStatus(BaseModel):
    status: Literal["UP", "DEGRADED", "DOWN"]
    checked_at: datetime
    latency_ms: int
    details: dict[str, str] = {}

class ActualEntitlement(BaseModel):
    entitlement_id: str                       # NATIVE id: AD group sAMAccountName, SQL role, Linux group, app role
    entitlement_type: str                     # GROUP | ROLE | PERMISSION | SUDO_RULE | APP_ROLE
    scope: dict[str, str] = {}
    granted_at: datetime | None = None
    expires_at: datetime | None = None
    granted_via: str = "DIRECT"               # DIRECT | NESTED:<group>

class ActualAccountState(BaseModel):
    system_id: SystemId
    account_id: str                           # native primary id (sAMAccountName / login / username / account_id)
    scope: dict[str, str] = {}
    exists: bool
    account_type: str | None = None
    status: Literal["ENABLED", "DISABLED", "LOCKED", "EXPIRED", "UNKNOWN"] | None = None
    attributes: dict[str, AttrValue] = {}
    entitlements: list[ActualEntitlement] = []
    observed_at: datetime
    provider_version: str
```

| Tool | In | Out | Governance |
|---|---|---|---|
| `health_check` | — | `HealthStatus` | read-only · LOW · idempotent |
| `get_account_state` | `account_id*`, `scope={}` (SQL: `database?`; Linux: `host*`; App: `system_id*`) | `ReadResult[ActualAccountState]` | `account.state` · read-only · LOW · idempotent |

## 9. Versioning & contract tests

* `contract_version` is semver. Breaking change ⇒ new tool name `<tool>_v2`; keep the old one until the agent is migrated.
* `tests/mcp/test_contracts.py` snapshots the tool list + JSON Schemas of each server and fails on drift.
* Every server ships an in-memory MCP client test that exercises each tool: success, `EXISTS`/`NO_CHANGE`, dry-run, missing grant, retryable error.
