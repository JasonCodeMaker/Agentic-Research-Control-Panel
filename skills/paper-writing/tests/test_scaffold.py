"""Stage 0 — the component is discoverable, attributed, and can lay out a project."""

from pathlib import Path

import common

COMPONENT = Path(__file__).resolve().parent.parent


def test_entrypoints_exist():
    assert (COMPONENT / "SKILL.md").is_file()
    assert (COMPONENT / "README.md").is_file()


def test_skill_declares_component_name():
    text = (COMPONENT / "SKILL.md").read_text(encoding="utf-8")
    assert "paper-writing" in text


def test_attribution_names_three_sources():
    attr = (COMPONENT / "references" / "ATTRIBUTION.md").read_text(encoding="utf-8")
    for src in ("paper-writing-skill", "journal-adapt", "Research-Paper-Writing-Skills"):
        assert src in attr
    assert "MIT" in attr


def test_reference_layout_present():
    refs = COMPONENT / "references"
    assert (refs / "workflow_kernel" / "profiles").is_dir()
    assert (refs / "global_guide_bank").is_dir()
    assert (refs / "adapter").is_dir()


def test_ensure_project_skeleton_builds_full_tree(tmp_root):
    home = common.ensure_project_skeleton("demo", root=tmp_root)
    assert home == tmp_root / "projects" / "demo"
    for sub in common.PROJECT_SUBDIRS:
        assert (home / sub).is_dir()


def test_default_workspace_is_cwd_paper(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    home = common.ensure_project_skeleton("demo")
    assert home == tmp_path / "paper" / "projects" / "demo"
    assert (tmp_path / "paper").is_dir()


def test_init_project_writes_paper_yaml_stub(tmp_root):
    home = common.init_project("demo", root=tmp_root)
    spec = common.load_yaml(home / "paper.yaml")
    assert spec["paper"]["id"] == "demo"
    assert "claims" in spec and "evidence" in spec and "terminology" in spec
