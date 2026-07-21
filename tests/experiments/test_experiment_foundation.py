import json
import sys
from datetime import datetime

import pytest

from lib.experiments import harvest, launch as launch_module
from lib.experiments.launch import (
    _write_immutable_json,
    freeze_context,
    launch_run,
    prepare_run,
)
from lib.experiments.reconcile import reconcile_runs
from lib.experiments.report import open_runs
from lib.experiments.status import canonical_status
from lib.research_state import CommandRejected, EventStore, ResearchPaths
from lib.research_state.io import write_json_atomic


ACTOR = {"type": "agent", "id": "test"}
USER = {"type": "user", "id": "test-user"}


def _launch_spec():
    return {
        "purpose": "exercise the runtime contract",
        "config_ref": "config/test.yaml",
        "gate": {"metric": "smoke", "operator": "exists"},
        "control_mode": "CHECKPOINTED",
    }


def _record_launch_ack(store, *, package_id, experiment_id, key):
    store.commit(
        event_type="DecisionRecorded",
        aggregate_type="decision",
        aggregate_id=key,
        payload={
            "record": {
                "id": key,
                "kind": "LAUNCH_ACK",
                "status": "ACKNOWLEDGED",
                "package_id": package_id,
                "experiment_id": experiment_id,
                "actor": USER,
                "evidence": [{"kind": "ACTOR_ATTESTATION"}],
            }
        },
        actor=USER,
        idempotency_key=key,
        expected_version=0,
    )


def _seed(tmp_path):
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
        actor=ACTOR,
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
                "phase": "READY_TO_LAUNCH",
                "blocker": None,
                "direction_id": "direction/pkg",
                "sourceVersion": 1,
                "sourceChange": "test",
                "sourceExperiments": [{"id": "exp", "version": 1, "source": "test"}],
            }
        },
        actor=ACTOR,
        idempotency_key="seed-package",
        expected_version=0,
    )
    EventStore(paths, migration_mode=True).commit(
        event_type="AggregateUpserted",
        aggregate_type="experiment",
        aggregate_id="exp",
        payload={
            "record": {
                "id": "exp",
                "package_id": "pkg",
                "local_id": "exp",
                "direction_id": "direction/pkg",
                "scope_status": "ACTIVE",
                "scope_version": 1,
                "scope_source": "test",
                "scope_confirmation": "CONFIRMED",
                "confirmed_direction_version": 1,
                "status": "READY",
                "hypothesis": "test",
                "spec": _launch_spec(),
            }
        },
        actor=ACTOR,
        idempotency_key="seed-experiment",
        expected_version=0,
    )
    _record_launch_ack(
        store,
        package_id="pkg",
        experiment_id="exp",
        key="ack-pkg-exp",
    )
    return paths, store


def _run_events(store, run_id):
    return [
        event
        for event in store.events()
        if event["aggregate_type"] == "run"
        and event["aggregate_id"] == run_id
    ]


def _after_authorization_lease(store, run_id):
    event = next(
        event
        for event in store.events()
        if event["event_type"] == "RunLaunchAuthorized"
        and event["aggregate_id"] == run_id
    )
    authorized_at = datetime.fromisoformat(
        event["occurred_at"].replace("Z", "+00:00")
    ).timestamp()
    record = store.state()["aggregates"]["run"][run_id]
    return authorized_at + record["authorization_lease_seconds"] + 1


def _seed_open_allocation(store, allocation_id="alloc-crash"):
    store.commit(
        event_type="AggregateUpserted",
        aggregate_type="resource_allocation",
        aggregate_id=allocation_id,
        payload={
            "record": {
                "id": allocation_id,
                "alloc_id": allocation_id,
                "server": "test-gpu",
                "gpu_count": 1,
                "gpu_ids": ["0"],
                "status": "OPEN",
                "package_id": "pkg",
                "experiment_id": "exp",
            }
        },
        actor=ACTOR,
        idempotency_key=f"seed-allocation:{allocation_id}",
        expected_version=0,
    )


