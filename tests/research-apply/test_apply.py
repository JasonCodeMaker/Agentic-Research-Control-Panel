"""Stage-3: a staged self-learning proposal can only land via a distinct human action + a clearing
jury verdict. The proposer (research-reflect) is never the applier (research-apply)."""

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


def test_proposal_cannot_land_without_human_action(tmp_path):
    rules = tmp_path / "project-rules.md"
    rules.write_text("# rules\n", encoding="utf-8")
    with pytest.raises(PermissionError):
        apply.apply(_staged(tmp_path), human_token=None, jury_verdict="SOUND", rules_path=rules)
    assert rules.read_text() == "# rules\n"  # nothing landed


def test_unsound_jury_blocks_landing(tmp_path):
    rules = tmp_path / "project-rules.md"
    rules.write_text("# rules\n", encoding="utf-8")
    with pytest.raises(ValueError):
        apply.apply(_staged(tmp_path), human_token="user-ack", jury_verdict="UNSOUND", rules_path=rules)
    assert rules.read_text() == "# rules\n"


def test_human_action_plus_sound_jury_lands(tmp_path):
    rules = tmp_path / "project-rules.md"
    rules.write_text("# rules\n", encoding="utf-8")
    apply.apply(_staged(tmp_path), human_token="user-ack", jury_verdict="SOUND", rules_path=rules)
    assert "cap retries at 3" in rules.read_text()
