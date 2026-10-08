# Memory

Contract: `docs/contracts/platform-mcps.md §2`. Memory is **non-authoritative**: it improves speed and consistency, never correctness or authorization.

## Where memory is used
* **Read:** LOAD_RELEVANT_MEMORY retrieves ≤ 5 records (`memory_search` with subject refs of the resolved objects). They are passed to GENERATE_PLAN only, wrapped as untrusted hints (`<memory authoritative="false">`). Policy, validation and approval never see memory.
* **Write:** only the post-run learning pipeline (`agent/memory/learner.py`, async after WRITE_AUDIT). The LLM cannot call memory write tools.

## Learning pipeline (deterministic, from the audit timeline of the finished request)
1. Extract candidates with rules, not free text: clarification resolved (`"Chris" → EMP-1005`), approver response times, recurring failure + workaround, explicit user preference ("always use the Finance OU"), successful plan shape for a recurring request type.
2. Drop candidates that restate Knowledge-owned facts (entitlement status, policy outcome) or contain secrets or personal data beyond ids.
3. Check each against Knowledge at the pinned version. Conflict ⇒ do not write.
4. `memory_write` (dedupe merges duplicates and reinforces). Outcome of the request reinforces retrieved memories (`HELPFUL`/`UNHELPFUL`).

## Conflicts with Knowledge
On retrieval, memories about entitlements or policies are re-checked against Knowledge. If they disagree: `memory_flag_conflict`, exclude from context, log `MEMORY_CONFLICT`. Knowledge always wins (eval SAF-04; graceful degradation: REL-09).

## Retention
`expires_at` for observations (default 180 days). Confidence decays by non-use through the recency term. `memory_forget` is soft by default; hard delete only by a human actor.

## Good vs bad memory
Good: "Requests for finance reports from Audit usually mean `FIN_READ`; confirmed 3×." Bad: "`APP_X_ADMIN` is active" (Knowledge owns status), "Alice's password is …" (secret), "Always approve Bob" (authorization).
