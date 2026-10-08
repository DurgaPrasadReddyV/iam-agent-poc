# Knowledge MCP Contract

The **authoritative, temporal, append-only catalog** of what exists and what may be requested: systems, account schemas, identities, recorded accounts and assignments, entitlements (groups, roles, permissions, app roles) with lifecycle and relationships, and policy documents.
Port **8101** · `kind=KNOWLEDGE` · package `knowledge_server` in `mcp/knowledge-server/` · Phase 2. Read `00-conventions.md` first.

**Knowledge is not live state.** It stores *recorded desired/assigned state*. Actual state always comes from a provisioner's `get_account_state`. Reconciliation = Knowledge (desired) vs provider (actual).

| Principle | Meaning |
|---|---|
| Authoritative | Every response carries `meta.authoritative=true` and the `knowledge_version` it was computed at. Memory or LLM text never overrides it. |
| Append-only | Rows are never updated or deleted (DB triggers enforce it). A change is a new row. |
| Deterministic | No LLM, no embeddings. Same input + same selector ⇒ identical output. Time comes from an injected `Clock`. |
| Explained refusals | An unusable entitlement is *found*, with status, verdict, reason and replacement. Never a bare "not found". |
| Pinned reads | The workflow pins `knowledge_version` once (state LOAD_CURRENT_KNOWLEDGE) and passes it on every later read. `meta.head_version > meta.knowledge_version` is the stale-plan signal. |

---

## 1. Architecture

```
MCP tools (thin: Pydantic in/out, no logic)
   └─► domain/  pure functions, no I/O, injected Clock:
         temporal (resolution) · search (normalize+rank) · lifecycle (entitlement FSM)
         graph (replacement chain, dependency closure, conflicts) · expr (restricted expression language)
         proposals (proposal FSM, impact preview) · validation
   └─► repo/    SQLAlchemy 2 + Alembic, append-only writes, one transaction per commit
   └─► SQLite   data/knowledge.db
seed/loader ──► repo (same append path, relative dates, §7)
```

| Table | Versioned entity | Natural key |
|---|---|---|
| `knowledge_commits` | one row per commit: `kv` (global counter), `committed_at`, `proposal_id`, `actor`, `content_hash` | `kv` |
| `systems` | System | `system_id` |
| `account_schemas` | AccountSchema (attributes + naming rules) | `system_id, account_type` |
| `identities` | Identity (HR fixture) | `identity_id` |
| `account_records` | AccountRecord (recorded accounts) | `system_id, account_id, scope` |
| `entitlements` | Entitlement (groups, roles, permissions, app roles) | `entitlement_id` |
| `entitlement_relationships` | DEPENDS_ON / CONFLICTS_WITH / REPLACES. Ending one = new row with `active=false` | `relationship_id` |
| `policies` | PolicyVersion | `policy_id` |
| `assignments` | AssignmentRecord. Ending one = new row with `status=ENDED` | `assignment_id` |
| `knowledge_proposals`, `proposal_events` | **Not** append-only knowledge. The mutable proposal workflow store and its event log | `proposal_id` |
| `idempotency` | `idempotency_key → ApplyResult` (≥ 24 h) | key |

Every versioned table has the same columns: `row_id, <entity>_id, version, knowledge_version, valid_from, valid_to, change_id, created_at, created_by` + the typed payload.

```sql
CREATE TABLE entitlements (
  row_id            INTEGER PRIMARY KEY,
  entitlement_id    TEXT    NOT NULL,                 -- stable logical id, e.g. APP_X_ADMIN
  version           INTEGER NOT NULL,                 -- per entitlement, starts at 1
  knowledge_version INTEGER NOT NULL REFERENCES knowledge_commits(kv),
  system_id         TEXT    NOT NULL,
  native_id         TEXT    NOT NULL,                 -- id inside the target system
  entitlement_type  TEXT    NOT NULL CHECK (entitlement_type IN ('GROUP','ROLE','PERMISSION','SUDO_RULE','APP_ROLE')),
  scope_json        TEXT    NOT NULL DEFAULT '{}',    -- {"database":"FinanceDB"} / {"host":"lx-prod-01"}
  display_name      TEXT    NOT NULL,
  description       TEXT,
  status            TEXT    NOT NULL CHECK (status IN ('PROPOSED','ACTIVE','DEPRECATED','RETIRED','BLOCKED')),
  requestable       INTEGER NOT NULL DEFAULT 1,
  risk_level        TEXT    NOT NULL CHECK (risk_level IN ('LOW','MEDIUM','HIGH','CRITICAL')),
  owner             TEXT,
  tags_json         TEXT    NOT NULL DEFAULT '[]',
  aliases_json      TEXT    NOT NULL DEFAULT '[]',
  deprecation_json  TEXT,                             -- DeprecationInfo
  valid_from        TEXT    NOT NULL,                 -- ISO-8601 UTC, effective time (may be in the future)
  valid_to          TEXT,                             -- EXPLICIT sunset only; otherwise computed at read time
  change_id         TEXT,                             -- proposal that created the row
  created_at        TEXT    NOT NULL,
  created_by        TEXT    NOT NULL,
  UNIQUE (entitlement_id, version)
);
CREATE INDEX ix_ent_lookup ON entitlements (system_id, native_id);
CREATE TRIGGER entitlements_no_update BEFORE UPDATE ON entitlements BEGIN SELECT RAISE(ABORT,'append-only'); END;
CREATE TRIGGER entitlements_no_delete BEFORE DELETE ON entitlements BEGIN SELECT RAISE(ABORT,'append-only'); END;
```
Same two triggers on every versioned table (not on `knowledge_proposals`, `proposal_events`, `idempotency`).

