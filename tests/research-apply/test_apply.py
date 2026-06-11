"""Stage-3: a staged self-learning proposal can only land via a distinct human action + a clearing
jury verdict. The proposer (research-reflect) is never the applier (research-apply). Landing goes
through research-op --target rule (the single rule entry), into data/rules.js."""

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "skills" / "research-apply" / "scripts"))
import apply  # noqa: E402


def _staged(tmp_path):
    d = tmp_path / "pending" / "p-1"
    d.mkdir(parents=True)
    (d / "proposal.json").write_text(json.dumps(
        {"finding": {"kind": "CONSECUTIVE_VALIDATION_FAILURE"}, "suggested_diff": "cap retries at 3", "status": "STAGED"}),
        encoding="utf-8")
    return d


def _project(tmp_path, monkeypatch):
    (tmp_path / "research_html" / "data").mkdir(parents=True)
    (tmp_path / "research_html" / "data" / "rules.js").write_text("window.RESEARCH_RULES = [];\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RESEARCH_RUNTIME_ROOT", str(tmp_path / "outputs"))


def _rules(tmp_path):
    text = (tmp_path / "research_html" / "data" / "rules.js").read_text()
    return json.loads(text[len("window.RESEARCH_RULES = "):].rstrip().rstrip(";"))


def test_proposal_cannot_land_without_human_action(tmp_path, monkeypatch):
    _project(tmp_path, monkeypatch)
    with pytest.raises(PermissionError):
        apply.apply(_staged(tmp_path), human_token=None, jury_verdict="SOUND")
    assert _rules(tmp_path) == []  # nothing landed


def test_unsound_jury_blocks_landing(tmp_path, monkeypatch):
    _project(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        apply.apply(_staged(tmp_path), human_token="user-ack", jury_verdict="UNSOUND")
    assert _rules(tmp_path) == []


def test_human_action_plus_sound_jury_lands(tmp_path, monkeypatch):
    _project(tmp_path, monkeypatch)
    apply.apply(_staged(tmp_path), human_token="user-ack", jury_verdict="SOUND")
    rows = _rules(tmp_path)
    assert rows and rows[0]["level"] == "project" and rows[0]["origin"] == "apply"
    assert "cap retries at 3" in rows[0]["text"]
