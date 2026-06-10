"""CLI gate: apply.py is invocable as a script; lands only when human-gated + sound."""

import json
import subprocess
import sys
from pathlib import Path

CLI = Path(__file__).resolve().parents[2] / "skills" / "research-apply" / "scripts" / "apply.py"


def _run(args):
    return subprocess.run([sys.executable, str(CLI)] + args, capture_output=True, text=True)


def _stage(tmp_path):
    pdir = tmp_path / "p-1"
    pdir.mkdir()
    (pdir / "proposal.json").write_text(
        json.dumps({"finding": {}, "suggested_diff": "new rule X", "status": "STAGED"}))
    return pdir


def test_apply_cli_lands_with_human_and_sound(tmp_path):
    pdir = _stage(tmp_path)
    rules = tmp_path / "rules.md"
    rules.write_text("# rules\n")
    r = _run(["--proposal-dir", str(pdir), "--human-token", "alice-approved",
              "--jury-verdict", "SOUND", "--rules-path", str(rules)])
    assert r.returncode == 0, r.stderr
    assert "new rule X" in rules.read_text()
    assert json.loads((pdir / "proposal.json").read_text())["status"] == "LANDED"


def test_apply_cli_refuses_without_human_token(tmp_path):
    pdir = _stage(tmp_path)
    rules = tmp_path / "rules.md"
    rules.write_text("# rules\n")
    r = _run(["--proposal-dir", str(pdir), "--human-token", "",
              "--jury-verdict", "SOUND", "--rules-path", str(rules)])
    assert r.returncode != 0
    assert "new rule X" not in rules.read_text()
