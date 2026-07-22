import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "research-resource" / "SKILL.md"


def test_research_resource_skill_carries_allocation_protocol():
    text = SKILL.read_text(encoding="utf-8")

    for phrase in (
        "$RESEARCH_ROOT/state/research.sqlite3",
        "$RESEARCH_ROOT/interface/",
        ".research/state/",
        ".research/experiments/",
        ".research/interface/",
        "$XDG_RUNTIME_DIR",
        "Resource aggregates",
        "ResourceAllocation aggregates",
        "Short-lived local projection",
        "Read-only generated projection",
        "lib/resource_alloc/cli.py",
        "recommends, the agent decides",
        "rejects before",
        "release",
        "terminal evidence is verified",
        "alloc_id",
        "does not launch a command or drive",
        "CUDA_VISIBLE_DEVICES",
    ):
        assert phrase in text, phrase

    for retired in (
        "outputs/",
        "research_html",
        "RESEARCH_RUNTIME_ROOT",
        "servers.json",
        "allocations.jsonl",
        "--outputs-root",
    ):
        assert retired not in text

    assert "git " not in text.lower()


def test_resource_references_use_the_same_authority_boundary():
    references = SKILL.parent / "references"
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(references.glob("*.md"))
    )

    for phrase in (
        "$RESEARCH_ROOT/state",
        "$RESEARCH_ROOT/experiments",
        "$RESEARCH_ROOT/interface",
        "$XDG_RUNTIME_DIR",
        "short-lived",
    ):
        assert phrase in text

    for retired in (
        "outputs/",
        "research_html",
        "RESEARCH_RUNTIME_ROOT",
        "servers.json",
        "allocations.jsonl",
        "lib/exp_live",
    ):
        assert retired not in text


def test_every_resource_reference_has_a_skill_caller():
    references = SKILL.parent / "references"
    available = {path.name for path in references.glob("*.md")}
    linked = set(re.findall(r"\(references/([^)]+\.md)\)", SKILL.read_text(encoding="utf-8")))

    assert linked == available
