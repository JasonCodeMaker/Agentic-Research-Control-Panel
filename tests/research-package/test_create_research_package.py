"""Manual state-backed research package creation contracts."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "skills/research-op/scripts"))
sys.path.insert(0, str(ROOT / "skills/research-package/scripts"))

from lib.research_state import CommandRejected, EventStore, ResearchPaths  # noqa: E402
import create_research_package  # noqa: E402
import management  # noqa: E402
from tests.scope_fixtures import (  # noqa: E402
    commit_accepted_scope,
    direction_node,
    experiment_node,
    project_node,
)


def test_manual_creation_commits_package_and_experiment_state(tmp_path):
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    scope_experiment = experiment_node(
        node_id="experiment/retrieval-v2/M0-baseline",
        source="scope-review:m0",
    )
    for node in (project_node(), direction_node(), scope_experiment):
        commit_accepted_scope(management, paths, node)
    direction_event = next(
        event
        for event in reversed(EventStore(paths).events())
        if event["aggregate_type"] == "direction"
        and event["aggregate_id"] == "dir/retrieval-v2"
    )
    experiment = {
        "scope_experiment_id": scope_experiment["id"],
        "local_id": "P0",
        "status": "READY",
        "measures": True,
    }

    result = create_research_package.main(
        [
            "--workspace",
            str(tmp_path),
            "--id",
            "2026-07-20-manual-package",
            "--name",
            "Manual package",
            "--category",
            "in-progress",
            "--tag",
            "manual",
            "--tag-meaning",
            "Direct state-backed package",
            "--problem",
            "Verify the retrieval baseline",
            "--objective",
            "Establish one reproducible comparison",
            "--motivation",
            "Pin evidence before method changes",
            "--hypothesis",
            "The declared baseline is reproducible",
            "--primary-metric",
            "Recall@10",
            "--source-direction",
            "dir/retrieval-v2",
            "--source-version",
            "1",
            "--source-change",
            direction_event["event_id"],
            "--source-experiments",
            json.dumps(
                [
                    {
                        "id": "experiment/retrieval-v2/M0-baseline",
                        "version": 1,
                        "source": "scope-review:m0",
                    }
                ]
            ),
            "--experiments",
            json.dumps([experiment]),
        ]
    )

    assert result == 0
    state = EventStore(paths).state()
    package = state["aggregates"]["package"][
        "2026-07-20-manual-package"
    ]
    committed = state["aggregates"]["experiment"][scope_experiment["id"]]
    assert package["artifactRoot"] == (
        ".research/experiments/2026-07-20-manual-package/"
    )
    assert package["direction_id"] == "dir/retrieval-v2"
    assert package["sourceExperiments"] == [
        {
            "id": "experiment/retrieval-v2/M0-baseline",
            "version": 1,
            "source": "scope-review:m0",
        }
    ]
    assert committed["spec"] == scope_experiment["spec"]
    assert committed["id"] == scope_experiment["id"]
    assert committed["package_id"] == "2026-07-20-manual-package"
    assert committed["local_id"] == "P0"
    assert committed["output"] == (
        ".research/experiments/2026-07-20-manual-package/"
        "P0/<run-id>/result.json"
    )


@pytest.mark.parametrize(
    "retired",
    [
        "localId",
        "controlMode",
        "config",
        "sourceTask",
        "source_task_id",
        "source_task",
    ],
)
def test_experiment_normalizer_rejects_retired_task_adapters(retired):
    row = {
        "scope_experiment_id": "experiment/retrieval-v2/M0-baseline",
        "local_id": "P0",
        retired: "legacy",
    }
    with pytest.raises(CommandRejected, match="cannot define or copy"):
        management.normalize_experiment_binding("package", row)