---

## 2. Temporal model

Two clocks. **Effective time** (`valid_from`, `as_of`): when something is true in the real world. **Knowledge time** (`knowledge_version`, a global commit counter): when Knowledge learned it. A row's `knowledge_version` = the commit that wrote it.

```python
class TemporalSelector(BaseModel):
    as_of: datetime | None = None            # effective time; default = clock.now()
    knowledge_version: int | None = None     # pin: ignore rows written after this commit; default = head
    known_at: datetime | None = None         # alternative pin by commit time; mutually exclusive with knowledge_version
```
`known_at` → `max(kv) where committed_at <= known_at`. Pin > head → `VALIDATION_ERROR`.

**Resolution** (one entity): candidates = rows with `knowledge_version <= pin` and `valid_from <= as_of` and (`valid_to` is null or `valid_to > as_of`). Winner = greatest `valid_from`; tie → highest `version` (a same-`valid_from` newer version is a *correction*). No candidate but rows exist ⇒ resolve to the earliest visible row and flag `not_yet_effective=true`.

**Computed at read time (never stored):** `valid_to` = next visible row's `valid_from` (else explicit sunset, else null); `superseded_by` = next visible version; `updated_at` = `created_at` of the latest visible row.

**Write rules:** a new row's `valid_from` must be ≥ the latest visible row's `valid_from` for that entity (equal = correction). A future `valid_from` = *scheduled change*; it appears in `LifecycleView.scheduled_changes` and becomes the resolved row once `as_of` reaches it.

**Worked example (seed, `T` = seed "now"):**

| ver | status | valid_from | notes |
|---|---|---|---|
| 1 | PROPOSED | T-540d | |
| 2 | ACTIVE | T-520d | |
| 3 | ACTIVE | T-400d | owner/description update |
| 4 | DEPRECATED | T-120d | `replacement_ids=[APP_X_PLATFORM_ADMIN]`, `retire_at=T+60d` |
| 5 | RETIRED | T+60d | recorded in advance (scheduled) |

| Query | Resolves to |
|---|---|
| `as_of=T`, head | v4 DEPRECATED; `scheduled_changes=[v5 @T+60d]`; `provisionable=false (DEPRECATED)` |
| `as_of=T+61d`, head | v5 RETIRED |
| `as_of=T-200d`, head | v3 ACTIVE (v3.valid_to = T-120d computed) |
| `as_of=T`, pin = commit before v4 was written | v3 ACTIVE (v4 invisible: "what did we know then") |

Seed commits are back-stamped (`committed_at = valid_from`, capped at seed "now") so `known_at` queries work in demos.

---

## 3. Models (`libs/iam_contracts/knowledge.py`)

### 3.1 Envelope and paging
```python
class KnowledgeMeta(BaseModel):
    knowledge_version: int                    # version the answer was computed at
    head_version: int                         # current head (head > knowledge_version ⇒ pinned read is behind)
    as_of: datetime
    authoritative: Literal[True] = True
    selector: TemporalSelector                # as resolved (defaults filled in)

class KnowledgeResult(ReadResult[T], Generic[T]):    # every Knowledge read returns this
    meta: KnowledgeMeta

class Page(BaseModel, Generic[T]):
    items: list[T]; total: int; next_page_token: str | None = None

class EntitlementRef(BaseModel):              # how callers point at an entitlement; at least one field
    entitlement_id: str | None = None; system_id: str | None = None
    native_id: str | None = None; name: str | None = None      # name may be ambiguous → AMBIGUOUS verdict
```
Every versioned entity also carries `version, knowledge_version, valid_from, valid_to (computed), not_yet_effective: bool=False`.

### 3.2 Search results
```python
class Scored(BaseModel, Generic[T]):
    item: T; score: float                     # 0..1
    match: Literal["EXACT_ID","NATIVE_ID","EXACT_NAME","ALIAS","PREFIX","TOKEN","FUZZY"]
    matched_on: str                           # field or alias that matched

class SearchResult(BaseModel, Generic[T]):
    query: str
    resolution: Literal["EXACT","AMBIGUOUS","NONE"]
    items: list[Scored[T]]; total: int; next_page_token: str | None = None
    suggestions: list[str] = []               # near-miss names when NONE
```
Normalization: lower-case, strip all non-alphanumerics (`APP_X_Admin` = `app x admin`). Scores: EXACT_ID/NATIVE_ID 1.0 · EXACT_NAME 0.98 · ALIAS 0.95 · PREFIX 0.85 · TOKEN 0.70–0.84 · FUZZY (Damerau-Levenshtein ratio ≥ 0.82) 0.60–0.80. Sort: score desc, ACTIVE first, id asc.
`resolution=EXACT` iff exactly one item matched via EXACT_ID/NATIVE_ID/EXACT_NAME/ALIAS after filters. `AMBIGUOUS` if ≥ 2 such items, or only PREFIX/TOKEN/FUZZY items ≥ 0.60. Otherwise `NONE`. The agent must clarify on AMBIGUOUS and must never auto-pick.

