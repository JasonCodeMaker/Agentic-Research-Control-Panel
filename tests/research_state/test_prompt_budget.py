from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMMON_SKILLS = (
    "research-brainstorm",
    "research-op",
    "research-package",
    "research-run",
)


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_bootloaders_are_independently_bounded() -> None:
    agents = _text("AGENTS.md")
    claude = _text("CLAUDE.md")

    assert len(agents) <= 5_000
    assert len(claude) <= 5_200
    assert "Do not automatically read" in agents
    assert "Required Read Order" not in agents
    assert "independently sufficient" in claude
    for bootloader in (agents, claude):
        assert "invoke `humanizer` and use its final rewrite" in bootloader
        assert "invoke `ponytail`" in bootloader
        assert "invoke `ponytail-review` on the resulting diff" in bootloader


def test_bootloader_plus_one_common_skill_stays_below_prompt_budget() -> None:
    bootloader = _text("AGENTS.md")

    for skill in COMMON_SKILLS:
        body = _text(f"skills/{skill}/SKILL.md")
        assert len(bootloader) + len(body) <= 15_000, skill


def test_normal_skills_route_compatibility_out_of_default_context() -> None:
    package = _text("skills/research-package/SKILL.md")
    operation = _text("skills/research-op/SKILL.md")

    assert "references/compatibility-workflows.md" in package
    assert "references/compatibility-scope.md" in operation
    assert "Do not load compatibility guidance" in package
    assert "Normal Project and Package work does not load" in operation
