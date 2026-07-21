"""Read fixtures for the deterministic verifier API.

Verdict persistence belongs to the governed research state or the producing
Experiment run.  This test therefore creates its JSON fixture locally instead
of exposing a second arbitrary-path writer from ``lib.verifier``.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
import verifier  # noqa: E402


def _verdict(**over):
    v = {"producer": "claude-opus", "judge": "gpt-4o", "scope_version": 1,
         "artifact_id": "exp-001", "result": "SOUND"}
    v.update(over)
    return v


def _write_verdict_fixture(verdicts_dir, verdict):
    record = {"verdict_id": "fixture-verdict", **verdict}
    path = verdicts_dir / f"{record['verdict_id']}.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return record


def test_round_trip_read_verdict(tmp_path):
    rec = _write_verdict_fixture(tmp_path, _verdict())
    assert verifier.read_verdict(tmp_path, rec["verdict_id"]) == rec


def test_verifier_exposes_no_standalone_persistence_writer():
    assert not hasattr(verifier, "write_verdict")
