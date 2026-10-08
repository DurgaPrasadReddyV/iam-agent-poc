# Provisioning MCP Contracts — AD · SQL · Linux · App

You build these four servers. Read `00-conventions.md` first (envelopes, outcomes, grants, governance, manifest).
Every server also implements the **common provider contract**: `health_check` and `get_account_state` (§8 of the conventions).
POC backend = mock store (SQLite per server) behind a `Provider` interface; the MCP contract must stay identical when a real provider replaces the mock.

| Server | `system_id` | Port | Real-provider mapping hint |
|---|---|---|---|
| `ad` | `ACTIVE_DIRECTORY` | 8111 | LDAP/ADSI or PowerShell AD module |
| `sql` | `SQL_SERVER` | 8112 | T-SQL: `CREATE LOGIN`, `CREATE USER`, `ALTER ROLE … ADD MEMBER`, `GRANT/REVOKE` |
| `linux` | `LINUX` | 8113 | `useradd/usermod/groupadd/gpasswd` + `/etc/sudoers.d` via SSH/Ansible |
| `app` | `APP_X`, `APP_Y` (multi-tenant mock) | 8114 | SCIM 2.0 / vendor API |

Notation: every input also has `context: ToolContext`; write tools also have `dry_run=false`. `*` required. Output `WriteResult[T]` / `ReadResult[T]` are defined in the conventions.

---

## 1. AD server (`ad`, `ACTIVE_DIRECTORY`)

### Models
```python
class ADUserLookup(BaseModel):            # exactly ONE field set, else VALIDATION_ERROR
    sam_account_name: str | None = None; user_principal_name: str | None = None
    employee_id: str | None = None; object_guid: str | None = None; distinguished_name: str | None = None

class ADGroupLookup(BaseModel):           # exactly ONE
    sam_account_name: str | None = None; distinguished_name: str | None = None; object_guid: str | None = None

class ADMemberRef(BaseModel):
    kind: Literal["USER", "GROUP"]
    user: ADUserLookup | None = None; group: ADGroupLookup | None = None

class ADUser(BaseModel):
    object_guid: str; sam_account_name: str; user_principal_name: str
    distinguished_name: str; ou: str
    given_name: str | None = None; surname: str | None = None; display_name: str | None = None
    mail: str | None = None; employee_id: str | None = None
    department: str | None = None; title: str | None = None; manager_sam: str | None = None
    enabled: bool; account_expires: datetime | None = None
    member_of: list[str] = []                         # direct group sAMAccountNames
    extension_attributes: dict[str, AttrValue] = {}
    when_created: datetime; when_changed: datetime

class ADGroup(BaseModel):
    object_guid: str; sam_account_name: str; distinguished_name: str; ou: str
    description: str | None = None
    group_scope: Literal["GLOBAL", "DOMAIN_LOCAL", "UNIVERSAL"]
    group_category: Literal["SECURITY", "DISTRIBUTION"]
    managed_by: str | None = None; member_count: int
    when_created: datetime; when_changed: datetime

class ADMembership(BaseModel):
    group_sam: str; member_sam: str; member_kind: Literal["USER", "GROUP"]
    added_at: datetime | None = None; expires_at: datetime | None = None; via: str = "DIRECT"

class ADGroupView(BaseModel):  group: ADGroup; members: list[ADMembership] | None = None
class GroupMembershipPage(BaseModel):
    group_sam: str; members: list[ADMembership]; total: int; next_page_token: str | None = None
class UserAttributes(BaseModel):  sam_account_name: str; attributes: dict[str, AttrValue]
class CreateUserResult(WriteResult[ADUser]):  credential_ref: str | None = None   # never the secret
```

