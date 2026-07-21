"""research-onboard: the steps 1->3 on-ramp. Deterministic units behind the bridging skill."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "research-onboard" / "SKILL.md"
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "skills" / "research-onboard" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "research-op" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "research-scope" / "scripts"))

import onboard  # noqa: E402
from lib.research_state import (  # noqa: E402
    EventStore,
    ResearchPaths,
    StateQuery,
    UpgradeRequired,
)
import management  # noqa: E402
import scope_ssot  # noqa: E402
import triage  # noqa: E402
from tests.scope_fixtures import commit_accepted_scope, project_spec  # noqa: E402


# --- workspace_state -------------------------------------------------------

def _initialized_paths(tmp_path):
    paths = ResearchPaths.resolve(workspace=tmp_path)
    EventStore(paths).initialize()
    return paths


def test_workspace_state_empty(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".gitignore").write_text(".research/interface/\n")
    assert onboard.workspace_state(_initialized_paths(tmp_path)) == "empty"


def test_workspace_state_ignores_setup_protocol_files(tmp_path):
    (tmp_path / "AGENTS.md").write_text("managed protocol\n")
    (tmp_path / "CLAUDE.md").write_text("managed protocol\n")
    assert onboard.workspace_state(_initialized_paths(tmp_path)) == "empty"


def test_workspace_state_existing(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "README.md").write_text("# My DL project\n")
    assert onboard.workspace_state(_initialized_paths(tmp_path)) == "existing"


def test_workspace_state_requires_research_init_when_absent(tmp_path):
    paths = ResearchPaths.resolve(workspace=tmp_path)
    with pytest.raises(UpgradeRequired, match="setup-required.*research-init"):
        onboard.workspace_state(paths)


def test_workspace_state_requires_explicit_legacy_upgrade(tmp_path):
    (tmp_path / "outputs").mkdir()
    paths = ResearchPaths.resolve(workspace=tmp_path)
    with pytest.raises(UpgradeRequired, match="upgrade-required"):
        onboard.workspace_state(paths)


# --- scaffold_skeleton -----------------------------------------------------

def test_scaffold_skeleton_creates_layout(tmp_path):
    onboard.scaffold_skeleton(tmp_path)
    for d in ("src", "scripts", "configs", "data", "baselines", "figures"):
        assert (tmp_path / d).is_dir()
    assert (tmp_path / "src" / "__init__.py").exists()
    assert not (tmp_path / "results").exists()
    assert not (tmp_path / "logs").exists()


def test_scaffold_skeleton_idempotent(tmp_path):
    onboard.scaffold_skeleton(tmp_path)
    onboard.scaffold_skeleton(tmp_path)  # second run must not raise
    assert (tmp_path / "src").is_dir()


# --- write_prior_knowledge -------------------------------------------------

def test_write_prior_knowledge(tmp_path):
    paths = _initialized_paths(tmp_path)
    note_ref = onboard.write_prior_knowledge(
        paths,
        "# Prior knowledge\n\n- dataset: MSRVTT\n",
    )
    assert note_ref["uri"].startswith("state/notes/")
    assert len(note_ref["sha256"]) == 64
    note_path = paths.root / note_ref["uri"]
    assert note_path.read_text(encoding="utf-8").startswith("# Prior knowledge")


# --- build_project_proposal ------------------------------------------------

def _good_spec():
    return project_spec()


def test_build_project_proposal_valid():
    item = onboard.build_project_proposal(
        "project/cifar10", _good_spec(), source="read:README.md,CLAUDE.md")
    assert item["level"] == "project"
    assert item["op"] == "create"
    assert item["gate"] == "USER_ONLY"  # project gate per scope_ssot.REQUIRED_GATE
    assert item["proposed_spec"] == _good_spec()
    assert item["proposed_node"]["spec"] == _good_spec()
    assert item["proposed_node"]["level"] == "project"
    assert "id" in item  # triage.propose enforces an id


def test_build_project_proposal_accepts_short_exact_objective():
    spec = project_spec(goal="Investigating Composed Video Retrieval")
    item = onboard.build_project_proposal(
        "project/composed-video-retrieval", spec, source="user-dialogue:onboarding")
    assert item["proposed_node"]["spec"]["goal"] == "Investigating Composed Video Retrieval"


def test_build_project_proposal_binds_prior_knowledge_note(tmp_path):
    paths = _initialized_paths(tmp_path)
    note_ref = onboard.write_prior_knowledge(paths, "# Prior knowledge\n")
    item = onboard.build_project_proposal(
        "project/cifar10",
        _good_spec(),
        source="read:README.md",
        prior_knowledge=note_ref,
    )
    assert item["proposed_node"]["prior_knowledge"] == note_ref


def test_accepted_project_keeps_the_bound_prior_knowledge_note(tmp_path):
    paths = _initialized_paths(tmp_path)
    note_ref = onboard.write_prior_knowledge(paths, "# Prior knowledge\n")
    item = onboard.build_project_proposal(
        "project/cifar10",
        _good_spec(),
        source="read:README.md",
        prior_knowledge=note_ref,
    )
    triage.propose(paths, item)
    visible_hash = triage.pending(paths)[0]["proposal_hash"]
    triage.dispose(
        paths,
        item["id"],
        "ACCEPTED",
        visible_hash,
        actor={"type": "user", "id": "test-pm"},
    )
    payload, causation_id = management.accepted_scope_payload(paths, item["id"])
    management.commit_scope_transition(
        paths,
        payload,
        causation_id=causation_id,
    )

    project = StateQuery(paths).show("project", "project/cifar10")["data"]
    assert project["prior_knowledge"] == note_ref


def test_build_project_proposal_rejects_bad_spec():
    bad = {**_good_spec(), "metric": "top-1"}  # 'metric' is a direction field, illegal for project
    with pytest.raises(scope_ssot.RuleViolation):
        onboard.build_project_proposal("project/cifar10", bad, source="x")


def test_build_project_proposal_rejects_reading_in_spec():
    bad = {**_good_spec(), "measured": 0.91}  # a reading must never live in a spec
    with pytest.raises(scope_ssot.RuleViolation):
        onboard.build_project_proposal("project/cifar10", bad, source="x")


# --- has_project_scope -----------------------------------------------------

def test_has_project_scope_false_when_empty(tmp_path):
    paths = _initialized_paths(tmp_path)
    assert onboard.has_project_scope(paths) is False


def test_has_project_scope_true_after_commit(tmp_path):
    paths = ResearchPaths.resolve(workspace=tmp_path)
    node = {
        "id": "project/cifar10", "level": "project", "parents": [], "version": 1,
        "status": "ACTIVE", "spec": _good_spec(), "source": "accepted",
    }
    commit_accepted_scope(management, paths, node)
    assert onboard.has_project_scope(paths) is True


def test_skill_requires_clear_scope_review_and_next_step():
    text = SKILL.read_text(encoding="utf-8")
    assert "The agent drafts; the user decides once." in text
    assert "**Project review**" in text
    assert "CONFIRM/确认" in text
    assert "3 to 100 words" in text
    assert "--receipt" in text
    assert "--op scope-accept" in text
    assert "Keep item ids, hashes, NoteRefs" in text
    assert "do not scaffold automatically" in text
    assert "Candidate, not yet submitted" not in text
    assert "ACCEPT <item-id>" not in text
    assert ".research/interface" in text
