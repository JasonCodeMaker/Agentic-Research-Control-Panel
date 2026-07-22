"""State-only materialization contracts for research-package."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "skills/research-op/scripts"))
sys.path.insert(0, str(ROOT / "skills/research-package/scripts"))
sys.path.insert(0, str(ROOT / "skills/research-brainstorm/scripts"))

from lib.research_state import (  # noqa: E402
    CommandConflict,
    EventStore,
    ResearchPaths,
    StateQuery,
)
from lib.interface import build_interface  # noqa: E402
import brainstorm  # noqa: E402
import brainstorm_transfer  # noqa: E402
import create_from_scope  # noqa: E402
import draft_package  # noqa: E402
import management  # noqa: E402
import reopen_as_draft  # noqa: E402
from tests.scope_fixtures import (  # noqa: E402
    commit_accepted_scope,
    direction_node,
    proposal_item,
    project_node,
)


ACTOR = {"type": "agent", "id": "test"}
EXPERIMENT_ID = "experiment/retrieval-v2/M0-baseline-validity"
EXPERIMENT_SPEC = {
    "purpose": (
        "Run a baseline reproduction study that verifies the declared retrieval "
        "pipeline before any new method changes are evaluated in production."
    ),
    "config_ref": "scope:dir/retrieval-v2#m0-baseline-validity",
    "gate": (
        "The reproduced baseline metric must fall within the accepted tolerance "
        "window before downstream experiments compare new method variants fairly "
        "and reliably."
    ),
    "control_mode": "CHECKPOINTED",
}


def _scope_experiment_node(
    *,
    node_id: str = EXPERIMENT_ID,
    parent: str = "dir/retrieval-v2",
    status: str = "ACTIVE",
    package_id: str | None = None,
) -> dict:
    return {
        "id": node_id,
        "level": "experiment",
        "parents": [parent],
        "version": 1,
        "status": status,
        "spec": copy.deepcopy(EXPERIMENT_SPEC),
        "package_id": package_id,
        "source": f"test:{node_id}",
    }


def _commit_scope(
    paths: ResearchPaths,
    *,
    include_experiment: bool = True,
) -> None:
    nodes = [project_node(), direction_node()]
    if include_experiment:
        nodes.append(_scope_experiment_node())
    for node in nodes:
        commit_accepted_scope(management, paths, node, actor=ACTOR)


def _add_legacy_brainstorm(
    paths: ResearchPaths,
    idea_id: str,
    *,
    title: str,
    idea: str,
    document_html: str,
    abstract: str | None = None,
) -> None:
    """Seed the pre-Draft-Package shape to protect read compatibility."""
    note = management.write_note(
        paths,
        document_html,
        mime="text/html;profile=brainstorm-fragment",
        title=title,
    )
    record = {
        "id": idea_id,
        "title": title,
        "idea": idea,
        "abstract": abstract or idea,
        "status": "ACTIVE",
        "created_at": "2026-07-21T00:00:00+00:00",
        "updated_at": "2026-07-21T00:00:00+00:00",
        "detailPath": f"brainstorm/2026-07-21-{idea_id}.html",
        "document_note": note,
    }
    management.create_brainstorm(
        paths,
        idea_id,
        record,
        actor=ACTOR,
        idempotency_key=f"legacy-brainstorm:{idea_id}",
    )


def _convert_ready_draft(paths: ResearchPaths, brainstorm_id: str) -> dict:
    draft_package.convert(
        paths,
        brainstorm_id=brainstorm_id,
        package_id=None,
        actor_id="test-pm",
    )
    state = EventStore(paths).state()
    package = state["aggregates"]["package"][brainstorm_id]
    version = int(state["aggregate_versions"][f"package/{brainstorm_id}"])
    management.revise_draft_package(
        paths,
        brainstorm_id,
        {
            "draftStatus": "SCOPE_READY",
            "draftRevision": int(package["draftRevision"]) + 1,
        },
        expected_version=version,
        actor=ACTOR,
        idempotency_key=f"test-ready-draft:{brainstorm_id}",
    )
    return EventStore(paths).state()["aggregates"]["package"][brainstorm_id]


def test_materializes_scope_as_package_scoped_experiment(tmp_path):
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    _commit_scope(paths)

    result = create_from_scope.main(
        [
            "--workspace",
            str(tmp_path),
            "--direction-id",
            "dir/retrieval-v2",
            "--id",
            "retrieval-package",
        ]
    )

    assert result == 0
    state = EventStore(paths).state()
    package = state["aggregates"]["package"]["retrieval-package"]
    experiment = state["aggregates"]["experiment"][EXPERIMENT_ID]
    assert package["sourceDirection"] == "dir/retrieval-v2"
    assert package["sourceExperiments"] == [
        {
            "id": EXPERIMENT_ID,
            "version": 1,
            "source": f"test:{EXPERIMENT_ID}",
        }
    ]
    assert list(state["aggregates"]["experiment"]) == [EXPERIMENT_ID]
    assert experiment["id"] == EXPERIMENT_ID
    assert experiment["local_id"] == "P0"
    assert experiment["package_id"] == "retrieval-package"
    assert experiment["scope_status"] == "ACTIVE"
    assert experiment["scope_confirmation"] == "CONFIRMED"
    assert experiment["spec"] == EXPERIMENT_SPEC
    assert experiment["output"] == (
        ".research/experiments/retrieval-package/P0/<run-id>/result.json"
    )
    assert "after" not in experiment
    assert set(experiment) == {
        "id",
        "local_id",
        "package_id",
        "direction_id",
        "spec",
        "status",
        "scope_version",
        "scope_status",
        "scope_confirmation",
        "confirmed_direction_version",
        "scope_source",
        "_scope_transition",
        "output",
        "measures",
        "requiresCode",
        "complex",
    }


def test_activates_the_same_reviewed_draft_package(tmp_path):
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    commit_accepted_scope(management, paths, project_node(), actor=ACTOR)
    package_id = brainstorm.add_brainstorm(
        paths,
        {
            "id": "retrieval-package",
            "title": "Retrieval package proposal",
            "idea": "Align reproduction and transfer before freezing experiments.",
            "document_html": (
                "<section><h2>Proposal</h2>"
                "<p>The same document must survive activation.</p></section>"
            ),
        },
    )
    before = _convert_ready_draft(paths, package_id)
    binding = brainstorm.draft_source_binding(paths, package_id)

    direction = direction_node(source=f"draft-package:{package_id}")
    proposal = proposal_item(direction)
    proposal["source_package"] = binding
    proposal["source_brainstorms"] = []
    management.submit_proposal(paths, proposal, actor=ACTOR)
    pending = management.pending_proposals(paths)[-1]
    management.dispose_proposal(
        paths,
        proposal["id"],
        "ACCEPTED",
        pending["proposal_hash"],
        actor={"type": "user", "id": "test-pm"},
    )
    payload, causation_id = management.accepted_scope_payload(paths, proposal["id"])
    management.commit_scope_transition(
        paths,
        payload,
        actor=ACTOR,
        causation_id=causation_id,
    )
    commit_accepted_scope(
        management,
        paths,
        _scope_experiment_node(),
        actor=ACTOR,
    )

    assert create_from_scope.main(
        [
            "--workspace",
            str(tmp_path),
            "--direction-id",
            "dir/retrieval-v2",
            "--id",
            package_id,
        ]
    ) == 0

    state = EventStore(paths).state()
    package = state["aggregates"]["package"][package_id]
    assert package["lifecycle"] == "ACTIVE"
    assert package["executionAuthorized"] is True
    assert package["document_note"] == before["document_note"]
    assert package["documentPath"] == "docs/proposal.html"
    assert package["scopeBinding"] == {
        "source_package": binding,
        "direction_id": "dir/retrieval-v2",
        "direction_version": 1,
        "experiment_ids": [EXPERIMENT_ID],
    }
    events = EventStore(paths).events()
    package_events = [
        row["event_type"]
        for row in events
        if row["aggregate_type"] == "package"
        and row["aggregate_id"] == package_id
    ]
    assert package_events == [
        "PackageDraftCreated",
        "PackageDraftRevised",
        "PackageActivated",
    ]


def test_reopens_never_run_activated_package_as_same_draft(tmp_path):
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    commit_accepted_scope(management, paths, project_node(), actor=ACTOR)
    package_id = brainstorm.add_brainstorm(
        paths,
        {
            "id": "retrieval-package",
            "title": "Retrieval package proposal",
            "idea": "Align reproduction and transfer before freezing experiments.",
            "document_html": (
                "<section><h2>Proposal</h2>"
                "<p>Return this document to Draft without changing its identity.</p>"
                "</section>"
            ),
        },
    )
    reviewed = _convert_ready_draft(paths, package_id)
    binding = brainstorm.draft_source_binding(paths, package_id)
    direction = direction_node(source=f"draft-package:{package_id}")
    proposal = proposal_item(direction)
    proposal["source_package"] = binding
    proposal["source_brainstorms"] = []
    management.submit_proposal(paths, proposal, actor=ACTOR)
    pending = management.pending_proposals(paths)[-1]
    management.dispose_proposal(
        paths,
        proposal["id"],
        "ACCEPTED",
        pending["proposal_hash"],
        actor={"type": "user", "id": "test-pm"},
    )
    payload, causation_id = management.accepted_scope_payload(paths, proposal["id"])
    management.commit_scope_transition(
        paths,
        payload,
        actor=ACTOR,
        causation_id=causation_id,
    )
    commit_accepted_scope(
        management,
        paths,
        _scope_experiment_node(),
        actor=ACTOR,
    )
    assert create_from_scope.main(
        [
            "--workspace",
            str(tmp_path),
            "--direction-id",
            "dir/retrieval-v2",
            "--id",
            package_id,
        ]
    ) == 0
    active_experiment_status = EventStore(paths).state()["aggregates"][
        "experiment"
    ][EXPERIMENT_ID]["status"]

    result = reopen_as_draft.reopen(
        paths,
        package_id=package_id,
        reason="The Package design needs another alignment pass.",
        actor_id="test-pm",
    )

    state = EventStore(paths).state()
    package = state["aggregates"]["package"][package_id]
    experiment = state["aggregates"]["experiment"][EXPERIMENT_ID]
    assert result["status"] == "reopened_as_draft"
    assert package["lifecycle"] == "DRAFT"
    assert package["draftStatus"] == "REFINING"
    assert package["draftRevision"] == reviewed["draftRevision"] + 1
    assert package["executionAuthorized"] is False
    assert package["phase"] is None
    assert package["direction_id"] is None
    assert package["sourceExperiments"] == []
    assert package["scopeBinding"] is None
    assert package["documentPath"] == "docs/proposal.html"
    assert package["document_note"] == reviewed["document_note"]
    assert experiment["package_id"] is None
    assert experiment["scope_confirmation"] == "STALE"
    assert experiment["status"] == "BLOCKED"
    assert experiment["status_before_scope_stale"] == active_experiment_status
    assert "local_id" not in experiment
    assert "output" not in experiment
    context = StateQuery(paths).context(package_id)["data"]
    assert context["execution_authorized"] is False
    assert context["proposal_document"]["note"] == reviewed["document_note"]
    history = StateQuery(paths).history("experiment", EXPERIMENT_ID)["data"]
    assert history[-1]["event_type"] == "PackageReopenedAsDraft"
    assert (
        paths.interface
        / "packages"
        / package_id
        / "docs"
        / "proposal.html"
    ).is_file()


def test_scope_acceptance_rejects_a_refined_draft_after_review(tmp_path):
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    commit_accepted_scope(management, paths, project_node(), actor=ACTOR)
    package_id = brainstorm.add_brainstorm(
        paths,
        {"id": "stale-draft", "title": "Stale", "idea": "Versioned proposal"},
    )
    _convert_ready_draft(paths, package_id)
    proposal = proposal_item(direction_node(source=f"draft-package:{package_id}"))
    proposal["source_package"] = brainstorm.draft_source_binding(paths, package_id)
    proposal["source_brainstorms"] = []
    management.submit_proposal(paths, proposal, actor=ACTOR)
    pending = management.pending_proposals(paths)[-1]

    draft_package.revise(
        paths,
        package_id=package_id,
        patch={"abstract": "Changed after the visible review."},
        actor_id="test",
    )
    with pytest.raises(CommandConflict, match="changed after the visible Scope review"):
        management.dispose_proposal(
            paths,
            proposal["id"],
            "ACCEPTED",
            pending["proposal_hash"],
            actor={"type": "user", "id": "test-pm"},
        )


def test_materialization_transfers_source_brainstorm_into_package_docs(tmp_path):
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    commit_accepted_scope(management, paths, project_node(), actor=ACTOR)
    _add_legacy_brainstorm(
        paths,
        "retrieval-proposal",
        title="Retrieval proposal",
        abstract="A source proposal for the ratified Direction.",
        idea="Test the retrieval change before execution.",
        document_html=(
            '<section class="doc-section" id="proposal-body">'
            "<h2>Proposal body</h2><p>Package-owned source content.</p>"
            "</section>"
        ),
    )
    direction = direction_node(source="brainstorms:retrieval-proposal")
    item = proposal_item(direction)
    item["source_brainstorms"] = ["retrieval-proposal"]
    management.submit_proposal(paths, item, actor=ACTOR)
    pending = management.pending_proposals(paths)[-1]
    management.dispose_proposal(
        paths,
        item["id"],
        "ACCEPTED",
        pending["proposal_hash"],
        actor={"type": "user", "id": "test-pm"},
    )
    payload, causation_id = management.accepted_scope_payload(paths, item["id"])
    management.commit_scope_transition(
        paths,
        payload,
        actor=ACTOR,
        causation_id=causation_id,
    )
    commit_accepted_scope(
        management,
        paths,
        _scope_experiment_node(),
        actor=ACTOR,
    )

    with pytest.raises(SystemExit, match="exactly match"):
        create_from_scope.main(
            [
                "--workspace",
                str(tmp_path),
                "--direction-id",
                "dir/retrieval-v2",
                "--id",
                "retrieval-package",
                "--source-brainstorms",
                "[]",
            ]
        )
    failed_state = EventStore(paths).state()
    assert "retrieval-package" not in failed_state["aggregates"]["package"]
    assert "retrieval-proposal" in failed_state["aggregates"]["brainstorm"]

    assert create_from_scope.main(
        [
            "--workspace",
            str(tmp_path),
            "--direction-id",
            "dir/retrieval-v2",
            "--id",
            "retrieval-package",
        ]
    ) == 0

    state = EventStore(paths).state()
    package = state["aggregates"]["package"]["retrieval-package"]
    assert state["aggregates"]["brainstorm"] == {}
    assert package["sourceBrainstorms"][0]["id"] == "retrieval-proposal"
    assert package["sourceBrainstorms"][0]["ownership"] == "package"
    assert package["docsGroups"][0]["id"] == "source-proposal"
    document_path = "docs/retrieval-proposal.html"
    assert package["interface_notes"][document_path] == package[
        "sourceBrainstorms"
    ][0]["document_note"]
    event = EventStore(paths).events()[-1]
    assert event["event_type"] == "PackageMaterialized"
    assert event["payload"]["brainstorm_consumptions"][0][
        "aggregate_id"
    ] == "retrieval-proposal"
    history = StateQuery(paths).history(
        "brainstorm", "retrieval-proposal"
    )["data"]
    assert [row["event_type"] for row in history][-1] == "PackageMaterialized"

    build_interface(paths)
    assert not list(
        (paths.interface / "brainstorm").glob("*retrieval-proposal.html")
    )
    page = (
        paths.interface
        / "packages"
        / "retrieval-package"
        / document_path
    ).read_text(encoding="utf-8")
    assert 'data-page="package-source-proposal"' in page
    assert "Package-owned source content." in page
    assert "Back to Package docs" in page
    assert 'href="../../../assets/brainstorm.css"' in page


def test_reopens_legacy_materialized_package_from_owned_source_proposal(tmp_path):
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    commit_accepted_scope(management, paths, project_node(), actor=ACTOR)
    _add_legacy_brainstorm(
        paths,
        "retrieval-proposal",
        title="Retrieval proposal",
        idea="Test the retrieval change before execution.",
        document_html=(
            '<section class="doc-section" id="proposal-body">'
            "<h2>Proposal body</h2><p>Package-owned source content.</p>"
            "</section>"
        ),
    )
    direction = direction_node(source="brainstorms:retrieval-proposal")
    item = proposal_item(direction)
    item["source_brainstorms"] = ["retrieval-proposal"]
    management.submit_proposal(paths, item, actor=ACTOR)
    pending = management.pending_proposals(paths)[-1]
    management.dispose_proposal(
        paths,
        item["id"],
        "ACCEPTED",
        pending["proposal_hash"],
        actor={"type": "user", "id": "test-pm"},
    )
    payload, causation_id = management.accepted_scope_payload(paths, item["id"])
    management.commit_scope_transition(
        paths,
        payload,
        actor=ACTOR,
        causation_id=causation_id,
    )
    commit_accepted_scope(
        management,
        paths,
        _scope_experiment_node(),
        actor=ACTOR,
    )
    assert create_from_scope.main(
        [
            "--workspace",
            str(tmp_path),
            "--direction-id",
            "dir/retrieval-v2",
            "--id",
            "retrieval-package",
        ]
    ) == 0
    active = EventStore(paths).state()["aggregates"]["package"][
        "retrieval-package"
    ]
    source_note = active["sourceBrainstorms"][0]["document_note"]

    reopen_as_draft.reopen(
        paths,
        package_id="retrieval-package",
        reason="Return the legacy Package to proposal refinement.",
        actor_id="test-pm",
    )

    state = EventStore(paths).state()
    package = state["aggregates"]["package"]["retrieval-package"]
    assert package["lifecycle"] == "DRAFT"
    assert package["draftRevision"] == 1
    assert package["documentPath"] == "docs/proposal.html"
    assert package["document_note"] == source_note
    assert state["aggregates"]["experiment"][EXPERIMENT_ID]["package_id"] is None


def test_existing_package_repair_transfers_and_removes_brainstorm_atomically(
    tmp_path,
):
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    _commit_scope(paths)
    assert create_from_scope.main(
        [
            "--workspace",
            str(tmp_path),
            "--direction-id",
            "dir/retrieval-v2",
            "--id",
            "retrieval-package",
        ]
    ) == 0
    _add_legacy_brainstorm(
        paths,
        "repair-proposal",
        title="Repair proposal",
        idea="Move this document under the existing Package.",
        document_html="<section><h2>Repair source</h2></section>",
    )

    result = brainstorm_transfer.transfer_existing(
        paths,
        package_id="retrieval-package",
        brainstorm_ids=["repair-proposal"],
        actor={"type": "user", "id": "test-pm"},
    )

    state = EventStore(paths).state()
    package = state["aggregates"]["package"]["retrieval-package"]
    assert result["removed_brainstorms"] == ["repair-proposal"]
    assert state["aggregates"]["brainstorm"] == {}
    assert package["sourceBrainstorms"][0]["id"] == "repair-proposal"
    event = EventStore(paths).events()[-1]
    assert event["event_type"] == "PackageMutationApplied"
    assert event["payload"]["brainstorm_consumptions"][0][
        "aggregate_id"
    ] == "repair-proposal"
    repeated = brainstorm_transfer.transfer_existing(
        paths,
        package_id="retrieval-package",
        brainstorm_ids=["repair-proposal"],
        actor={"type": "user", "id": "test-pm"},
    )
    assert repeated == {
        "package_event_id": None,
        "removed_brainstorms": [],
        "already_converted": ["repair-proposal"],
    }


def test_check_requires_accepted_scope_experiment(tmp_path):
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    _commit_scope(paths, include_experiment=False)

    status = create_from_scope.materialization_status(
        paths=paths,
        direction_id="dir/retrieval-v2",
        package_id="retrieval-package",
    )

    assert status["materializable"] is False
    assert status["direction"]["state"] == "committed"
    assert status["experiments"] == {"state": "missing", "count": 0}


def test_scope_experiment_selection_uses_only_unassigned_active_children():
    accepted = {
        "id": EXPERIMENT_ID,
        "direction_id": "dir/retrieval-v2",
        "package_id": None,
        "scope_status": "ACTIVE",
        "spec": copy.deepcopy(EXPERIMENT_SPEC),
    }
    linked = {
        **copy.deepcopy(accepted),
        "id": "experiment/retrieval-v2/linked",
        "package_id": "existing-package",
    }
    inactive = {
        **copy.deepcopy(accepted),
        "id": "experiment/retrieval-v2/archived",
        "scope_status": "ARCHIVED",
    }
    other_direction = {
        **copy.deepcopy(accepted),
        "id": "experiment/other/active",
        "direction_id": "dir/other",
    }
    accepted_later = {
        **copy.deepcopy(accepted),
        "id": "experiment/retrieval-v2/M2-mechanism",
    }
    state = {
        "aggregates": {
            "experiment": {
                row["id"]: row
                for row in (
                    accepted_later,
                    linked,
                    inactive,
                    other_direction,
                    accepted,
                )
            }
        }
    }

    selected = create_from_scope._scope_experiments(
        state,
        "dir/retrieval-v2",
    )

    assert [row["aggregate_id"] for row in selected] == [
        EXPERIMENT_ID,
        "experiment/retrieval-v2/M2-mechanism",
    ]