### Tools
| Tool | In → Out | Behavior / errors |
|---|---|---|
| `create_user` | `sam_account_name*`(≤20), `user_principal_name*`, `ou*`, `given_name*`, `surname*`, `employee_id*`, `display_name?`, `mail?`, `department?`, `title?`, `manager_sam?`, `initial_state=ENABLED`, `account_expires?`, `extension_attributes={}`, `account_schema_version?`, `credential_mode=GENERATE_AND_ESCROW` → `CreateUserResult` | Natural keys: sAM, UPN, employee_id. All match one object → `EXISTS`+`drift`. Match different objects → `BLOCKED NATURAL_KEY_CONFLICT`. Unknown extension attribute → `VALIDATION_ERROR`. Password never returned. |
| `get_user` | `user*: ADUserLookup`, `include_groups=true` → `ReadResult[ADUser]` | `found=false` when absent. |
| `update_user` | `user*`, `changes*: list[AttributeChange]` → `WriteResult[ADUser]` | Allowed: `given_name, surname, display_name, mail, department, title, manager_sam, account_expires, ou` (move). Others → `PROTECTED_ATTRIBUTE`. Same values → `NO_CHANGE`. |
| `disable_user` | `user*`, `reason*`, `move_to_ou?` → `WriteResult[ADUser]` | Already disabled → `NO_CHANGE`. Does **not** touch group memberships (removals are separate planned `remove_group_member` actions). |
| `create_group` | `sam_account_name*`, `ou*`, `description*`, `managed_by*`, `group_scope=GLOBAL`, `group_category=SECURITY`, `extension_attributes={}` → `WriteResult[ADGroup]` | Exists → `EXISTS`+`drift` (no duplicate). Provider also enforces `NAMING_PATTERN` (config) as defense in depth. |
| `get_group` | `group*: ADGroupLookup`, `include_members=false`, `member_limit=200` → `ReadResult[ADGroupView]` | |
| `delete_group` | `group*`, `reason*`, `require_empty=true` → `WriteResult[ADGroup]` | Absent → `NO_CHANGE`. Non-empty + `require_empty` → `BLOCKED PRECONDITION_FAILED`. **Not compensable.** |
| `add_group_member` | `group*`, `member*: ADMemberRef`, `expires_at?` → `WriteResult[ADMembership]` | Already member → `NO_CHANGE` (`UPDATED` if expiry differs). `expires_at` while manifest `supports_expiry=false` → `BLOCKED UNSUPPORTED_OPERATION` (never silently ignore). |
| `remove_group_member` | `group*`, `member*` → `WriteResult[ADMembership]` | Not a member → `NO_CHANGE`. |
| `get_group_membership` | `group*`, `recursive=false`, `page_size=200`, `page_token?` → `ReadResult[GroupMembershipPage]` | `recursive` resolves nested groups; `via` shows the path. |
| `set_user_attribute` | `user*`, `attribute*` (LDAP or schema logical name), `op=SET`, `value?`, `expected_current?` → `WriteResult[ADUser]` | `expected_current` = compare-and-set; mismatch → `RETRYABLE CONCURRENT_MODIFICATION`. Protected: `objectGUID, sAMAccountName, userAccountControl, memberOf, adminCount, pwdLastSet, primaryGroupID, sIDHistory` → `PROTECTED_ATTRIBUTE`. |
| `get_user_attributes` | `user*`, `attributes?: list[str]` (None = all readable) → `ReadResult[UserAttributes]` | |
| `health_check`, `get_account_state` | see conventions (`account_id` = sAMAccountName) | `entitlements` = direct+nested group memberships. |

### Governance (manifest)
| tool | capability | RO | approval | risk | idem | dry-run | destructive | compensating |
|---|---|---|---|---|---|---|---|---|
| create_user | account.create | N | N | MEDIUM | Y | Y | N | disable_user |
| get_user | account.read | Y | N | LOW | Y | – | – | – |
| update_user | account.update | N | N | MEDIUM | Y | Y | N | update_user (restore `before`) |
| disable_user | account.disable | N | **Y** | HIGH | Y | Y | Y | – |
| create_group | group.create | N | **Y** | HIGH | Y | Y | N | delete_group |
| get_group | group.read | Y | N | LOW | Y | – | – | – |
| delete_group | group.delete | N | **Y** | CRITICAL | Y | Y | Y | none |
| add_group_member | group.add_member | N | N* | MEDIUM | Y | Y | N | remove_group_member |
| remove_group_member | group.remove_member | N | **Y** | MEDIUM | Y | Y | Y | add_group_member |
| get_group_membership | group.read_members | Y | N | LOW | Y | – | – | – |
| set_user_attribute | account.set_attribute | N | N | MEDIUM | Y | Y | N | set_user_attribute |
| get_user_attributes | account.read_attributes | Y | N | LOW | Y | – | – | – |

`*` Policy (not the tool) escalates approval based on the entitlement's risk. Recommended extras (not required): `enable_user`, `search_users`, `search_groups`, `update_group`.