### 3.3 Catalog entities
```python
EntitlementType = Literal["GROUP","ROLE","PERMISSION","SUDO_RULE","APP_ROLE"]
EntitlementStatus = Literal["PROPOSED","ACTIVE","DEPRECATED","RETIRED","BLOCKED"]
ProvisionableReason = Literal["DEPRECATED","RETIRED","BLOCKED","NOT_YET_EFFECTIVE","NOT_REQUESTABLE","SYSTEM_RETIRED"]

class System(BaseModel):
    system_id: str; display_name: str; kind: Literal["DIRECTORY","DATABASE","OS","APPLICATION"]
    status: Literal["ACTIVE","RETIRED"]; owner: str | None = None; environment: str = "POC"
    account_types: list[str]; entitlement_types: list[EntitlementType]
    attributes: dict[str, AttrValue] = {}     # {"domain":"corp.example.com"}

class AccountAttributeDef(BaseModel):
    name: str; type: Literal["STRING","INT","BOOL","DATE","ENUM","STRING_LIST"]
    required: bool = False; source: Literal["INPUT","DERIVED","SYSTEM_GENERATED"] = "INPUT"
    max_length: int | None = None; pattern: str | None = None          # anchored regex
    enum_values: list[str] = []; derive: str | None = None             # restricted expression, below
    mutable: bool = True; protected: bool = False                      # protected ⇒ agent may never set it
    description: str | None = None

class NamingRule(BaseModel):
    target: Literal["ACCOUNT_ID","GROUP_NAME","ENTITLEMENT_NATIVE_ID"]
    pattern: str                              # anchored regex the result must match
    derive: str | None = None                 # expression, e.g. lower(substr(input.given_name,0,1) + input.surname)
    collision: Literal["APPEND_NUMBER","FAIL"] = "APPEND_NUMBER"; max_length: int | None = None

class AccountSchema(BaseModel):
    system_id: str; account_type: str; attributes: list[AccountAttributeDef]
    naming: list[NamingRule]; defaults: dict[str, AttrValue] = {}      # e.g. {"ou":"OU=Staff,DC=corp"}

class SystemSchema(BaseModel):                # get_system_schema: "everything needed to plan work in this system"
    system: System; account_schemas: list[AccountSchema]
    object_types: list[str]; entitlement_types: list[EntitlementType]

class Identity(BaseModel):
    identity_id: str; employee_id: str; given_name: str; surname: str; display_name: str; email: str
    department: str | None = None; title: str | None = None; manager_id: str | None = None
    employment_status: Literal["ACTIVE","ON_LEAVE","CONTRACTOR","LEAVER"]
    start_date: date | None = None; end_date: date | None = None; attributes: dict[str, AttrValue] = {}

class AccountRecord(BaseModel):
    account_record_id: str; identity_id: str | None = None; system_id: str; account_type: str
    account_id: str; scope: dict[str, str] = {}                        # native primary id
    status: Literal["ACTIVE","DISABLED","DELETED"]; attributes: dict[str, AttrValue] = {}
    registered_via: str | None = None                                  # request_id

class AssignmentRecord(BaseModel):
    assignment_id: str; identity_id: str | None = None; system_id: str; account_id: str; scope: dict[str, str] = {}
    entitlement_id: str; entitlement_version: int                      # version resolved when assigned
    status: Literal["ACTIVE","ENDED"]; assigned_at: datetime; ended_at: datetime | None = None
    expires_at: datetime | None = None; source_request_id: str | None = None; evidence_ref: str | None = None

class DeprecationInfo(BaseModel):
    deprecated_at: datetime; retire_at: datetime | None = None
    replacement_ids: list[str] = []; reason: str; migration_note: str | None = None
    new_assignments_allowed: bool = False

class Entitlement(BaseModel):
    entitlement_id: str; system_id: str; native_id: str; entitlement_type: EntitlementType
    scope: dict[str, str] = {}; display_name: str; description: str | None = None
    status: EntitlementStatus; requestable: bool = True; risk_level: RiskLevel
    owner: str | None = None; tags: list[str] = []; aliases: list[str] = []
    deprecation: DeprecationInfo | None = None

class EntitlementRelationship(BaseModel):
    relationship_id: str; from_id: str; to_id: str
    kind: Literal["DEPENDS_ON","CONFLICTS_WITH","REPLACES"]       # REPLACES: from_id replaces to_id
    strength: Literal["HARD","SOFT"] = "HARD"; rationale: str; active: bool = True
```
**Restricted expression language** (`derive`, `NamingRule.derive`): literals (string, int, bool), `input.<attr>`, operators `+ == != and or not in`, functions `lower upper trim substr(s,start,len) replace coalesce len if(cond,a,b) format_date`. Hand-written parser. **No `eval`/`exec`.** Unknown identifiers or functions ⇒ validation error at schema-publish time.

### 3.4 Entitlement summary, detail, history
```python
class EntitlementSummary(BaseModel):
    entitlement_id: str; system_id: str; native_id: str; entitlement_type: EntitlementType
    display_name: str; scope: dict[str, str] = {}; status: EntitlementStatus; requestable: bool; risk_level: RiskLevel
    version: int; effective_from: datetime; effective_until: datetime | None = None   # effective_until computed
    provisionable: bool                                # computed: ACTIVE ∧ requestable ∧ system ACTIVE ∧ effective
    provisionable_reason: ProvisionableReason | None = None   # why not (None when provisionable)
    replacement_ids: list[str] = []

class ScheduledChange(BaseModel):
    version: int; effective_from: datetime; status: EntitlementStatus; summary: str

class LifecycleView(BaseModel):
    status: EntitlementStatus; effective_since: datetime; effective_until: datetime | None = None
    deprecation: DeprecationInfo | None = None; scheduled_changes: list[ScheduledChange] = []

class EntitlementDetail(BaseModel):
    entitlement: Entitlement; summary: EntitlementSummary; lifecycle: LifecycleView
    relationships: list[EntitlementRelationship]       # active at the selector
    applicable_policy_ids: list[str]

class VersionRecord(BaseModel):
    version: int; knowledge_version: int; valid_from: datetime; valid_to: datetime | None
    status: str; summary: str; diff: list[FieldChange]       # vs previous visible version
    change_id: str | None = None; created_at: datetime; created_by: str

class LifecycleEvent(BaseModel):
    at: datetime; version: int; detail: str
    kind: Literal["REGISTERED","ACTIVATED","UPDATED","DEPRECATED","REPLACEMENT_PROPOSED","RETIRED","BLOCKED","UNBLOCKED","CORRECTED"]

class EntityHistory(BaseModel):
    entity_type: str; entity_id: str; versions: list[VersionRecord]; lifecycle_events: list[LifecycleEvent]
```