def test_context_hash_is_deterministic_and_excludes_capture_time():
    first = freeze_context(
        {"source_seq": 7, "source_hash": "abc", "data": {"b": 2, "a": 1}},
        experiment_id="exp",
        captured_at=10,
    )
    second = freeze_context(
        {"data": {"a": 1, "b": 2}, "source_hash": "abc", "source_seq": 7},
        experiment_id="exp",
        captured_at=999,
    )
    assert first["context_sha256"] == second["context_sha256"]
    assert first["captured_at"] != second["captured_at"]


def test_foreground_launch_writes_canonical_hierarchy_and_event_order(tmp_path):
    paths, store = _seed(tmp_path)
    command = [
        sys.executable,
        "-c",
        'print(\'{"step": 1, "total": 1, "loss": 0.25}\')',
    ]
    result = launch_run(
        paths=paths,
        package_id="pkg",
        experiment_id="exp",
        run_id="run-one",
        command=command,
        cwd=tmp_path,
        use_tmux=False,
    )

    assert result.run_dir == paths.root / "experiments/pkg/exp/run-one"
    assert result.status == "COMPLETED"
    assert json.loads(result.run_path.read_text())["run_id"] == "run-one"
    context = json.loads(result.context_path.read_text())
    assert context["selected_experiment_id"] == "exp"
    assert (result.run_dir / "metrics.jsonl").exists()
    assert not (paths.root / "_live").exists()
    assert not (paths.root / "runs.jsonl").exists()
    assert [event["event_type"] for event in _run_events(store, "run-one")] == [
        "RunLaunchAuthorized",
        "RunLaunched",
        "RunTerminal",
    ]
    assert store.state()["aggregates"]["run"]["run-one"]["status"] == "COMPLETED"
    assert open_runs(paths) == []

    with pytest.raises(FileExistsError):
        _write_immutable_json(result.run_path, {"replacement": True})
    assert json.loads(result.run_path.read_text())["run_id"] == "run-one"


@pytest.mark.parametrize(
    ("authorized_environment", "recorded_environment", "observed"),
    [
        ({}, {"CUDA_VISIBLE_DEVICES": ""}, "SET:"),
        (
            {"CUDA_VISIBLE_DEVICES": ""},
            {"CUDA_VISIBLE_DEVICES": ""},
            "SET:",
        ),
    ],
)
def test_foreground_launch_replays_exact_authorized_environment(
    tmp_path,
    monkeypatch,
    authorized_environment,
    recorded_environment,
    observed,
):
    paths, _ = _seed(tmp_path)
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "9")
    result = launch_run(
        paths=paths,
        package_id="pkg",
        experiment_id="exp",
        run_id="environment-binding",
        command=[
            sys.executable,
            "-c",
            (
                "import os; "
                "value = os.environ.get('CUDA_VISIBLE_DEVICES'); "
                "print('UNSET' if value is None else f'SET:{value}')"
            ),
        ],
        cwd=tmp_path,
        environment=authorized_environment,
        use_tmux=False,
    )

    assert result.status == "COMPLETED"
    assert (result.run_dir / "log.txt").read_text(encoding="utf-8").strip() == observed
    run = json.loads(result.run_path.read_text(encoding="utf-8"))
    assert run["environment"]["keys"] == recorded_environment


