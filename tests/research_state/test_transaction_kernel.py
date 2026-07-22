from __future__ import annotations

import copy

import pytest

from lib.research_state import (
    EventStore,
    ResearchPaths,
    StateQuery,
    approval_receipt,
    build_transaction_payload,
    commit_transaction,
    review_digest,
)
from lib.research_state.reducer import fold


AGENT = {"type": "agent", "id": "test-agent"}
USER = {"type": "user", "id": "test-user"}


def _paths(tmp_path):
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    EventStore(paths).initialize()
    return paths


def _draft_package(package_id: str) -> dict:
    return {
        "id": package_id,
        "direction_id": None,
        "sourceVersion": None,
        "sourceChange": None,
        "sourceExperiments": [],
        "lifecycle": "DRAFT",
        "phase": None,
        "blocker": None,
        "draftStatus": "REFINING",
        "draftRevision": 1,
        "executionAuthorized": False,
    }


def test_agent_materializes_brainstorm_and_package_in_one_event(tmp_path):
    paths = _paths(tmp_path)
    EventStore(paths).commit(
        event_type="BrainstormCreated",
        aggregate_type="brainstorm",
        aggregate_id="idea-one",
        payload={"record": {"id": "idea-one", "status": "ACTIVE"}},
        actor=AGENT,
        idempotency_key="seed-idea",
    )
    payload = build_transaction_payload(
        command_kind="DRAFT_MATERIALIZE",
        owner_type="package",
        owner_id="package-one",
        participants=[
            {
                "aggregate_type": "brainstorm",
                "aggregate_id": "idea-one",
                "expected_version": 1,
                "aggregate_version": 2,
                "operation": "put",
                "record": {
                    "id": "idea-one",
                    "status": "MATERIALIZED",
                    "materialized_as": "package-one",
                },
            },
            {
                "aggregate_type": "package",
                "aggregate_id": "package-one",
                "expected_version": 0,
                "aggregate_version": 1,
                "operation": "put",
                "record": _draft_package("package-one"),
            },
        ],
    )

    event = commit_transaction(
        paths,
        payload=payload,
        actor=AGENT,
        idempotency_key="materialize-one",
        entry_skill="research-package",
    )

    assert event["event_type"] == "TransactionCommitted"
    state = EventStore(paths).state()
    assert state["aggregates"]["brainstorm"]["idea-one"] == {
        "id": "idea-one",
        "status": "MATERIALIZED",
        "materialized_as": "package-one",
    }
    assert state["aggregates"]["package"]["package-one"]["lifecycle"] == "DRAFT"
    assert state == fold(EventStore(paths).events())
    assert StateQuery(paths).history("brainstorm", "idea-one")["data"][-1][
        "event_id"
    ] == event["event_id"]


def test_user_approval_binds_exact_transaction_content(tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    record = {
        "id": "project",
        "level": "project",
        "parents": [],
        "version": 1,
        "status": "ACTIVE",
        "spec": {"problem": "test"},
        "source": "onboarding",
    }
    payload = build_transaction_payload(
        command_kind="PROJECT_COMMIT",
        owner_type="project",
        owner_id="project",
        participants=[
            {
                "aggregate_type": "project",
                "aggregate_id": "project",
                "expected_version": 0,
                "aggregate_version": 1,
                "operation": "put",
                "record": record,
            }
        ],
    )
    payload["approval"] = approval_receipt(
        action="COMMIT_PROJECT",
        subject="project",
        content_sha256=review_digest(payload),
        actor_id=USER["id"],
        review_id="review-project-one",
    )
    tampered = copy.deepcopy(payload)
    tampered["participants"][0]["record"]["spec"]["problem"] = "changed"

    with pytest.raises(ValueError, match="does not bind"):
        commit_transaction(
            paths,
            payload=tampered,
            actor=USER,
            idempotency_key="tampered-project",
            entry_skill="research-onboard",
        )

    assert EventStore(paths).events() == []
    with monkeypatch.context() as patch:
        patch.setattr(
            EventStore,
            "events",
            lambda _store: (_ for _ in ()).throw(
                AssertionError("vNext commit scanned the event ledger")
            ),
        )
        event = commit_transaction(
            paths,
            payload=payload,
            actor=USER,
            idempotency_key="commit-project",
            entry_skill="research-onboard",
        )
    assert EventStore(paths).state()["aggregates"]["project"]["project"] == record
    assert event["aggregate_version"] == 1


def test_stale_participant_rejects_the_whole_transaction(tmp_path):
    paths = _paths(tmp_path)
    EventStore(paths).commit(
        event_type="BrainstormCreated",
        aggregate_type="brainstorm",
        aggregate_id="idea-one",
        payload={"record": {"id": "idea-one", "status": "ACTIVE"}},
        actor=AGENT,
        idempotency_key="seed-idea",
    )
    before = EventStore(paths).state()
    payload = build_transaction_payload(
        command_kind="DRAFT_MATERIALIZE",
        owner_type="package",
        owner_id="package-one",
        participants=[
            {
                "aggregate_type": "brainstorm",
                "aggregate_id": "idea-one",
                "expected_version": 0,
                "aggregate_version": 1,
                "operation": "put",
                "record": {"id": "idea-one", "status": "MATERIALIZED"},
            },
            {
                "aggregate_type": "package",
                "aggregate_id": "package-one",
                "expected_version": 0,
                "aggregate_version": 1,
                "operation": "put",
                "record": _draft_package("package-one"),
            },
        ],
    )

    with pytest.raises(ValueError, match="stale transaction participant"):
        commit_transaction(
            paths,
            payload=payload,
            actor=AGENT,
            idempotency_key="stale-materialize",
            entry_skill="research-package",
        )

    assert EventStore(paths).state() == before
    assert [event["event_type"] for event in EventStore(paths).events()] == [
        "BrainstormCreated"
    ]
