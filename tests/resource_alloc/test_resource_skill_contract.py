from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "research-resource" / "SKILL.md"
RUN_SKILL = ROOT / "skills" / "research-run" / "SKILL.md"
CLAUDE = ROOT / "CLAUDE.md"


def test_research_resource_skill_carries_allocation_protocol():
    text = SKILL.read_text(encoding="utf-8")

    for phrase in (
        "outputs/_resources/servers.json",
        "allocations.jsonl",
        "lib/resource_alloc/cli.py",
        "recommends, the agent decides",
        "reject-before-write",
        "release",
        "verified completion",
        "alloc_id",
        "never drives a remote",
        "CUDA_VISIBLE_DEVICES",
    ):
        assert phrase in text, phrase

    assert "git " not in text.lower()


def test_launch_hooks_are_additive():
    run_text = RUN_SKILL.read_text(encoding="utf-8")
    assert "outputs/_resources/servers.json" in run_text
    assert "research-resource" in run_text

    claude = CLAUDE.read_text(encoding="utf-8")
    assert "resource registry" in claude
