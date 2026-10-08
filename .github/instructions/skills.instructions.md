---
applyTo: "skills/**"
---
# Skill rules
- A skill is `skills/<name>/SKILL.md`: YAML frontmatter (`name` = folder name, `description`, `risk_level`, `required_context`, `allowed_tools`, `input_schema`, `output_schema`) then the sections Purpose, Use when, Procedure, Guardrails, Output, Failure handling, Example.
- Always quote `description` (a colon breaks YAML). `allowed_tools` entries are `server.tool` (must exist in `docs/contracts/`) or `"capability:<tag>"` (must exist in `00-conventions.md` section 7). `tests/skills` parses every skill and checks this.
- Least privilege: list only what a step needs. `capability:` entries constrain the plan; they never give the LLM direct provider access.
- Changing a skill: update `skills/README.md` if intents change, and add or adjust an eval case.
