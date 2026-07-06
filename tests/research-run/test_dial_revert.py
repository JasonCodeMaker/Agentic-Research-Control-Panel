"""Stage-2c: a direction/project scope transition auto-reverts affected Tasks to Supervised + locked."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "research-run" / "scripts"))
import dial  # noqa: E402


def _tasks():
    return [
        {"id": "t1", "control_mode": "AUTONOMOUS", "locked": False},
        {"id": "t2", "control_mode": "DEFERRED", "locked": False},
        {"id": "t3", "control_mode": "SUPERVISED", "locked": False},
    ]


def test_direction_transition_reverts_affected_tasks():
    txn = {"level": "direction", "op": "revise", "dial_revert": ["t1", "t2"]}
    out = {t["id"]: t for t in dial.revert_on_scope_change(_tasks(), txn)}
    assert out["t1"]["control_mode"] == "SUPERVISED" and out["t1"]["locked"] is True
    assert out["t2"]["control_mode"] == "SUPERVISED" and out["t2"]["locked"] is True
    assert out["t3"]["control_mode"] == "SUPERVISED"  # untouched (was already SUPERVISED)


def test_task_level_transition_does_not_revert():
    txn = {"level": "task", "op": "revise", "dial_revert": ["t1"]}
    assert dial.revert_on_scope_change(_tasks(), txn) == _tasks()
