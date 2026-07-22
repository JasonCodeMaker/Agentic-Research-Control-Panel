"""research-brainstorm CLI: the SKILL drives brainstorm.py via Bash(python3 *)."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "skills" / "research-brainstorm" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "research-package" / "scripts"))

import brainstorm  # noqa: E402
import draft_package  # noqa: E402
from lib.interface import build_interface  # noqa: E402
from lib.research_state import ResearchPaths  # noqa: E402
from tests.scope_fixtures import direction_spec  # noqa: E402


def test_cli_add_then_list(tmp_path, capsys):
    rc = brainstorm.main(["add", "--workspace", str(tmp_path), "--title", "Idea A", "--idea", "do A"])
    assert rc == 0
    added = json.loads(capsys.readouterr().out)
    assert added["detailPath"].endswith(f"-{added['id']}.html")
    assert added["detailPath"].startswith("brainstorm/")
    rc = brainstorm.main(["list", "--workspace", str(tmp_path)])
    assert rc == 0
    items = json.loads(capsys.readouterr().out)
    assert len(items) == 1
    assert items[0]["title"] == "Idea A"
    assert items[0]["detailPath"] == added["detailPath"]
    build_interface(ResearchPaths.resolve(workspace=tmp_path, environ={}))
    assert (tmp_path / ".research" / "interface" / added["detailPath"]).is_file()


def test_cli_add_and_revise_document_body(tmp_path, capsys):
    first = tmp_path / "first.html"
    second = tmp_path / "second.html"
    first.write_text("<section><h2>Initial draft</h2><p>v1</p></section>", encoding="utf-8")
    second.write_text("<section><h2>Refined draft</h2><p>v2</p></section>", encoding="utf-8")
    snapshot = [{"label": "Core question", "value": "Does it transfer?"}]

    rc = brainstorm.main([
        "add", "--workspace", str(tmp_path), "--id", "doc-one",
        "--title", "Document one", "--idea", "Broad direction",
        "--abstract", "Initial TLDR", "--snapshot", json.dumps(snapshot),
        "--body-file", str(first),
    ])
    assert rc == 0
    added = json.loads(capsys.readouterr().out)

    rc = brainstorm.main([
        "revise", "--workspace", str(tmp_path), "--id", "doc-one",
        "--abstract", "Audited TLDR", "--body-file", str(second),
    ])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["revised"] is True

    build_interface(ResearchPaths.resolve(workspace=tmp_path, environ={}))
    rendered = (
        tmp_path / ".research" / "interface" / added["detailPath"]
    ).read_text(encoding="utf-8")
    assert "Audited TLDR" in rendered
    assert "Refined draft" in rendered
    assert "Initial draft" not in rendered
    assert "Revision 2" in rendered


def test_cli_remove(tmp_path, capsys):
    brainstorm.main(["add", "--workspace", str(tmp_path), "--title", "Idea", "--idea", "x", "--id", "bs-1"])
    capsys.readouterr()
    rc = brainstorm.main(["remove", "--workspace", str(tmp_path), "--id", "bs-1"])
    assert rc == 0
    capsys.readouterr()
    brainstorm.main(["list", "--workspace", str(tmp_path)])
    assert json.loads(capsys.readouterr().out) == []


def test_cli_delete_archived_duplicate(tmp_path, capsys):
    brainstorm.main(["add", "--workspace", str(tmp_path), "--title", "Idea", "--idea", "x", "--id", "bs-1"])
    capsys.readouterr()
    brainstorm.main(["remove", "--workspace", str(tmp_path), "--id", "bs-1"])
    capsys.readouterr()
    assert brainstorm.main([
        "delete", "--workspace", str(tmp_path), "--id", "bs-1",
        "--reason", "merged into canonical document", "--actor-id", "reviewer",
    ]) == 0
    capsys.readouterr()
    brainstorm.main(["list", "--workspace", str(tmp_path), "--include-archived"])
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


def test_cli_build_proposal_binds_the_reviewed_draft(tmp_path, capsys):
    brainstorm.main([
        "add", "--workspace", str(tmp_path), "--id", "draft-one",
        "--title", "Draft one", "--idea", "Refine before Scope",
    ])
    capsys.readouterr()
    draft_package.convert(
        ResearchPaths.resolve(workspace=tmp_path, environ={}),
        brainstorm_id="draft-one",
        package_id=None,
        actor_id="reviewer",
    )

    rc = brainstorm.main([
        "build-proposal", "--workspace", str(tmp_path),
        "--node-id", "dir/x", "--parent-project-id", "project/main",
        "--spec", json.dumps(direction_spec()),
        "--source", "draft-package:draft-one",
        "--source-package-id", "draft-one",
    ])
    assert rc == 0
    item = json.loads(capsys.readouterr().out)
    assert item["source_package"]["id"] == "draft-one"
    assert item["source_package"]["draft_revision"] == 1
    assert len(item["source_package"]["document_sha256"]) == 64


def test_cli_direction_ready(tmp_path, capsys):
    spec = {"hypothesis": "h", "metric": "m", "baselines": ["b"], "success_gate": "p"}
    rc = brainstorm.main(["direction-ready", "--spec", json.dumps(spec)])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["ready"] is True