### Example — `create_user` (Scenario 1)
```json
{"context":{"request_id":"REQ-123","plan_id":"PLAN-9","action_id":"A-1","actor":"agent:iam-orchestrator","agent_model":"planner","knowledge_version":42,"policy_set_version":"PS-0007","idempotency_key":"sha256:…","execution_grant":"eyJ…"},
 "dry_run":false,"sam_account_name":"asmith","user_principal_name":"alice.smith@corp.example.com",
 "ou":"OU=Finance,OU=Users,DC=corp,DC=example,DC=com","given_name":"Alice","surname":"Smith",
 "employee_id":"E10042","department":"Finance","manager_sam":"bjones","account_schema_version":3}
```
```json
{"status":"SUCCESS","outcome":"CREATED","target":{"system_id":"ACTIVE_DIRECTORY","object_type":"USER","native_id":"asmith","scope":{}},
 "before":null,"after":{"sam_account_name":"asmith","enabled":true,"member_of":[]},
 "changes":[{"field":"enabled","before":null,"after":true}],"drift":[],"replayed":false,
 "executed_at":"2026-10-01T09:30:12Z","error":null,"credential_ref":"vault://ad/asmith/initial"}
```

---

## 2. SQL server (`sql`, `SQL_SERVER`)

### Models
```python
class SqlLogin(BaseModel):
    login_name: str
    login_type: Literal["WINDOWS_LOGIN", "WINDOWS_GROUP", "SQL_LOGIN", "EXTERNAL_PROVIDER"]
    sid: str | None = None; default_database: str | None = None
    is_disabled: bool; server_roles: list[str] = []; create_date: datetime; modify_date: datetime

class SqlDatabaseUser(BaseModel):
    database: str; user_name: str
    user_type: Literal["MAPPED_TO_LOGIN", "CONTAINED", "EXTERNAL_PROVIDER", "WITHOUT_LOGIN"]
    mapped_login: str | None = None; default_schema: str | None = None
    database_roles: list[str] = []; create_date: datetime

class SqlRole(BaseModel):
    role_name: str; scope: Literal["SERVER", "DATABASE"]; database: str | None = None
    owner: str | None = None; is_fixed: bool = False; members: list[str] = []

class SqlPermission(BaseModel):
    scope: Literal["SERVER", "DATABASE", "SCHEMA", "OBJECT"]
    database: str | None = None; securable: str | None = None        # "SCHEMA::finance" | "dbo.Invoices"
    permission: str                                                  # SELECT | INSERT | UPDATE | DELETE | EXECUTE | VIEW DEFINITION …
    grantee: str; state: Literal["GRANT", "GRANT_WITH_GRANT_OPTION", "DENY"]
    grantor: str | None = None; expires_at: datetime | None = None

class SqlRoleMembership(BaseModel):
    role_name: str; scope: Literal["SERVER", "DATABASE"]; database: str | None = None
    member: str; via: str = "DIRECT"

class SqlUserView(BaseModel):  login: SqlLogin | None; database_users: list[SqlDatabaseUser]
class SqlRolesView(BaseModel):  roles: list[SqlRole]; memberships: list[SqlRoleMembership]
class SqlInheritedPermission(BaseModel):  permission: SqlPermission; via_role: str
class SqlPermissionsView(BaseModel):  principal: str; direct: list[SqlPermission]; inherited: list[SqlInheritedPermission]
class CreateLoginResult(WriteResult[SqlLogin]):  credential_ref: str | None = None
```

