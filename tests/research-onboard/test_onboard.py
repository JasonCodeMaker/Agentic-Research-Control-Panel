"""research-onboard: the steps 1->3 on-ramp. Deterministic units behind the bridging skill."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "skills" / "research-onboard" / "scripts"))

import onboard  # noqa: E402
import scope_ssot  # noqa: E402


# --- workspace_state -------------------------------------------------------

def test_workspace_state_empty(tmp_path):
    # only pipeline-managed / noise entries present -> nothing to analyze
    (tmp_path / ".git").mkdir()
    (tmp_path / "research_html").mkdir()
    (tmp_path / "outputs").mkdir()
    (tmp_path / ".gitignore").write_text("outputs/\n")
    assert onboard.workspace_state(tmp_path) == "empty"


def test_workspace_state_existing(tmp_path):
    (tmp_path / "outputs").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "README.md").write_text("# My DL project\n")
    assert onboard.workspace_state(tmp_path) == "existing"


# --- scaffold_skeleton -----------------------------------------------------

def test_scaffold_skeleton_creates_layout(tmp_path):
    onboard.scaffold_skeleton(tmp_path)
    for d in ("src", "scripts", "configs", "data", "baselines", "results", "logs"):
        assert (tmp_path / d).is_dir()
    assert (tmp_path / "src" / "__init__.py").exists()


def test_scaffold_skeleton_idempotent(tmp_path):
    onboard.scaffold_skeleton(tmp_path)
    onboard.scaffold_skeleton(tmp_path)  # second run must not raise
    assert (tmp_path / "src").is_dir()


# --- write project protocol stubs ------------------------------------------

def test_claude_stub_written_when_absent(tmp_path):
    assert onboard.write_project_claude_stub(tmp_path) is True
    assert (tmp_path / "CLAUDE.md").exists()


def test_claude_stub_no_clobber(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("USER CONTENT\n")
    assert onboard.write_project_claude_stub(tmp_path) is False
    assert (tmp_path / "CLAUDE.md").read_text() == "USER CONTENT\n"


def test_agents_stub_written_when_absent(tmp_path):
    assert onboard.write_project_agents_stub(tmp_path) is True
    text = (tmp_path / "AGENTS.md").read_text()
    assert "CLAUDE.md" in text
    assert "WORKFLOW.md" in text


def test_agents_stub_no_clobber(tmp_path):
    (tmp_path / "AGENTS.md").write_text("USER CONTENT\n")
    assert onboard.write_project_agents_stub(tmp_path) is False
    assert (tmp_path / "AGENTS.md").read_text() == "USER CONTENT\n"


# --- write_prior_knowledge -------------------------------------------------

def test_write_prior_knowledge(tmp_path):
    state_root = tmp_path / "outputs"
    p = onboard.write_prior_knowledge(state_root, "# Prior knowledge\n\n- dataset: MSRVTT\n")
    assert p == state_root / "_scope" / "prior_knowledge.md"
    assert p.read_text().startswith("# Prior knowledge")


# --- build_project_proposal ------------------------------------------------

def _good_yardstick():
    return {
        "north_star": "Beat ResNet-18 on CIFAR-10 top-1 accuracy",
        "contribution_spine": ["mixup augmentation", "cosine schedule"],
        "non_goals": ["no architecture search"],
    }


def test_build_project_proposal_valid():
    item = onboard.build_project_proposal(
        "project/cifar10", _good_yardstick(), provenance="read:README.md,CLAUDE.md")
    assert item["level"] == "project"
    assert item["op"] == "create"
    assert item["gate"] == "USER_ONLY"  # project gate per scope_ssot.REQUIRED_GATE
    assert item["proposed_yardstick"] == _good_yardstick()
    assert item["proposed_node"]["yardstick"] == _good_yardstick()
    assert item["proposed_node"]["level"] == "project"
    assert "id" in item  # triage.propose enforces an id


def test_build_project_proposal_rejects_bad_yardstick():
    bad = {**_good_yardstick(), "metric": "top-1"}  # 'metric' is a direction field, illegal for project
    with pytest.raises(scope_ssot.RuleViolation):
        onboard.build_project_proposal("project/cifar10", bad, provenance="x")


def test_build_project_proposal_rejects_reading_in_yardstick():
    bad = {**_good_yardstick(), "measured": 0.91}  # a reading must never live in a yardstick
    with pytest.raises(scope_ssot.RuleViolation):
        onboard.build_project_proposal("project/cifar10", bad, provenance="x")


# --- has_project_scope -----------------------------------------------------

def test_has_project_scope_false_when_empty(tmp_path):
    assert onboard.has_project_scope(tmp_path / "transitions.jsonl") is False


def test_has_project_scope_true_after_commit(tmp_path):
    log = tmp_path / "transitions.jsonl"
    node = {
        "id": "project/cifar10", "level": "project", "parents": [], "version": 1,
        "status": "ACTIVE", "yardstick": _good_yardstick(), "provenance": "accepted",
    }
    scope_ssot.propose_transition(node, op="create", gate="USER_ONLY", log_path=log)
    assert onboard.has_project_scope(log) is True
