"""Stage-2c: an Async/Autonomous tick must write a typed PACK bundle for the absent reader."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "research-run" / "scripts"))
import pack  # noqa: E402


def _bundle():
    return {
        "attempted": "ran sweep over lr",
        "found": "lr=3e-4 best",
        "hypothesis_state": "supported",
        "next_action": "scale to full data",
        "blocking_decision": "none",
    }


def test_incomplete_pack_is_rejected(tmp_path):
    log = tmp_path / "pack.jsonl"
    with pytest.raises(ValueError):
        pack.write_pack(log, {"attempted": "x"})  # missing required fields
    assert not log.exists()  # reject-before-write


def test_complete_pack_appends_and_latest_is_tail(tmp_path):
    log = tmp_path / "pack.jsonl"
    pack.write_pack(log, _bundle())
    second = {**_bundle(), "next_action": "write paper"}
    pack.write_pack(log, second)
    assert pack.latest(log)["next_action"] == "write paper"
