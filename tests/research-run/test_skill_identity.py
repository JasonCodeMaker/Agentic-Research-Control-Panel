"""Skill identity contract for the narrowed /research-run command."""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _frontmatter(path):
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert m, f"{path} has no YAML frontmatter"
    return m.group(1), text


def test_research_run_skill_is_the_package_completion_entrypoint():
    fm, text = _frontmatter(ROOT / "skills" / "research-run" / "SKILL.md")
    assert re.search(r"^name:\s*research-run\s*$", fm, re.M)
    assert "/research-run" in fm
    assert "complete an existing scoped research package" in fm
    assert "R1 scope" not in fm
    assert "R2 search/read" not in fm
    assert "R3 ideate" not in fm
    assert "complete the package" in text


def test_research_run_documents_workflow_ticket_and_loop_discipline():
    _, text = _frontmatter(ROOT / "skills" / "research-run" / "SKILL.md")
    for token in (
        "workflowState",
        "requiredMutations",
        "stopGate",
        "perRun",
        "Resume Block",
        "cross-stage to-do",
        "Shared agent return",
    ):
        assert token in text


def test_research_auto_is_only_a_compatibility_alias():
    fm, text = _frontmatter(ROOT / "skills" / "research-auto" / "SKILL.md")
    assert re.search(r"^name:\s*research-auto\s*$", fm, re.M)
    assert "/research-run" in fm
    assert "compatibility alias" in text
    assert "scripts/admission.py" not in text
