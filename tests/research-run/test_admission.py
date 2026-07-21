"""State-only admission contract for /research-run."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "research-run" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import admission  # noqa: E402
from lib.research_state import UpgradeRequired  # noqa: E402
from state_fixtures import (  # noqa: E402
    CANONICAL_EXPERIMENT_ID,
    add_pending_direction,
    remove_interface,
    seed,
)


def _ok_adapter(role: str):
    def run(context):
        return {
            "agent_role": role,
            "assigned_scope": context["sourceExperiment"],
            "status": "ROLE_OK",
            "evidence": ["sha256:evidence"],
            "blockers": [],
            "recommended_next_action": "verify",
            "source_seq": context["source_seq"],
            "source_hash": context["source_hash"],
            "sourceDirection": context["sourceDirection"],
            "sourceExperiment": context["sourceExperiment"],
            "mutations": [],
        }

    return run


def test_empty_workspace_is_no_project_and_remains_uninitialized(tmp_path):
    assert admission.detect_admission_state(tmp_path) == "NO_PROJECT"
    assert not (tmp_path / ".research").exists()


def test_legacy_workspace_requires_explicit_upgrade(tmp_path):
    (tmp_path / "outputs").mkdir()
    with pytest.raises(UpgradeRequired, match="upgrade-required"):
        admission.detect_admission_state(tmp_path)


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        ({"project": True, "direction": False, "experiment": False, "package": False}, "NO_DIRECTION"),
        ({"project": True, "direction": True, "experiment": False, "package": False}, "NO_EXPERIMENT"),
        ({"project": True, "direction": True, "experiment": True, "package": False}, "NO_PACKAGE"),
    ],
)
def test_missing_management_record_selects_owning_handoff(
    tmp_path,
    options,
    expected,
):
    seed(tmp_path, **options)
    assert admission.detect_admission_state(tmp_path) == expected


def test_full_state_is_not_ready_until_readiness_passes(tmp_path):
    seed(tmp_path)
    assert admission.detect_admission_state(tmp_path, pkg_id="pkg-1") == "NOT_READY"
    assert (
        admission.detect_admission_state(
            tmp_path,
            pkg_id="pkg-1",
            readiness_ok=True,
        )
        == "READY"
    )


def test_explicit_unknown_package_is_not_silently_replaced(tmp_path):
    seed(tmp_path)
    with pytest.raises(KeyError, match="unknown package"):
        admission.build_research_context(tmp_path, pkg_id="missing")


def test_readiness_action_uses_experiment_control_mode(tmp_path):
    seed(tmp_path)
    result = admission.run_front_door(tmp_path, pkg_id="pkg-1")
    action = result["actions"][0]
    assert action["type"] == "RUN_READINESS"
    assert action["control_mode"] == "SUPERVISED"


def test_missing_interface_does_not_block_ready_state(tmp_path):
    paths = seed(tmp_path)
    remove_interface(paths)
    assert not paths.interface.exists()
    result = admission.run_front_door(
        tmp_path,
        pkg_id="pkg-1",
        readiness_ok=True,
        role_sequence=[],
        adapters={},
    )
    assert result["entered"] is True
    assert result["state"] == "READY"
    assert not paths.interface.exists()


def test_context_is_hash_stamped_and_experiment_is_canonical(tmp_path):
    seed(tmp_path)
    context = admission.build_research_context(tmp_path, pkg_id="pkg-1")
    assert context["source_seq"] > 0
    assert context["source_hash"]
    assert context["package"]["id"] == "pkg-1"
    assert (
        context["experiments"][0]["aggregate_id"]
        == CANONICAL_EXPERIMENT_ID
    )


def test_pending_proposal_blocks_entry_without_disposing_it(tmp_path):
    paths = seed(tmp_path)
    add_pending_direction(paths)
    result = admission.run_front_door(
        paths,
        pkg_id="pkg-1",
        readiness_ok=True,
    )
    assert result["entered"] is False
    assert result["actions"][0]["type"] == "AWAIT_TRIAGE_DECISION"
    assert result["actions"][0]["pending"] == ["proposal-direction"]


def test_ready_front_door_dispatches_experiment_with_state_stamp(tmp_path):
    seed(tmp_path)
    result = admission.run_front_door(
        tmp_path,
        pkg_id="pkg-1",
        readiness_ok=True,
        role_sequence=["verify"],
        adapters={"verify": _ok_adapter("verify")},
    )
    tick = result["tick"]
    assert tick["rejection"] is None
    assert tick["experiment_id"] == CANONICAL_EXPERIMENT_ID
    assert (
        tick["role_returns"][0]["sourceExperiment"]
        == CANONICAL_EXPERIMENT_ID
    )


def test_front_door_resolves_package_local_selection_to_scope_identity(tmp_path):
    seed(tmp_path)
    result = admission.run_front_door(
        tmp_path,
        pkg_id="pkg-1",
        experiment={"id": "P1", "local_id": "P1", "package_id": "pkg-1"},
        readiness_ok=True,
        role_sequence=["verify"],
        adapters={"verify": _ok_adapter("verify")},
    )
    assert result["tick"]["experiment_id"] == CANONICAL_EXPERIMENT_ID
    assert (
        result["tick"]["role_returns"][0]["sourceExperiment"]
        == CANONICAL_EXPERIMENT_ID
    )


def test_ready_front_door_can_use_the_selected_package_id(tmp_path):
    seed(tmp_path)
    result = admission.run_front_door(
        tmp_path,
        readiness_ok=True,
        role_sequence=[],
        adapters={},
    )
    assert result["tick"]["pkg"] == "pkg-1"


def test_admission_rejects_direct_write_mutation():
    rejected = admission.validate_admission_action(
        {
            "type": "ENTER_RUN_LOOP",
            "mutations": [
                {"op": "write_file", "target": "current-state", "payload": {}}
            ],
        }
    )
    assert rejected
    assert any("direct writes" in reason for reason in rejected["reasons"])
