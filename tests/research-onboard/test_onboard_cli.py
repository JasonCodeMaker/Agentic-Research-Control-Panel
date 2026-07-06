"""research-onboard CLI: the SKILL drives onboard.py via Bash(python3 *)."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "skills" / "research-onboard" / "scripts"))

import onboard  # noqa: E402
from tests.scope_fixtures import project_spec  # noqa: E402


def test_cli_detect(tmp_path, capsys):
    (tmp_path / "src").mkdir()
    rc = onboard.main(["detect", "--cwd", str(tmp_path)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["state"] == "existing"


def test_cli_scaffold(tmp_path, capsys):
    rc = onboard.main(["scaffold", "--cwd", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "src").is_dir()
    out = json.loads(capsys.readouterr().out)
    assert "src" in out["created_dirs"]
    assert out["claude_md_written"] is True
    assert out["agents_md_written"] is True
    assert (tmp_path / "CLAUDE.md").exists()
    assert (tmp_path / "AGENTS.md").exists()


def test_cli_build_proposal(tmp_path, capsys):
    spec = project_spec()
    rc = onboard.main([
        "build-proposal", "--node-id", "project/cifar10",
        "--spec", json.dumps(spec), "--source", "read:README.md",
    ])
    assert rc == 0
    item = json.loads(capsys.readouterr().out)
    assert item["level"] == "project"
    assert item["gate"] == "USER_ONLY"


def test_cli_has_project_scope_false(tmp_path, capsys):
    rc = onboard.main(["has-project-scope", "--transitions", str(tmp_path / "t.jsonl")])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["has_project_scope"] is False
