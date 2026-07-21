"""research-onboard CLI: the SKILL drives onboard.py via Bash(python3 *)."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "skills" / "research-onboard" / "scripts"))

import onboard  # noqa: E402
from lib.research_state import EventStore, ResearchPaths  # noqa: E402
from tests.scope_fixtures import project_spec  # noqa: E402


def _initialize(tmp_path):
    EventStore(ResearchPaths.resolve(workspace=tmp_path)).initialize()


def test_cli_detect(tmp_path, capsys):
    (tmp_path / "src").mkdir()
    _initialize(tmp_path)
    rc = onboard.main(["--workspace", str(tmp_path), "detect"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["state"] == "existing"


def test_cli_scaffold(tmp_path, capsys):
    _initialize(tmp_path)
    rc = onboard.main(["--workspace", str(tmp_path), "scaffold"])
    assert rc == 0
    assert (tmp_path / "src").is_dir()
    out = json.loads(capsys.readouterr().out)
    assert "src" in out["created_dirs"]
    assert "claude_md_written" not in out
    assert "agents_md_written" not in out
    assert not (tmp_path / "CLAUDE.md").exists()
    assert not (tmp_path / "AGENTS.md").exists()


def test_cli_scaffold_requires_research_init(tmp_path, capsys):
    rc = onboard.main(["--workspace", str(tmp_path), "scaffold"])
    assert rc == 2
    out = json.loads(capsys.readouterr().out)
    assert "research-init" in out["detail"]
    assert not (tmp_path / ".research").exists()


def test_cli_build_proposal(tmp_path, capsys):
    spec = project_spec()
    rc = onboard.main([
        "--workspace", str(tmp_path),
        "build-proposal", "--node-id", "project/cifar10",
        "--spec", json.dumps(spec), "--source", "read:README.md",
    ])
    assert rc == 0
    item = json.loads(capsys.readouterr().out)
    assert item["level"] == "project"
    assert item["gate"] == "USER_ONLY"


def test_cli_has_project_scope_false(tmp_path, capsys):
    _initialize(tmp_path)
    rc = onboard.main([
        "--workspace", str(tmp_path),
        "has-project-scope",
    ])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["has_project_scope"] is False


def test_cli_prior_knowledge_returns_note_ref(tmp_path, capsys):
    _initialize(tmp_path)
    rc = onboard.main([
        "--workspace", str(tmp_path),
        "write-prior-knowledge",
        "--content", "# Prior knowledge\n",
    ])
    assert rc == 0
    note_ref = json.loads(capsys.readouterr().out)["note_ref"]
    assert note_ref["uri"] == f"state/notes/{note_ref['sha256']}.md"
