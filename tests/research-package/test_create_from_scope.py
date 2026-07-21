"""State-only materialization contracts for research-package."""

from __future__ import annotations

import copy
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "skills/research-op/scripts"))
sys.path.insert(0, str(ROOT / "skills/research-package/scripts"))

from lib.research_state import EventStore, ResearchPaths  # noqa: E402
import create_from_scope  # noqa: E402
import management  # noqa: E402
from tests.scope_fixtures import (  # noqa: E402
    commit_accepted_scope,
    direction_node,
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
