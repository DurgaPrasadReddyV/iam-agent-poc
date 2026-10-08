# Provisioning: plans, validation, execution, verification, reconciliation

Tool contracts: `docs/contracts/provisioning-mcp.md`. Workflow context: `docs/agent-workflow.md`.

## 1. Plan model (`libs/iam_contracts/plan.py`)
```python
class ResolvedRef(BaseModel):                      # x-iam-ref: must come from a Knowledge/provider response in THIS run
    entitlement_id: str; version: int; system_id: str; native_id: str; scope: dict[str, str] = {}

class PlanVersions(BaseModel):
    knowledge_version: int; policy_set_version: str
    account_schema_versions: dict[str, int]; entitlement_versions: dict[str, int]

class CompensationSpec(BaseModel): capability: str; args: dict[str, Any]     # = the declared compensating_tool, neutral form

class ProvisioningAction(BaseModel):
    action_id: str; order: int; capability: str                 # neutral tag, e.g. "group.add_member"
    system_id: str; object_type: str | None = None
    args: dict[str, Any]                                         # provider-neutral; refs appear as ResolvedRef
    depends_on: list[str] = []; destructive: bool = False; risk_level: RiskLevel
    expected_outcome: Literal["CREATED","UPDATED","DELETED","EXISTS","NO_CHANGE"]
    compensation: CompensationSpec | None = None; rationale: str   # rationale is excluded from the hash

class ReconciliationItem(BaseModel):
    kind: Literal["ACCOUNT","ATTRIBUTE","ENTITLEMENT"]; key: str
    action: Literal["ADD","REMOVE","MODIFY","NO_CHANGE","UNKNOWN"]
    desired: AttrValue = None; actual: AttrValue = None; reason: str
    requires_policy: bool; requires_approval: bool

class ProvisioningPlan(BaseModel):
    plan_id: str; request_id: str; intent: str; subject_identity_id: str | None
    actions: list[ProvisioningAction]; versions: PlanVersions; reconciliation: list[ReconciliationItem]
    created_at: datetime; created_by_model: str | None = None
    plan_hash: str        # sha256 of canonical JSON excluding plan_hash, created_at, created_by_model, rationale
```
`DesiredState` = the Knowledge-derived target for the touched scope (`identity, system, account attributes, entitlements with versions`). `ActualState` = the provider's `ActualAccountState`.

## 2. Reconcile only what the request touches
Diff desired vs actual **only for the account and the entitlements named in the request** (never "make the account equal Knowledge").
| Situation | Item |
|---|---|
| desired, not actual | `ADD` |
| attribute differs | `MODIFY` |
| equal | `NO_CHANGE` |
| actual, not desired, and the request asks to remove it | `REMOVE` (needs explicit policy ALLOW **and** approval) |
| actual, not desired, not requested | reported as drift, never removed by a provisioning request |
| actual state unreadable (provider DOWN) or native id unmapped | `UNKNOWN` ⇒ plan cannot proceed for that item |
```python
class ReconciliationReport(BaseModel):
    scope: dict[str, list[str]]; knowledge_version: int; generated_at: datetime
    items: list[ReconciliationItem]; summary: dict[str, int]          # counts per action
    remediation_plan: ProvisioningPlan | None = None                  # only when remediate=true
```
Reconciliation (scenario 7) is a separate request type that **reports** drift between Knowledge and provider state and proposes remediation as a normal plan (each REMOVE still needs policy and approval).

## 3. Capability binding
Plans carry neutral tags. At execution the registry resolves `(capability, system_id, object_type)` → `(server, tool)`, and an **argument binder** maps neutral args to the tool's input model. Bindings are data (`agent/execution/bindings/<system>.yaml`), checked against the tool `inputSchema` at startup:
```yaml
- capability: group.add_member
  system_id: ACTIVE_DIRECTORY
  server: ad
  tool: add_group_member
  args:                        # align with provisioning-mcp.md
    group:  { sam_account_name: "$ref.native_id" }
    member: { kind: USER, user: { sam_account_name: "$account_id" } }
```
Core agent code contains no tool-name literals.