### 3.5 Relationship results
```python
class ReplacementOption(BaseModel):
    entitlement: EntitlementSummary; relationship_id: str; effective_from: datetime
    migration_note: str | None = None; origin: Literal["DECLARED_IN_DEPRECATION","REPLACES_RELATIONSHIP"]

class ReplacementResult(BaseModel):
    entitlement_id: str; status: EntitlementStatus; needs_replacement: bool
    options: list[ReplacementOption]; chain: list[str]          # follows REPLACES transitively (max depth 5, cycle-safe)
    terminal_usable_ids: list[str]                               # first provisionable entitlement(s) on each chain

class DependencyNode(BaseModel):
    entitlement_id: str; required_by: list[str]; strength: Literal["HARD","SOFT"]; depth: int
    provisionable: bool; provisionable_reason: ProvisionableReason | None = None

class DependencyResult(BaseModel):
    requested: list[str]
    closure: list[DependencyNode]                  # dependencies only, in PROVISIONING ORDER (dependencies first)
    missing: list[str]                             # closure minus held_entitlement_ids
    unresolvable: list[str]                        # HARD dependency not provisionable ⇒ plan must be refused
    cycles: list[list[str]] = []

class Conflict(BaseModel):
    a: str; b: str; strength: Literal["HARD","SOFT"]; where: Literal["WITHIN_REQUEST","WITH_HELD"]
    relationship_id: str; rationale: str

class ConflictResult(BaseModel):
    conflicts: list[Conflict]; blocking: bool      # blocking = any HARD
```

### 3.6 Policy documents (stored here, evaluated by the Policy MCP)
```python
ConditionOp = Literal["EQ","NE","IN","NOT_IN","CONTAINS","GT","GTE","LT","LTE","EXISTS","MATCHES"]
class ValueOperand(BaseModel): value: AttrValue
class RefOperand(BaseModel):  ref: str   # requester.<attr> subject.<attr> entitlement.<attr> request.operation request.justification held.entitlement_ids
class Condition(BaseModel):               # exactly ONE of all/any/not_/op (model_validator); typed AST, never a string
    model_config = ConfigDict(populate_by_name=True)
    all: list["Condition"] | None = None; any: list["Condition"] | None = None
    not_: "Condition | None" = Field(None, alias="not")
    op: ConditionOp | None = None; left: ValueOperand | RefOperand | None = None; right: ValueOperand | RefOperand | None = None
Condition.model_rebuild()

class PolicyScope(BaseModel):             # empty list = no restriction on that axis
    operations: list[str] = []; system_ids: list[str] = []; entitlement_ids: list[str] = []
    entitlement_tags: list[str] = []; risk_levels: list[RiskLevel] = []
class PolicyRule(BaseModel):
    rule_id: str; effect: Literal["ALLOW","DENY"]; when: Condition; reason_code: str; description: str
class ApproverSpec(BaseModel):
    kind: Literal["MANAGER","ENTITLEMENT_OWNER","SYSTEM_OWNER","ROLE","USER"]; ref: str | None = None
class ApprovalRule(BaseModel):
    rule_id: str; when: Condition; approvers: list[ApproverSpec]
    mode: Literal["ANY_ONE","ALL","SEQUENTIAL"] = "ANY_ONE"; sla_hours: int = 48; auto_approve: bool = False
class Obligation(BaseModel):
    type: Literal["NOTIFY","REQUIRE_JUSTIFICATION","TIME_BOUND","REVIEW_AFTER_DAYS"]; params: dict[str, AttrValue] = {}
class PolicyVersion(BaseModel):
    policy_id: str; version: int; knowledge_version: int; title: str; description: str
    scope: PolicyScope; rules: list[PolicyRule]; approval_rules: list[ApprovalRule] = []
    obligations: list[Obligation] = []; valid_from: datetime; valid_to: datetime | None = None; content_hash: str
class PolicySummary(BaseModel):
    policy_id: str; version: int; title: str; scope: PolicyScope; valid_from: datetime; valid_to: datetime | None
```
Evaluation semantics (deny-overrides, default-deny, approval merge) live in `platform-mcps.md §1`.

### 3.7 State snapshot
```python
class StateScope(BaseModel):
    include: list[Literal["SYSTEMS","ACCOUNT_SCHEMAS","IDENTITIES","ACCOUNTS","ASSIGNMENTS","ENTITLEMENTS","RELATIONSHIPS","POLICIES"]] = ["ENTITLEMENTS","POLICIES"]
    system_ids: list[str] = []; identity_ids: list[str] = []; entitlement_ids: list[str] = []

class KnowledgeStateSnapshot(BaseModel):
    knowledge_version: int; as_of: datetime
    systems: list[System] = []; account_schemas: list[AccountSchema] = []; identities: list[Identity] = []
    accounts: list[AccountRecord] = []; assignments: list[AssignmentRecord] = []
    entitlements: list[Entitlement] = []; relationships: list[EntitlementRelationship] = []; policies: list[PolicyVersion] = []
    counts: dict[str, int]; state_hash: str; truncated: bool = False   # equal hash ⇒ equal state; max 500 items per list

class KnowledgeVersionInfo(BaseModel):
    head_version: int; head_committed_at: datetime; content_hash: str; schema_version: str; seed_version: str | None
```

