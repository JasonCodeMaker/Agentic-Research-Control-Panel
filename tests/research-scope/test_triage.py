"""Stage-2c: an agent-proposed scope change lands as a pending Triage item — the SSOT is PM-write-only."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "research-scope" / "scripts"))
import triage  # noqa: E402


def _item():
    return {"id": "tr1", "node_id": "dir/x", "op": "revise", "gate": "user+xmodel-audit",
            "cause": "metric saturated"}


def test_agent_proposal_lands_pending_and_leaves_ssot_untouched(tmp_path):
    triage_log = tmp_path / "triage.jsonl"
    scope_log = tmp_path / "_scope" / "transitions.jsonl"
    triage.propose(triage_log, _item())
    pending = triage.pending(triage_log)
    assert [p["id"] for p in pending] == ["tr1"]
    assert not scope_log.exists()  # the agent cannot mutate the SSOT — only propose


def test_reject_archives_and_leaves_ssot_untouched(tmp_path):
    triage_log = tmp_path / "triage.jsonl"
    scope_log = tmp_path / "_scope" / "transitions.jsonl"
    triage.propose(triage_log, _item())
    triage.dispose(triage_log, "tr1", "reject")
    assert triage.pending(triage_log) == []        # no longer pending
    assert not scope_log.exists()                  # rejection never touches the SSOT
