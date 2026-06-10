"""research-brainstorm Phase 1: the pre-package idea store + direction-proposal builder."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "skills" / "research-brainstorm" / "scripts"))

import brainstorm  # noqa: E402
import scope_ssot  # noqa: E402


# --- idea store (brainstorms.js) ------------------------------------------

def test_read_empty_when_absent(tmp_path):
    assert brainstorm.read_brainstorms(tmp_path) == []


def test_add_assigns_id_and_roundtrips(tmp_path):
    bid = brainstorm.add_brainstorm(tmp_path, {"title": "Mixup helps", "idea": "augment with mixup"})
    items = brainstorm.read_brainstorms(tmp_path)
    assert [i["id"] for i in items] == [bid]
    assert items[0]["title"] == "Mixup helps"
    assert "created_at" in items[0]


def test_add_dedupes_ids_from_same_title(tmp_path):
    a = brainstorm.add_brainstorm(tmp_path, {"title": "Same idea", "idea": "x"})
    b = brainstorm.add_brainstorm(tmp_path, {"title": "Same idea", "idea": "y"})
    assert a != b
    assert len(brainstorm.read_brainstorms(tmp_path)) == 2


def test_remove_is_idempotent(tmp_path):
    bid = brainstorm.add_brainstorm(tmp_path, {"title": "T", "idea": "i"})
    assert brainstorm.remove_brainstorm(tmp_path, bid) is True
    assert brainstorm.read_brainstorms(tmp_path) == []
    assert brainstorm.remove_brainstorm(tmp_path, bid) is False  # already gone, no error


def test_consume_returns_records_and_removes(tmp_path):
    brainstorm.add_brainstorm(tmp_path, {"title": "A", "idea": "a", "id": "bs-1"})
    brainstorm.add_brainstorm(tmp_path, {"title": "B", "idea": "b", "id": "bs-2"})
    brainstorm.add_brainstorm(tmp_path, {"title": "C", "idea": "c", "id": "bs-3"})
    taken = brainstorm.consume_brainstorms(tmp_path, ["bs-1", "bs-3"])
    assert [t["id"] for t in taken] == ["bs-1", "bs-3"]
    assert [i["id"] for i in brainstorm.read_brainstorms(tmp_path)] == ["bs-2"]


def test_consume_skips_missing_ids(tmp_path):
    brainstorm.add_brainstorm(tmp_path, {"title": "A", "idea": "a", "id": "bs-1"})
    taken = brainstorm.consume_brainstorms(tmp_path, ["bs-1", "nope"])
    assert [t["id"] for t in taken] == ["bs-1"]
    assert brainstorm.read_brainstorms(tmp_path) == []


# --- precondition + readiness ---------------------------------------------

def _project_yardstick():
    return {"north_star": "beat baseline", "contribution_spine": ["mixup"], "non_goals": ["no NAS"]}


def _commit_project(log, node_id="project/main"):
    node = {"id": node_id, "level": "project", "parents": [], "version": 1,
            "status": "ACTIVE", "yardstick": _project_yardstick(), "provenance": "accepted"}
    scope_ssot.propose_transition(node, op="create", gate="USER_ONLY", log_path=log)


def test_active_project_ids(tmp_path):
    log = tmp_path / "transitions.jsonl"
    assert brainstorm.active_project_ids(log) == []
    _commit_project(log)
    assert brainstorm.active_project_ids(log) == ["project/main"]


def _good_direction_yardstick():
    return {
        "hypothesis": "mixup improves top-1",
        "metric": "top-1 accuracy",
        "baselines": ["ResNet-18"],
        "success_predicate": "top-1 > baseline + 1.0",
    }


def test_direction_ready_true():
    assert brainstorm.direction_ready(_good_direction_yardstick()) is True


def test_direction_ready_false_missing_field():
    y = {k: v for k, v in _good_direction_yardstick().items() if k != "success_predicate"}
    assert brainstorm.direction_ready(y) is False


def test_direction_ready_false_empty_baselines():
    y = {**_good_direction_yardstick(), "baselines": []}
    assert brainstorm.direction_ready(y) is False


# --- direction proposal builder -------------------------------------------

def test_build_direction_proposal_valid():
    item = brainstorm.build_direction_proposal(
        "dir/mixup", _good_direction_yardstick(),
        parent_project_id="project/main", provenance="brainstorms:bs-1,bs-2",
        source_brainstorms=["bs-1", "bs-2"])
    assert item["level"] == "direction"
    assert item["op"] == "create"
    assert item["gate"] == "USER_CROSS_MODEL_AUDIT"  # direction gate
    assert item["proposed_node"]["parents"] == ["project/main"]
    assert item["proposed_node"]["yardstick"] == _good_direction_yardstick()
    assert item["source_brainstorms"] == ["bs-1", "bs-2"]
    assert "id" in item


def test_build_direction_proposal_rejects_reading_in_yardstick():
    bad = {**_good_direction_yardstick(), "measured": 0.9}
    with pytest.raises(scope_ssot.RuleViolation):
        brainstorm.build_direction_proposal("dir/x", bad, parent_project_id="project/main",
                                            provenance="p")


def test_build_direction_proposal_rejects_wrong_level_field():
    bad = {**_good_direction_yardstick(), "north_star": "oops"}  # project field, illegal for direction
    with pytest.raises(scope_ssot.RuleViolation):
        brainstorm.build_direction_proposal("dir/x", bad, parent_project_id="project/main",
                                            provenance="p")
