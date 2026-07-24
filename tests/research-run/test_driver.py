"""Dispatch, stale-read, and command-envelope contracts."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "research-run" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import driver  # noqa: E402
from lib.research_state import StateQuery  # noqa: E402
from state_fixtures import (  # noqa: E402
    CANONICAL_EXPERIMENT_ID,
    LEGACY_EXPERIMENT_ID,
    remove_interface,
    seed,
)


EXPERIMENT = {
    "id": CANONICAL_EXPERIMENT_ID,
    "local_id": "P1",
    "aggregate_id": CANONICAL_EXPERIMENT_ID,
    "package_id": "pkg-1",
    "spec": {
        "purpose": "measure the toy metric",
        "config_ref": "config.yaml",
        "gate": "measured >= 0.80",
        "control_mode": "SUPERVISED",
    },
}


def _return(role, *, mutations=None, **overrides):
    report = {
        "agent_role": role,
        "assigned_scope": CANONICAL_EXPERIMENT_ID,
        "status": "ROLE_OK",
        "evidence": [f"{role}-evidence"],
        "blockers": [],
        "recommended_next_action": "proceed",
        "source_seq": 7,
        "source_hash": "state-7",
        "sourceDirection": "dir/d1",
        "sourceExperiment": CANONICAL_EXPERIMENT_ID,
        "mutations": mutations or [],
    }
    report.update(overrides)
    return report


def test_role_return_requires_evidence_and_all_stamp_fields():
    report = _return("review", evidence=[])
    errors = driver.validate_role_return(report)
    assert any("evidence" in error for error in errors)
    del report["source_hash"]
    errors = driver.validate_role_return(report)
    assert any("source_hash" in error for error in errors)


def test_role_return_rejects_stale_state_and_experiment():
    report = _return("review", source_seq=6, sourceExperiment="experiment/d1/old")
    errors = driver.validate_role_return(
        report,
        context={
            "source_seq": 7,
            "source_hash": "state-7",
            "sourceDirection": "dir/d1",
            "sourceExperiment": CANONICAL_EXPERIMENT_ID,
        },
    )
    assert sum("stale state report" in error for error in errors) == 2


def test_direct_write_and_unknown_target_are_refused():
    errors = driver.validate_mutation(
        {"op": "write_file", "target": "current-state", "payload": {}}
    )
    assert any("direct writes" in error for error in errors)
    assert any("target" in error for error in errors)
    errors = driver.validate_mutation(
        {"op": "insert", "target": "tracker-live-check-row", "payload": {}}
    )
    assert any("not a supported research-op target" in error for error in errors)


def test_valid_research_op_envelope_compiles_to_canonical_cli(tmp_path):
    paths = seed(tmp_path)
    envelope = {
        "op": "insert",
        "target": "results-gate-row",
        "payload": {"exp_id": "P1"},
        "idempotency_key": "test:P1",
        "expected_version": 4,
    }
    assert driver.validate_mutation(envelope) == []
    command = driver.research_op_argv(paths, "pkg-1", envelope)
    assert command[0] == sys.executable
    assert command[1].endswith("skills/research-op/scripts/research_op.py")
    assert command[command.index("--research-root") + 1] == str(paths.root)
    assert command[command.index("--target") + 1] == "results-gate-row"
    assert command[command.index("--expected-version") + 1] == "4"


def test_workflow_snapshot_reads_state_when_interface_is_absent(tmp_path):
    paths = seed(tmp_path)
    remove_interface(paths)
    snapshot = driver.load_workflow_snapshot(paths, "pkg-1")
    assert snapshot["sourceDirection"] == "dir/d1"
    assert snapshot["experiments"] == [
        {
            "expId": "P1",
            "status": "READY",
            "implementationReadiness": "NOT_REQUIRED",
            "currentChangeId": None,
            "reviewChangeId": None,
        }
    ]
    assert snapshot["openRuns"] == []
    assert not paths.interface.exists()


def test_tick_uses_canonical_experiment_and_compiles_mutations(tmp_path):
    paths = seed(tmp_path)
    snapshot = driver.load_workflow_snapshot(paths, "pkg-1")
    mutation = {
        "op": "insert",
        "target": "results-gate-row",
        "payload": {"exp_id": "P1"},
    }

    def adapter(context):
        return _return(
            "verify",
            mutations=[mutation],
            source_seq=context["source_seq"],
            source_hash=context["source_hash"],
            sourceDirection=context["sourceDirection"],
            sourceExperiment=context["sourceExperiment"],
        )

    result = driver.run_tick(
        "pkg-1",
        EXPERIMENT,
        ["verify"],
        {"verify": adapter},
        paths=paths,
        context={
            "source_seq": snapshot["source_seq"],
            "source_hash": snapshot["source_hash"],
            "sourceDirection": "dir/d1",
            "sourceExperiment": CANONICAL_EXPERIMENT_ID,
        },
    )
    assert result["rejection"] is None
    assert result["experiment_id"] == CANONICAL_EXPERIMENT_ID
    assert result["proposed_mutations"] == [mutation]
    assert len(result["research_op_commands"]) == 1
    assert result["continuity"]["purpose"] == "measure the toy metric"


def test_tick_rejects_stale_dispatch_before_calling_adapter(tmp_path):
    paths = seed(tmp_path)
    called = False

    def adapter(_context):
        nonlocal called
        called = True
        return _return("verify")

    result = driver.run_tick(
        "pkg-1",
        EXPERIMENT,
        ["verify"],
        {"verify": adapter},
        paths=paths,
        context={
            "source_seq": 0,
            "source_hash": "",
            "sourceDirection": "dir/wrong",
        },
    )
    assert result["rejection"]
    assert "stale dispatch context" in result["rejection"]["errors"][0]
    assert "sourceDirection" in result["rejection"]["errors"][0]
    assert called is False


def test_tick_stops_when_adapter_is_missing():
    result = driver.run_tick(
        "pkg-1",
        EXPERIMENT,
        ["missing"],
        {},
        context={
            "source_seq": 7,
            "source_hash": "state-7",
            "sourceDirection": "dir/d1",
            "sourceExperiment": CANONICAL_EXPERIMENT_ID,
        },
    )
    assert result["rejection"]["role"] == "missing"
    assert result["proposed_mutations"] == []


def test_adapter_cannot_mutate_the_dispatch_identity():
    def adapter(context):
        context["source_hash"] = "forged"
        return _return("verify", source_hash="forged")

    result = driver.run_tick(
        "pkg-1",
        EXPERIMENT,
        ["verify"],
        {"verify": adapter},
        context={
            "source_seq": 7,
            "source_hash": "state-7",
            "sourceDirection": "dir/d1",
            "sourceExperiment": CANONICAL_EXPERIMENT_ID,
        },
    )
    assert result["rejection"]
    assert any(
        "source_hash" in error
        for error in result["rejection"]["errors"]
    )


def test_bound_experiment_resolution_keeps_legacy_aggregate_compatible(tmp_path):
    paths = seed(tmp_path, legacy_experiment=True)
    snapshot = StateQuery(paths).show("experiment")
    aggregate_id, experiment = driver.resolve_bound_experiment(
        snapshot["data"],
        "pkg-1",
        "P1",
    )
    assert aggregate_id == LEGACY_EXPERIMENT_ID
    assert experiment["local_id"] == "P1"


def test_bound_experiment_resolution_fails_closed_on_local_alias_collision():
    records = {
        CANONICAL_EXPERIMENT_ID: {
            "id": CANONICAL_EXPERIMENT_ID,
            "package_id": "pkg-1",
            "local_id": "P1",
        },
        "experiment/d1/e2": {
            "id": "experiment/d1/e2",
            "package_id": "pkg-1",
            "local_id": "P1",
        },
    }
    with pytest.raises(ValueError, match=r"found 2"):
        driver.resolve_bound_experiment(records, "pkg-1", "P1")
