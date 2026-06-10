"""Item 5 TDD gate: the verifier persists a structured verdict record, and rejects an incomplete or
self-judged verdict before writing anything.

Ledger 1 trust-cross-model-jury ("persists a structured verdict record") / Ledger 3 verdict record
(missing producer/judge/scope/artifact or producer == judge is rejected).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
import verifier  # noqa: E402
from verifier import VerifierError  # noqa: E402


def _verdict(**over):
    v = {"producer": "claude-opus", "judge": "gpt-4o", "scope_version": 1,
         "artifact_id": "exp-001", "result": "SOUND"}
    v.update(over)
    return v


def test_write_verdict_persists_required_fields(tmp_path):
    rec = verifier.write_verdict(tmp_path, _verdict())
    path = tmp_path / f"{rec['verdict_id']}.json"
    assert path.exists()
    assert all(rec[f] == _verdict()[f] for f in ("producer", "judge", "scope_version",
                                                 "artifact_id", "result"))


def test_missing_required_field_rejected_before_write(tmp_path):
    bad = _verdict()
    del bad["artifact_id"]
    with pytest.raises(VerifierError):
        verifier.write_verdict(tmp_path, bad)
    assert list(tmp_path.glob("*.json")) == []  # reject-before-write: nothing on disk


def test_producer_equals_judge_rejected_before_write(tmp_path):
    with pytest.raises(VerifierError):
        verifier.write_verdict(tmp_path, _verdict(judge="claude-opus"))
    assert list(tmp_path.glob("*.json")) == []


def test_round_trip_read_verdict(tmp_path):
    rec = verifier.write_verdict(tmp_path, _verdict())
    assert verifier.read_verdict(tmp_path, rec["verdict_id"]) == rec
