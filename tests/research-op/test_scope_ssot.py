"""Stage-0 TDD gate for the Scope SSOT. Mirrors plan/prototype/scope-ssot-design.html §8."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
import scope_ssot  # noqa: E402
from scope_ssot import RuleViolation  # noqa: E402


VALID_PROJECT_SPEC = {
    "goal": (
        "Build an auditable research workflow that keeps project intent, package execution, "
        "evidence review, and user decisions aligned across repeated experiments."
    ),
    "contributions": [
        "Maintain a typed Scope log for ratified research intent.",
        "Project accepted Directions into packages with traceable provenance.",
    ],
    "out_of_scope": [
        "Do not automate paper writing or claim adoption without evidence.",
    ],
}

VALID_DIRECTION_SPEC = {
    "hypothesis": (
        "Adding supervised contrastive pretraining before retrieval fine tuning will improve "
        "zero shot ranking stability without changing the evaluation corpus or data budget."
    ),
    "metric": {"name": "Recall@10", "dir": "higher"},
    "baselines": [
        "CLIP zero shot retrieval baseline on the same held out split.",
    ],
    "success_gate": (
        "Recall at ten must improve by at least two absolute points over the declared baseline "
        "on the held out evaluation split."
    ),
}

VALID_TASK_SPEC = {
    "experiment": (
        "Run a baseline reproduction study that verifies the declared retrieval pipeline before "
        "any new method changes are evaluated in production."
    ),
    "config": "scope:dir/contrastive-v2#m0-baseline-validity",
    "gate": (
        "The reproduced baseline metric must fall within the accepted tolerance window before "
        "downstream experiments can compare new method variants fairly."
    ),
    "control_mode": "CHECKPOINTED",
}


def _project_node():
    return {
        "id": "project/main",
        "level": "project",
        "parents": [],
        "version": 1,
        "status": "ACTIVE",
        "spec": {**VALID_PROJECT_SPEC},
        "source": "txn-project",
    }


def _direction_node():
    return {
        "id": "dir/contrastive-v2",
        "level": "direction",
        "parents": ["project/main"],
        "version": 1,
        "status": "ACTIVE",
        "spec": {**VALID_DIRECTION_SPEC},
        "source": "txn-0",
    }


def _task_node():
    return {
        "id": "task/contrastive-v2/M0-baseline-validity",
        "level": "task",
        "parents": ["dir/contrastive-v2"],
        "version": 1,
        "status": "ACTIVE",
        "spec": {**VALID_TASK_SPEC},
        "source": "txn-task",
    }


def test_node_round_trips():
    node = _direction_node()
    assert scope_ssot.node_from_json(scope_ssot.node_to_json(node)) == node


def test_missing_required_spec_field_rejected():
    node = _direction_node()
    del node["spec"]["success_gate"]
    with pytest.raises(RuleViolation, match="missing spec field"):
        scope_ssot.validate_node(node)


def test_out_of_schema_field_rejected():
    node = _direction_node()
    node["spec"]["foobar"] = "x"
    with pytest.raises(RuleViolation):
        scope_ssot.validate_node(node)


def test_reading_in_spec_rejected():
    node = _direction_node()
    node["spec"]["measured"] = 0.5  # a reading, not an intent
    with pytest.raises(RuleViolation):
        scope_ssot.validate_node(node)


def test_old_yardstick_key_rejected():
    node = _direction_node()
    node["yardstick"] = node.pop("spec")
    with pytest.raises(RuleViolation, match="spec"):
        scope_ssot.validate_node(node)


@pytest.mark.parametrize("old_field", ["north_star", "success_predicate", "config_ref", "gate_predicate"])
def test_old_spec_field_names_rejected(old_field):
    node = _direction_node()
    node["spec"][old_field] = "old"
    with pytest.raises(RuleViolation):
        scope_ssot.validate_node(node)


def test_scalar_string_spec_rejects_too_short_value():
    node = _direction_node()
    node["spec"]["hypothesis"] = "too short for a ratified research direction"
    with pytest.raises(RuleViolation, match="20-100 words"):
        scope_ssot.validate_node(node)


def test_scalar_string_spec_rejects_too_long_value():
    node = _direction_node()
    node["spec"]["success_gate"] = " ".join(f"word{i}" for i in range(101))
    with pytest.raises(RuleViolation, match="20-100 words"):
        scope_ssot.validate_node(node)


def test_list_spec_rejects_non_list_value():
    node = _project_node()
    node["spec"]["contributions"] = "typed Scope log with package provenance"
    with pytest.raises(RuleViolation, match="non-empty list"):
        scope_ssot.validate_node(node)


def test_list_spec_rejects_short_item():
    node = _project_node()
    node["spec"]["out_of_scope"] = ["paper writing"]
    with pytest.raises(RuleViolation, match="5-50 words"):
        scope_ssot.validate_node(node)


def test_config_ref_can_be_short_and_control_mode_is_enum():
    node = _task_node()
    scope_ssot.validate_node(node)

    node["spec"]["control_mode"] = "reckless"
    with pytest.raises(RuleViolation, match="control_mode"):
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


def test_global_version_is_log_position_not_node_version(tmp_path):
    log = tmp_path / "transitions.jsonl"
    assert scope_ssot.global_version(scope_ssot.read_log(log)) == 0

    scope_ssot.propose_transition(
        _project_node(), op="create", gate="USER_ONLY", log_path=log)
    scope_ssot.propose_transition(
        _direction_node(), op="create", gate="USER_CROSS_MODEL_AUDIT", log_path=log)
    records = scope_ssot.read_log(log)
    assert scope_ssot.global_version(records) == 2

    revised_project = _project_node()
    revised_project["version"] = 2
    scope_ssot.propose_transition(
        revised_project, op="revise", gate="USER_ONLY", log_path=log)
    records = scope_ssot.read_log(log)
    assert scope_ssot.global_version(records) == 3
    assert scope_ssot.fold(records)["dir/contrastive-v2"]["version"] == 1


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
        "version": 1, "status": "active", "spec": {}, "source": "t",
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
    n2["spec"]["success_gate"] = (
        "Recall at ten must improve by at least three absolute points over the declared baseline "
        "on the held out evaluation split."
    )
    scope_ssot.propose_transition(n2, op="revise", gate="USER_CROSS_MODEL_AUDIT", log_path=log,
                                  trigger="exp#42", cause="metric saturated")
    return log


def test_fold_returns_latest_version_per_node(tmp_path):
    recs = scope_ssot.read_log(_create_revise_log(tmp_path))
    proj = scope_ssot.fold(recs)
    assert set(proj) == {"dir/contrastive-v2"}
    node = proj["dir/contrastive-v2"]
    assert node["version"] == 2  # later transition wins
    assert "three absolute points" in node["spec"]["success_gate"]


def test_fold_marks_archived_node(tmp_path):
    log = _create_revise_log(tmp_path)
    n3 = _direction_node()
    n3["version"] = 3
    n3["status"] = "ARCHIVED"
    scope_ssot.propose_transition(n3, op="archive", gate="USER_CROSS_MODEL_AUDIT", log_path=log,
                                  trigger="t3", cause="superseded by v3")
    proj = scope_ssot.fold(scope_ssot.read_log(log))
    assert proj["dir/contrastive-v2"]["status"] == "ARCHIVED"


def test_intent_returns_current_spec(tmp_path):
    recs = scope_ssot.read_log(_create_revise_log(tmp_path))
    spec = scope_ssot.intent("dir/contrastive-v2", recs)
    assert "three absolute points" in spec["success_gate"]  # the folded latest gate


def test_assert_consistent_passes_on_fold(tmp_path):
    recs = scope_ssot.read_log(_create_revise_log(tmp_path))
    scope_ssot.assert_consistent(scope_ssot.fold(recs), recs)  # must not raise


def test_assert_consistent_flags_planted_drift(tmp_path):
    recs = scope_ssot.read_log(_create_revise_log(tmp_path))
    proj = scope_ssot.fold(recs)
    proj["dir/contrastive-v2"]["version"] = 99  # planted projection drift
    with pytest.raises(RuleViolation):
        scope_ssot.assert_consistent(proj, recs)