### Tools
| Tool | In → Out | Behavior / errors |
|---|---|---|
| `create_login` | `login_name*`, `login_type*`, `default_database?`, `credential_mode=GENERATE_AND_ESCROW` (SQL_LOGIN only), `check_policy=true`, `check_expiration=true` → `CreateLoginResult` | Prefer `WINDOWS_LOGIN` (no credential). Exists → `EXISTS`+`drift` (**Scenario 6**: no duplicate; agent inspects and decides). |
| `disable_login` | `login_name*`, `reason*`, `kill_sessions=false` → `WriteResult[SqlLogin]` | Already disabled → `NO_CHANGE`. |
| `create_database_user` | `database*`, `user_name*`, `user_type=MAPPED_TO_LOGIN`, `for_login?`, `default_schema="dbo"` → `WriteResult[SqlDatabaseUser]` | `MAPPED_TO_LOGIN` requires the login to exist, else `BLOCKED PRECONDITION_FAILED`. Exists → `EXISTS`+`drift`. |
| `create_role` | `role_name*`, `scope*`, `database?` (required when `DATABASE`), `owner?` → `WriteResult[SqlRole]` | Exists → `EXISTS`. Fixed role names (`db_owner`, `sysadmin`, …) → `PROTECTED_OBJECT`. |
| `grant_permission` | `grantee*`, `grantee_kind*` (`LOGIN`\|`DATABASE_USER`\|`ROLE`), `scope*`, `database?`, `securable?`, `permission*`, `with_grant_option=false`, `expires_at?` → `WriteResult[SqlPermission]` | Already granted → `NO_CHANGE`. Config blocklist (`CONTROL`, `ALTER ANY *`, `IMPERSONATE`, `with_grant_option=true`) → `BLOCKED PROTECTED_OBJECT` unless the grant is marked privileged. Expiry only if `supports_expiry`. |
| `revoke_permission` | same as grant + `cascade=false` → `WriteResult[SqlPermission]` | Not granted → `NO_CHANGE`. This tool never issues `DENY`. |
| `get_user` | `login_name?` **or** (`database?`+`user_name?`) → `ReadResult[SqlUserView]` | Exactly one addressing mode, else `VALIDATION_ERROR`. |
| `get_roles` | `principal?`, `database?`, `scope?`, `include_members=false` → `ReadResult[SqlRolesView]` | `principal` set → that principal's memberships; else role listing. |
| `get_permissions` | `principal*`, `database?`, `securable?`, `include_inherited=true` → `ReadResult[SqlPermissionsView]` | |
| **`add_role_member`** (addition) | `role_name*`, `scope*`, `database?`, `member*`, `member_kind*` → `WriteResult[SqlRoleMembership]` | Needed for role-based entitlements (`ALTER ROLE … ADD MEMBER`). Fixed server roles (`sysadmin`, `securityadmin`, `serveradmin`) → `PROTECTED_OBJECT`. Already member → `NO_CHANGE`. |
| **`remove_role_member`** (addition) | same → `WriteResult[SqlRoleMembership]` | Not a member → `NO_CHANGE`. |
| `health_check`, `get_account_state` | `account_id` = login name; `scope.database?` | `entitlements` = server roles + database roles + direct permissions (`entitlement_type` ROLE / PERMISSION). |

### Governance (manifest)
| tool | capability | RO | approval | risk | idem | dry-run | destructive | compensating |
|---|---|---|---|---|---|---|---|---|
| create_login | account.create (`LOGIN`) | N | **Y** | HIGH | Y | Y | N | disable_login |
| disable_login | account.disable (`LOGIN`) | N | **Y** | HIGH | Y | Y | Y | none |
| create_database_user | account.create (`DB_USER`) | N | N | MEDIUM | Y | Y | N | none |
| create_role | role.create | N | **Y** | HIGH | Y | Y | N | none |
| grant_permission | permission.grant | N | **Y** | HIGH | Y | Y | N | revoke_permission |
| revoke_permission | permission.revoke | N | **Y** | HIGH | Y | Y | Y | grant_permission |
| get_user / get_roles / get_permissions | account.read / role.read / permission.read | Y | N | LOW | Y | – | – | – |
| add_role_member | role.add_member | N | N* | MEDIUM | Y | Y | N | remove_role_member |
| remove_role_member | role.remove_member | N | **Y** | MEDIUM | Y | Y | Y | add_role_member |

### Example — `create_login` when the login already exists (Scenario 6)
```json
{"status":"SUCCESS","outcome":"EXISTS","target":{"system_id":"SQL_SERVER","object_type":"LOGIN","native_id":"CORP\\jsmith","scope":{}},
 "after":{"login_name":"CORP\\jsmith","login_type":"WINDOWS_LOGIN","is_disabled":false,"default_database":"master","server_roles":[]},
 "drift":[{"field":"default_database","before":"master","after":"FinanceDB"}],"changes":[],"replayed":false,
 "executed_at":"2026-10-01T09:31:00Z","error":null,"credential_ref":null}
```

---

## 3. Linux server (`linux`, `LINUX`) — every tool is per `host`

### Models
```python
class LinuxUser(BaseModel):
    host: str; username: str; uid: int; primary_group: str; home_dir: str; shell: str
    gecos: str | None = None; locked: bool; expires_on: date | None = None
    groups: list[str] = []; ssh_key_fingerprints: list[str] = []; sudo_rule_ids: list[str] = []

class LinuxGroup(BaseModel):
    host: str; name: str; gid: int; system_group: bool = False; members: list[str] = []

class LinuxMembership(BaseModel):
    host: str; username: str; group: str; added_at: datetime | None = None; expires_at: datetime | None = None

class SudoRule(BaseModel):
    host: str; rule_id: str; principal: str; principal_type: Literal["USER", "GROUP"]
    run_as: str = "root"; commands: list[str]; nopasswd: bool = False
    source_file: str                                   # /etc/sudoers.d/iam-<rule_id>
    expires_at: datetime | None = None

class LinuxGroupsView(BaseModel):  host: str; groups: list[LinuxGroup]
```