---

## 4. Tools

Every read tool also accepts `selector: TemporalSelector | None` and returns `KnowledgeResult[...]`. `*` required. Gets return `found=false` (not an error) for unknown ids. ★ = addition to the spec.

### 4.1 Systems and schemas
| Tool | In → Out | Notes |
|---|---|---|
| `search_systems` | `query?`, `kind?`, `status?`, `limit=20`, `page_token?` → `SearchResult[System]` | |
| `get_system` | `system_id*` → `System` | |
| `get_system_schema` | `system_id*` → `SystemSchema` | One call: system + account schemas + naming rules + entitlement types. |
| `get_account_schema` | `system_id*`, `account_type?` → `AccountSchema` | Default type = the system's first `account_types` entry. |

### 4.2 Identities and accounts
| Tool | In → Out | Notes |
|---|---|---|
| `search_identities` ★ | `query*`, `department?`, `employment_status?`, `limit=10` → `SearchResult[Identity]` | Matches employee_id, email, display name, given+surname. Two people with the same name ⇒ `AMBIGUOUS`. |
| `get_identity` ★ | exactly one of `identity_id`/`employee_id`/`email`; `include_accounts=true`, `include_assignments=true` → `IdentityView{identity, accounts, assignments}` | |
| `search_accounts` | `identity_id?`, `system_id?`, `account_id?`, `status?`, `limit=20` → `SearchResult[AccountRecord]` | |
| `get_account` | `system_id*` + (`account_id` or `identity_id`+`account_type`), `include_assignments=true` → `AccountView{account, assignments}` | `found=false` = "not recorded in Knowledge", **not** "absent in the provider". |

### 4.3 Entitlements, groups, roles
| Tool | In → Out | Notes |
|---|---|---|
| `search_entitlements` | `query*`, `system_id?`, `entitlement_type?`, `status?: list` (default **all statuses**), `scope?`, `tags?`, `limit=10`, `page_token?` → `SearchResult[EntitlementSummary]` | Default returns deprecated/retired/blocked too, so the agent can explain a refusal. `provisionable(+_reason)` is computed per item. |
| `get_entitlement` | `entitlement_id*` or (`system_id*`+`native_id*`) → `EntitlementDetail` | |
| `get_entitlement_history` | `entitlement_id*`, `include_future=true` → `EntityHistory` | Only the knowledge pin of the selector applies. |
| `search_groups`, `get_group`, `get_group_history` | same as the entitlement tools, type forced to `GROUP` | Wrong type ⇒ `found=false`. |
| `search_roles`, `get_role` | same, type ∈ `ROLE, APP_ROLE` | |
| `check_entitlement_usable` ★ | `entitlement*: EntitlementRef`, `operation=ASSIGN` (`ASSIGN`/`REMOVE`/`KEEP`) → `UsabilityCheck` | The **single gate** the planner calls per requested entitlement. |

```python
UsabilityVerdict = Literal["USABLE","DEPRECATED","RETIRED","BLOCKED","NOT_YET_EFFECTIVE","NOT_REQUESTABLE","NOT_FOUND","AMBIGUOUS"]
class UsabilityCheck(BaseModel):
    verdict: UsabilityVerdict; entitlement: EntitlementSummary | None = None
    reason: str; reason_codes: list[str]                  # deterministic template text, no LLM
    replacement: ReplacementResult | None = None          # filled for DEPRECATED / RETIRED
    effective_from: datetime | None = None; effective_until: datetime | None = None
    policy_versions: dict[str, int] = {}                  # lifecycle policies consulted (informational)
    candidates: list[EntitlementSummary] = []             # when AMBIGUOUS
```
Verdict rules for `ASSIGN`: ACTIVE∧requestable∧effective ⇒ `USABLE`; PROPOSED or future-dated ⇒ `NOT_YET_EFFECTIVE`; `requestable=false` ⇒ `NOT_REQUESTABLE`; else the status name. For `REMOVE`/`KEEP`, a DEPRECATED, RETIRED or BLOCKED entitlement is `USABLE` with `reason_codes=["REMOVAL_ALLOWED"]` (access can always be taken away).

### 4.4 Relationships
| Tool | In → Out | Notes |
|---|---|---|
| `find_entitlement_replacement` | `entitlement_id*` → `ReplacementResult` | Uses `DeprecationInfo.replacement_ids` and active `REPLACES` edges. |
| `find_entitlement_dependencies` | `entitlement_ids*`, `held_entitlement_ids=[]`, `include_soft=true` → `DependencyResult` | `closure` is topologically ordered. A dependency cycle ⇒ listed in `cycles`, plan must be refused. |
| `find_entitlement_conflicts` | `entitlement_ids*`, `held_entitlement_ids=[]` → `ConflictResult` | Checks pairs within the request and request-vs-held. |

### 4.5 Policy documents
| Tool | In → Out | Notes |
|---|---|---|
| `get_policy` | `policy_id*`, `version?` → `PolicyVersion` | Without `version`, resolved at the selector. |
| `list_policies` | `system_id?`, `entitlement_id?`, `operation?`, `include_inactive=false`, `limit=50` → `Page[PolicySummary]` | |
| `evaluate_policy` | `PolicyEvaluationInput` (`platform-mcps.md §1`) → `PolicyDecision` + `meta` | **Pass-through only:** forwards to the Policy MCP and holds no decision logic. The deterministic workflow calls the Policy MCP directly. |

