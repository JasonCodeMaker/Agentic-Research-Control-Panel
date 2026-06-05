"""CLI gate: triage.py is invocable as a script (propose -> pending -> dispose)."""

import json
import subprocess
import sys
from pathlib import Path

CLI = Path(__file__).resolve().parents[2] / "skills" / "research-scope" / "scripts" / "triage.py"


def _run(args):
    return subprocess.run([sys.executable, str(CLI)] + args, capture_output=True, text=True)


def test_triage_cli_propose_pending_dispose(tmp_path):
    log = tmp_path / "triage.jsonl"
    item = {"id": "t1", "kind": "scope-change", "detail": "revise direction metric"}
    r = _run(["propose", "--log", str(log), "--item", json.dumps(item)])
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "t1"

    r = _run(["pending", "--log", str(log)])
    assert r.returncode == 0, r.stderr
    assert [i["id"] for i in json.loads(r.stdout)] == ["t1"]

    r = _run(["dispose", "--log", str(log), "--id", "t1", "--decision", "accept"])
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "accepted"

    r = _run(["pending", "--log", str(log)])
    assert json.loads(r.stdout) == []
