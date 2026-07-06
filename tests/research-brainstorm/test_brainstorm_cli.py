"""research-brainstorm CLI: the SKILL drives brainstorm.py via Bash(python3 *)."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "skills" / "research-brainstorm" / "scripts"))

import brainstorm  # noqa: E402
from tests.scope_fixtures import direction_spec  # noqa: E402


def test_cli_add_then_list(tmp_path, capsys):
    rc = brainstorm.main(["add", "--root", str(tmp_path), "--title", "Idea A", "--idea", "do A"])
    assert rc == 0
    added = json.loads(capsys.readouterr().out)
    assert added["detailPath"].startswith("brainstorm/")
    assert added["detailPath"].endswith(f"-{added['id']}.html")
    rc = brainstorm.main(["list", "--root", str(tmp_path)])
    assert rc == 0
    items = json.loads(capsys.readouterr().out)
    assert len(items) == 1
    assert items[0]["title"] == "Idea A"
    assert items[0]["detailPath"] == added["detailPath"]
    assert (tmp_path / added["detailPath"]).exists()


def test_cli_remove(tmp_path, capsys):
    brainstorm.main(["add", "--root", str(tmp_path), "--title", "Idea", "--idea", "x", "--id", "bs-1"])
    capsys.readouterr()
    rc = brainstorm.main(["remove", "--root", str(tmp_path), "--id", "bs-1"])
    assert rc == 0
    capsys.readouterr()
    brainstorm.main(["list", "--root", str(tmp_path)])
    assert json.loads(capsys.readouterr().out) == []


def test_cli_build_proposal(tmp_path, capsys):
    spec = direction_spec()
    rc = brainstorm.main([
        "build-proposal", "--node-id", "dir/x", "--parent-project-id", "project/main",
        "--spec", json.dumps(spec), "--source", "brainstorms:bs-1",
        "--source-brainstorms", json.dumps(["bs-1"]),
    ])
    assert rc == 0
    item = json.loads(capsys.readouterr().out)
    assert item["level"] == "direction"
    assert item["gate"] == "USER_CROSS_MODEL_AUDIT"
    assert item["source_brainstorms"] == ["bs-1"]


def test_cli_direction_ready(tmp_path, capsys):
    spec = {"hypothesis": "h", "metric": "m", "baselines": ["b"], "success_gate": "p"}
    rc = brainstorm.main(["direction-ready", "--spec", json.dumps(spec)])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["ready"] is True
