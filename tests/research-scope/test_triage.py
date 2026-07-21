"""Stage-2c: an agent proposal lands pending; Scope writes are PM-decision-gated."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "research-scope" / "scripts"))
import triage  # noqa: E402
from lib.research_state import ResearchPaths  # noqa: E402
from tests.scope_fixtures import direction_node, proposal_item  # noqa: E402


USER = {"type": "user", "id": "test-pm"}


def _item(*, version=1):
    node = direction_node(
        node_id="dir/x",
        version=version,
        source=f"triage:tr1:v{version}",
    )
    return proposal_item(
        node,
        op="revise",
        proposal_id="tr1",
    )


def _paths(tmp_path):
    return ResearchPaths.resolve(workspace=tmp_path)


def test_agent_proposal_lands_pending_without_committing_scope(tmp_path):
    paths = _paths(tmp_path)
    triage.propose(paths, _item())
    pending = triage.pending(paths)
    assert [p["id"] for p in pending] == ["tr1"]
    assert pending[0]["proposal_hash"]
    assert paths.current.exists()
    assert '"direction": {}' in paths.current.read_text(encoding="utf-8")


def test_accept_records_bound_proposal_snapshot(tmp_path):
    paths = _paths(tmp_path)
    triage.propose(paths, _item())
    visible_hash = triage.pending(paths)[0]["proposal_hash"]
    triage.dispose(paths, "tr1", "ACCEPTED", visible_hash, actor=USER)
    records = triage._read(paths)
    accepted = records[-1]
    assert accepted["status"] == "accepted"
    assert accepted["proposal_hash"] == records[0]["proposal_hash"]
    assert accepted["accepted_proposal"]["proposed_node"]["id"] == "dir/x"


def test_repeated_accept_keeps_original_proposal_snapshot(tmp_path):
    paths = _paths(tmp_path)
    triage.propose(paths, _item())
    visible_hash = triage.pending(paths)[0]["proposal_hash"]
    triage.dispose(paths, "tr1", "ACCEPTED", visible_hash, actor=USER)
    triage.dispose(paths, "tr1", "ACCEPTED", visible_hash, actor=USER)
    records = triage._read(paths)
    accepted = records[-1]
    assert accepted["status"] == "accepted"
    assert accepted["proposal_hash"] == records[0]["proposal_hash"]
    assert accepted["accepted_proposal"]["proposed_node"]["id"] == "dir/x"


def test_reject_archives_and_leaves_scope_aggregates_untouched(tmp_path):
    paths = _paths(tmp_path)
    triage.propose(paths, _item())
    visible_hash = triage.pending(paths)[0]["proposal_hash"]
    triage.dispose(paths, "tr1", "REJECTED", visible_hash, actor=USER)
    assert triage.pending(paths) == []
    assert '"direction": {}' in paths.current.read_text(encoding="utf-8")


def test_reproposal_same_id_replaces_pending_view(tmp_path):
    paths = _paths(tmp_path)
    original = _item()
    revised = _item(version=2)
    revised["change"] = "revise dir/x with the PM-requested stricter gate"
    revised["rationale"] = "The PM requested a stricter success gate."

    triage.propose(paths, original)
    original_hash = triage.pending(paths)[0]["proposal_hash"]
    triage.propose(paths, revised)

    pending = triage.pending(paths)
    assert len(pending) == 1
    assert pending[0]["id"] == "tr1"
    assert pending[0]["proposed_node"] == revised["proposed_node"]
    assert pending[0]["proposal_hash"] == triage.proposal_hash(revised)
    assert pending[0]["proposal_hash"] != original_hash


def test_disposition_requires_the_visible_proposal_hash(tmp_path):
    paths = _paths(tmp_path)
    triage.propose(paths, _item())

    try:
        triage.dispose(
            paths,
            "tr1",
            "ACCEPTED",
            "0" * 64,
            actor=USER,
        )
        assert False, "expected hash-bound disposition rejection"
    except Exception as exc:
        assert getattr(exc, "rule", "") == "proposal-hash-mismatch"

    assert [row["id"] for row in triage.pending(paths)] == ["tr1"]
    assert "proposal-hash-mismatch" in paths.audit_actions.read_text(encoding="utf-8")


@pytest.mark.parametrize("decision", ["ACCEPTED", "REJECTED"])
def test_disposition_without_explicit_user_actor_is_rejected_and_audited(
    tmp_path,
    decision,
):
    paths = _paths(tmp_path)
    triage.propose(paths, _item())
    visible_hash = triage.pending(paths)[0]["proposal_hash"]

    try:
        triage.dispose(paths, "tr1", decision, visible_hash)
        assert False, "expected implicit agent disposition to be rejected"
    except Exception as exc:
        assert getattr(exc, "rule", "") == "proposal-disposition-user-required"

    assert [row["id"] for row in triage.pending(paths)] == ["tr1"]
    audit = paths.audit_actions.read_text(encoding="utf-8")
    assert "proposal-disposition-user-required" in audit
