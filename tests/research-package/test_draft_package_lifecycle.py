"""Two-approval Brainstorm -> Draft Package -> active Package lifecycle."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
for candidate in (
    ROOT,
    ROOT / "lib",
    ROOT / "skills" / "research-op" / "scripts",
    ROOT / "skills" / "research-brainstorm" / "scripts",
    ROOT / "skills" / "research-package" / "scripts",
):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from lib.research_state import (  # noqa: E402
    CommandConflict,
    CommandRejected,
    EventStore,
    ResearchPaths,
    StateQuery,
)
import brainstorm  # noqa: E402
import draft_package  # noqa: E402
import management  # noqa: E402
import research_op  # noqa: E402
from tests.scope_fixtures import (  # noqa: E402
    commit_accepted_scope,
    direction_node,
    experiment_node,
    project_node,
)


ACTOR = {"type": "agent", "id": "test"}
USER = {"type": "user", "id": "test-pm"}


def _draft(paths: ResearchPaths, package_id: str = "package-one") -> dict:
    commit_accepted_scope(management, paths, project_node(), actor=ACTOR)
    brainstorm.add_brainstorm(
        paths,
        {
            "id": package_id,
            "title": "One governed proposal",
            "idea": "Refine an idea before it receives Package authority.",
            "document_html": (
                "<section><h2>Research question</h2>"
                "<p>Keep both approval boundaries explicit.</p></section>"
            ),
        },
    )
    brainstorm_record = StateQuery(paths).brainstorms()["data"]["items"][0]
    source_note = brainstorm_record["document_note"]
    result = draft_package.convert(
        paths,
        brainstorm_id=package_id,
        package_id=None,
        actor_id=USER["id"],
    )
    assert result["status"] == "converted"
    assert StateQuery(paths).brainstorms()["data"]["items"] == []
    package = StateQuery(paths).show("package", package_id)["data"]
    assert package["document_note"] == source_note
    assert package["lifecycle"] == "DRAFT"
    assert package["draftStatus"] == "REFINING"
    assert package["executionAuthorized"] is False
    assert [
        row["event_type"]
        for row in StateQuery(paths).history("brainstorm", package_id)["data"]
    ] == ["BrainstormCreated", "PackageDraftCreated"]
    return package


def _pending_finalization(
    paths: ResearchPaths,
    package_id: str = "package-one",
) -> tuple[dict, dict]:
    direction = direction_node(source=f"draft-package:{package_id}")
    experiment = experiment_node(source=f"draft-package:{package_id}")
    proposal = draft_package.build_finalization_proposal(
        paths,
        package_id=package_id,
        direction=direction,
        experiments=[experiment],
    )
    record, _ = management.submit_proposal(paths, proposal, actor=ACTOR)
    return proposal, record


def test_full_proposal_requires_atomic_package_finalize(tmp_path):
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    draft = _draft(paths)
    proposal, pending = _pending_finalization(paths)
    before = EventStore(paths).state()
    assert before["aggregates"]["direction"] == {}
    assert before["aggregates"]["experiment"] == {}

    with pytest.raises(
        CommandRejected,
        match="must be approved through package-finalize",
    ):
        management.dispose_proposal(
            paths,
            proposal["id"],
            "ACCEPTED",
            pending["proposal_hash"],
            actor=USER,
        )
    assert EventStore(paths).state() == before

    event_count = len(EventStore(paths).events())
    event = management.finalize_draft_package(
        paths,
        "package-one",
        proposal["id"],
        pending["proposal_hash"],
        actor=USER,
    )
    assert len(EventStore(paths).events()) == event_count + 1
    assert event["event_type"] == "PackageActivated"

    state = EventStore(paths).state()
    package = state["aggregates"]["package"]["package-one"]
    direction_id = direction_node()["id"]
    experiment_id = experiment_node()["id"]
    assert (
        package["lifecycle"],
        package["phase"],
        package["draftStatus"],
        package["executionAuthorized"],
    ) == ("ACTIVE", "CONTEXT_LOADED", "SCOPE_READY", True)
    assert package["document_note"] == draft["document_note"]
    assert package["scopeBinding"]["source_package"] == {
        "id": "package-one",
        "draft_revision": 1,
        "document_sha256": draft["document_note"]["sha256"],
    }
    assert state["aggregates"]["direction"][direction_id]["status"] == "ACTIVE"
    assert state["aggregates"]["experiment"][experiment_id]["package_id"] == "package-one"
    assert state["aggregates"]["proposal"][proposal["id"]]["disposition"] == "ACCEPTED"
    for aggregate_type, aggregate_id in (
        ("package", "package-one"),
        ("proposal", proposal["id"]),
        ("direction", direction_id),
        ("experiment", experiment_id),
    ):
        assert StateQuery(paths).history(aggregate_type, aggregate_id)["data"][-1][
            "event_id"
        ] == event["event_id"]

    replay = management.finalize_draft_package(
        paths,
        "package-one",
        proposal["id"],
        pending["proposal_hash"],
        actor=USER,
    )
    assert replay["event_id"] == event["event_id"]
    assert len(EventStore(paths).events()) == event_count + 1


def test_finalization_rejects_a_draft_revised_after_review(tmp_path):
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    _draft(paths)
    proposal, pending = _pending_finalization(paths)
    draft_package.revise(
        paths,
        package_id="package-one",
        patch={"abstract": "Changed after the full proposal was shown."},
        actor_id="test",
    )

    with pytest.raises(CommandConflict, match="changed after the visible Scope review"):
        management.finalize_draft_package(
            paths,
            "package-one",
            proposal["id"],
            pending["proposal_hash"],
            actor=USER,
        )
    state = EventStore(paths).state()
    assert state["aggregates"]["package"]["package-one"]["lifecycle"] == "DRAFT"
    assert state["aggregates"]["direction"] == {}
    assert state["aggregates"]["experiment"] == {}
    assert state["aggregates"]["proposal"][proposal["id"]]["disposition"] == "PENDING"


def test_finalization_requires_a_user_actor(tmp_path):
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    _draft(paths)
    proposal, pending = _pending_finalization(paths)

    with pytest.raises(CommandRejected, match="explicit user approval"):
        management.finalize_draft_package(
            paths,
            "package-one",
            proposal["id"],
            pending["proposal_hash"],
            actor=ACTOR,
        )
    assert EventStore(paths).state()["aggregates"]["direction"] == {}


def test_package_finalize_cli_uses_one_user_approval(tmp_path, capsys):
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    _draft(paths)
    proposal, pending = _pending_finalization(paths)

    assert research_op.main(
        [
            "--workspace",
            str(tmp_path),
            "--pkg",
            "package-one",
            "--op",
            "package-finalize",
            "--from-triage",
            proposal["id"],
            "--proposal-hash",
            pending["proposal_hash"],
            "--actor-type",
            "user",
            "--actor-id",
            "test-pm",
        ]
    ) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["op"] == "package-finalize"
    assert receipt["lifecycle"] == "ACTIVE"
    assert receipt["phase"] == "CONTEXT_LOADED"
