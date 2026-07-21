"""CLI gate: triage.py is invocable as a script (propose -> pending -> dispose)."""

import json
import subprocess
import sys
from pathlib import Path

from tests.scope_fixtures import direction_node, proposal_item

CLI = Path(__file__).resolve().parents[2] / "skills" / "research-scope" / "scripts" / "triage.py"


def _run(args):
    return subprocess.run([sys.executable, str(CLI)] + args, capture_output=True, text=True)


def test_triage_cli_propose_pending_dispose(tmp_path):
    item = proposal_item(
        direction_node(
            node_id="dir/cli",
            source="triage:t1",
        ),
        proposal_id="t1",
    )
    base = ["--workspace", str(tmp_path)]
    r = _run([*base, "propose", "--item", json.dumps(item)])
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "t1"

    r = _run([*base, "pending"])
    assert r.returncode == 0, r.stderr
    pending = json.loads(r.stdout)
    assert [i["id"] for i in pending] == ["t1"]
    visible_hash = pending[0]["proposal_hash"]

    r = _run(
        [
            *base,
            "dispose",
            "--id",
            "t1",
            "--decision",
            "ACCEPTED",
            "--proposal-hash",
            visible_hash,
        ]
    )
    assert r.returncode == 2
    assert json.loads(r.stdout)["rule"] == "proposal-disposition-user-required"

    r = _run(
        [
            *base,
            "dispose",
            "--id",
            "t1",
            "--decision",
            "ACCEPTED",
            "--proposal-hash",
            visible_hash,
            "--actor-type",
            "user",
            "--actor-id",
            "test-pm",
        ]
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "accepted"

    r = _run([*base, "pending"])
    assert json.loads(r.stdout) == []
