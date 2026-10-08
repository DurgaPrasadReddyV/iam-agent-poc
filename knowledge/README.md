# knowledge/

Seed data and schemas for the Knowledge MCP (spec: `docs/knowledge-model.md`, loader: `docs/contracts/knowledge-mcp.md` section 7).

| Folder | Content |
|---|---|
| `systems/` | systems and account schemas (attributes, naming rules, defaults) |
| `entitlements/` | entitlements with explicit version lists (relative dates `T-120d`) |
| `policies/` | policy versions as typed condition trees |
| `seed/` | identities, relationships, recorded accounts and assignments, `profiles/` (`default`, `acceptance`) |
| `schemas/` | JSON Schemas generated from the Pydantic models, used to validate the YAML (`make seed` fails on invalid files) |

Rules: dates are relative to `SEED_NOW`; never put secrets here; every file validates against its schema in CI.