### Tools
| Tool | In → Out | Behavior / errors |
|---|---|---|
| `create_user` | `host*`, `username*` (`^[a-z_][a-z0-9_-]{0,31}$`), `full_name?`, `uid?`, `primary_group?`, `home_dir?`, `shell="/bin/bash"`, `create_home=true`, `ssh_public_keys=[]`, `expires_on?` → `WriteResult[LinuxUser]` | No password is ever set (account created with locked password; key/SSSD auth). Exists → `EXISTS`+`drift`. UID taken by another user → `NATURAL_KEY_CONFLICT`. UID < 1000 or reserved name (`root`, `daemon`…) → `PROTECTED_OBJECT`. |
| `disable_user` | `host*`, `username*`, `reason*`, `revoke_ssh_keys=false`, `kill_sessions=false` → `WriteResult[LinuxUser]` | Lock password + expire account. Already locked → `NO_CHANGE`. Does not remove groups/sudo (separate planned removals). |
| `create_group` | `host*`, `name*`, `gid?`, `system=false` → `WriteResult[LinuxGroup]` | Exists → `EXISTS`+`drift`. |
| `add_user_to_group` | `host*`, `username*`, `group*`, `expires_at?` → `WriteResult[LinuxMembership]` | Supplementary groups only. Member already → `NO_CHANGE`. |
| `remove_user_from_group` | `host*`, `username*`, `group*` → `WriteResult[LinuxMembership]` | Primary group → `PRECONDITION_FAILED`. Not a member → `NO_CHANGE`. |
| `grant_sudo` | `host*`, `principal*`, `principal_type*`, `commands*` (absolute paths or named aliases), `run_as="root"`, `nopasswd=false`, `expires_at?`, `rule_name?` → `WriteResult[SudoRule]` | Rule file name deterministic: `iam-<hash(principal,commands,run_as,nopasswd)>` under `/etc/sudoers.d/` only (never edit `/etc/sudoers`). Syntax-validated (visudo `-cf` equivalent) before activation → `VALIDATION_ERROR`. `ALL` or `nopasswd` + broad commands → `PROTECTED_OBJECT` unless marked privileged. Same rule exists → `NO_CHANGE`. |
| `revoke_sudo` | `host*`, `principal*`, `principal_type*`, `rule_id?` → `WriteResult[SudoRule]` | No `rule_id` = all IAM-managed rules of the principal. Only `iam-` files are managed; others → `PROTECTED_OBJECT`. Absent → `NO_CHANGE`. |
| `get_user` | `host*`, `username?` \| `uid?` → `ReadResult[LinuxUser]` | Includes groups and sudo rule ids. |
| `get_groups` | `host*`, `username?`, `group_name?`, `include_system=false` → `ReadResult[LinuxGroupsView]` | `username` → that user's groups; `group_name` → one group + members; neither → all. |
| `health_check`, `get_account_state` | `account_id` = username; `scope.host*` | `entitlements` = groups (`GROUP`) + sudo rules (`SUDO_RULE`). |

### Governance (manifest)
| tool | capability | RO | approval | risk | idem | dry-run | destructive | compensating |
|---|---|---|---|---|---|---|---|---|
| create_user | account.create | N | N | MEDIUM | Y | Y | N | disable_user |
| disable_user | account.disable | N | **Y** | HIGH | Y | Y | Y | none |
| create_group | group.create | N | **Y** | MEDIUM | Y | Y | N | none |
| add_user_to_group | group.add_member | N | N* | MEDIUM | Y | Y | N | remove_user_from_group |
| remove_user_from_group | group.remove_member | N | **Y** | MEDIUM | Y | Y | Y | add_user_to_group |
| grant_sudo | privilege.sudo.grant | N | **Y** | CRITICAL | Y | Y | N | revoke_sudo |
| revoke_sudo | privilege.sudo.revoke | N | **Y** | HIGH | Y | Y | Y | grant_sudo |
| get_user / get_groups | account.read / group.read | Y | N | LOW | Y | – | – | – |

---

## 4. App / SaaS server (`app`, `APP_X` + `APP_Y`) — generic, SCIM-shaped