def test_composite_experiment_key_uses_package_local_path_segment(tmp_path):
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    store = EventStore(paths)
    store.initialize()
    EventStore(paths, migration_mode=True).commit(
        event_type="AggregateImported",
        aggregate_type="direction",
        aggregate_id="direction/vision",
        payload={
            "record": {
                "id": "direction/vision",
                "level": "direction",
                "parents": ["project/test"],
                "version": 1,
                "status": "ACTIVE",
                "source": "test",
                "spec": {},
            },
            "migration": {"source": "test-fixture"},
        },
        actor=ACTOR,
        idempotency_key="composite-direction",
    )
    store.commit(
        event_type="AggregateUpserted",
        aggregate_type="package",
        aggregate_id="vision",
        payload={
            "record": {
                "id": "vision",
                "lifecycle": "ACTIVE",
                "phase": "READY_TO_LAUNCH",
                "blocker": None,
                "direction_id": "direction/vision",
                "sourceVersion": 1,
                "sourceChange": "test",
                "sourceExperiments": [
                    {"id": "vision::P1", "version": 1, "source": "test"}
                ],
            }
        },
        actor=ACTOR,
        idempotency_key="composite-package",
    )
    EventStore(paths, migration_mode=True).commit(
        event_type="AggregateUpserted",
        aggregate_type="experiment",
        aggregate_id="vision::P1",
        payload={
            "record": {
                "id": "vision::P1",
                "package_id": "vision",
                "local_id": "P1",
                "direction_id": "direction/vision",
                "scope_status": "ACTIVE",
                "scope_version": 1,
                "scope_source": "test",
                "scope_confirmation": "CONFIRMED",
                "confirmed_direction_version": 1,
                "aliases": ["baseline"],
                "status": "READY",
                "spec": _launch_spec(),
            }
        },
        actor=ACTOR,
        idempotency_key="composite-experiment",
    )
    _record_launch_ack(
        store,
        package_id="vision",
        experiment_id="vision::P1",
        key="ack-vision-p1",
    )

    result = launch_run(
        paths=paths,
        package_id="vision",
        experiment_id="baseline",
        run_id="run-one",
        command=[sys.executable, "-c", "pass"],
        cwd=tmp_path,
        use_tmux=False,
    )
    run = json.loads(result.run_path.read_text())
    assert result.run_dir == paths.root / "experiments/vision/P1/run-one"
    assert run["experiment_id"] == "vision::P1"
    assert run["experiment_local_id"] == "P1"
    assert store.state()["aggregates"]["run"]["run-one"]["experiment_id"] == "vision::P1"


def test_reconcile_repairs_launch_before_terminal(tmp_path):
    paths, store = _seed(tmp_path)
    prepared = prepare_run(
        paths=paths,
        package_id="pkg",
        experiment_id="exp",
        run_id="lost-callbacks",
        command=[sys.executable, "-c", "pass"],
        cwd=tmp_path,
        now=lambda: 10.0,
    )
    write_json_atomic(
        prepared.run_dir / "status.json",
        {
            "schema_version": 1,
            "run_id": prepared.run_id,
            "package_id": "pkg",
            "experiment_id": "exp",
            "status": "RUN_FAILED",
            "started_at": 11.0,
            "ended_at": 12.0,
            "exit_code": 1,
            "pid": 123,
            "launch_failed": False,
        },
    )
    write_json_atomic(
        prepared.run_dir / "result.json",
            {
                "schema_version": 1,
                "kind": "runtime-terminal",
                "run_id": prepared.run_id,
                "package_id": "pkg",
                "experiment_id": "exp",
                "status": "FAILED",
                "protocol": {},
                "measurements": {},
                "verdict": "INCONCLUSIVE",
                "validity": "UNMEASURED",
                "supported_claims": [],
                "unsupported_claims": [],
                "decision_candidate": None,
                "evidence": [],
            },
    )

    with pytest.raises(CommandRejected, match="earlier RunLaunched"):
        store.commit(
            event_type="RunTerminal",
            aggregate_type="run",
            aggregate_id=prepared.run_id,
            payload={"status": "FAILED"},
            actor=ACTOR,
            idempotency_key="illegal-terminal-first",
            expected_version=1,
        )

    result = reconcile_runs(paths)
    assert result.errors == ()
    assert [action.event_type for action in result.actions] == [
        "RunLaunched",
        "RunTerminal",
    ]
    assert [event["event_type"] for event in _run_events(store, prepared.run_id)] == [
        "RunLaunchAuthorized",
        "RunLaunched",
        "RunTerminal",
    ]
    assert store.state()["aggregates"]["run"][prepared.run_id]["status"] == "FAILED"
    assert reconcile_runs(paths).actions == ()


