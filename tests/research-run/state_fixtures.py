from __future__ import annotations

import shutil
from typing import Any

from lib.research_state import EventStore, ResearchPaths


ACTOR = {"type": "system", "id": "research-run-test"}
CANONICAL_EXPERIMENT_ID = "experiment/d1/e1"
LEGACY_EXPERIMENT_ID = "pkg-1::P1"


def seed(
    root,
    *,
    project: bool = True,
    direction: bool = True,
    experiment: bool = True,
    package: bool = True,
    legacy_experiment: bool = False,
    phase: str = "CONTEXT_LOADED",
) -> ResearchPaths:
    paths = ResearchPaths.resolve(workspace=root, environ={})
    store = EventStore(paths)
    scope_store = EventStore(paths, migration_mode=True)
    store.initialize()

    def commit(aggregate_type: str, aggregate_id: str, record: dict[str, Any]) -> None:
        target_store = (
            scope_store
            if aggregate_type in {"project", "direction", "experiment"}
            else store
        )
        target_store.commit(
            event_type="AggregateUpserted",
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            payload={"record": record},
            actor=ACTOR,
            idempotency_key=f"seed:{aggregate_type}:{aggregate_id}",
            expected_version=0,
        )

    if project:
        commit(
            "project",
            "project/main",
            {
                "id": "project/main",
                "level": "project",
                "parents": [],
                "version": 1,
                "status": "ACTIVE",
                "spec": {"objective": "test objective"},
                "source": "research-run-test",
            },
        )
    if direction:
        commit(
            "direction",
            "dir/d1",
            {
                "id": "dir/d1",
                "level": "direction",
                "status": "ACTIVE",
                "parents": ["project/main"],
                "version": 1,
                "spec": {"hypothesis": "test hypothesis"},
                "source": "research-run-test",
            },
        )
    if experiment:
        experiment_id = (
            LEGACY_EXPERIMENT_ID
            if legacy_experiment
            else CANONICAL_EXPERIMENT_ID
        )
        commit(
            "experiment",
            experiment_id if package else CANONICAL_EXPERIMENT_ID,
            {
                "id": (
                    "P1"
                    if package and legacy_experiment
                    else CANONICAL_EXPERIMENT_ID
                ),
                "local_id": "P1" if package else CANONICAL_EXPERIMENT_ID,
                "package_id": "pkg-1" if package else None,
                "direction_id": "dir/d1",
                "status": "READY",
                "scope_status": "ACTIVE",
                "scope_confirmation": "CONFIRMED",
                "scope_version": 1,
                "scope_source": "research-run-test",
                "confirmed_direction_version": 1,
                "aliases": (
                    ["P1"]
                    if legacy_experiment
                    else ["P1", LEGACY_EXPERIMENT_ID]
                ),
                "spec": {
                    "purpose": "measure the toy metric",
                    "config_ref": "config.yaml",
                    "gate": "measured >= 0.80",
                    "control_mode": "SUPERVISED",
                },
            },
        )
    if package:
        commit(
            "package",
            "pkg-1",
            {
                "id": "pkg-1",
                "direction_id": "dir/d1",
                "sourceVersion": 1,
                "sourceChange": "research-run-test",
                "sourceExperiments": [
                    {
                        "id": (
                            LEGACY_EXPERIMENT_ID
                            if legacy_experiment
                            else CANONICAL_EXPERIMENT_ID
                        ),
                        "version": 1,
                        "source": "research-run-test",
                    }
                ],
                "lifecycle": "ACTIVE",
                "phase": phase,
                "blocker": None,
            },
        )
    return paths


def add_brainstorm(paths: ResearchPaths, idea_id: str) -> None:
    EventStore(paths).commit(
        event_type="AggregateUpserted",
        aggregate_type="brainstorm",
        aggregate_id=idea_id,
        payload={
            "record": {
                "id": idea_id,
                "title": idea_id,
                "status": "ACTIVE",
            }
        },
        actor=ACTOR,
        idempotency_key=f"seed:brainstorm:{idea_id}",
        expected_version=0,
    )


def add_pending_direction(paths: ResearchPaths) -> None:
    EventStore(paths).commit(
        event_type="ProposalSubmitted",
        aggregate_type="proposal",
        aggregate_id="proposal-direction",
        payload={
            "record": {
                "id": "proposal-direction",
                "status": "pending",
                "proposed_node": {
                    "id": "dir/d1",
                    "level": "direction",
                    "parents": ["project/main"],
                },
            }
        },
        actor=ACTOR,
        idempotency_key="seed:proposal:direction",
        expected_version=0,
    )


def remove_interface(paths: ResearchPaths) -> None:
    """Simulate a missing rebuildable projection after state initialization."""
    shutil.rmtree(paths.interface)
