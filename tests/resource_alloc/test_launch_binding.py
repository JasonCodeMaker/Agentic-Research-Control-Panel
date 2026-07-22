import json
import sys

from lib.experiments import launch
from lib.research_state import EventStore, ResearchPaths


AGENT = {"type": "agent", "id": "test"}
USER = {"type": "user", "id": "pm"}


def _seed(tmp_path, *, allocation=False):
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    store = EventStore(paths)
    store.initialize()
    EventStore(paths, fixture_mode=True).commit(
        event_type="AggregateImported",
        aggregate_type="direction",
        aggregate_id="direction/pkg-a",
        payload={
            "record": {
                "id": "direction/pkg-a",
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
        aggregate_id="pkg-a",
        payload={
            "record": {
                "id": "pkg-a",
                "lifecycle": "ACTIVE",
                "phase": "READY_TO_LAUNCH",
                "blocker": None,
                "direction_id": "direction/pkg-a",
                "sourceVersion": 1,
                "sourceChange": "test",
                "sourceExperiments": [
                    {"id": "pkg-a::P1", "version": 1, "source": "test"}
                ],
            }
        },
        actor=AGENT,
        idempotency_key="seed-package",
    )
    EventStore(paths, fixture_mode=True).commit(
        event_type="AggregateUpserted",
        aggregate_type="experiment",
        aggregate_id="pkg-a::P1",
        payload={
            "record": {
                "id": "pkg-a::P1",
                "local_id": "P1",
                "package_id": "pkg-a",
                "direction_id": "direction/pkg-a",
                "scope_status": "ACTIVE",
                "scope_version": 1,
                "scope_source": "test",
                "scope_confirmation": "CONFIRMED",
                "confirmed_direction_version": 1,
                "status": "READY",
                "spec": {
                    "purpose": "smoke test",
                    "config_ref": "config/test.yaml",
                    "gate": "process exits successfully",
                    "control_mode": "CHECKPOINTED",
                },
            }
        },
        actor=AGENT,
        idempotency_key="seed-experiment",
    )
    store.commit(
        event_type="DecisionRecorded",
        aggregate_type="decision",
        aggregate_id="launch-ack",
        payload={
            "record": {
                "id": "launch-ack",
                "kind": "LAUNCH_ACK",
                "status": "ACKNOWLEDGED",
                "package_id": "pkg-a",
                "experiment_id": "pkg-a::P1",
                "actor": USER,
                "evidence": [{"kind": "ACTOR_ATTESTATION"}],
            }
        },
        actor=USER,
        idempotency_key="seed-launch-ack",
    )
    if allocation:
        store.commit(
            event_type="AggregateUpserted",
            aggregate_type="resource_allocation",
            aggregate_id="a-123",
            payload={
                "record": {
                    "id": "a-123",
                    "alloc_id": "a-123",
                    "server": "bunya",
                    "gpu_count": 1,
                    "gpu_ids": ["0"],
                    "status": "OPEN",
                    "package_id": "pkg-a",
                    "experiment_id": "pkg-a::P1",
                }
            },
            actor=AGENT,
            idempotency_key="seed-allocation",
        )
    return paths


def _launch(tmp_path, *, server="local", alloc_id=None):
    paths = _seed(tmp_path, allocation=alloc_id is not None)
    return launch.launch_run(
        paths=paths,
        package_id="pkg-a",
        experiment_id="P1",
        run_id="run-one",
        command=[sys.executable, "-c", "print('ok')"],
        resource={"server": server, "alloc_id": alloc_id},
        environment=(
            {"CUDA_VISIBLE_DEVICES": "0"}
            if alloc_id is not None
            else {}
        ),
        use_tmux=False,
    )


def test_run_records_server_and_allocation_binding(tmp_path):
    result = _launch(tmp_path, server="bunya", alloc_id="a-123")
    run = json.loads(result.run_path.read_text(encoding="utf-8"))
    assert run["resource"] == {"server": "bunya", "alloc_id": "a-123"}
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    allocation = EventStore(paths).state()["aggregates"]["resource_allocation"][
        "a-123"
    ]
    assert allocation["run_id"] == "run-one"
    linked = [
        event
        for event in EventStore(paths).events()
        if event["event_type"] == "ResourceAllocationLinked"
    ]
    assert linked[0]["causation_id"] == result.authorization_event_id


def test_run_records_local_server_without_allocation(tmp_path):
    result = _launch(tmp_path)
    run = json.loads(result.run_path.read_text(encoding="utf-8"))
    assert run["resource"] == {"server": "local", "alloc_id": None}
