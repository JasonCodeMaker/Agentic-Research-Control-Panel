"""Failure signal -> Learning -> Decisions -> Rule -> ephemeral Context Pack."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "skills" / "research-op" / "scripts"))

import context_pack  # noqa: E402
import context_pack.build as context_build  # noqa: E402
from ops import evolution  # noqa: E402
from research_state import EventStore, ResearchPaths  # noqa: E402
from self_evolve import induce, oracles, schema  # noqa: E402
from tests.scope_fixtures import (  # noqa: E402
    direction_node,
    experiment_spec,
    project_node,
)


EXPERIMENT_ID = "experiment/main/M0-validate"
SCOPE_SOURCE = "fixture:self-evolve-e2e-import"


def _ref():
    return {
        "uri": "experiments/pkg/exp/run/result.json",
        "sha256": "e" * 64,
        "size_bytes": 100,
        "kind": "FILE",
        "package_id": "pkg",
        "experiment_id": EXPERIMENT_ID,
        "run_id": "run",
    }


def _scope():
    return {"project": "project/main", "packages": ["*"], "task_types": ["metric-change"]}


def _failure_event():
    return {
        "schema_version": schema.EVENT_SCHEMA,
        "event_id": "evt_42",
        "type": "test-failure-fixed",
        "source": "research-op",
        "subject": "metric implementation",
        "idempotency_key": "tf:before:after",
        "observed_at": "2026-06-05T00:00:00+10:00",
        "scope": _scope(),
        "evidence_refs": [_ref()],
    }


def _draft():
    return {
        "id": "rule.verify-metric-contract",
        "title": "Verify metric semantics before accepting a claim",
        "description": "Prevents metric-name ambiguity from becoming a claim.",
        "content": "If a custom metric changes, validate its contract before accepting the result.",
        "scope": _scope(),
        "evidence_refs": [_ref()],
    }


def _evidence(eid, ver, stage, result):
    return {
        "schema_version": schema.EVIDENCE_SCHEMA,
        "evidence_id": f"evd_{stage}",
        "entity_id": eid,
        "entity_version": ver,
        "stage": stage,
        "oracle": {"id": f"{stage}-v1", "result": result},
        "evidence_refs": [_ref()],
    }


def _transition(eid, ver, frm, to, **over):
    base = {
        "schema_version": schema.TRANSITION_SCHEMA,
        "transition_id": f"{eid}-{to}",
        "store": "rule",
        "entity_id": eid,
        "entity_version": ver,
        "expected_from_state": frm,
        "to_state": to,
        "op": "promote",
        "risk_class": "R1_CONTEXT",
        "idempotency_key": f"{eid}:{ver}:{to}",
        "evidence_refs": [_ref()],
    }
    base.update(over)
    return base


def _seed_package(paths):
    EventStore(paths).initialize()
    store = EventStore(paths, migration_mode=True)
    rows = [
        (
            "project",
            "project/main",
            project_node(
                "project/main",
                source=SCOPE_SOURCE,
                goal="Audit",
            ),
        ),
        (
            "direction",
            "dir/main",
            direction_node(
                "dir/main",
                parent="project/main",
                source=SCOPE_SOURCE,
                hypothesis="Method helps",
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
    for index, (kind, key, record) in enumerate(rows):
        store.commit(
            event_type="AggregateImported",
            aggregate_type=kind,
            aggregate_id=key,
            payload={"record": record},
            actor={"type": "system", "id": "test"},
            idempotency_key=f"seed:{index}",
            expected_version=0,
        )


def test_failure_to_active_to_contextpack(tmp_path):
    paths = ResearchPaths.resolve(workspace=tmp_path)
    _seed_package(paths)
    event = _failure_event()
    evolution.run("evolution-observe", event, paths)
    rule = induce.induce_rule(event, _draft())
    eid, ver = rule["id"], rule["version"]
    evolution.run("evolution-create", rule, paths)

    results = {
        "schema_scope": oracles.schema_scope(rule),
        "faithfulness": oracles.faithfulness({"entailed": True}),
        "original_reproduction": oracles.original_reproduction({"before": "fail", "after": "pass"}),
        "regression_smoke": oracles.regression_smoke({"regressions": []}),
        "conflict": oracles.conflict([]),
    }
    admission = oracles.resolve_admission(results)
    assert admission == "FULLY_ADMITTED"
    for stage, result in results.items():
        evolution.run("evolution-evidence-add", _evidence(eid, ver, stage, result), paths)

    for frm, to in [("CANDIDATE", "VALIDATING"), ("VALIDATING", "PROVISIONAL")]:
        evolution.run("evolution-transition", _transition(eid, ver, frm, to), paths)
    evolution.run(
        "evolution-transition",
        _transition(eid, ver, "PROVISIONAL", "RULE_ACTIVE", admission=admission),
        paths,
    )
    md = context_pack.render_md(context_build.build(paths, "pkg")[0])
    assert rule["content"] in md
    assert not list(paths.root.rglob("context_pack.*"))

    evolution.run(
        "evolution-transition",
        _transition(
            eid,
            ver,
            "RULE_ACTIVE",
            "INVALIDATED",
            transition_id=f"{eid}-inv",
            idempotency_key=f"{eid}:{ver}:INVALIDATED",
            op="invalidate",
            reason="scope changed",
        ),
        paths,
    )
    assert rule["content"] not in context_pack.render_md(context_build.build(paths, "pkg")[0])


def test_failed_repro_rejects_admission():
    results = {
        "schema_scope": "ORACLE_PASS",
        "faithfulness": "ORACLE_PASS",
        "original_reproduction": "ORACLE_FAIL",
        "regression_smoke": "ORACLE_PASS",
        "conflict": "ORACLE_PASS",
    }
    assert oracles.resolve_admission(results) == "REJECTED"
