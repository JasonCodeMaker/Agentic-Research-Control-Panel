"""Identity and storage-boundary contract for /research-run."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "research-run" / "SKILL.md"
PRODUCTION = [
    SKILL,
    ROOT / "skills" / "research-run" / "scripts" / "admission.py",
    ROOT / "skills" / "research-run" / "scripts" / "driver.py",
    ROOT / "skills" / "research-run" / "scripts" / "skeleton.py",
]


def _frontmatter():
    text = SKILL.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert match
    return match.group(1), text


def test_skill_is_the_existing_package_experiment_executor():
    frontmatter, text = _frontmatter()
    assert re.search(r"^name:\s*research-run\s*$", frontmatter, re.M)
    description = re.search(
        r'^description:\s*"([^"]+)"\s*$',
        frontmatter,
        re.M,
    ).group(1)
    assert description.startswith("Use when")
    assert len(description) < 1024
    assert "existing research package" in description
    assert "one Experiment at a time" in text


def test_skill_documents_authoritative_state_and_command_seams():
    _, text = _frontmatter()
    for token in (
        "ResearchPaths",
        "StateQuery",
        "lib.experiments",
        "research-op",
        ".research/experiments/",
        "source_seq",
        "source_hash",
        "sourceExperiment",
    ):
        assert token in text
    assert "a missing interface does not block execution" in text


def test_targeted_production_surface_has_no_retired_storage_reference():
    combined = "\n".join(path.read_text(encoding="utf-8") for path in PRODUCTION)
    for retired in (
        "research_html",
        "outputs/",
        "RESEARCH_RUNTIME_ROOT",
        "scope_ssot",
        "sourceTask",
    ):
        assert retired not in combined
    assert not re.search(r"\bTask\b", combined)


def test_retired_dial_and_pack_scripts_are_not_part_of_research_run():
    scripts = ROOT / "skills" / "research-run" / "scripts"
    assert not (scripts / "dial.py").exists()
    assert not (scripts / "pack.py").exists()
    assert "dial.py" not in SKILL.read_text(encoding="utf-8")
    assert "pack.py" not in SKILL.read_text(encoding="utf-8")
