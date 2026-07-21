import json
import subprocess
import sys
from pathlib import Path

from lib.research_state import EventStore, ResearchPaths

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "lib" / "resource_alloc" / "cli.py"

NVSMI = "0, 100, 49152, 0\n1, 100, 49152, 0\n"


def _run(tmp_path, *args, stdin=None):
    result = subprocess.run(
        [sys.executable, str(CLI), "--research-root", str(tmp_path), *args],
        capture_output=True, text=True, input=stdin,
    )
    return result


def _seed_experiment(tmp_path):
    store = EventStore(
        ResearchPaths(workspace=tmp_path.parent, root=tmp_path),
        migration_mode=True,
    )
    for aggregate_type, aggregate_id, record in (
        (
            "package",
            "demo",
            {
                "id": "demo",
                "direction_id": "direction/demo",
                "lifecycle": "ACTIVE",
                "phase": "READY_TO_LAUNCH",
                "blocker": None,
            },
        ),
        (
            "experiment",
            "experiment/demo/P1",
            {
                "id": "experiment/demo/P1",
                "package_id": "demo",
                "local_id": "P1",
                "direction_id": "direction/demo",
                "status": "READY",
                "spec": {
                    "purpose": "Exercise resource allocation.",
                    "config_ref": "configs/test.yaml",
                    "gate": "allocation is recorded",
                    "control_mode": "CHECKPOINTED",
                },
            },
        ),
    ):
        store.commit(
            event_type="AggregateImported",
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            payload={
                "record": record,
                "migration": {"source": "test-fixture"},
            },
            actor={"type": "system", "id": "test"},
            idempotency_key=f"seed-{aggregate_type}",
        )


def _authorize_run(tmp_path, alloc_id):
    store = EventStore(ResearchPaths(workspace=tmp_path.parent, root=tmp_path))
    store.commit(
        event_type="RunLaunchAuthorized",
        aggregate_type="run",
        aggregate_id="P1-20260612-101500",
        payload={
            "record": {
                "id": "P1-20260612-101500",
                "package_id": "demo",
                "experiment_id": "experiment/demo/P1",
                "dir": "experiments/demo/P1/P1-20260612-101500",
                "resource": {"server": "local", "alloc_id": alloc_id},
            }
        },
        actor={"type": "agent", "id": "test"},
        entry_skill="research-run",
        idempotency_key="seed-authorized-run",
        expected_version=0,
    )


def test_cli_register_list_recommend_allocate_release_roundtrip(tmp_path):
    server = {"name": "local", "kind": "local", "gpus": [{"type": "a6000", "count": 2, "mem_gb": 48}]}
    out = _run(tmp_path, "register", stdin=json.dumps(server))
    assert out.returncode == 0, out.stderr
    _seed_experiment(tmp_path)

    out = _run(tmp_path, "list")
    assert "local" in out.stdout

    smi = tmp_path / "smi.txt"
    smi.write_text(NVSMI, encoding="utf-8")
    out = _run(tmp_path, "snapshot", "--server", "local", "--from-nvidia-smi", str(smi))
    assert out.returncode == 0, out.stderr

    out = _run(tmp_path, "recommend", "--pkg", "demo", "--exp", "P1", "--gpu-count", "1")
    assert out.returncode == 0, out.stderr
    rec = json.loads(out.stdout)
    assert rec["candidates"][0]["server"] == "local"
    assert rec["candidates"][0]["availability"] == "confirmed-free"

    out = _run(tmp_path, "allocate", "--server", "local", "--pkg", "demo", "--exp", "P1",
               "--gpu-count", "1", "--reason", "smoke")
    assert out.returncode == 0, out.stderr
    alloc_id = json.loads(out.stdout)["alloc_id"]
    _authorize_run(tmp_path, alloc_id)

    out = _run(tmp_path, "link", "--alloc", alloc_id, "--run-id", "P1-20260612-101500")
    assert out.returncode == 0, out.stderr

    out = _run(tmp_path, "status")
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout)["servers"][0]["open_allocations"] == 1

    out = _run(tmp_path, "release", "--alloc", alloc_id, "--outcome", "COMPLETED")
    assert out.returncode == 0, out.stderr
    assert json.loads(_run(tmp_path, "status").stdout)["servers"][0]["open_allocations"] == 0


def test_cli_rejections_exit_nonzero_with_reason(tmp_path):
    out = _run(tmp_path, "register", stdin=json.dumps({"name": "x", "kind": "warp-drive"}))
    assert out.returncode != 0
    assert "kind" in out.stderr

    out = _run(tmp_path, "allocate", "--server", "ghost", "--pkg", "demo", "--exp", "P1")
    assert out.returncode != 0


def test_cli_argument_rejection_is_audited_without_full_command(tmp_path):
    secret = "cli-secret-must-not-enter-audit"
    out = _run(
        tmp_path,
        "allocate",
        "--server",
        "local",
        "--pkg",
        "demo",
        "--exp",
        "P1",
        "--gpu-count",
        "not-an-integer",
        "--reason",
        secret,
    )

    assert out.returncode == 2
    audit_text = (tmp_path / "audit" / "actions.jsonl").read_text(
        encoding="utf-8"
    )
    rows = [json.loads(line) for line in audit_text.splitlines()]
    assert [row["outcome"] for row in rows] == [
        "COMMAND_RECEIVED",
        "COMMAND_REJECTED",
    ]
    assert rows[-1]["rejection_reason"]["rule"] == (
        "resource-cli-arguments-invalid"
    )
    assert secret not in audit_text
    assert "not-an-integer" not in audit_text


def test_cli_writes_only_under_research_root(tmp_path):
    server = {"name": "local", "kind": "local", "gpus": [{"type": "a6000", "count": 1}]}
    _run(tmp_path, "register", stdin=json.dumps(server))
    _seed_experiment(tmp_path)
    _run(tmp_path, "allocate", "--server", "local", "--pkg", "demo", "--exp", "P1")

    written = {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()}
    assert {
        "VERSION",
        "state/.lock",
        "state/current.json",
        "state/events.jsonl",
        "audit/actions.jsonl",
    } <= written
    assert any(path.startswith("interface/") for path in written)
    assert {path.split("/", 1)[0] for path in written} <= {
        "VERSION",
        "state",
        "audit",
        "interface",
    }


def test_concurrent_allocations_cannot_overbook(tmp_path):
    server = {
        "name": "local",
        "kind": "local",
        "gpus": [{"type": "a6000", "count": 1}],
    }
    assert _run(tmp_path, "register", stdin=json.dumps(server)).returncode == 0
    _seed_experiment(tmp_path)
    command = [
        sys.executable,
        str(CLI),
        "--research-root",
        str(tmp_path),
        "allocate",
        "--server",
        "local",
        "--pkg",
        "demo",
        "--exp",
        "P1",
        "--gpu-count",
        "1",
    ]
    processes = [
        subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for _ in range(2)
    ]
    outputs = [process.communicate(timeout=10) for process in processes]

    assert sorted(process.returncode for process in processes) == [0, 1], outputs
    events = [
        json.loads(line)
        for line in (tmp_path / "state" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    allocations = [
        event for event in events if event["event_type"] == "ResourceAllocationCreated"
    ]
    assert len(allocations) == 1
