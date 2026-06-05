"""CLI gate: banlist.py is invocable as a script (allowed filter + reopen prune)."""

import json
import subprocess
import sys
from pathlib import Path

CLI = Path(__file__).resolve().parents[2] / "skills" / "research-ideate" / "scripts" / "banlist.py"


def _run(args):
    return subprocess.run([sys.executable, str(CLI)] + args, capture_output=True, text=True)


def test_banlist_cli_allowed_and_reopen(tmp_path):
    bfile = tmp_path / "banlist.json"
    bfile.write_text(json.dumps([{"id": "idea-a", "failed_on_metric": "recall"}]))

    r = _run(["allowed", "--banlist", str(bfile), "--candidates", json.dumps(["idea-a", "idea-b"])])
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == ["idea-b"]

    r = _run(["reopen", "--banlist", str(bfile), "--reopened", json.dumps(["idea-a"])])
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == []
    assert json.loads(bfile.read_text()) == []
