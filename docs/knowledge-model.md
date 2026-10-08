# Knowledge Model and Seed Dataset

Entities, temporal rules, tools: `docs/contracts/knowledge-mcp.md`. This file specifies the **seed data** (`knowledge/seed/*.yaml`) that the demos and evals depend on. Dates are relative to `T` = `SEED_NOW` (tests: `2026-06-01T00:00:00Z`).

## Systems and account schemas (v1)
| `system_id` | kind | owner | account types | naming / derivation |
|---|---|---|---|---|
| `ACTIVE_DIRECTORY` | DIRECTORY | it-directory | USER | `sam_account_name = lower(substr(input.given_name,0,1) + input.surname)` (≤ 20, `^[a-z][a-z0-9]{1,19}$`, collision ⇒ append number). UPN `given.surname@corp.example.com`. `ou = "OU=" + input.department + ",OU=Users,DC=corp,DC=example,DC=com"`. Protected: `objectSid`, `adminCount`, `userAccountControl`. |
| `SQL_SERVER` | DATABASE | dba-team | LOGIN | `login_name = "CORP\\" + sam`, type `WINDOWS_LOGIN`, default DB `FinanceDB` for Finance |
| `LINUX` | OS | platform-ops | USER (scope `host`) | `username = sam`, shell `/bin/bash` |
| `APP_X`, `APP_Y` | APPLICATION | appx-owners / appy-owners | ACCOUNT | `account_id = email` |

## Identities (HR fixture)
| id | Name | Dept / status | Manager | Used for |
|---|---|---|---|---|
| EMP-1001 | Alice Smith | Finance / ACTIVE | EMP-1000 | Main demo: no accounts yet |
| EMP-1000 | Eve Martin | Finance / ACTIVE | — | Alice's manager; owner of finance entitlements |
| EMP-1002 | Bob Rao | Engineering / ACTIVE | EMP-1010 | Has AD, Linux, holds `APP_X_ADMIN` |
| EMP-1003 | Carol Diaz | Finance / ACTIVE | EMP-1000 | Holds `FIN_WRITE` (SoD demo) |
| EMP-1004 | Dan Wu | Sales / **LEAVER** | EMP-1011 | Leaver deny |
| EMP-1005 / 1006 | Chris Park / Chris Patel | IT / ACTIVE | — | Ambiguous name |
| EMP-1007 | Frank Ito | Finance / **CONTRACTOR** | EMP-1000 | Contractor approval rule |
| EMP-1008 | John Smith | Finance / ACTIVE | EMP-1000 | SQL login already exists (scenario 6) |
| EMP-1010 / 1011 | Gina Okafor / Hal Brooks | Engineering / Sales | — | Managers |
| EMP-1020 | Ivy Chen | IT / ACTIVE, role `iam-admin` | — | Knowledge changes |
| EMP-1021 | Sam Park | Security / ACTIVE, role `security-approver` | — | High-risk approver |

## Entitlements
| `entitlement_id` | System · native id (scope) | Status | Risk | Notes |
|---|---|---|---|---|
| `FIN_READ` | AD group `GRP_Finance_Read` | ACTIVE | LOW | tag `finance-read`, owner EMP-1000 |
| `FIN_WRITE` | AD group `GRP_Finance_Write` | ACTIVE | MEDIUM | `CONFLICTS_WITH FIN_AUDIT` (HARD) |
| `FIN_AUDIT` | AD group `GRP_Finance_Audit` | ACTIVE | MEDIUM | |
| `ENG_ALL` | AD group `GRP_Engineering` | ACTIVE | LOW | |
| `SQL_FIN_READER` | SQL role `db_datareader` (`database=FinanceDB`) | ACTIVE | MEDIUM | `DEPENDS_ON FIN_READ` (HARD) |
| `SQL_FIN_WRITER` | SQL role `db_datawriter` (`FinanceDB`) | ACTIVE | HIGH | `DEPENDS_ON FIN_WRITE` |
| `SQL_SYSADMIN` | SQL server role `sysadmin` | **BLOCKED** | CRITICAL | `requestable=false` |
| `LX_DEVOPS` | Linux group `devops` (`host=lx-prod-01`) | ACTIVE | MEDIUM | |
| `LX_SUDO_DEPLOY` | Linux sudo rule `deploy` (`lx-prod-01`) | ACTIVE | CRITICAL | `DEPENDS_ON LX_DEVOPS`; approval ALL (security + system owner) |
| `APP_X_USER` | App role `user` (APP_X) | ACTIVE | LOW | |
| `APP_X_ADMIN` | App role `admin` (APP_X) | timeline below | HIGH | replaced by `APP_X_PLATFORM_ADMIN` |
| `APP_X_PLATFORM_ADMIN` | App role `platform_admin` (APP_X) | ACTIVE since T-120d | HIGH | `REPLACES APP_X_ADMIN` |
| `APP_Y_VIEWER` | App role `viewer` (APP_Y) | ACTIVE | LOW | |
| `APP_Y_AUDITOR` | App role `auditor` (APP_Y) | **PROPOSED** (v1 @T-5d) | MEDIUM | → `NOT_YET_EFFECTIVE` |
| `LEGACY_FIN_RW` | AD group `GRP_Legacy_Fin_RW` | **RETIRED** (@T-200d) | HIGH | replaced by `FIN_WRITE` |