def test_reconcile_expires_authorization_before_run_json_and_releases_allocation(
    tmp_path,
    monkeypatch,
):
    paths, store = _seed(tmp_path)
    _seed_open_allocation(store)
    link_allocation = launch_module._link_allocation

    def hard_crash(*args, **kwargs):
        link_allocation(*args, **kwargs)
        raise SystemExit("synthetic hard crash after authorization")

    monkeypatch.setattr(launch_module, "_link_allocation", hard_crash)
    with pytest.raises(SystemExit, match="synthetic hard crash"):
        prepare_run(
            paths=paths,
            package_id="pkg",
            experiment_id="exp",
            run_id="crash-before-run-json",
            command=[sys.executable, "-c", "pass"],
            cwd=tmp_path,
            resource={"server": "test-gpu", "alloc_id": "alloc-crash"},
            environment={"CUDA_VISIBLE_DEVICES": "0"},
            authorization_lease_seconds=1,
        )

    run_dir = paths.run_dir("pkg", "exp", "crash-before-run-json")
    assert not run_dir.exists()
    reconciled = reconcile_runs(
        paths,
        now=_after_authorization_lease(store, "crash-before-run-json"),
    )

    assert reconciled.errors == ()
    assert [action.event_type for action in reconciled.actions] == [
        "RunLaunchFailed",
        "ResourceAllocationReleased",
    ]
    state = store.state()
    run = state["aggregates"]["run"]["crash-before-run-json"]
    allocation = state["aggregates"]["resource_allocation"]["alloc-crash"]
    assert run["status"] == "FAILED"
    assert run["launch_failed"] is True
    assert allocation["status"] == "RELEASED"
    assert allocation["outcome"] == "RUN_LAUNCH_FAILED"
    assert allocation["run_launch_failed_event_id"] == (
        run["launch_failed_event_id"]
    )
    release_event = next(
        event
        for event in store.events()
        if event["event_type"] == "ResourceAllocationReleased"
        and event["aggregate_id"] == "alloc-crash"
    )
    assert release_event["causation_id"] == run["launch_failed_event_id"]

    event_count = len(store.events())
    repeated = reconcile_runs(
        paths,
        now=_after_authorization_lease(store, "crash-before-run-json") + 60,
    )
    assert repeated.errors == ()
    assert repeated.actions == ()
    assert len(store.events()) == event_count


def test_reconcile_expires_partial_run_directory_without_process_evidence(
    tmp_path,
    monkeypatch,
):
    paths, store = _seed(tmp_path)

    def hard_crash(*_args, **_kwargs):
        raise SystemExit("synthetic crash before immutable write")

    monkeypatch.setattr(launch_module, "_write_immutable_json", hard_crash)
    with pytest.raises(SystemExit, match="before immutable write"):
        prepare_run(
            paths=paths,
            package_id="pkg",
            experiment_id="exp",
            run_id="partial-envelope",
            command=[sys.executable, "-c", "pass"],
            cwd=tmp_path,
            environment={},
            authorization_lease_seconds=1,
        )

    run_dir = paths.run_dir("pkg", "exp", "partial-envelope")
    assert run_dir.is_dir()
    assert (run_dir / "files").is_dir()
    assert not (run_dir / "run.json").exists()
    reconciled = reconcile_runs(
        paths,
        now=_after_authorization_lease(store, "partial-envelope"),
    )

    assert reconciled.errors == ()
    assert [action.event_type for action in reconciled.actions] == [
        "RunLaunchFailed"
    ]
    run = store.state()["aggregates"]["run"]["partial-envelope"]
    assert run["status"] == "FAILED"
    assert run["failure_reason"] == (
        "authorization lease expired before immutable run.json was published"
    )


