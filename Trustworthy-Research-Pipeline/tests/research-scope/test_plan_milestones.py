import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "skills" / "research-scope" / "scripts"))

import plan_milestones  # noqa: E402
import scope_ssot  # noqa: E402
import triage  # noqa: E402


def _direction_node():
    return {
        "id": "dir/retrieval-v2",
        "level": "direction",
        "parents": ["project/main"],
        "version": 2,
        "status": "active",
        "yardstick": {
            "hypothesis": "Contrastive retrieval improves zero-shot Recall@1",
            "metric": {"name": "Recall@1", "dir": "higher"},
            "baselines": ["CLIP zero-shot = 42.3"],
            "success_predicate": "Recall@1 >= 48",
        },
        "provenance": "accepted:t1",
    }


def _write_direction(log):
    scope_ssot.propose_transition(
        _direction_node(),
        op="create",
        gate="user+xmodel-audit",
        log_path=log,
        trigger="accepted direction",
        cause="PM accepted direction",
    )


def test_plan_milestones_writes_pending_task_proposals_only(tmp_path):
    transitions = tmp_path / "var" / "research" / "_scope" / "transitions.jsonl"
    triage_log = tmp_path / "var" / "research" / "_scope" / "triage.jsonl"
    _write_direction(transitions)

    rc = plan_milestones.main([
        "--direction-id", "dir/retrieval-v2",
        "--transitions", str(transitions),
        "--triage", str(triage_log),
    ])

    assert rc == 0
    pending = triage.pending(triage_log)
    assert len(pending) == 5
    assert all(item["level"] == "task" for item in pending)
    assert all(item["gate"] == "agent+async-ack" for item in pending)
    assert pending[0]["proposed_node"]["parents"] == ["dir/retrieval-v2"]
    assert pending[0]["proposed_node"]["yardstick"]["autonomy_level"] == "checkpoints"

    # The script proposes only; the committed transition log still has just the Direction.
    records = scope_ssot.read_log(transitions)
    assert [r["node_id"] for r in records] == ["dir/retrieval-v2"]


def test_plan_milestones_dry_run_does_not_write_triage(tmp_path, capsys):
    transitions = tmp_path / "var" / "research" / "_scope" / "transitions.jsonl"
    triage_log = tmp_path / "var" / "research" / "_scope" / "triage.jsonl"
    _write_direction(transitions)

    rc = plan_milestones.main([
        "--direction-id", "dir/retrieval-v2",
        "--transitions", str(transitions),
        "--triage", str(triage_log),
        "--dry-run",
    ])

    assert rc == 0
    proposals = json.loads(capsys.readouterr().out)
    assert len(proposals) == 5
    assert not triage_log.exists()


def test_plan_milestones_rejects_pending_only_direction(tmp_path):
    triage_log = tmp_path / "var" / "research" / "_scope" / "triage.jsonl"
    triage_log.parent.mkdir(parents=True)
    triage_log.write_text('{"id":"t1","level":"direction","status":"pending"}\n', encoding="utf-8")

    with pytest.raises(SystemExit, match="Committed direction not found"):
        plan_milestones.main([
            "--direction-id", "dir/retrieval-v2",
            "--transitions", str(tmp_path / "var" / "research" / "_scope" / "transitions.jsonl"),
            "--triage", str(triage_log),
        ])
