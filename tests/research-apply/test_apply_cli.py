"""CLI gate: apply.py is invocable as a script; lands only when human-gated + sound."""

import json
import os
import subprocess
import sys
from pathlib import Path

CLI = Path(__file__).resolve().parents[2] / "skills" / "research-apply" / "scripts" / "apply.py"


def _run(args, cwd, env_outputs):
    env = dict(os.environ, RESEARCH_RUNTIME_ROOT=str(env_outputs))
    return subprocess.run([sys.executable, str(CLI)] + args, cwd=cwd,
                          capture_output=True, text=True, env=env)


def _stage(tmp_path):
    pdir = tmp_path / "p-1"
    pdir.mkdir()
    (pdir / "proposal.json").write_text(
        json.dumps({"finding": {}, "suggested_diff": "new rule X", "status": "STAGED"}))
    (tmp_path / "research_html" / "data").mkdir(parents=True)
    (tmp_path / "research_html" / "data" / "rules.js").write_text("window.RESEARCH_RULES = [];\n")
    return pdir


def _rules_text(tmp_path):
    return (tmp_path / "research_html" / "data" / "rules.js").read_text()


def test_apply_cli_lands_with_human_and_sound(tmp_path):
    pdir = _stage(tmp_path)
    r = _run(["--proposal-dir", str(pdir), "--human-token", "alice-approved",
              "--jury-verdict", "SOUND"], cwd=tmp_path, env_outputs=tmp_path / "outputs")
    assert r.returncode == 0, r.stderr + r.stdout
    assert "new rule X" in _rules_text(tmp_path)
    assert json.loads((pdir / "proposal.json").read_text())["status"] == "LANDED"


def test_apply_cli_refuses_without_human_token(tmp_path):
    pdir = _stage(tmp_path)
    r = _run(["--proposal-dir", str(pdir), "--human-token", "",
              "--jury-verdict", "SOUND"], cwd=tmp_path, env_outputs=tmp_path / "outputs")
    assert r.returncode != 0
    assert "new rule X" not in _rules_text(tmp_path)
