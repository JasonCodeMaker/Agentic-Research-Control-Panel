"""Stage-0 TDD gate for the Scope SSOT. Mirrors plan/prototype/scope-ssot-design.html §8."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
import scope_ssot  # noqa: E402
from scope_ssot import RuleViolation  # noqa: E402


def _direction_node():
    return {
        "id": "dir/contrastive-v2",
        "level": "direction",
        "parents": ["project/main"],
        "version": 1,
        "status": "ACTIVE",
        "yardstick": {
            "hypothesis": "contrastive pretrain helps recall",
            "metric": {"name": "Recall@10", "dir": "higher"},
            "baselines": ["xpool"],
            "success_predicate": "Recall@10 >= baseline + 2",
        },
        "provenance": "txn-0",
    }


def test_node_round_trips():
    node = _direction_node()
    assert scope_ssot.node_from_json(scope_ssot.node_to_json(node)) == node


def test_out_of_schema_field_rejected():
    node = _direction_node()
    node["yardstick"]["foobar"] = "x"
    with pytest.raises(RuleViolation):
        scope_ssot.validate_node(node)


def test_reading_in_yardstick_rejected():
    node = _direction_node()
    node["yardstick"]["measured"] = 0.5  # a reading, not an intent
    with pytest.raises(RuleViolation):
        scope_ssot.validate_node(node)


def test_direction_transition_requires_user_xmodel_gate(tmp_path):
    log = tmp_path / "transitions.jsonl"
    node = _direction_node()
    with pytest.raises(RuleViolation):
        scope_ssot.propose_transition(node, op="revise", gate="AGENT_DEFERRED_ACK", log_path=log)
    assert scope_ssot.read_log(log) == []  # reject-before-write: nothing appended


def test_direction_transition_accepts_correct_gate(tmp_path):
    log = tmp_path / "transitions.jsonl"
    node = _direction_node()
    scope_ssot.propose_transition(
        node, op="revise", gate="USER_CROSS_MODEL_AUDIT", log_path=log,
        trigger="exp#42", cause="metric saturated",
    )
    recs = scope_ssot.read_log(log)
    assert len(recs) == 1
    assert scope_ssot.history("dir/contrastive-v2", recs) == recs


def test_propagation_invalidate_and_reopen():
    memory = [
        {"id": "r1", "kind": "RESULT", "metric": "Recall@10"},
        {"id": "r2", "kind": "RESULT", "metric": "nDCG@10"},
        {"id": "i1", "kind": "IDEA", "failed_on_metric": "Recall@10"},
        {"id": "i2", "kind": "IDEA", "failed_on_metric": "latency"},
    ]
    out = scope_ssot.propagate(old_metric="Recall@10", new_metric="nDCG@10", memory=memory)
    assert set(out["INVALIDATE"]) == {"r1"}
    assert set(out["REOPEN_IDEA"]) == {"i1"}
    assert set(out["RETAIN"]) == {"r2", "i2"}


def test_multihomed_refcount():
    node = {
        "id": "base/B", "level": "direction", "parents": ["dir/A", "dir/B2"],
        "version": 1, "status": "active", "yardstick": {}, "provenance": "t",
    }
    assert scope_ssot.should_invalidate(node, {"dir/B2"}) is False  # one parent still active
    assert scope_ssot.should_invalidate(node, set()) is True        # last owner gone


def _create_revise_log(tmp_path):
    """A two-transition log on one node: create v1 -> revise v2 (metric sharpened)."""
    log = tmp_path / "transitions.jsonl"
    n1 = _direction_node()
    scope_ssot.propose_transition(n1, op="create", gate="USER_CROSS_MODEL_AUDIT", log_path=log,
                                  trigger="t0", cause="initial")
    n2 = _direction_node()
    n2["version"] = 2
    n2["yardstick"]["success_predicate"] = "Recall@10 >= baseline + 3"
    scope_ssot.propose_transition(n2, op="revise", gate="USER_CROSS_MODEL_AUDIT", log_path=log,
                                  trigger="exp#42", cause="metric saturated")
    return log


def test_fold_returns_latest_version_per_node(tmp_path):
    recs = scope_ssot.read_log(_create_revise_log(tmp_path))
    proj = scope_ssot.fold(recs)
    assert set(proj) == {"dir/contrastive-v2"}
    node = proj["dir/contrastive-v2"]
    assert node["version"] == 2  # later transition wins
    assert node["yardstick"]["success_predicate"] == "Recall@10 >= baseline + 3"


def test_fold_marks_archived_node(tmp_path):
    log = _create_revise_log(tmp_path)
    n3 = _direction_node()
    n3["version"] = 3
    n3["status"] = "ARCHIVED"
    scope_ssot.propose_transition(n3, op="archive", gate="USER_CROSS_MODEL_AUDIT", log_path=log,
                                  trigger="t3", cause="superseded by v3")
    proj = scope_ssot.fold(scope_ssot.read_log(log))
    assert proj["dir/contrastive-v2"]["status"] == "ARCHIVED"


def test_intent_returns_current_yardstick(tmp_path):
    recs = scope_ssot.read_log(_create_revise_log(tmp_path))
    yard = scope_ssot.intent("dir/contrastive-v2", recs)
    assert yard["success_predicate"] == "Recall@10 >= baseline + 3"  # the folded (latest) bar


def test_assert_consistent_passes_on_fold(tmp_path):
    recs = scope_ssot.read_log(_create_revise_log(tmp_path))
    scope_ssot.assert_consistent(scope_ssot.fold(recs), recs)  # must not raise


def test_assert_consistent_flags_planted_drift(tmp_path):
    recs = scope_ssot.read_log(_create_revise_log(tmp_path))
    proj = scope_ssot.fold(recs)
    proj["dir/contrastive-v2"]["version"] = 99  # planted projection drift
    with pytest.raises(RuleViolation):
        scope_ssot.assert_consistent(proj, recs)
