from __future__ import annotations

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

from lib.interface.package import _package_card_summary, _template_mapping  # noqa: E402
from lib.research_state import EventStore, ResearchPaths, StateQuery  # noqa: E402
from lib.research_state.reducer import fold  # noqa: E402
import brainstorm  # noqa: E402
import draft_package  # noqa: E402
import management  # noqa: E402


OLD_ID = "2026-07-21-feedback-conditioned-sqr-for-tvr"
NEW_ID = "2026-07-21-Reproducing-VideoSearch-R1"
TITLE = "Reproducing-VideoSearch-R1"
RATIONALE = "The bounded core purpose is reproducing VideoSearch-R1."
USER = {"type": "user", "id": "test-user"}
AGENT = {"type": "agent", "id": "test-agent"}


def _paths(tmp_path: Path) -> ResearchPaths:
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    EventStore(paths).initialize()
    return paths


def _active_package() -> dict:
    return {
        "id": OLD_ID,
        "slug": OLD_ID,
        "name": "Feedback Conditioned Sqr For Tvr",
        "title": "Reproducing VideoSearch-R1 and migrating SQR",
        "direction_id": "direction/reproduction",
        "sourceVersion": 1,
        "sourceChange": "evt_scope",
        "sourceExperiments": [
            {"id": "experiment/reproduction/p0", "version": 1, "source": "scope"}
        ],
        "lifecycle": "ACTIVE",
        "phase": "CONTEXT_LOADED",
        "blocker": None,
        "executionAuthorized": True,
        "artifactRoot": f".research/experiments/{OLD_ID}/",
        "runtime": f".research/experiments/{OLD_ID}/",
        "scopeBinding": {
            "source_package": {
                "id": OLD_ID,
                "draft_revision": 1,
                "document_sha256": "a" * 64,
            },
            "direction_id": "direction/reproduction",
            "direction_version": 1,
            "experiment_ids": ["experiment/reproduction/p0"],
        },
        "sourceBrainstorms": [
            {"id": "reproduction", "convertedInto": OLD_ID}
        ],
        "methodsTried": [],
        "resultGateRows": [],
        "resultBlocks": [],
        "analysisInsights": [],
    }


def _experiment() -> dict:
    return {
        "id": "experiment/reproduction/p0",
        "local_id": "P0",
        "package_id": OLD_ID,
        "direction_id": "direction/reproduction",
        "spec": {
            "purpose": "Reproduce the released checkpoint.",
            "config_ref": "scope:reproduction@1",
            "gate": "Record audit-ready reproduction evidence.",
            "control_mode": "CHECKPOINTED",
        },
        "status": "PLANNED",
        "scope_status": "ACTIVE",
        "scope_confirmation": "CONFIRMED",
        "scope_version": 1,
        "scope_source": "scope",
        "confirmed_direction_version": 1,
        "output": f".research/experiments/{OLD_ID}/P0/<run-id>/result.json",
    }


def _seed(paths: ResearchPaths) -> None:
    store = EventStore(paths, migration_mode=True)
    store.commit(
        event_type="AggregateImported",
        aggregate_type="brainstorm",
        aggregate_id="reproduction",
        payload={
            "record": {
                "id": "reproduction",
                "status": "MATERIALIZED",
                "materialized_as": OLD_ID,
            }
        },
        actor=AGENT,
        idempotency_key="seed-brainstorm",
    )
    store.commit(
        event_type="AggregateImported",
        aggregate_type="package",
        aggregate_id=OLD_ID,
        payload={"record": _active_package()},
        actor=AGENT,
        idempotency_key="seed-package",
    )
    store.commit(
        event_type="AggregateImported",
        aggregate_type="experiment",
        aggregate_id="experiment/reproduction/p0",
        payload={"record": _experiment()},
        actor=AGENT,
        idempotency_key="seed-experiment",
    )


