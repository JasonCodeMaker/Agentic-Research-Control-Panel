"""The research-op read surface stays on structured state, never HTML."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "skills" / "research-op" / "scripts" / "research_op.py"
sys.path.insert(0, str(ROOT))

from lib.research_state import EventStore, ResearchPaths  # noqa: E402


def _run(workspace, *args):
    return subprocess.run(
        [
            sys.executable,
            str(CLI),
            *args,
            "--workspace",
            str(workspace),
            "--research-root",
            ".research",
        ],
        capture_output=True,
        text=True,
    )


def test_show_context_history_and_audit_queries(tmp_path):
    paths = ResearchPaths.resolve(workspace=tmp_path, research_root=".research")
    store = EventStore(paths)
    store.initialize()
    EventStore(paths, migration_mode=True).commit(
        event_type="AggregateImported",
        aggregate_type="direction",
        aggregate_id="direction/pkg-1",
        payload={
            "record": {
                "id": "direction/pkg-1",
                "level": "direction",
                "parents": ["project/test"],
                "version": 1,
                "status": "ACTIVE",
                "source": "test",
                "spec": {},
            },
            "migration": {"source": "test-fixture"},
        },
        actor={"type": "system", "id": "test"},
        idempotency_key="direction",
    )
    package_event = store.commit(
        event_type="AggregateUpserted",
        aggregate_type="package",
        aggregate_id="pkg-1",
        payload={
            "record": {
                "id": "pkg-1",
                "lifecycle": "ACTIVE",
                "phase": "CONTEXT_LOADED",
                "blocker": None,
                "direction_id": "direction/pkg-1",
                "sourceVersion": 1,
                "sourceChange": "test",
                "sourceExperiments": [
                    {"id": "exp-1", "version": 1, "source": "test"}
                ],
            }
        },
        actor={"type": "system", "id": "test"},
        idempotency_key="package",
        expected_version=0,
    )
    EventStore(paths, migration_mode=True).commit(
        event_type="AggregateUpserted",
        aggregate_type="experiment",
        aggregate_id="exp-1",
        payload={
            "record": {
                "id": "exp-1",
                "package_id": "pkg-1",
                "direction_id": "direction/pkg-1",
                "scope_status": "ACTIVE",
                "scope_version": 1,
                "scope_source": "test",
                "scope_confirmation": "CONFIRMED",
                "confirmed_direction_version": 1,
                "status": "PLANNED",
                "spec": {
                    "purpose": "Exercise the bounded context query.",
                    "config_ref": "configs/test.yaml",
                    "gate": "query includes the selected Experiment",
                    "control_mode": "CHECKPOINTED",
                },
            }
        },
        actor={"type": "system", "id": "test"},
        idempotency_key="experiment",
        expected_version=0,
    )

    shown = _run(tmp_path, "show", "package", "pkg-1")
    context = _run(tmp_path, "context", "pkg-1")
    full_context = _run(tmp_path, "context", "pkg-1", "--full")
    history = _run(tmp_path, "history", "package/pkg-1")
    audit = _run(tmp_path, "audit", package_event["command_id"])

    for result in (shown, context, full_context, history, audit):
        assert result.returncode == 0, result.stdout + result.stderr
        payload = json.loads(result.stdout)
        assert payload["source_seq"] == 3
        assert payload["source_hash"]
    assert json.loads(shown.stdout)["data"]["id"] == "pkg-1"
    context_data = json.loads(context.stdout)["data"]
    assert context_data["view"] == "compact"
    assert len(context.stdout) <= 4001
    assert {
        experiment["id"]
        for experiment in context_data["selection"]["experiments"]
    } == {"exp-1"}
    assert "stamp" in json.loads(full_context.stdout)["data"]
    assert len(json.loads(history.stdout)["data"]) == 1
    assert {
        row["outcome"] for row in json.loads(audit.stdout)["data"]
    } == {"COMMAND_COMMITTED"}


def test_queries_do_not_require_or_create_interface(tmp_path):
    paths = ResearchPaths.resolve(workspace=tmp_path, research_root=".research")
    EventStore(paths).initialize()

    shown = _run(tmp_path, "show", "paper")

    assert shown.returncode == 0, shown.stdout + shown.stderr
    assert json.loads(shown.stdout)["data"] == {}
    assert not (tmp_path / "research_html").exists()
    assert not paths.interface.exists() or not any(paths.interface.iterdir())