### 4.6 State
| Tool | In → Out | Notes |
|---|---|---|
| `get_current_iam_state` | `scope: StateScope` → `KnowledgeStateSnapshot` | = `get_state_at_time` with `as_of=now`, head. |
| `get_state_at_time` | `scope: StateScope`, `selector*` → `KnowledgeStateSnapshot` | Reproduces any past (or scheduled-future) state. |
| `get_knowledge_version` | — → `KnowledgeVersionInfo` | Cheap staleness probe used by the executor before writes. |

### 4.7 Derivation and validation ★ (deterministic, replaces LLM guessing)
| Tool | In → Out | Notes |
|---|---|---|
| `derive_account_attributes` | `system_id*`, `account_type*`, `identity_id*`, `overrides={}` → `DerivedAttributes` | Applies schema `defaults`, `derive` expressions and naming rules. |
| `validate_account_attributes` | `system_id*`, `account_type*`, `attributes*`, `mode*` (`CREATE`/`UPDATE`) → `ValidationReport` | Required, type, pattern, enum, max_length, `protected`, unknown attributes. |
| `validate_entitlement_definition` | `entitlement*: EntitlementDraft` → `ValidationReport` | Naming, `(system_id, native_id)` unique, type allowed for system, relationship targets exist, no REPLACES/DEPENDS_ON cycle. |

```python
class DerivationTrace(BaseModel): attribute: str; expression: str | None; inputs: dict[str, AttrValue]; result: AttrValue; source: str
class NamingProposal(BaseModel):
    account_id: str; candidates: list[str]
    collision_checked_against: Literal["KNOWLEDGE_ONLY"] = "KNOWLEDGE_ONLY"   # provider still enforces uniqueness (EXISTS / NATURAL_KEY_CONFLICT)
class DerivedAttributes(BaseModel):
    attributes: dict[str, AttrValue]; traces: list[DerivationTrace]; naming: NamingProposal | None
    missing_required: list[str]; schema_version: int
class ValidationIssue(BaseModel): path: str; code: str; message: str; severity: Literal["ERROR","WARNING"]
class ValidationReport(BaseModel): valid: bool; issues: list[ValidationIssue]; schema_version: int | None = None
```

### 4.8 Change pipeline ★ (see §6)
| Tool | In → Out | Notes |
|---|---|---|
| `propose_knowledge_change` | `change*: KnowledgeChange`, `justification*`, `evidence=[]`, `requested_by*` → `KnowledgeProposal` | Creates the proposal, validates, computes `impact`. **No grant needed** (touches only the proposal store). Never changes knowledge. |
| `get_knowledge_proposal` | `proposal_id*` → `KnowledgeProposal` | |
| `list_knowledge_proposals` | `status?`, `change_type?`, `requested_by?`, `entity_id?`, `limit=25` → `Page[KnowledgeProposal]` | |
| `withdraw_knowledge_proposal` | `proposal_id*`, `reason*` → `KnowledgeProposal` | Requester only. Not allowed after `APPLIED`. |
| `record_proposal_approval` | `proposal_id*`, `approval_id*`, `decision*` (`APPROVED`/`REJECTED`/`EXPIRED`) → `KnowledgeProposal` | `llm_exposed=false`. Status projection only. Authority to apply comes from the grant. |
| `apply_knowledge_change` | `proposal_id*`, `expected_head_version?` → `ApplyResult` | `llm_exposed=false`. **Requires execution grant** whose `plan_hash` = `proposal.change_hash`. Supports `dry_run`. Idempotent (replay ⇒ `replayed=true`). |

```python
class ApplyResult(WriteResult[KnowledgeProposal]):
    new_knowledge_version: int | None = None; rows_written: list[str] = []   # "entitlements:APP_X_ADMIN:v4"
```

**Governance (publish via annotations + manifest):**
| Tools | read_only | requires_approval | risk | idempotent | dry_run | destructive | llm_exposed |
|---|---|---|---|---|---|---|---|
| every read/search/get/find/check/derive/validate/state tool | ✔ | ✘ | LOW | ✔ | ✘ | ✘ | ✔ |
| `propose_knowledge_change`, `withdraw_knowledge_proposal` | ✘ | ✘ | LOW | ✔ | ✘ | ✘ | ✔ |
| `record_proposal_approval` | ✘ | ✘ | MEDIUM | ✔ | ✘ | ✘ | **✘** |
| `apply_knowledge_change` | ✘ | **✔** | HIGH | ✔ | ✔ | ✘ | **✘** |

Exception to conventions C5: propose/withdraw/record mutate only the proposal store, so they need no grant. Only `apply_knowledge_change` writes knowledge.

---

## 5. Resources (read-only, JSON; all accept `?as_of=&knowledge_version=`)

`iam://server/manifest` · `iam://knowledge/version` · `iam://knowledge/systems` · `iam://knowledge/systems/{system_id}/schema` · `iam://knowledge/entitlements/{id}` · `iam://knowledge/entitlements/{id}/versions/{n}` · `iam://knowledge/policies/{id}` · `iam://knowledge/policies/{id}/versions/{n}` · `iam://knowledge/identities/{id}` · `iam://knowledge/ontology` (entity types, relationship kinds, statuses, capability tags) · `iam://knowledge/lifecycle-rules` (the transition table in §6.2 as JSON)

---

## 6. Change pipeline

Knowledge changes only through proposals. The Knowledge server never calls the Approval MCP; the **orchestrator** is the glue (create approval → record decision → mint grant → apply).