def test_normal_conversion_uses_agent_designed_canonical_identity(tmp_path):
    paths = _paths(tmp_path)
    brainstorm.add_brainstorm(
        paths,
        {
            "id": "reproduction-source",
            "title": "A long exploratory source title",
            "idea": "Reproduce VideoSearch-R1 before further transfer work.",
            "created_at": "2026-07-21T01:00:00+00:00",
        },
    )

    result = draft_package.convert(
        paths,
        brainstorm_id="reproduction-source",
        package_id=None,
        actor_id="test-agent",
        title=TITLE,
        title_rationale=RATIONALE,
    )

    assert result["package_id"] == NEW_ID
    package = StateQuery(paths).show("package", NEW_ID)["data"]
    assert package["id"] == package["slug"] == NEW_ID
    assert package["name"] == package["title"] == TITLE
    assert package["identityContractVersion"] == 1
    assert package["identityRationale"] == RATIONALE
    assert package["sourceBrainstorms"][0]["title"] == (
        "A long exploratory source title"
    )


def test_pre_run_identity_rename_is_atomic_and_idempotent(tmp_path):
    paths = _paths(tmp_path)
    _seed(paths)
    review = management.prepare_package_identity_rename(
        paths,
        OLD_ID,
        TITLE,
        RATIONALE,
    )

    assert review["review"] == {
        "old_id": OLD_ID,
        "new_id": NEW_ID,
        "name": TITLE,
        "title": TITLE,
        "core_purpose": RATIONALE,
        "bound_experiments": ["experiment/reproduction/p0"],
        "scope_change": False,
    }
    event = management.rename_package_identity(
        paths,
        OLD_ID,
        TITLE,
        RATIONALE,
        review["receipt"]["content_sha256"],
        actor=USER,
        review_id="conversation-review",
    )

    state = EventStore(paths).state()
    assert OLD_ID not in state["aggregates"]["package"]
    package = state["aggregates"]["package"][NEW_ID]
    assert package["id"] == package["slug"] == NEW_ID
    assert package["name"] == package["title"] == TITLE
    assert package["scopeBinding"]["source_package"]["id"] == NEW_ID
    assert package["sourceBrainstorms"][0]["convertedInto"] == NEW_ID
    assert state["aggregates"]["brainstorm"]["reproduction"][
        "materialized_as"
    ] == NEW_ID
    assert package["identityHistory"][-1]["id"] == OLD_ID
    experiment = state["aggregates"]["experiment"]["experiment/reproduction/p0"]
    assert experiment["package_id"] == NEW_ID
    assert experiment["output"] == (
        f".research/experiments/{NEW_ID}/P0/<run-id>/result.json"
    )
    assert state == fold(EventStore(paths).events())
    assert StateQuery(paths).history("package", NEW_ID)["data"][-1][
        "event_id"
    ] == event["event_id"]

    replay = management.rename_package_identity(
        paths,
        OLD_ID,
        TITLE,
        RATIONALE,
        review["receipt"]["content_sha256"],
        actor=USER,
        review_id="conversation-review",
    )
    assert replay["event_id"] == event["event_id"]


def test_rename_rejects_existing_evidence_directory(tmp_path):
    paths = _paths(tmp_path)
    _seed(paths)
    (paths.experiments / OLD_ID).mkdir(parents=True)

    with pytest.raises(ValueError, match="evidence directory exists"):
        management.prepare_package_identity_rename(
            paths,
            OLD_ID,
            TITLE,
            RATIONALE,
        )


def test_rename_preserves_the_original_identity_date(tmp_path):
    paths = _paths(tmp_path)
    _seed(paths)

    with pytest.raises(ValueError, match="identity date must remain 2026-07-21"):
        management.prepare_package_identity_rename(
            paths,
            OLD_ID,
            TITLE,
            RATIONALE,
            identity_date="2026-07-22",
        )


def test_card_and_detail_use_the_same_canonical_title():
    package = _active_package()
    package.update(
        {
            "id": NEW_ID,
            "slug": NEW_ID,
            "name": TITLE,
            "title": TITLE,
            "identityContractVersion": 1,
            "identityDate": "2026-07-21",
            "identityRationale": RATIONALE,
        }
    )

    assert _package_card_summary(package)["title"] == TITLE
    assert _template_mapping(package)["name"] == TITLE
