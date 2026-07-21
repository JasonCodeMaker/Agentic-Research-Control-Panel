"""Writer-to-query integration for knowledge and governed learning."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "skills" / "research-op" / "scripts"))

import context_pack  # noqa: E402
import context_pack.build as build  # noqa: E402
import management  # noqa: E402
from research_state import EventStore, ResearchPaths  # noqa: E402
from tests.scope_fixtures import (  # noqa: E402
    direction_node,
    experiment_spec,
    project_node,
)


ACTOR = {"type": "system", "id": "test"}
EXPERIMENT_ID = "experiment/main/M0-evaluate-retrieval"
SCOPE_SOURCE = "fixture:context-pack-e2e-import"


def _ref():
    return {
        "uri": "experiments/pkg/exp/run/result.json",
        "sha256": "b" * 64,
        "size_bytes": 100,
        "kind": "FILE",
        "package_id": "pkg",
        "experiment_id": EXPERIMENT_ID,
        "run_id": "run",
    }


def _import_record(store, aggregate_type, aggregate_id, record):
    EventStore(store.paths, migration_mode=True).commit(
        event_type="AggregateImported",
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        payload={"record": record},
        actor=ACTOR,
        idempotency_key=f"seed:{aggregate_type}:{aggregate_id}",
        expected_version=0,
    )


def test_management_writers_flow_into_ephemeral_context(tmp_path):
    paths = ResearchPaths.resolve(workspace=tmp_path)
    store = EventStore(paths)
    store.initialize()
    _import_record(
        store,
        "project",
        "project/main",
        project_node(
            "project/main",
            source=SCOPE_SOURCE,
            goal="Auditable retrieval",
        ),
    )
    _import_record(
        store,
        "direction",
        "dir/main",
        direction_node(
            "dir/main",
            parent="project/main",
            source=SCOPE_SOURCE,
            hypothesis="A better retriever helps",
            success_gate="R@1 >= 48",
        ),
    )
    _import_record(
        store,
        "package",
        "pkg",
        {
            "id": "pkg",
            "direction_id": "dir/main",
            "sourceDirection": "dir/main",
            "sourceVersion": 1,
            "sourceChange": SCOPE_SOURCE,
            "sourceExperiments": [
                {
                    "id": EXPERIMENT_ID,
                    "version": 1,
                    "source": SCOPE_SOURCE,
                }
            ],
            "lifecycle": "ACTIVE",
            "phase": "CONTEXT_LOADED",
        },
    )
    _import_record(
        store,
        "experiment",
        EXPERIMENT_ID,
        {
            "id": EXPERIMENT_ID,
            "local_id": "exp",
            "package_id": "pkg",
            "direction_id": "dir/main",
            "status": "PLANNED",
            "spec": experiment_spec(
                purpose="Evaluate retrieval",
                gate="R@1 >= 48",
            ),
            "scope_version": 1,
            "scope_status": "ACTIVE",
            "scope_confirmation": "CONFIRMED",
            "confirmed_direction_version": 1,
            "scope_source": SCOPE_SOURCE,
        },
    )

    management.commit_registry_add(
        paths,
        "paper",
        {"id": "dpr", "title": "Dense Passage Retrieval", "url": "https://example.test"},
        package_id="pkg",
    )
    management.commit_registry_add(
        paths,
        "gap",
        {"id": "g1", "summary": "No zero-shot evaluation"},
        package_id="pkg",
    )
    management.commit_evolution_learning(
        paths,
        {
            "id": "learning:metric",
            "observation": "Reproduce the baseline before claiming a lift.",
            "scope": {
                "project": "project/main",
                "packages": ["pkg"],
                "task_types": ["retrieval"],
            },
            "evidence_refs": [_ref()],
        },
        idempotency_key="learning:metric",
    )

    payload = build.query_json(paths, "pkg")
    md = context_pack.render_md(build.build(paths, "pkg")[0])
    assert payload["stamp"]["source_seq"] == EventStore(paths).state()["source_seq"]
    assert "Dense Passage Retrieval" in md
    assert "No zero-shot evaluation" in md
    assert "Reproduce the baseline before claiming a lift" in md
    assert not list(paths.root.rglob("context_pack.*"))