### 6.1 Change model
```python
class ChangeBase(BaseModel):
    change_type: str
    valid_from: datetime | None = None        # default = apply time; future = scheduled change

class RegisterEntitlement(ChangeBase):   change_type: Literal["REGISTER_ENTITLEMENT"]; entitlement: EntitlementDraft; initial_status: Literal["PROPOSED","ACTIVE"] = "PROPOSED"
class ActivateEntitlement(ChangeBase):   change_type: Literal["ACTIVATE_ENTITLEMENT"]; entitlement_id: str
class UpdateEntitlement(ChangeBase):     change_type: Literal["UPDATE_ENTITLEMENT"]; entitlement_id: str; changes: list[AttributeChange]   # display_name, description, owner, tags, aliases, risk_level, requestable
class DeprecateEntitlement(ChangeBase):  change_type: Literal["DEPRECATE_ENTITLEMENT"]; entitlement_id: str; reason: str; retire_at: datetime | None = None; replacement_ids: list[str] = []
class RetireEntitlement(ChangeBase):     change_type: Literal["RETIRE_ENTITLEMENT"]; entitlement_id: str; reason: str
class BlockEntitlement(ChangeBase):      change_type: Literal["BLOCK_ENTITLEMENT"]; entitlement_id: str; reason: str
class UnblockEntitlement(ChangeBase):    change_type: Literal["UNBLOCK_ENTITLEMENT"]; entitlement_id: str; restore_status: Literal["ACTIVE","DEPRECATED"]; reason: str
class ProposeReplacement(ChangeBase):    change_type: Literal["PROPOSE_REPLACEMENT"]; entitlement_id: str; replacement_id: str; migration_note: str | None = None
class AddRelationship(ChangeBase):       change_type: Literal["ADD_RELATIONSHIP"]; from_id: str; to_id: str; kind: Literal["DEPENDS_ON","CONFLICTS_WITH","REPLACES"]; strength: Literal["HARD","SOFT"] = "HARD"; rationale: str
class EndRelationship(ChangeBase):       change_type: Literal["END_RELATIONSHIP"]; relationship_id: str; reason: str
class PublishPolicyVersion(ChangeBase):  change_type: Literal["PUBLISH_POLICY_VERSION"]; policy: PolicyDraft          # new immutable version of policy_id
class UpdateAccountSchema(ChangeBase):   change_type: Literal["UPDATE_ACCOUNT_SCHEMA"]; schema: AccountSchema
class RegisterIdentity(ChangeBase):      change_type: Literal["REGISTER_IDENTITY"]; identity: Identity
class RegisterAccount(ChangeBase):       change_type: Literal["REGISTER_ACCOUNT"]; account: AccountRecord
class UpdateAccountRecord(ChangeBase):   change_type: Literal["UPDATE_ACCOUNT_RECORD"]; system_id: str; account_id: str; changes: list[AttributeChange]
class RecordAssignment(ChangeBase):      change_type: Literal["RECORD_ASSIGNMENT"]; assignment: AssignmentRecord
class EndAssignment(ChangeBase):         change_type: Literal["END_ASSIGNMENT"]; assignment_id: str; reason: str; source_request_id: str | None = None

KnowledgeChange = Annotated[Union[RegisterEntitlement, ActivateEntitlement, ...all of the above...], Field(discriminator="change_type")]
ChangeClass = Literal["FACT_REGISTRATION","CATALOG_CHANGE"]
```
`EntitlementDraft`, `PolicyDraft` = the entity model without server-assigned fields (`version`, `knowledge_version`, `valid_to`, `content_hash`).
`change_class` is **derived by the server, never supplied**: `FACT_REGISTRATION` = {REGISTER_IDENTITY, REGISTER_ACCOUNT, UPDATE_ACCOUNT_RECORD, RECORD_ASSIGNMENT, END_ASSIGNMENT}; everything else is `CATALOG_CHANGE`.

```python
class EvidenceRef(BaseModel):
    kind: Literal["VERIFICATION_RESULT","AUDIT_EVENT","PROVIDER_READ","DOCUMENT","TICKET"]; ref: str; hash: str | None = None

class ImpactPreview(BaseModel):
    affected_entitlement_ids: list[str] = []; affected_policy_ids: list[str] = []
    active_assignments_affected: int = 0; identities_affected: int = 0
    replacement_available: bool | None = None; diff: list[FieldChange] = []; notes: list[str] = []

ProposalStatus = Literal["DRAFT","VALIDATION_FAILED","PENDING_APPROVAL","APPROVED","REJECTED","APPLIED","EXPIRED","WITHDRAWN"]
class KnowledgeProposal(BaseModel):
    proposal_id: str; status: ProposalStatus; change_class: ChangeClass; change: KnowledgeChange; change_hash: str   # sha256 of canonical JSON
    requested_by: str; justification: str; evidence: list[EvidenceRef] = []
    base_knowledge_version: int; validation: ValidationReport | None = None; impact: ImpactPreview | None = None
    auto_approvable: bool = False; approval_id: str | None = None
    created_at: datetime; updated_at: datetime; expires_at: datetime
    applied_knowledge_version: int | None = None; supersedes_proposal_id: str | None = None
```
`auto_approvable=true` iff (a) the change is a `FACT_REGISTRATION`, or (b) it is `ACTIVATE_ENTITLEMENT` for an entitlement whose `REGISTER_ENTITLEMENT` was already APPLIED, **and** there is ≥ 1 evidence of kind `VERIFICATION_RESULT` (ref = audit `event_id` of a `STATE_VERIFIED` event with `state=VERIFIED`). The Approval MCP's policy-auto path re-checks that event in the Audit MCP. Every other `CATALOG_CHANGE` needs a human approval in the POC (**the FinanceReader policy change and the APP_X_ADMIN deprecation are CATALOG_CHANGEs**).

