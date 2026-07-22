"""Brainstorm to Draft, Scope Bundle, and terminal Package lifecycle."""

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
            "problem": (
                "The current retrieval workflow lacks a governed way to test "
                "whether a proposed method transfers across tasks."
            ),
            "motivation": (
                "A matched evaluation can expose whether the shared retrieval "
                "structure makes that transfer plausible."
            ),
            "objective": (
                "Run the bounded comparison and record enough evidence to judge "
                "whether the proposed transfer is realized."
            ),
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
    ] == ["BrainstormCreated", "TransactionCommitted"]
    materialized = EventStore(paths).state()["aggregates"]["brainstorm"][package_id]
    assert materialized["status"] == "MATERIALIZED"
    assert materialized["materialized_as"] == package_id
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


def test_scope_bundle_is_one_approval_and_one_atomic_event(tmp_path):
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    draft = _draft(paths)
    direction = direction_node(source="draft-package:package-one")
    experiment = experiment_node(source="draft-package:package-one")
    review = management.prepare_scope_bundle(
        paths,
        "package-one",
        direction,
        [experiment],
    )
    assert review["review"]["research_intent"] == {
        "problem": draft["problem"],
        "motivation": draft["motivation"],
        "objective": draft["objective"],
        "hypothesis": direction["spec"]["hypothesis"],
    }
    before_count = len(EventStore(paths).events())

    event = management.finalize_scope_bundle(
        paths,
        "package-one",
        direction,
        [experiment],
        review["receipt"]["content_sha256"],
        actor=USER,
        review_id="conversation-review-one",
    )

    assert event["event_type"] == "TransactionCommitted"
    assert event["payload"]["command_kind"] == "SCOPE_BUNDLE_COMMIT"
    assert len(EventStore(paths).events()) == before_count + 1
    state = EventStore(paths).state()
    assert all(
        proposal.get("proposal_kind") != "package_finalization"
        for proposal in state["aggregates"]["proposal"].values()
    )
    package = state["aggregates"]["package"]["package-one"]
    assert package["lifecycle"] == "ACTIVE"
    assert package["executionLease"] == {
        "status": "OPEN",
        "scope_sha256": package["executionLease"]["scope_sha256"],
        "package_revision": draft["draftRevision"],
        "experiment_ids": [experiment["id"]],
        "grants": ["IMPLEMENT", "LAUNCH", "RECORD_RESULTS"],
    }
    assert state["aggregates"]["direction"][direction["id"]]["status"] == "ACTIVE"
    assert state["aggregates"]["experiment"][experiment["id"]]["package_id"] == (
        "package-one"
    )
    for aggregate_type, aggregate_id in (
        ("package", "package-one"),
        ("direction", direction["id"]),
        ("experiment", experiment["id"]),
    ):
        assert StateQuery(paths).history(aggregate_type, aggregate_id)["data"][-1][
            "event_id"
        ] == event["event_id"]

    replay = management.finalize_scope_bundle(
        paths,
        "package-one",
        direction,
        [experiment],
        review["receipt"]["content_sha256"],
        actor=USER,
        review_id="conversation-review-one",
    )
    assert replay["event_id"] == event["event_id"]
    assert len(EventStore(paths).events()) == before_count + 1


@pytest.mark.parametrize(
    ("patch", "message"),
    [
        ({"motivation": ""}, "explicit Problem, Motivation, Objective"),
        (
            {
                "objective": (
                    "The current retrieval workflow lacks a governed way to test "
                    "whether a proposed method transfers across tasks."
                )
            },
            "distinct roles",
        ),
        (
            {"hypothesis": "A different draft hypothesis."},
            "must match the reviewed Direction hypothesis",
        ),
    ],
)
def test_scope_bundle_rejects_invalid_research_intent(tmp_path, patch, message):
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    _draft(paths)
    draft_package.revise(
        paths,
        package_id="package-one",
        patch=patch,
        actor_id="test",
    )

    with pytest.raises(CommandRejected, match=message):
        management.prepare_scope_bundle(
            paths,
            "package-one",
            direction_node(source="draft-package:package-one"),
            [experiment_node(source="draft-package:package-one")],
        )


def test_scope_bundle_review_is_invalidated_by_draft_revision(tmp_path):
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    _draft(paths)
    direction = direction_node(source="draft-package:package-one")
    experiment = experiment_node(source="draft-package:package-one")
    review = management.prepare_scope_bundle(
        paths,
        "package-one",
        direction,
        [experiment],
    )
    draft_package.revise(
        paths,
        package_id="package-one",
        patch={"abstract": "Changed after review."},
        actor_id="test",
    )

    with pytest.raises(CommandConflict, match="changed after the user review"):
        management.finalize_scope_bundle(
            paths,
            "package-one",
            direction,
            [experiment],
            review["receipt"]["content_sha256"],
            actor=USER,
            review_id="stale-review",
        )


