---
applyTo: "tests/**"
---
# Test rules
- Deterministic: frozen `Clock` (`2026-06-01T00:00:00Z`), seeded ids, mock LLM cassettes, no network.
- Layers: unit (domain), contract (schema snapshots and tool behavior via in-memory MCP client), property (`hypothesis`), eval (`tests/end-to-end/evals`, IDs like `RET-01`, `SAF-03`), end-to-end scenarios.
- Eval cases are data (YAML/JSON): input request, seed state, expected refusal/plan/outcome and expected audit events. Assert on structured results, never on LLM prose.
- Every safety rule in `AGENTS.md` has at least one test that tries to violate it.
- Name tests after behavior (`test_deprecated_entitlement_is_refused_with_replacement`).