### 6.2 Lifecycle transitions
Proposal status:
| From | To | Trigger | Guard |
|---|---|---|---|
| (new) | DRAFT | `propose_knowledge_change` | — |
| DRAFT | VALIDATION_FAILED | validation (same call) | ≥ 1 `ERROR` issue. Terminal; re-propose with `supersedes_proposal_id`. |
| DRAFT | PENDING_APPROVAL | validation (same call) | no errors |
| PENDING_APPROVAL | APPROVED / REJECTED / EXPIRED | `record_proposal_approval` (or TTL sweep, default 7 d) | `approval_id` attached |
| DRAFT, PENDING_APPROVAL, APPROVED | WITHDRAWN | `withdraw_knowledge_proposal` | requester only |
| APPROVED | APPLIED | `apply_knowledge_change` | valid grant (`plan_hash == change_hash`); change re-validated at current head; `expected_head_version` (if given) matches |
| APPROVED | EXPIRED | TTL sweep (24 h unapplied) | — |
Terminal: VALIDATION_FAILED, REJECTED, APPLIED, EXPIRED, WITHDRAWN. Any other transition ⇒ `PRECONDITION_FAILED`. If re-validation at apply fails ⇒ `FAILED PRECONDITION_FAILED` with `details.issues`; proposal stays `APPROVED` and must be withdrawn and re-proposed.

Entitlement status (checked against the status resolved just before the new row's `valid_from`):
| From | Allowed to | Change |
|---|---|---|
| (none) | PROPOSED, ACTIVE | REGISTER_ENTITLEMENT |
| PROPOSED | ACTIVE, RETIRED | ACTIVATE / RETIRE (abandon) |
| ACTIVE | DEPRECATED, BLOCKED | DEPRECATE / BLOCK |
| DEPRECATED | ACTIVE (reinstate), RETIRED, BLOCKED | ACTIVATE (reinstate) / RETIRE / BLOCK |
| BLOCKED | ACTIVE, DEPRECATED | UNBLOCK (`restore_status`) |
| RETIRED | — terminal | register a new entitlement instead |
`ACTIVE → RETIRED` directly is illegal: deprecate first. `DEPRECATE` with `replacement_ids` requires each replacement to exist and be `ACTIVE` at the effective time.

---

## 7. Seed loader (`knowledge/seed/`, `make seed`)

* YAML under `knowledge/`: `systems/` (systems + account schemas), `entitlements/` (with explicit version lists), `policies/` (with version lists), `seed/` (identities, relationships, accounts, assignments) and `schemas/` (generated JSON Schemas used to validate the YAML). `SEED_PROFILE=default|acceptance` selects the variant (see `docs/knowledge-model.md`).
* Relative dates: `now`, `T-540d`, `T+60d`, `T-3h`. Resolved against `SEED_NOW` (env) or the injected `Clock`. Tests freeze `SEED_NOW=2026-06-01T00:00:00Z`.
* The loader goes through the **same append path** as `apply_knowledge_change` (one commit per row, chronological), then writes `seed_runs(content_hash)`; re-running with an unchanged seed is a no-op.
* Dataset content (APP_X_ADMIN timeline, FinanceReader policy history, Alice, conflicts, dependencies) is specified in `docs/knowledge-model.md`.

---

## 8. Build stack and layout

SQLAlchemy 2 + Alembic · Pydantic 2 · pytest + hypothesis · structlog · OpenTelemetry · jsonschema · PyYAML · ruff · mypy (strict) · import-linter. Use `FastMCP`; `mcp.run(transport="streamable-http")` on 8101.

```
mcp/knowledge-server/
  AGENTS.md  pyproject.toml  alembic.ini  migrations/
  src/knowledge_server/
    server.py  config.py  resources.py
    tools/   systems.py identities.py entitlements.py relationships.py policies.py state.py validation.py changes.py
    domain/  temporal.py search.py lifecycle.py graph.py expr.py proposals.py impact.py hashing.py clock.py
    repo/    models.py repository.py unit_of_work.py
    seed/    loader.py
  tests/     (unit: domain/*, contract: tools/*, property: temporal + search)
```

---

## 9. Acceptance checklist

- [ ] `tools/list` equals §4 exactly (snapshot test); manifest governance matches the table in §4.
- [ ] UPDATE/DELETE on any versioned table raises (trigger test).
- [ ] Temporal worked example (§2) passes at all four query points; property test: resolution is stable under row insertion order.
- [ ] Pinned read ignores later commits; `meta.head_version` reflects head.
- [ ] `search_entitlements("APP_X_Admin")` returns the DEPRECATED entitlement with `provisionable=false`, reason `DEPRECATED`, replacement `APP_X_PLATFORM_ADMIN`.
- [ ] `check_entitlement_usable` returns every verdict in §4.3, including `AMBIGUOUS` (never auto-picks) and `REMOVE` on a deprecated entitlement ⇒ `USABLE`.
- [ ] Dependency closure is in provisioning order; cycles and unresolvable HARD dependencies are reported.
- [ ] Conflicts detected within the request and against held entitlements.
- [ ] Both lifecycle tables in §6.2 enforced, illegal transitions return `PRECONDITION_FAILED`.
- [ ] `apply_knowledge_change` rejects: no grant, wrong `plan_hash`, stale re-validation; replay returns `replayed=true`; `dry_run` writes nothing.
- [ ] `derive_account_attributes` is deterministic; the expression parser rejects unknown functions and never uses `eval`.
- [ ] Every response includes `meta.authoritative=true` and `knowledge_version`.