def test_reconcile_preserves_partial_launch_with_process_evidence(
    tmp_path,
    monkeypatch,
):
    paths, store = _seed(tmp_path)

    def hard_crash(*_args, **_kwargs):
        raise SystemExit("synthetic crash before immutable write")

    monkeypatch.setattr(launch_module, "_write_immutable_json", hard_crash)
    with pytest.raises(SystemExit):
        prepare_run(
            paths=paths,
            package_id="pkg",
            experiment_id="exp",
            run_id="partial-with-process",
            command=[sys.executable, "-c", "pass"],
            cwd=tmp_path,
            environment={},
            authorization_lease_seconds=1,
        )
    run_dir = paths.run_dir("pkg", "exp", "partial-with-process")
    write_json_atomic(
        run_dir / "status.json",
        {
            "schema_version": 1,
            "run_id": "partial-with-process",
            "package_id": "pkg",
            "experiment_id": "exp",
            "status": "RUNNING",
            "started_at": 1.0,
            "pid": 123,
        },
    )

    reconciled = reconcile_runs(
        paths,
        now=_after_authorization_lease(store, "partial-with-process"),
    )

    assert reconciled.actions == ()
    assert len(reconciled.errors) == 1
    assert "process evidence requires manual recovery" in reconciled.errors[0]
    run = store.state()["aggregates"]["run"]["partial-with-process"]
    assert run["status"] == "QUEUED"
    assert not run.get("launch_failed")


def test_complete_immutable_envelope_satisfies_authorization_lease(tmp_path):
    paths, store = _seed(tmp_path)
    prepared = prepare_run(
        paths=paths,
        package_id="pkg",
        experiment_id="exp",
        run_id="complete-queued-envelope",
        command=[sys.executable, "-c", "pass"],
        cwd=tmp_path,
        environment={},
        authorization_lease_seconds=1,
    )
    assert prepared.run_path.is_file()
    assert prepared.context_path.is_file()

    reconciled = reconcile_runs(
        paths,
        now=_after_authorization_lease(store, prepared.run_id),
    )

    assert reconciled.errors == ()
    assert reconciled.actions == ()
    run = store.state()["aggregates"]["run"][prepared.run_id]
    assert run["status"] == "QUEUED"
    assert not run.get("launch_failed")


def test_failed_process_creation_records_launch_failed_without_launched(tmp_path):
    paths, store = _seed(tmp_path)
    with pytest.raises(FileNotFoundError):
        launch_run(
            paths=paths,
            package_id="pkg",
            experiment_id="exp",
            run_id="cannot-start",
            command=["/definitely/missing/executable"],
            cwd=tmp_path,
            use_tmux=False,
        )
    assert [event["event_type"] for event in _run_events(store, "cannot-start")] == [
        "RunLaunchAuthorized",
        "RunLaunchFailed",
    ]
    status = json.loads(
        paths.run_dir("pkg", "exp", "cannot-start")
        .joinpath("status.json")
        .read_text()
    )
    assert status["status"] == "FAILED"
    assert status["launch_failed"] is True


def test_harvester_rejects_tampered_run_json_before_process_start(tmp_path):
    paths, store = _seed(tmp_path)
    marker = tmp_path / "must-not-exist"
    prepared = prepare_run(
        paths=paths,
        package_id="pkg",
        experiment_id="exp",
        run_id="tampered-run",
        command=[sys.executable, "-c", "pass"],
        cwd=tmp_path,
    )
    tampered = dict(prepared.run)
    tampered["command"] = [
        sys.executable,
        "-c",
        f"from pathlib import Path; Path({str(marker)!r}).touch()",
    ]
    write_json_atomic(prepared.run_path, tampered)

    with pytest.raises(ValueError, match="launch_sha256"):
        harvest.run_command(
            paths=paths,
            run_dir=prepared.run_dir,
            run=tampered,
        )
    assert not marker.exists()
    assert [event["event_type"] for event in _run_events(store, "tampered-run")] == [
        "RunLaunchAuthorized",
        "RunLaunchFailed",
    ]


def test_reconciler_ignores_active_legacy_outputs(tmp_path):
    paths, _ = _seed(tmp_path)
    legacy = tmp_path / "outputs/pkg/runs/active/status.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text('{"status":"RUNNING"}\n', encoding="utf-8")

    result = reconcile_runs(paths)
    assert result.scanned == 0
    assert result.actions == ()
    assert legacy.read_text(encoding="utf-8") == '{"status":"RUNNING"}\n'


@pytest.mark.parametrize(
    ("legacy", "canonical"),
    [("RUN_FAILED", "FAILED"), ("RUN_HALTED", "HALTED")],
)
def test_status_adapter_maps_legacy_values(legacy, canonical):
    assert canonical_status(legacy) == canonical
