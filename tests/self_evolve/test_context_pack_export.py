"""Unified Learning/Decision/Rule state reaches Context Pack without export."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "skills" / "research-op" / "scripts"))

import context_pack  # noqa: E402
import context_pack.build as context_build  # noqa: E402
import management  # noqa: E402
from lib.interface.build import build_interface  # noqa: E402
from lib.research_state import CommandRejected, EventStore, ResearchPaths  # noqa: E402
from self_evolve import state  # noqa: E402
from tests.scope_fixtures import (  # noqa: E402
    direction_node,
    experiment_spec,
    project_node,
)


ACTOR = {"type": "system", "id": "test"}
EXPERIMENT_ID = "experiment/main/M0-validate"
SCOPE_SOURCE = "fixture:self-evolve-import"


def _ref(package_id="pkg"):
    return {
        "uri": f"experiments/{package_id}/exp/run/result.json",
        "sha256": "c" * 64,
        "size_bytes": 10,
        "kind": "FILE",
        "package_id": package_id,
        "experiment_id": EXPERIMENT_ID,
        "run_id": "run",
    }


def _seed_workspace(tmp_path):
    paths = ResearchPaths.resolve(workspace=tmp_path)
    EventStore(paths).initialize()
    store = EventStore(paths, migration_mode=True)
    rows = [
        (
            "project",
            "project/main",
            project_node(
                "project/main",
                source=SCOPE_SOURCE,
                goal="Auditable research",
            ),
        ),
        (
            "direction",
            "dir/main",
            direction_node(
                "dir/main",
                parent="project/main",
                source=SCOPE_SOURCE,
                hypothesis="A method helps",
            ),
        ),
        (
            "package",
            "pkg",
            {
                "id": "pkg",
                "direction_id": "dir/main",
                "sourceDirection": "dir/main",
                "sourceVersion": 1,
                "sourceChange": SCOPE_SOURCE,
                "sourceExperiments": [
                    {
                        "id": EXPERIMENT_ID,
                        "version": 1,
                        "source": SCOPE_SOURCE,
                    }
                ],
                "lifecycle": "ACTIVE",
                "phase": "CONTEXT_LOADED",
            },
        ),
        (
            "experiment",
            EXPERIMENT_ID,
            {
                "id": EXPERIMENT_ID,
                "local_id": "exp",
                "package_id": "pkg",
                "direction_id": "dir/main",
                "status": "PLANNED",
                "spec": experiment_spec(
                    purpose="Validate",
                    gate="pass",
                ),
                "scope_version": 1,
                "scope_status": "ACTIVE",
                "scope_confirmation": "CONFIRMED",
                "confirmed_direction_version": 1,
                "scope_source": SCOPE_SOURCE,
            },
        ),
    ]
    for index, (kind, aggregate_id, record) in enumerate(rows):
        store.commit(
            event_type="AggregateImported",
            aggregate_type=kind,
            aggregate_id=aggregate_id,
            payload={"record": record},
            actor=ACTOR,
            idempotency_key=f"seed:{index}",
            expected_version=0,
        )
    return paths


def _promote(paths, *, rule_id="rule.metric", packages=None):
    packages = packages or ["*"]
    learning_id = state.learning_aggregate_id(rule_id, "1")
    scope = {
        "project": "project/main",
        "packages": packages,
        "task_types": ["metric"],
    }
    management.commit_evolution_learning(
        paths,
        {
            "id": learning_id,
            "observation": "Metric contracts prevent false claims.",
            "scope": scope,
            "evidence_refs": [_ref(packages[0] if packages != ["*"] else "pkg")],
        },
        idempotency_key=f"learning:{rule_id}",
    )
    decision_id = f"decision:{rule_id}"
    management.commit_evolution_decision(
        paths,
        {
            "id": decision_id,
            "decision_type": "ADMISSION",
            "subject_id": learning_id,
            "admission": "FULLY_ADMITTED",
            "evidence_refs": [_ref(packages[0] if packages != ["*"] else "pkg")],
        },
        idempotency_key=f"decision:{rule_id}",
    )
    management.commit_evolution_rule_promotion(
        paths,
        learning_id=learning_id,
        decision_id=decision_id,
        rule={
            "id": rule_id,
            "version": "1",
            "title": "Verify metrics",
            "content": "Always verify the metric contract.",
            "scope": scope,
            "origin": "selfevolve",
        },
        idempotency_key=f"promote:{rule_id}",
    )
    return learning_id, decision_id


def test_promoted_rule_is_queried_directly_from_state(tmp_path):
    paths = _seed_workspace(tmp_path)
    _promote(paths)
    projection = paths.interface_data / "rules.js"
    build_interface(paths)
    assert projection.exists()
    projection.write_text("intentionally invalid projection", encoding="utf-8")
    md = context_pack.render_md(context_build.build(paths, "pkg")[0])
    assert "Always verify the metric contract" in md
    assert [event["event_type"] for event in EventStore(paths).events()][-3:] == [
        "LearningRecorded",
        "DecisionRecorded",
        "RulePromoted",
    ]


def test_package_rule_scope_is_preserved(tmp_path):
    paths = _seed_workspace(tmp_path)
    _promote(paths, rule_id="rule.pkg", packages=["pkg"])
    rule = EventStore(paths).state()["aggregates"]["rule"]["rule.pkg@1"]
    assert rule["level"] == "package"
    assert rule["kind"] == "binding"
    assert rule["package_id"] == "pkg"


def test_learning_without_evidence_cannot_be_recorded_or_promoted(tmp_path):
    paths = _seed_workspace(tmp_path)
    with pytest.raises(CommandRejected, match="non-empty list"):
        management.commit_evolution_learning(
            paths,
            {
                "id": "learning:no-evidence",
                "observation": "Unsupported",
                "scope": {
                    "project": "project/main",
                    "packages": ["*"],
                    "task_types": ["metric"],
                },
                "evidence_refs": [],
            },
            idempotency_key="learning:no-evidence",
        )
    assert not EventStore(paths).state()["aggregates"]["rule"]


def test_migrated_learning_without_evidence_is_blocked_at_promotion(tmp_path):
    paths = _seed_workspace(tmp_path)
    store = EventStore(paths, migration_mode=True)
    store.commit(
        event_type="AggregateImported",
        aggregate_type="learning",
        aggregate_id="learning:legacy",
        payload={
            "record": {
                "id": "learning:legacy",
                "observation": "Legacy unsupported lesson",
                "scope": {
                    "project": "project/main",
                    "packages": ["*"],
                    "task_types": ["metric"],
                },
            }
        },
        actor=ACTOR,
        idempotency_key="import:legacy-learning",
        expected_version=0,
    )
    management.commit_evolution_decision(
        paths,
        {
            "id": "decision:legacy",
            "decision_type": "ADMISSION",
            "subject_id": "learning:legacy",
            "admission": "FULLY_ADMITTED",
            "evidence_refs": [_ref()],
        },
        idempotency_key="decision:legacy",
    )
    with pytest.raises(CommandRejected, match="no valid EvidenceRef"):
        management.commit_evolution_rule_promotion(
            paths,
            learning_id="learning:legacy",
            decision_id="decision:legacy",
            rule={
                "id": "rule.legacy",
                "version": "1",
                "content": "Do not promote this.",
                "scope": {
                    "project": "project/main",
                    "packages": ["*"],
                    "task_types": ["metric"],
                },
            },
            idempotency_key="promote:legacy",
        )
    assert "rule.legacy@1" not in store.state()["aggregates"]["rule"]


def test_selfevolve_origin_and_scope_shape_are_enforced(tmp_path):
    paths = _seed_workspace(tmp_path)
    learning_id, decision_id = _promote(paths, rule_id="rule.good")
    with pytest.raises(CommandRejected, match="origin"):
        management.commit_evolution_rule_promotion(
            paths,
            learning_id=learning_id,
            decision_id=decision_id,
            rule={
                "id": "rule.bad",
                "version": "1",
                "content": "Bad origin",
                "scope": {
                    "project": "project/main",
                    "packages": ["*"],
                    "task_types": ["metric"],
                },
                "origin": "user",
            },
            idempotency_key="promote:bad",
        )


def test_promotion_decision_must_govern_the_same_learning(tmp_path):
    paths = _seed_workspace(tmp_path)
    learning_id = state.learning_aggregate_id("rule.target", "1")
    scope = {
        "project": "project/main",
        "packages": ["*"],
        "task_types": ["metric"],
    }
    management.commit_evolution_learning(
        paths,
        {
            "id": learning_id,
            "observation": "Target observation",
            "scope": scope,
            "evidence_refs": [_ref()],
        },
        idempotency_key="learning:target",
    )
    management.commit_evolution_learning(
        paths,
        {
            "id": "learning:other",
            "observation": "Other observation",
            "scope": scope,
            "evidence_refs": [_ref()],
        },
        idempotency_key="learning:other",
    )
    management.commit_evolution_decision(
        paths,
        {
            "id": "decision:other",
            "decision_type": "ADMISSION",
            "subject_id": "learning:other",
            "admission": "FULLY_ADMITTED",
            "evidence_refs": [_ref()],
        },
        idempotency_key="decision:other",
    )
    with pytest.raises(CommandRejected, match="does not govern Learning"):
        management.commit_evolution_rule_promotion(
            paths,
            learning_id=learning_id,
            decision_id="decision:other",
            rule={
                "id": "rule.target",
                "version": "1",
                "content": "Never cross-link admission decisions.",
                "scope": scope,
            },
            idempotency_key="promote:target",
        )


def test_retired_rule_drops_from_context(tmp_path):
    paths = _seed_workspace(tmp_path)
    _, _ = _promote(paths)
    management.commit_evolution_decision(
        paths,
        {
            "id": "decision:retire",
            "decision_type": "RULE_LIFECYCLE",
            "subject_id": "rule.metric@1",
            "outcome": "INVALIDATED",
            "evidence_refs": [_ref()],
        },
        idempotency_key="decision:retire",
    )
    management.commit_evolution_rule_retirement(
        paths,
        rule_id="rule.metric",
        version="1",
        decision_id="decision:retire",
        lifecycle_state="INVALIDATED",
        idempotency_key="retire:rule.metric",
    )
    md = context_pack.render_md(context_build.build(paths, "pkg")[0])
    assert "Always verify the metric contract" not in md
