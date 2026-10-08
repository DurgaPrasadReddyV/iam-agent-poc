"""Every skill must parse and reference only tools/capabilities that exist in the contracts."""
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SKILLS = sorted((ROOT / "skills").glob("*/SKILL.md"))
KEYS = {"name", "description", "risk_level", "required_context", "allowed_tools", "input_schema", "output_schema"}
SECTIONS = ["# ", "## Purpose", "## Use when", "## Procedure", "## Guardrails", "## Output", "## Failure handling", "## Example"]
SERVER_DOCS = {
    "knowledge": "knowledge-mcp.md", "policy": "platform-mcps.md", "memory": "platform-mcps.md",
    "approval": "platform-mcps.md", "audit": "platform-mcps.md", "notification": "platform-mcps.md",
}


def _tokens(doc: str) -> set[str]:
    text = (ROOT / "docs" / "contracts" / doc).read_text(encoding="utf-8")
    return set(re.findall(r"`([a-z][a-z_]+)`", text))


def _capabilities() -> set[str]:
    text = (ROOT / "docs" / "contracts" / "00-conventions.md").read_text(encoding="utf-8")
    return set(re.findall(r"`((?:account|group|role|permission|privilege)\.[a-z_.]+)`", text))


def _load(path: Path) -> tuple[dict, str]:
    match = re.match(r"---\n(.*?)\n---\n(.*)", path.read_text(encoding="utf-8"), re.S)
    assert match, f"{path}: missing frontmatter"
    return yaml.safe_load(match.group(1)), match.group(2)


def test_nine_skills_exist() -> None:
    assert len(SKILLS) == 9


@pytest.mark.parametrize("path", SKILLS, ids=lambda p: p.parent.name)
def test_skill_is_valid(path: Path) -> None:
    meta, body = _load(path)
    assert set(meta) == KEYS
    assert meta["name"] == path.parent.name
    assert meta["risk_level"] in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
    for marker in SECTIONS:
        assert marker in body, f"{path.parent.name}: missing section {marker.strip()}"
    capabilities = _capabilities()
    for tool in meta["allowed_tools"]:
        if tool.startswith("capability:"):
            assert tool.split(":", 1)[1] in capabilities, f"unknown capability {tool}"
        else:
            server, name = tool.split(".", 1)
            assert name in _tokens(SERVER_DOCS[server]), f"unknown tool {tool}"