`APP_X_ADMIN` timeline (worked example in the Knowledge contract §2): v1 PROPOSED @T-540d · v2 ACTIVE @T-520d · v3 ACTIVE @T-400d · v4 DEPRECATED @T-120d (replacement `APP_X_PLATFORM_ADMIN`, `retire_at=T+60d`) · v5 RETIRED @T+60d (scheduled).

## Recorded accounts and assignments (Knowledge) and provider mock seeds
* Bob (`brao`): AD user, Linux user on `lx-prod-01`; assigned `ENG_ALL`, `LX_DEVOPS`, `APP_X_ADMIN` (assigned @T-300d, entitlement version 3).
* Carol (`cdiaz`): AD user; `FIN_WRITE`. Frank (`fito`): AD user. Eve (`emartin`): AD user.
* Each provisioner mock seeds the same accounts from `docker/seed/*.json` (generated from the YAML), **plus deliberate drift** for the reconciliation demo: Bob is also in `GRP_Finance_Read` in AD (not in Knowledge), Carol is missing from `GRP_Finance_Write` in AD (in Knowledge).
* `SQL_SERVER` mock already has the login `CORP\jsmith` (WINDOWS_LOGIN, default database `master`, no roles) for John Smith (EMP-1008). Requesting his SQL login with default database `FinanceDB` yields `EXISTS` + drift (scenario 6, same as the contract example).

## Policies (seed history; `knowledge/policies/*.yaml`)
| Policy | Versions | Behavior |
|---|---|---|
| `POL_FINANCE_READ` | v1 @T-300d · v2 @T-100d · **v3 applied live in the demo** | v1: ALLOW if subject dept ∈ {Finance, Audit} and ACTIVE. v2: adds approval rule: CONTRACTOR ⇒ MANAGER, SLA 24 h. v3: every finance-read assignment ⇒ ENTITLEMENT_OWNER approval + `REQUIRE_JUSTIFICATION`. |
| `POL_FINANCE_WRITE` | v1 | ALLOW Finance employees, MANAGER approval; DENY contractors |
| `POL_PRIVILEGED` | v1 | Scope risk ∈ {HIGH, CRITICAL}: approval SYSTEM_OWNER (+ SECURITY, mode ALL for CRITICAL); DENY contractors on CRITICAL |
| `POL_LEAVERS` | v1 | DENY any ASSIGN/CREATE for `subject.employment_status = LEAVER` (`SUBJECT_LEAVER`) |
| `POL_ACCOUNT_CREATE` | v1 | ALLOW CREATE_ACCOUNT for ACTIVE employees; contractors need MANAGER approval |
| `POL_APP_STANDARD` | v1 | ALLOW ASSIGN of LOW/MEDIUM APP_X/APP_Y entitlements to ACTIVE employees, no approval |
| `POL_KNOWLEDGE_CHANGE` | v1 | ALLOW CREATE_ENTITLEMENT / CHANGE_ENTITLEMENT_STATUS / PUBLISH_POLICY if `requester.roles` contains `iam-admin`; approval SECURITY |
Remember: the tool-level `requires_approval` floor still forces an APPROVED approval behind every provisioner write, so an ALLOW with no approval rules is backed by a **policy-auto approval**.

## Seed profiles (`SEED_PROFILE`)
* `default`: everything above, including the already-deprecated `APP_X_ADMIN` (v4, v5 scheduled) and `POL_FINANCE_READ` v1–v2. Demos 1–9 run on it.
* `acceptance`: `APP_X_ADMIN` seeded **only through v3 (ACTIVE)** and `POL_FINANCE_READ` through v2, so the final acceptance test performs the deprecation and the policy v3 change live through the proposal flow (`docs/evaluation.md`).

## Seed rules
Idempotent loader · chronological commits · deterministic ids (`ENT-…` = the stable `entitlement_id`) · a `seed_version` string in `get_knowledge_version` · unit test asserts the seed validates against every schema and produces the §2 worked-example resolutions.