## 4. VALIDATE_PLAN checks (all deterministic)
| # | Check | Failure |
|---|---|---|
| V1 | Plan parses against the schema | re-plan |
| V2 | Every id/ref was resolved this run (`x-iam-ref`); no invented entitlements | re-plan / REFUSED |
| V3 | Every entitlement is `USABLE` for its operation (`check_entitlement_usable`) | REFUSED |
| V4 | Dependencies present and ordered before dependents | re-plan |
| V5 | No HARD conflict within the plan or with held entitlements | REFUSED |
| V6 | Every capability is bound and available (`health_check` UP) | `CAPABILITY_UNAVAILABLE` |
| V7 | Bound args validate against each tool's `inputSchema` | re-plan |
| V8 | Account attributes pass `validate_account_attributes` (no protected attributes) | re-plan |
| V9 | `evaluate_plan` is ALLOW or APPROVAL_REQUIRED; destructive actions have explicit ALLOW | REFUSED |
| V10 | Dry-run of every write: status SUCCESS, `predicted_outcome == expected_outcome` | re-plan |
| V11 | No destructive action the request did not ask for | REFUSED |
| V12 | No action targets a system or subject outside the request | REFUSED |
| V13 | Action count ≤ `MAX_PLAN_ACTIONS` (blast radius) | REFUSED |
| V14 | Knowledge head not ahead of the pin in a way that changes verdicts | back to EVALUATE_POLICY |

## 5. Execution
Actions run strictly by `order`. For each: mint a per-action grant (args hash of the **bound** arguments) → call with `idempotency_key = sha256(plan_id:action_id)` → inspect `WriteResult`.
* `SUCCESS` (`CREATED`/`UPDATED`/`EXISTS`/`NO_CHANGE`): continue. `EXISTS` with `drift` is recorded; the plan was validated with the dry-run so a surprise `EXISTS` ⇒ stop and re-validate.
* `RETRYABLE` and idempotent: up to 3 attempts, exponential backoff + jitter (tenacity). If destructive, re-read state first.
* `BLOCKED` / `FAILED` / `PARTIAL_SUCCESS`: stop, **compensate** completed `CREATED`/`UPDATED` actions in reverse order via their `compensation`, emit `COMPENSATION_STARTED`, end FAILED.
* Never continue past a failed action. Never mark success on a missing result.

## 6. Verification
For each touched account call `get_account_state`, compare with `DesiredState` over the touched scope: **VERIFIED** (all match) · **DRIFT** (any mismatch) · **UNKNOWN** (read failed). Only VERIFIED allows UPDATE_KNOWLEDGE and a success message.
```python
class VerificationReport(BaseModel):
    request_id: str; plan_id: str; state: Literal["VERIFIED","DRIFT","UNKNOWN"]
    items: list[ReconciliationItem]; systems_checked: list[str]
    observed_at: dict[str, datetime]                                  # per system; must be later than that system's last write
```

## 7. Knowledge update
After VERIFIED, one `propose_knowledge_change` per fact (`REGISTER_ACCOUNT`, `RECORD_ASSIGNMENT`, `END_ASSIGNMENT`) with `VERIFICATION_RESULT` evidence (audit `event_id` of STATE_VERIFIED). These are `FACT_REGISTRATION`: auto-approvable, applied with a grant.

## 8. Recovery (skill `incident-recovery`)
```python
class RecoveryOption(BaseModel):
    kind: Literal["RETRY_REMAINING","COMPENSATE","RECONCILE","MANUAL","ESCALATE"]
    description: str; plan: ProvisioningPlan | None = None        # any writing option is a NEW plan (new hash, new approval)
    manual_steps: list[str] = []; requires_approval: bool = True

class RecoveryProposal(BaseModel):
    request_id: str
    diagnosis: Literal["PROVIDER_TRANSIENT","PARTIAL_EXECUTION","VERIFICATION_DRIFT","COMPENSATION_INCOMPLETE","POLICY_OR_KNOWLEDGE_CHANGED","UNKNOWN"]
    evidence_event_ids: list[str]; options: list[RecoveryOption]; recommended: int | None = None   # index into options
```
Recovery never reuses old grants or approvals and never replays a destructive action without re-reading state.
