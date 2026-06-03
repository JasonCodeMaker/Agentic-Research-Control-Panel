"""CLI gate: reflect.py is invocable as a script and stages a proposal for a doom-loop."""

import json
import subprocess
import sys
from pathlib import Path

CLI = Path(__file__).resolve().parents[2] / "skills" / "research-reflect" / "scripts" / "reflect.py"


def _run(args):
    return subprocess.run([sys.executable, str(CLI)] + args, capture_output=True, text=True)


def test_reflect_cli_stages_doom_loop_proposal(tmp_path):
    actions = tmp_path / "_actions.jsonl"
    rows = [{"op": "insert", "target": "methodsTried", "rule": "x", "validation": "rejected"} for _ in range(3)]
    actions.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    pending = tmp_path / "pending"

    r = _run(["--actions", str(actions), "--pending-dir", str(pending), "--threshold", "3"])
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert len(out["staged"]) == 1
    assert (pending / out["staged"][0] / "proposal.json").exists()
