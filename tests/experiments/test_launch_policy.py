import json

import pytest

from lib.experiments import launch
from lib.experiments.launch import prepare_run
from lib.research_state import CommandRejected, EventStore, ResearchPaths
from lib.research_state.io import read_jsonl


AGENT = {"type": "agent", "id": "test"}
USER = {"type": "user", "id": "pm"}


def _seed(
    tmp_path,
    *,
    phase="READY_TO_LAUNCH",
    spec=True,
    ack=True,
    allocation=None,
):
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    store = EventStore(paths)
    store.initialize()
    EventStore(paths, migration_mode=True).commit(
        event_type="AggregateImported",
        aggregate_type="direction",
        aggregate_id="direction/pkg",
        payload={
            "record": {
                "id": "direction/pkg",
                "level": "direction",
                "parents": ["project/test"],
                "version": 1,
                "status": "ACTIVE",
                "source": "test",
                "spec": {},
            },
            "migration": {"source": "test-fixture"},
        },
        actor=AGENT,
        idempotency_key="seed-direction",
    )
    store.commit(
        event_type="AggregateUpserted",
        aggregate_type="package",
        aggregate_id="pkg",
        payload={
            "record": {
                "id": "pkg",
                "lifecycle": "ACTIVE",
                "phase": phase,
                "blocker": None,
                "direction_id": "direction/pkg",
                "sourceVersion": 1,
                "sourceChange": "test",
                "sourceExperiments": [
                    {"id": "pkg::P1", "version": 1, "source": "test"}
                ],
            }
        },
        actor=AGENT,
        idempotency_key="seed-package",
    )
    experiment = {
        "id": "pkg::P1",
        "local_id": "P1",
        "package_id": "pkg",
        "direction_id": "direction/pkg",
        "scope_status": "ACTIVE",
        "scope_version": 1,
        "scope_source": "test",
        "scope_confirmation": "CONFIRMED",
        "confirmed_direction_version": 1,
        "status": "READY",
    }
    if spec:
        experiment["spec"] = {
            "purpose": "policy test",
            "config_ref": {"path": "config.json", "sha256": "abc"},
            "gate": {"metric": "accuracy", "operator": ">=", "value": 0.5},
            "control_mode": "CHECKPOINTED",
        }
    EventStore(paths, migration_mode=True).commit(
        event_type="AggregateUpserted" if spec else "AggregateImported",
        aggregate_type="experiment",
        aggregate_id="pkg::P1",
        payload={"record": experiment},
        actor=AGENT,
        idempotency_key="seed-experiment",
    )
    if ack:
        store.commit(
            event_type="DecisionRecorded",
            aggregate_type="decision",
            aggregate_id="ack",
            payload={
                "record": {
                    "id": "ack",
                    "kind": "LAUNCH_ACK",
                    "status": "ACKNOWLEDGED",
                    "package_id": "pkg",
                    "experiment_id": "pkg::P1",
                    "actor": USER,
                    "evidence": [{"kind": "ACTOR_ATTESTATION"}],
                }
            },
            actor=USER,
            idempotency_key="seed-ack",
        )
    if allocation is not None:
        record = {
            "id": "alloc",
            "alloc_id": "alloc",
            "server": "local",
            "gpu_count": 1,
            "gpu_ids": ["0"],
            "status": "OPEN",
            "package_id": allocation.get("package_id", "pkg"),
            "experiment_id": allocation.get("experiment_id", "pkg::P1"),
        }
        record.update(allocation)
        store.commit(
            event_type="AggregateUpserted",
            aggregate_type="resource_allocation",
            aggregate_id="alloc",
            payload={"record": record},
            actor=AGENT,
            idempotency_key="seed-allocation",
        )
    return paths, store


@pytest.mark.parametrize(
    ("seed_kwargs", "rule"),
    [
        ({"phase": "IMPLEMENTING"}, "package phase must be READY_TO_LAUNCH"),
        ({"spec": False}, "Experiment.spec requires"),
        ({"ack": False}, "requires a user LAUNCH_ACK"),
    ],
)
def test_authorization_rejects_before_run_or_directory_write(
    tmp_path, seed_kwargs, rule
):
    paths, store = _seed(tmp_path, **seed_kwargs)
    before = store.state()["source_seq"]
    with pytest.raises(CommandRejected, match=rule):
        prepare_run(
            paths=paths,
            package_id="pkg",
            experiment_id="P1",
            run_id="rejected",
            command=["true"],
            cwd=tmp_path,
        )

    assert store.state()["source_seq"] == before
    assert "rejected" not in store.state()["aggregates"]["run"]
    assert not paths.run_dir("pkg", "P1", "rejected").exists()
    outcomes = [
        row["outcome"]
        for row in read_jsonl(paths.audit_actions)
        if row.get("aggregate_id") == "rejected"
    ]
    assert outcomes == ["COMMAND_REJECTED"]


def test_cuda_launch_requires_matching_open_allocation(tmp_path):
    paths, _ = _seed(tmp_path)
    with pytest.raises(CommandRejected, match="no alloc_id"):
        prepare_run(
            paths=paths,
            package_id="pkg",
            experiment_id="P1",
            run_id="gpu-without-allocation",
            command=["true"],
            cwd=tmp_path,
            environment={"CUDA_VISIBLE_DEVICES": "0"},
        )

    paths, _ = _seed(
        tmp_path / "mismatch",
        allocation={"experiment_id": "pkg::P2"},
    )
    with pytest.raises(CommandRejected, match="belongs to"):
        prepare_run(
            paths=paths,
            package_id="pkg",
            experiment_id="P1",
            run_id="mismatched-allocation",
            command=["true"],
            cwd=tmp_path / "mismatch",
            resource={"alloc_id": "alloc"},
            environment={"CUDA_VISIBLE_DEVICES": "0"},
        )


