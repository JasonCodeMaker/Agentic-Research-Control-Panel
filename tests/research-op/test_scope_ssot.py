"""Pure Scope validation contracts.

Persistence, replay, history, and consistency belong to ``research_state``.
This module verifies only Project, Direction, and Experiment intent shapes.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from lib import scope_ssot  # noqa: E402
from lib.scope_ssot import RuleViolation  # noqa: E402
from tests.scope_fixtures import (  # noqa: E402
    direction_node,
    experiment_node,
    project_node,
)


@pytest.mark.parametrize(
    "factory",
    [project_node, direction_node, experiment_node],
)
def test_formal_scope_nodes_are_valid(factory):
    scope_ssot.validate_node(factory())


def test_missing_required_spec_field_is_rejected():
    node = direction_node()
    del node["spec"]["success_gate"]
    with pytest.raises(RuleViolation, match="missing spec field"):
        scope_ssot.validate_node(node)


def test_out_of_schema_and_empirical_fields_are_rejected():
    node = direction_node()
    node["spec"]["measured"] = 0.5
    with pytest.raises(RuleViolation, match="reading field"):
        scope_ssot.validate_node(node)

    node = direction_node()
    node["spec"]["foobar"] = "not part of Direction intent"
    with pytest.raises(RuleViolation, match="unknown spec field"):
        scope_ssot.validate_node(node)


@pytest.mark.parametrize("old_field", ["yardstick", "provenance"])
def test_legacy_node_fields_are_rejected(old_field):
    node = direction_node()
    if old_field == "yardstick":
        node[old_field] = node.pop("spec")
    else:
        node[old_field] = node.pop("source")
    with pytest.raises(RuleViolation):
        scope_ssot.validate_node(node)


@pytest.mark.parametrize(
    "old_field",
    ["north_star", "success_predicate", "config_ref", "gate_predicate"],
)
def test_legacy_direction_spec_fields_are_rejected(old_field):
    node = direction_node()
    node["spec"][old_field] = "legacy value"
    with pytest.raises(RuleViolation):
        scope_ssot.validate_node(node)


def test_text_bounds_and_project_goal_exception():
    project = project_node(goal="Investigating Composed Video Retrieval")
    scope_ssot.validate_node(project)

    direction = direction_node(
        hypothesis="Investigating Composed Video Retrieval"
    )
    with pytest.raises(RuleViolation, match="20-100 words"):
        scope_ssot.validate_node(direction)

    direction = direction_node(
        success_gate=" ".join(f"word{i}" for i in range(101))
    )
    with pytest.raises(RuleViolation, match="20-100 words"):
        scope_ssot.validate_node(direction)


def test_project_list_fields_require_bounded_nonempty_items():
    node = project_node()
    node["spec"]["contributions"] = "not a list"
    with pytest.raises(RuleViolation, match="non-empty list"):
        scope_ssot.validate_node(node)

    node = project_node()
    node["spec"]["out_of_scope"] = ["too short"]
    with pytest.raises(RuleViolation, match="5-50 words"):
        scope_ssot.validate_node(node)


def test_experiment_uses_formal_spec_and_control_mode():
    node = experiment_node()
    assert set(node["spec"]) == {
        "purpose",
        "config_ref",
        "gate",
        "control_mode",
    }
    scope_ssot.validate_node(node)

    node["spec"]["control_mode"] = "reckless"
    with pytest.raises(RuleViolation, match="control_mode"):
        scope_ssot.validate_node(node)


def test_task_level_and_task_spec_are_not_runtime_adapters():
    node = experiment_node()
    node["level"] = "task"
    with pytest.raises(RuleViolation, match="illegal level"):
        scope_ssot.validate_node(node)

    node = experiment_node()
    node["spec"] = {
        "experiment": node["spec"]["purpose"],
        "config": node["spec"]["config_ref"],
        "gate": node["spec"]["gate"],
        "control_mode": node["spec"]["control_mode"],
    }
    with pytest.raises(RuleViolation, match="missing spec field"):
        scope_ssot.validate_node(node)


def test_parent_and_status_contracts_are_fail_closed():
    direction = direction_node()
    direction["parents"] = []
    with pytest.raises(RuleViolation, match="require a parent"):
        scope_ssot.validate_node(direction)

    project = project_node()
    project["parents"] = ["project/another"]
    with pytest.raises(RuleViolation, match="cannot have parents"):
        scope_ssot.validate_node(project)

    experiment = experiment_node(status="PLANNED")
    with pytest.raises(RuleViolation, match="status must be one of"):
        scope_ssot.validate_node(experiment)


def test_experiment_package_id_is_optional_but_typed():
    node = experiment_node()
    node["package_id"] = "pkg/retrieval-v2"
    scope_ssot.validate_node(node)

    node["package_id"] = ""
    with pytest.raises(RuleViolation, match="package_id"):
        scope_ssot.validate_node(node)
