---
name: policy-evaluation
description: "Evaluate and explain policy decisions for a request or plan, and draft, simulate and propose policy changes (new policy versions). The decision itself is always made by the deterministic Policy MCP."
risk_level: MEDIUM
required_context: [requester, subject_identity, resolved_objects, held_entitlements, knowledge_pin]
allowed_tools: [
  policy.evaluate_policy, policy.evaluate_plan, policy.explain_decision, policy.get_policy_set_version,
  policy.simulate_policy_change, knowledge.get_policy, knowledge.list_policies, knowledge.search_entitlements,
  knowledge.get_entitlement, knowledge.propose_knowledge_change, knowledge.get_knowledge_proposal,
  knowledge.list_knowledge_proposals, memory.memory_search]
input_schema: {type: object, required: [mode], properties: {mode: {enum: [EVALUATE, EXPLAIN, PROPOSE_CHANGE]}, decision_id: {type: string}, policy_id: {type: string}, change_description: {type: string}, sample_requests: {type: array, items: {type: object}}}}
output_schema: {type: object, properties: {decision: {type: object, x-model: iam_contracts.policy.PolicyDecision}, explanation: {type: array, items: {type: string}}, proposal: {type: object, x-model: iam_contracts.knowledge.KnowledgeProposal}, simulation: {type: array, items: {type: object}}}}
---
# Policy Evaluation

## Purpose
Make policy outcomes understandable and let administrators evolve policy safely. Policy is data in Knowledge; the engine is deterministic (deny-overrides, default-deny).

## Use when
State EVALUATE_POLICY (executed by the engine with this skill's tools), questions like "why was this denied?", and intent `PROPOSE_POLICY_CHANGE`.

## Procedure
1. **Evaluate:** `evaluate_policy` with the exact inputs gathered by earlier states (never inferred ones). Missing inputs are reported as `INPUT_MISSING`; do not fill them in.
2. **Explain:** `explain_decision` ⇒ render the deterministic reasons, matched policy versions and approvals. Explanations quote codes and versions; they never reinterpret.
3. **Propose change:** read the current version with `get_policy`; draft a `PolicyDraft` as a typed condition tree (never a string). Run `simulate_policy_change` over representative sample requests (include requests that must keep their old outcome) and show before/after. Then `propose_knowledge_change(PUBLISH_POLICY_VERSION)`.
4. The workflow creates the approval (SECURITY), mints the grant and applies. The new version gets a new `knowledge_version`; older decisions stay reproducible.

## Guardrails
The LLM never overrides or "interprets" a decision. A policy change cannot loosen policy for an entitlement tagged HIGH/CRITICAL without an explicit simulation that shows it. Requester must hold `iam-admin` (policy `POL_KNOWLEDGE_CHANGE`).

## Output
`PolicyDecision`, deterministic explanation lines, and for changes a `KnowledgeProposal` with the simulation.

## Failure handling
Simulation shows an unexpected outcome change ⇒ do not propose; report the differing samples. Engine error ⇒ FAILED (never default to ALLOW).

## Example
"Finance read must now be approved by the entitlement owner" ⇒ `POL_FINANCE_READ` v3 draft, simulation: Alice's earlier ALLOW becomes `APPROVAL_REQUIRED`, contractor outcome unchanged.
