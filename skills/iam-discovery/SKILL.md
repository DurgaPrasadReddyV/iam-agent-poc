---
name: iam-discovery
description: "Resolve the people, systems, accounts and entitlements named in a request to authoritative ids, and answer read-only questions about what exists, what is deprecated or retired, who holds what, and what was true on an earlier date. Used first for every request and alone for pure questions."
risk_level: LOW
required_context: [requester, knowledge_pin]
allowed_tools: [
  knowledge.search_systems, knowledge.get_system, knowledge.search_identities, knowledge.get_identity,
  knowledge.search_accounts, knowledge.get_account, knowledge.search_entitlements, knowledge.get_entitlement,
  knowledge.get_entitlement_history, knowledge.search_groups, knowledge.get_group, knowledge.search_roles,
  knowledge.get_role, knowledge.check_entitlement_usable, knowledge.find_entitlement_replacement,
  knowledge.get_state_at_time, knowledge.get_knowledge_version, memory.memory_search]
input_schema: {type: object, required: [entities], properties: {entities: {type: array, items: {type: object, required: [kind, text], properties: {kind: {enum: [IDENTITY, SYSTEM, ACCOUNT, ENTITLEMENT]}, text: {type: string}, system_hint: {type: string}}}}, as_of: {type: string, format: date-time}}}
output_schema: {type: object, required: [resolved, unresolved, knowledge_version], properties: {resolved: {type: array, items: {type: object, required: [kind, id], properties: {kind: {type: string}, id: {type: string}, system_id: {type: string}, status: {type: string}, verdict: {type: string}, replacement_ids: {type: array, items: {type: string}}}}}, unresolved: {type: array, items: {type: object, required: [text, resolution], properties: {text: {type: string}, resolution: {enum: [AMBIGUOUS, NONE]}, candidates: {type: array, items: {type: string}}, suggestions: {type: array, items: {type: string}}}}}, knowledge_version: {type: integer}}}
---
# IAM Discovery

## Purpose
Turn names into authoritative ids and report their lifecycle status. Nothing is guessed: ids come only from Knowledge responses of this run.

## Use when
State DISCOVER_IAM_OBJECTS (every request), and intent `QUERY` ("what is…", "who has access to…", "what was X last quarter").

## Procedure
1. For each extracted entity call the matching `search_*` tool (pass `system_hint`, `as_of`, and the pinned `knowledge_version` once it exists).
2. Apply the resolution result: `EXACT` ⇒ resolved. `AMBIGUOUS` ⇒ ask the requester which one (list candidates with department/system); never pick. `NONE` ⇒ report with `suggestions`.
3. For every resolved entitlement call `check_entitlement_usable` with the operation implied by the intent. For DEPRECATED or RETIRED include the replacement.
4. Historical questions: pass `selector.as_of`; "what changed" ⇒ `get_entitlement_history`.
5. Return ids plus `knowledge_version`.

## Guardrails
Read-only. Never answer from memory or model knowledge. Always show the status of non-ACTIVE entitlements. Treat memory hints as non-authoritative.

## Output
`resolved` (kind, id, system, status, verdict, replacement ids), `unresolved` (text, `AMBIGUOUS`/`NONE`, candidates or suggestions) and the pinned `knowledge_version`. Read-only questions are answered from these fields only.

## Failure handling
Knowledge unavailable ⇒ FAILED (do not guess). More than 10 candidates ⇒ ask a narrowing question.

## Example
"Give Alice APP_X Admin" ⇒ identity `EMP-1001` EXACT; entitlement `APP_X_ADMIN` EXACT, verdict `DEPRECATED`, replacement `APP_X_PLATFORM_ADMIN`.