@pytest.mark.parametrize(
    ("allocation", "visible_devices", "rule"),
    [
        (
            {"gpu_count": 1, "gpu_ids": ["0"]},
            "0,1",
            "authorizes 1 GPU",
        ),
        (
            {"gpu_count": 1, "gpu_ids": ["1"]},
            "0",
            "authorizes GPU ids",
        ),
    ],
)
def test_allocation_exactly_constrains_gpu_count_and_ids(
    tmp_path,
    allocation,
    visible_devices,
    rule,
):
    paths, _ = _seed(tmp_path, allocation=allocation)
    with pytest.raises(CommandRejected, match=rule):
        prepare_run(
            paths=paths,
            package_id="pkg",
            experiment_id="P1",
            run_id="gpu-binding-rejected",
            command=["true"],
            cwd=tmp_path,
            resource={"alloc_id": "alloc"},
            environment={"CUDA_VISIBLE_DEVICES": visible_devices},
        )
    assert not paths.run_dir("pkg", "P1", "gpu-binding-rejected").exists()


def test_allocation_accepts_the_exact_gpu_binding(tmp_path):
    paths, store = _seed(
        tmp_path,
        allocation={"gpu_count": 2, "gpu_ids": ["2", "3"]},
    )
    prepared = prepare_run(
        paths=paths,
        package_id="pkg",
        experiment_id="P1",
        run_id="gpu-binding-authorized",
        command=["true"],
        cwd=tmp_path,
        resource={"alloc_id": "alloc"},
        environment={"CUDA_VISIBLE_DEVICES": "2,3"},
    )

    assert prepared.run["gpu_ids"] == ["2", "3"]
    allocation = store.state()["aggregates"]["resource_allocation"]["alloc"]
    assert allocation["run_id"] == prepared.run_id


def test_authorized_envelope_binds_ack_and_structured_spec(tmp_path):
    paths, store = _seed(tmp_path)
    prepared = prepare_run(
        paths=paths,
        package_id="pkg",
        experiment_id="P1",
        run_id="authorized",
        command=["true"],
        cwd=tmp_path,
        environment={},
    )
    run = json.loads(prepared.run_path.read_text(encoding="utf-8"))
    assert run["launch_ack_decision_id"] == "ack"
    assert run["experiment_id"] == "pkg::P1"
    assert run["context_source_seq"] == prepared.context["source_seq"]
    assert run["context_source_hash"] == prepared.context["source_hash"]
    assert store.state()["aggregates"]["run"]["authorized"]["status"] == "QUEUED"


def test_scope_execution_lease_replaces_per_launch_user_ack(tmp_path):
    paths, store = _seed(tmp_path, ack=False)
    digest = "a" * 64
    store.commit(
        event_type="AggregatePatched",
        aggregate_type="package",
        aggregate_id="pkg",
        payload={
            "patch": {
                "executionAuthorized": True,
                "executionLease": {
                    "status": "OPEN",
                    "scope_sha256": digest,
                    "package_revision": 1,
                    "experiment_ids": ["pkg::P1"],
                    "grants": ["IMPLEMENT", "LAUNCH", "RECORD_RESULTS"],
                },
            }
        },
        actor=USER,
        idempotency_key="seed-scope-lease",
    )

    prepared = prepare_run(
        paths=paths,
        package_id="pkg",
        experiment_id="P1",
        run_id="lease-authorized",
        command=["true"],
        cwd=tmp_path,
        environment={},
    )

    run = json.loads(prepared.run_path.read_text(encoding="utf-8"))
    assert run["launch_ack_decision_id"] == f"lease:{digest}"
    assert store.state()["aggregates"]["decision"] == {}


def test_caller_cannot_replace_authoritative_launch_context(tmp_path):
    paths, store = _seed(tmp_path)
    with pytest.raises(CommandRejected) as rejected:
        prepare_run(
            paths=paths,
            package_id="pkg",
            experiment_id="P1",
            run_id="forged-context",
            command=["true"],
            cwd=tmp_path,
            context={"source_seq": 0, "source_hash": "", "data": {}},
        )

    assert rejected.value.rule == "launch-context-not-authoritative"
    assert "forged-context" not in store.state()["aggregates"]["run"]
    assert not paths.run_dir("pkg", "P1", "forged-context").exists()


def test_state_change_after_context_capture_rejects_authorization(
    tmp_path,
    monkeypatch,
):
    paths, store = _seed(tmp_path)
    real_authorize = launch.research_management.authorize_run

    def authorize_after_concurrent_change(*args, **kwargs):
        store.commit(
            event_type="DecisionRecorded",
            aggregate_type="decision",
            aggregate_id="concurrent-decision",
            payload={
                "record": {
                    "id": "concurrent-decision",
                    "actor": AGENT,
                    "evidence": [{"kind": "STATE_CHANGE"}],
                }
            },
            actor=AGENT,
            idempotency_key="concurrent-context-change",
        )
        return real_authorize(*args, **kwargs)

    monkeypatch.setattr(
        launch.research_management,
        "authorize_run",
        authorize_after_concurrent_change,
    )
    with pytest.raises(CommandRejected) as rejected:
        prepare_run(
            paths=paths,
            package_id="pkg",
            experiment_id="P1",
            run_id="stale-context",
            command=["true"],
            cwd=tmp_path,
        )

    assert rejected.value.rule == "launch-context-stale"
    assert "stale-context" not in store.state()["aggregates"]["run"]
    assert not paths.run_dir("pkg", "P1", "stale-context").exists()