Every tool takes `system_id*` (`APP_X`, `APP_Y`, … ) so one mock serves many apps. Application entitlements may also be AD groups (e.g. `APP_X_ADMIN` in the seed is an AD group); Knowledge's `Entitlement.system_id` decides which server executes.

### Models
```python
class AppAccountLookup(BaseModel):         # exactly ONE
    account_id: str | None = None; user_name: str | None = None; external_id: str | None = None

class AppAccount(BaseModel):
    system_id: str; account_id: str; user_name: str; display_name: str | None = None
    email: str | None = None; external_id: str | None = None      # employee_id correlation
    active: bool; roles: list[str] = []; attributes: dict[str, AttrValue] = {}
    created_at: datetime; last_modified: datetime

class AppRole(BaseModel):
    system_id: str; role_id: str; name: str; description: str | None = None
    permissions: list[str] = []; is_system: bool = False; members_count: int = 0

class AppRoleAssignment(BaseModel):
    system_id: str; account_id: str; role_id: str
    assigned_at: datetime | None = None; expires_at: datetime | None = None
```

### Tools
| Tool | In → Out | Behavior / errors |
|---|---|---|
| `create_account` | `system_id*`, `user_name*`, `email*`, `external_id*`, `display_name?`, `initial_roles=[]`, `attributes={}`, `active=true` → `WriteResult[AppAccount]` | Natural keys: user_name, external_id, email. Exists → `EXISTS`+`drift`. |
| `get_account` | `system_id*`, `account*: AppAccountLookup` → `ReadResult[AppAccount]` | |
| `update_account` | `system_id*`, `account*`, `changes*: list[AttributeChange]` → `WriteResult[AppAccount]` | Allowed: `display_name`, `email`, `attributes.*`. `active`/`roles` → `PROTECTED_ATTRIBUTE`. |
| `disable_account` | `system_id*`, `account*`, `reason*` → `WriteResult[AppAccount]` | Already inactive → `NO_CHANGE`. |
| `create_role` | `system_id*`, `name*`, `description*`, `permissions*: list[str]` → `WriteResult[AppRole]` | Exists → `EXISTS`+`drift`. |
| `get_role` | `system_id*`, `role_id?` \| `name?`, `include_members=false` → `ReadResult[AppRole]` | |
| `assign_role` | `system_id*`, `account*`, `role*` (id or name), `expires_at?` → `WriteResult[AppRoleAssignment]` | Already assigned → `NO_CHANGE`. Expiry only if `supports_expiry`. |
| `revoke_role` | `system_id*`, `account*`, `role*` → `WriteResult[AppRoleAssignment]` | Not assigned → `NO_CHANGE`. |
| `health_check`, `get_account_state` | `account_id`; `scope.system_id*` | `entitlements` = roles (`APP_ROLE`). |

### Governance (manifest)
| tool | capability | RO | approval | risk | idem | dry-run | destructive | compensating |
|---|---|---|---|---|---|---|---|---|
| create_account | account.create | N | N | MEDIUM | Y | Y | N | disable_account |
| get_account | account.read | Y | N | LOW | Y | – | – | – |
| update_account | account.update | N | N | MEDIUM | Y | Y | N | update_account |
| disable_account | account.disable | N | **Y** | HIGH | Y | Y | Y | none |
| create_role | role.create | N | **Y** | HIGH | Y | Y | N | none |
| get_role | role.read | Y | N | LOW | Y | – | – | – |
| assign_role | role.add_member | N | N* | MEDIUM | Y | Y | N | revoke_role |
| revoke_role | role.remove_member | N | **Y** | MEDIUM | Y | Y | Y | assign_role |

---

## 5. Per-server acceptance checklist (copy into each server's tests)

1. `tools/list` matches the table above; manifest governance == tool annotations (`readOnlyHint`, `idempotentHint`, `destructiveHint`).
2. Each write: first call → `CREATED/UPDATED`; second identical call (new key) → `EXISTS`/`NO_CHANGE`; same idempotency key → `replayed=true`.
3. `dry_run=true` → no state change; `predicted_outcome` + `changes` equal what the real call later applies.
4. No `execution_grant` / wrong `args_hash` / expired → `BLOCKED GRANT_*`; **no side effect**.
5. Natural-key collision, protected object/attribute, unsupported expiry → `BLOCKED` with the documented code.
6. Injected transient fault → `RETRYABLE` and state unchanged.
7. After every write, `get_account_state` reflects exactly `after`.
8. No secret appears in any response, log line or audit payload.
