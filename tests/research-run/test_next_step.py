"""Rendered handoffs for state-backed /research-run admission."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "research-run" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import admission  # noqa: E402
from state_fixtures import add_brainstorm, remove_interface, seed  # noqa: E402


def _render(state, context=None):
    action = admission.build_admission_actions(state, context)[0]
    return admission.render_next_step(action)


def test_every_admission_state_renders_a_complete_next_step():
    for state in admission.STATES:
        context = (
            {"direction_id": "dir/d1"}
            if state == "NO_PACKAGE"
            else None
        )
        step = _render(state, context)
        for key in ("headline", "next_action", "offer", "awaits_user", "details"):
            assert key in step
        assert step["headline"].strip()
        assert step["next_action"].strip()
        assert isinstance(step["awaits_user"], bool)


def test_missing_experiment_hands_back_to_scope():
    step = _render("NO_EXPERIMENT")
    assert step["awaits_user"] is True
    assert "/research-scope" in step["next_action"]
    assert "Experiment" in step["headline"]


def test_interface_state_is_not_part_of_admission():
    assert "NO_INTERFACE" not in admission.STATES
    assert all(
        "INTERFACE" not in action_type
        for action_type in admission.ACTION_TYPES
    )
    assert "interface projection" in _render("READY")["offer"]


def test_seed_direction_reads_brainstorm_state(tmp_path):
    paths = seed(
        tmp_path,
        direction=False,
        experiment=False,
        package=False,
    )
    add_brainstorm(paths, "idea-2026-01")
    add_brainstorm(paths, "idea-2026-02")
    candidate = admission.detect_seed_direction(paths)
    assert candidate["found"] is True
    assert candidate["idea"] == "idea-2026-02"
    assert set(candidate["candidates"]) == {
        "idea-2026-01",
        "idea-2026-02",
    }
    assert candidate["source"].startswith("brainstorm/")


def test_direction_handoff_includes_seed_and_rendered_step(tmp_path):
    paths = seed(
        tmp_path,
        direction=False,
        experiment=False,
        package=False,
    )
    add_brainstorm(paths, "idea-1")
    action = admission.build_admission_actions(
        "NO_DIRECTION",
        {},
        root=paths,
    )[0]
    assert action["seed"]["idea"] == "idea-1"
    assert "idea-1" in action["next_step"]["next_action"]
    assert action["next_step"]["awaits_user"] is True


def test_front_door_returns_handoff_without_interface(tmp_path):
    paths = seed(
        tmp_path,
        direction=False,
        experiment=False,
        package=False,
    )
    remove_interface(paths)
    result = admission.run_front_door(paths)
    assert result["state"] == "NO_DIRECTION"
    assert result["actions"][0]["type"] == "HANDOFF_DIRECTION"
    assert result["actions"][0]["next_step"]["next_action"]
    assert not paths.interface.exists()


def test_build_actions_without_root_remains_a_pure_action_builder():
    assert admission.build_admission_actions("NOT_READY", {}) == [
        {"type": "RUN_READINESS", "control_mode": "AUTONOMOUS"}
    ]
