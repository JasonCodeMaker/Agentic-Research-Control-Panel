"""Event-backed evolution-* mutation contracts."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "skills" / "research-op" / "scripts"))

from lib.research_state import EventStore, ResearchPaths  # noqa: E402
from lib.self_evolve import schema, state  # noqa: E402
from ops import evolution  # noqa: E402


def _ref():
    return {
        "uri": "experiments/pkg/exp/run/result.json",
        "sha256": "d" * 64,
        "size_bytes": 8,
        "kind": "FILE",
        "package_id": "pkg",
        "experiment_id": "pkg::exp",
        "run_id": "run",
    }


def _scope():
    return {"project": "project/main", "packages": ["*"], "task_types": ["metric-change"]}


def _event(**over):
    base = {
        "schema_version": schema.EVENT_SCHEMA,
        "event_id": "evt_1",
        "type": "test-failure-fixed",
        "source": "research-op",
        "subject": "metric",
        "idempotency_key": "k1",
        "observed_at": "2026-06-05T00:00:00+10:00",
        "scope": _scope(),
        "evidence_refs": [_ref()],
    }
    base.update(over)
    return base


def _rule(**over):
    base = {
        "schema_version": schema.RULE_SCHEMA,
        "id": "rule.x",
        "version": "1.0.0",
        "title": "t",
        "description": "d",
        "content": "verify the metric contract",
        "scope": _scope(),
        "risk_class": "R1_CONTEXT",
        "provenance": {"generated_by": "rule-inducer-v1"},
        "validation_policy": {"required_oracles": ["faithfulness", "conflict"]},
        "evidence_refs": [_ref()],
    }
    base.update(over)
    base["content_digest"] = schema.content_digest(base)
    return base


def _transition(frm, to, **over):
    base = {
        "schema_version": schema.TRANSITION_SCHEMA,
        "transition_id": f"trn-{to}",
        "store": "rule",
        "entity_id": "rule.x",
        "entity_version": "1.0.0",
        "expected_from_state": frm,
        "to_state": to,
        "op": "promote",
        "risk_class": "R1_CONTEXT",
        "idempotency_key": f"rule.x:1.0.0:{to}",
        "approval_ref": None,
        "evidence_refs": [_ref()],
    }
    if to == "RULE_ACTIVE":
        base["admission"] = "FULLY_ADMITTED"
    base.update(over)
    return base


def _paths(tmp_path):
    return ResearchPaths.resolve(workspace=tmp_path)


def test_observe_commits_learning_and_deduplicates(tmp_path):
    paths = _paths(tmp_path)
    assert evolution.run("evolution-observe", _event(), paths)[0] == "PASSED"
    assert evolution.run("evolution-observe", _event(), paths)[0] == "PASSED"
    events = EventStore(paths).events()
    assert [event["event_type"] for event in events] == ["LearningRecorded"]


def test_observe_rejects_bad_event(tmp_path):
    with pytest.raises(evolution.EvolutionReject) as error:
        evolution.run("evolution-observe", {"schema_version": "x"}, _paths(tmp_path))
    assert error.value.rule == "event-schema"


def test_observe_rejects_missing_evidence(tmp_path):
    with pytest.raises(evolution.EvolutionReject) as error:
        evolution.run(
            "evolution-observe",
            _event(evidence_refs=[]),
            _paths(tmp_path),
        )
    assert error.value.rule == "learning-evidence-required"


def test_create_rule_records_non_binding_learning(tmp_path):
    paths = _paths(tmp_path)
    evolution.run("evolution-create", _rule(), paths)
    current = EventStore(paths).state()
    learning_id = state.learning_aggregate_id("rule.x", "1.0.0")
    assert learning_id in current["aggregates"]["learning"]
    assert current["aggregates"]["rule"] == {}


def test_full_promotion_emits_decisions_then_rule(tmp_path):
    paths = _paths(tmp_path)
    evolution.run("evolution-create", _rule(), paths)
    for frm, to in [
        ("CANDIDATE", "VALIDATING"),
        ("VALIDATING", "PROVISIONAL"),
        ("PROVISIONAL", "RULE_ACTIVE"),
    ]:
        evolution.run("evolution-transition", _transition(frm, to), paths)
    current = EventStore(paths).state()
    assert current["aggregates"]["rule"]["rule.x@1.0.0"]["status"] == "PROMOTED"
    assert state.lifecycle_state(paths, "rule.x", "1.0.0") == "RULE_ACTIVE"
    assert [event["event_type"] for event in EventStore(paths).events()] == [
        "LearningRecorded",
        "DecisionRecorded",
        "DecisionRecorded",
        "DecisionRecorded",
        "RulePromoted",
    ]


def test_illegal_edge_rejected_before_write(tmp_path):
    paths = _paths(tmp_path)
    evolution.run("evolution-create", _rule(), paths)
    before = EventStore(paths).state()["source_seq"]
    with pytest.raises(evolution.EvolutionReject) as error:
        evolution.run(
            "evolution-transition",
            _transition("CANDIDATE", "RULE_ACTIVE"),
            paths,
        )
    assert error.value.rule == "illegal-edge"
    assert EventStore(paths).state()["source_seq"] == before


def test_r3_promotion_needs_approval(tmp_path):
    paths = _paths(tmp_path)
    with pytest.raises(evolution.EvolutionReject) as error:
        evolution.run(
            "evolution-transition",
            _transition(
                "PROVISIONAL",
                "RULE_ACTIVE",
                risk_class="R3_PROJECT_EXEC",
            ),
            paths,
        )
    assert error.value.rule == "needs-approval"


def test_invalid_promotion_rejects_before_admission_decision(tmp_path):
    paths = _paths(tmp_path)
    bad = _rule(origin="user")
    evolution.run("evolution-create", bad, paths)
    for frm, to in [
        ("CANDIDATE", "VALIDATING"),
        ("VALIDATING", "PROVISIONAL"),
    ]:
        evolution.run("evolution-transition", _transition(frm, to), paths)
    before = EventStore(paths).state()["source_seq"]
    with pytest.raises(evolution.EvolutionReject) as error:
        evolution.run(
            "evolution-transition",
            _transition("PROVISIONAL", "RULE_ACTIVE"),
            paths,
        )
    assert error.value.rule == "rule-origin-reserved"
    assert EventStore(paths).state()["source_seq"] == before


def test_project_and_check_are_ephemeral(tmp_path):
    paths = _paths(tmp_path)
    evolution.run("evolution-create", _rule(), paths)
    assert evolution.run("evolution-project", {}, paths)[1] == []
    assert evolution.run("evolution-check", {}, paths)[0] == "PASSED"
    assert not (paths.root / "projections").exists()


def test_active_rule_can_only_be_retired_via_decision(tmp_path):
    paths = _paths(tmp_path)
    evolution.run("evolution-create", _rule(), paths)
    for frm, to in [
        ("CANDIDATE", "VALIDATING"),
        ("VALIDATING", "PROVISIONAL"),
        ("PROVISIONAL", "RULE_ACTIVE"),
        ("RULE_ACTIVE", "INVALIDATED"),
    ]:
        evolution.run("evolution-transition", _transition(frm, to), paths)
    rule = EventStore(paths).state()["aggregates"]["rule"]["rule.x@1.0.0"]
    assert rule["status"] == "RETIRED"
    assert rule["lifecycle_state"] == "INVALIDATED"


def test_management_is_the_only_self_evolve_event_writer():
    state_source = (ROOT / "lib/self_evolve/state.py").read_text(encoding="utf-8")
    evolution_source = (
        ROOT / "skills/research-op/scripts/ops/evolution.py"
    ).read_text(encoding="utf-8")
    management_source = (
        ROOT / "skills/research-op/scripts/management.py"
    ).read_text(encoding="utf-8")

    assert ".commit(" not in state_source
    for gateway in (
        "commit_evolution_learning",
        "commit_evolution_decision",
        "commit_evolution_rule_promotion",
        "commit_evolution_rule_retirement",
    ):
        assert f"management.{gateway}" in evolution_source
        assert f"def {gateway}" in management_source
