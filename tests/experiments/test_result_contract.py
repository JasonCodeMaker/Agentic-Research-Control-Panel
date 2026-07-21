import hashlib
import json
import sys

import pytest

from lib.experiments.contracts import verify_result_evidence
from lib.experiments.extract import extract_result
from lib.experiments.launch import launch_run, prepare_run
from lib.research_state import CommandRejected, EventStore, ResearchPaths


AGENT = {"type": "agent", "id": "test"}
USER = {"type": "user", "id": "pm"}


def _launch(tmp_path):
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
                "phase": "READY_TO_LAUNCH",
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
    EventStore(paths, migration_mode=True).commit(
        event_type="AggregateUpserted",
        aggregate_type="experiment",
        aggregate_id="pkg::P1",
        payload={
            "record": {
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
                "spec": {
                    "purpose": "verify evidence",
                    "config_ref": "config.yaml",
                    "gate": "loss <= 1",
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
    launched = launch_run(
        paths=paths,
        package_id="pkg",
        experiment_id="P1",
        run_id="run-one",
        command=[sys.executable, "-c", "print('loss=0.25')"],
        cwd=tmp_path,
        use_tmux=False,
    )
    return paths, launched


def test_terminal_result_evidence_is_hash_bound(tmp_path):
    paths, launched = _launch(tmp_path)
    run = json.loads(launched.run_path.read_text(encoding="utf-8"))
    result_path = launched.run_dir / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["evidence"]
    assert all(
        {
            "uri",
            "sha256",
            "size_bytes",
            "kind",
            "package_id",
            "experiment_id",
            "run_id",
        }
        <= set(ref)
        for ref in result["evidence"]
    )
    verify_result_evidence(paths, run, result)

    (launched.run_dir / "log.txt").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(ValueError, match="mismatch"):
        verify_result_evidence(paths, run, result)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("protocol", None, "protocol must be an object"),
        ("measurements", [], "measurements must be an object"),
        (
            "decision_candidate",
            "RUN_NEXT_EXPERIMENT",
            "decision_candidate must be an object or null",
        ),
        ("status", "RUNNING", "status must be terminal"),
    ],
)
def test_terminal_result_requires_complete_scientific_shape(
    tmp_path,
    field,
    value,
    message,
):
    paths, launched = _launch(tmp_path)
    run = json.loads(launched.run_path.read_text(encoding="utf-8"))
    result = json.loads(
        (launched.run_dir / "result.json").read_text(encoding="utf-8")
    )
    result[field] = value

    with pytest.raises(ValueError, match=message):
        verify_result_evidence(paths, run, result)


def test_extractor_adds_scientific_result_without_rewriting_run_intent(tmp_path):
    paths, launched = _launch(tmp_path)
    before = launched.run_path.read_bytes()
    table = launched.run_dir / "files" / "summary.json"
    table.parent.mkdir(exist_ok=True)
    table.write_text('{"loss": 0.25}\n', encoding="utf-8")

    result = extract_result(
        paths,
        launched.run_dir,
        payload={
            "protocol": {"name": "smoke"},
            "measurements": {"loss": 0.25},
            "verdict": "PASS",
            "validity": "VALID",
            "supported_claims": ["The smoke gate passed."],
            "unsupported_claims": [],
        },
        evidence_files=[table],
    )
    assert result["verdict"] == "PASS"
    assert result["validity"] == "VALID"
    assert any(ref["uri"].endswith("files/summary.json") for ref in result["evidence"])
    assert launched.run_path.read_bytes() == before

    result_path = launched.run_dir / "result.json"
    result_sha256 = hashlib.sha256(result_path.read_bytes()).hexdigest()
    store = EventStore(paths)
    run_events = [
        event
        for event in store.events()
        if event["aggregate_type"] == "run"
        and event["aggregate_id"] == "run-one"
    ]
    assert [event["event_type"] for event in run_events] == [
        "RunLaunchAuthorized",
        "RunLaunched",
        "RunTerminal",
        "RunResultFinalized",
    ]
    assert sum(
        event["event_type"] == "RunTerminal" for event in run_events
    ) == 1
    current = store.state()["aggregates"]["run"]["run-one"]
    assert current["status"] == "COMPLETED"
    assert current["latest_scientific_result"]["result_sha256"] == result_sha256
    assert current["latest_scientific_result"]["measurements"] == {"loss": 0.25}
    assert current["latest_scientific_result"]["evidence_count"] == len(
        result["evidence"]
    )
    interface_rows = [
        json.loads(line)
        for line in paths.interface_data.joinpath("live-runs.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    projected = next(row for row in interface_rows if row["run_id"] == "run-one")
    assert (
        projected["latest_scientific_result"]["result_sha256"]
        == result_sha256
    )

    repeated = extract_result(
        paths,
        launched.run_dir,
        payload={
            "protocol": {"name": "smoke"},
            "measurements": {"loss": 0.25},
            "verdict": "PASS",
            "validity": "VALID",
            "supported_claims": ["The smoke gate passed."],
            "unsupported_claims": [],
        },
        evidence_files=[table],
    )
    assert repeated == result
    assert sum(
        event["event_type"] == "RunResultFinalized"
        for event in store.events()
        if event["aggregate_type"] == "run"
        and event["aggregate_id"] == "run-one"
    ) == 1


def test_extractor_rejects_a_verdict_that_contradicts_the_gate(tmp_path):
    paths, launched = _launch(tmp_path)

    with pytest.raises(CommandRejected, match="contradicts gate"):
        extract_result(
            paths,
            launched.run_dir,
            payload={
                "protocol": {"name": "smoke"},
                "measurements": {"loss": 0.25},
                "verdict": "FAIL",
                "validity": "VALID",
                "supported_claims": [],
                "unsupported_claims": ["The declared gate did not pass."],
            },
        )

    assert not any(
        event["event_type"] == "RunResultFinalized"
        for event in EventStore(paths).events()
        if event["aggregate_id"] == launched.run_id
    )


def test_result_finalization_cannot_replace_terminal_ownership(tmp_path):
    paths, launched = _launch(tmp_path)
    pending = prepare_run(
        paths=paths,
        package_id="pkg",
        experiment_id="P1",
        run_id="not-terminal",
        command=[sys.executable, "-c", "pass"],
        cwd=tmp_path,
    )
    store = EventStore(paths)
    with pytest.raises(CommandRejected, match="earlier RunTerminal"):
        store.commit(
            event_type="RunResultFinalized",
            aggregate_type="run",
            aggregate_id=pending.run_id,
            payload={"result": {}},
            actor=AGENT,
            idempotency_key="illegal-result-finalization",
            expected_version=1,
        )
    assert [
        event["event_type"]
        for event in store.events()
        if event["aggregate_type"] == "run"
        and event["aggregate_id"] == pending.run_id
    ] == ["RunLaunchAuthorized"]
    assert launched.status == "COMPLETED"
