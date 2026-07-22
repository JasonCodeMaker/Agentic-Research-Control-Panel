from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
for candidate in (
    ROOT,
    ROOT / "skills" / "research-brainstorm" / "scripts",
    ROOT / "skills" / "research-onboard" / "scripts",
    ROOT / "skills" / "research-op" / "scripts",
    ROOT / "skills" / "research-package" / "scripts",
):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import brainstorm  # noqa: E402
import draft_package  # noqa: E402
import management  # noqa: E402
import onboard  # noqa: E402
from lib.research_state import EventStore, ResearchPaths  # noqa: E402
from tests.scope_fixtures import (  # noqa: E402
    direction_node,
    experiment_node,
    project_spec,
)


USER = {"type": "user", "id": "pm"}


def test_normal_loop_has_only_three_human_authority_boundaries(tmp_path):
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    EventStore(paths).initialize()

    project = onboard.project_node(
        "project/main",
        project_spec(),
        source="user onboarding review",
    )
    project_review = management.prepare_project_commit(paths, project)
    management.finalize_project_commit(
        paths,
        project,
        project_review["receipt"]["content_sha256"],
        actor=USER,
        review_id="review-project",
    )

    brainstorm.add_brainstorm(
        paths,
        {
            "id": "idea-one",
            "title": "One research idea",
            "idea": "Test one bounded hypothesis.",
            "document_html": (
                "<section><h2>Question</h2><p>Does the method help?</p></section>"
            ),
        },
    )
    draft_package.convert(
        paths,
        brainstorm_id="idea-one",
        package_id=None,
        actor_id="research-package",
    )
    draft_package.revise(
        paths,
        package_id="idea-one",
        patch={"abstract": "A reviewed and executable validation plan."},
        actor_id="research-package",
    )

    direction = direction_node(source="draft-package:idea-one")
    experiment = experiment_node(source="draft-package:idea-one")
    scope_review = management.prepare_scope_bundle(
        paths,
        "idea-one",
        direction,
        [experiment],
    )
    management.finalize_scope_bundle(
        paths,
        "idea-one",
        direction,
        [experiment],
        scope_review["receipt"]["content_sha256"],
        actor=USER,
        review_id="review-scope",
    )

    evidence = [{"kind": "RESULT_SUMMARY", "uri": "result://idea-one"}]
    outcome_review = management.prepare_package_decision(
        paths,
        "idea-one",
        "SUCCESS",
        "The declared gate passed.",
        evidence,
        actor_id=USER["id"],
    )
    management.finalize_package_decision(
        paths,
        "idea-one",
        "SUCCESS",
        "The declared gate passed.",
        evidence,
        outcome_review["receipt"]["content_sha256"],
        actor=USER,
        review_id="review-outcome",
    )

    store = EventStore(paths)
    state = store.state()
    transactions = [
        event
        for event in store.events()
        if event["event_type"] == "TransactionCommitted"
    ]
    command_kinds = [event["payload"]["command_kind"] for event in transactions]
    assert command_kinds == [
        "PROJECT_COMMIT",
        "DRAFT_MATERIALIZE",
        "DRAFT_REVISE",
        "SCOPE_BUNDLE_COMMIT",
        "PACKAGE_DECIDE",
    ]
    assert [
        event["payload"]["command_kind"]
        for event in transactions
        if isinstance(event["payload"].get("approval"), dict)
    ] == ["PROJECT_COMMIT", "SCOPE_BUNDLE_COMMIT", "PACKAGE_DECIDE"]
    assert state["aggregates"]["proposal"] == {}
    assert state["aggregates"]["brainstorm"]["idea-one"]["status"] == (
        "MATERIALIZED"
    )
    assert state["aggregates"]["package"]["idea-one"]["lifecycle"] == "ADOPTED"
    assert state["aggregates"]["package"]["idea-one"]["executionLease"][
        "status"
    ] == "CLOSED"
    assert {row["outcome"] for row in store.database.audit()} == {
        "COMMAND_COMMITTED"
    }