def test_scope_bundle_rejects_agent_actor(tmp_path):
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    _draft(paths)
    direction = direction_node(source="draft-package:package-one")
    experiment = experiment_node(source="draft-package:package-one")
    review = management.prepare_scope_bundle(
        paths,
        "package-one",
        direction,
        [experiment],
    )

    with pytest.raises(CommandRejected, match="explicit user approval"):
        management.finalize_scope_bundle(
            paths,
            "package-one",
            direction,
            [experiment],
            review["receipt"]["content_sha256"],
            actor=ACTOR,
            review_id="agent-cannot-approve",
        )


@pytest.mark.parametrize(
    ("outcome", "lifecycle"),
    [("SUCCESS", "ADOPTED"), ("FAIL", "ARCHIVED")],
)
def test_package_end_is_one_evidence_bound_decision(
    tmp_path,
    outcome,
    lifecycle,
):
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    _draft(paths)
    direction = direction_node(source="draft-package:package-one")
    experiment = experiment_node(source="draft-package:package-one")
    scope_review = management.prepare_scope_bundle(
        paths,
        "package-one",
        direction,
        [experiment],
    )
    management.finalize_scope_bundle(
        paths,
        "package-one",
        direction,
        [experiment],
        scope_review["receipt"]["content_sha256"],
        actor=USER,
        review_id="scope-review",
    )
    evidence = [{"kind": "RESULT_SUMMARY", "uri": "result://package-one"}]
    decision_review = management.prepare_package_decision(
        paths,
        "package-one",
        outcome,
        "The reviewed result supports this outcome.",
        evidence,
        actor_id=USER["id"],
    )

    event = management.finalize_package_decision(
        paths,
        "package-one",
        outcome,
        "The reviewed result supports this outcome.",
        evidence,
        decision_review["receipt"]["content_sha256"],
        actor=USER,
        review_id="outcome-review",
    )

    assert event["payload"]["command_kind"] == "PACKAGE_DECIDE"
    state = EventStore(paths).state()
    package = state["aggregates"]["package"]["package-one"]
    assert package["lifecycle"] == lifecycle
    assert package["executionLease"]["status"] == "CLOSED"
    decision_id = decision_review["receipt"]["decision_id"]
    assert state["aggregates"]["decision"][decision_id]["outcome"] == outcome
    replay = management.finalize_package_decision(
        paths,
        "package-one",
        outcome,
        "The reviewed result supports this outcome.",
        evidence,
        decision_review["receipt"]["content_sha256"],
        actor=USER,
        review_id="outcome-review",
    )
    assert replay["event_id"] == event["event_id"]


def test_package_outcome_cli_uses_the_reviewed_receipt(tmp_path, capsys):
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    _draft(paths)
    direction = direction_node(source="draft-package:package-one")
    experiment = experiment_node(source="draft-package:package-one")
    scope_review = management.prepare_scope_bundle(
        paths,
        "package-one",
        direction,
        [experiment],
    )
    management.finalize_scope_bundle(
        paths,
        "package-one",
        direction,
        [experiment],
        scope_review["receipt"]["content_sha256"],
        actor=USER,
        review_id="scope-review",
    )
    evidence = json.dumps(
        [{"kind": "RESULT_SUMMARY", "uri": "result://package-one"}]
    )
    common = [
        "--workspace",
        str(tmp_path),
        "--package-id",
        "package-one",
        "--outcome",
        "SUCCESS",
        "--reason",
        "The declared gate passed.",
        "--evidence",
        evidence,
        "--actor-id",
        USER["id"],
    ]

    assert draft_package.main([*common[:2], "review-outcome", *common[2:]]) == 0
    review = json.loads(capsys.readouterr().out)
    assert draft_package.main(
        [
            *common[:2],
            "commit-outcome",
            *common[2:],
            "--review-sha256",
            review["receipt"]["content_sha256"],
            "--review-id",
            "outcome-review",
        ]
    ) == 0
    committed = json.loads(capsys.readouterr().out)

    assert committed["status"] == "package_closed"
    assert EventStore(paths).state()["aggregates"]["package"]["package-one"][
        "lifecycle"
    ] == "ADOPTED"


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
