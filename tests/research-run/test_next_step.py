"""Next-step contract for /research-run admission. Two things must hold against the real chain:
  1. detect_seed_direction reads the shape the generator actually emits — a populated plan-invariants
     hypothesis in packages/<id>/plan.html (NOT a synthetic registry objectiveContract).
  2. The FSM itself (build_admission_actions / run_front_door) BAKES the seed + rendered next_step into
     the action at the real entry path, while still handing formation to the owning skill.
"""

import sys
from pathlib import Path

_PIPE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PIPE / "skills" / "research-run" / "scripts"))
sys.path.insert(0, str(_PIPE / "lib"))
import admission  # noqa: E402


def _scaffold_plan(root, pkg, hypothesis):
    """Write a packages/<pkg>/plan.html with the real plan-invariants hypothesis cell the generator emits."""
    d = root / "research_html" / "packages" / pkg
    d.mkdir(parents=True)
    (d / "plan.html").write_text(
        '<section data-section="plan-invariants"><ol data-list="plan-invariants">'
        '<li class="plan-invariant" data-field="hypothesis-one-line" data-invariant="hypothesis">'
        f'<span class="invariant-k">Hypothesis</span> <span class="invariant-v">{hypothesis}</span></li>'
        '</ol></section>', encoding="utf-8")


def _render(state, context=None, root=None):
    actions = admission.build_admission_actions(state, context)
    return admission.render_next_step(actions[0], root=root)


# ---- render_next_step: shape + non-emptiness for every action type ----

def test_every_action_renders_a_nonempty_next_step():
    for state in ("NO_DASHBOARD", "NO_PROJECT", "NO_DIRECTION", "NO_TASK",
                  "NO_PACKAGE", "NOT_READY", "READY"):
        ctx = {"direction_id": "direction/x", "source_txn": "txn1"} if state == "NO_PACKAGE" else None
        step = _render(state, ctx)
        for key in ("headline", "next_action", "offer", "awaits_user", "details"):
            assert key in step, f"state {state}: missing {key}"
        assert step["headline"].strip(), f"state {state}: empty headline"
        assert step["next_action"].strip(), f"state {state}: empty next_action"
        assert isinstance(step["awaits_user"], bool)


def test_missing_task_hands_off_instead_of_one_tap_continue():
    step = _render("NO_TASK")
    assert step["awaits_user"] is True
    assert "/research-scope" in step["next_action"]


def test_disposal_state_awaits_user():
    step = _render("NO_TASK", {"pending": [{"id": "p1", "level": "task"}]})
    assert step["awaits_user"] is True
    assert "accept" in step["offer"].lower() or "reject" in step["offer"].lower()


def test_dashboard_handoff_points_at_the_command():
    step = _render("NO_DASHBOARD")
    assert step["awaits_user"] is True
    assert "/research-dashboard" in step["next_action"]


def test_enter_loop_headline_is_plain_not_fsm_jargon():
    assert "READY" not in _render("READY")["headline"]


# ---- detect_seed_direction: reads the REAL on-disk shape ----

def test_detect_seed_reads_real_planhtml(tmp_path):
    _scaffold_plan(tmp_path, "2026-06-08-grdr-efficiency-figures",
                   "H1: at a matched ~300 candidate budget GRDR total latency <= every ANN baseline.")
    seed = admission.detect_seed_direction(tmp_path)
    assert seed["found"] is True
    assert seed["pkg"] == "2026-06-08-grdr-efficiency-figures"
    assert "plan.html" in seed["source"]


def test_detect_seed_ignores_unscaffolded_placeholder(tmp_path):
    _scaffold_plan(tmp_path, "2026-06-09-fresh", "$hypothesis")
    assert admission.detect_seed_direction(tmp_path)["found"] is False


def test_detect_seed_absent_when_no_packages(tmp_path):
    (tmp_path / "research_html" / "packages").mkdir(parents=True)
    assert admission.detect_seed_direction(tmp_path)["found"] is False


def test_detect_seed_picks_newest_and_lists_candidates(tmp_path):
    _scaffold_plan(tmp_path, "2026-06-01-older", "H1: older drafted direction hypothesis text here.")
    _scaffold_plan(tmp_path, "2026-06-08-newer", "H1: newer drafted direction hypothesis text here.")
    seed = admission.detect_seed_direction(tmp_path)
    assert seed["pkg"] == "2026-06-08-newer"
    assert set(seed["candidates"]) == {"2026-06-08-newer", "2026-06-01-older"}


# ---- the WIRING test: the FSM bakes seed + next_step into the real entry path ----

def test_build_actions_bakes_seed_and_next_step_at_state_C(tmp_path):
    _scaffold_plan(tmp_path, "2026-06-08-grdr-efficiency-figures",
                   "H1: GRDR total latency <= every ANN baseline at a matched candidate budget.")
    a = admission.build_admission_actions("NO_DIRECTION", {}, root=tmp_path)[0]
    assert a["type"] == "HANDOFF_DIRECTION"
    assert a["seed"]["found"] is True                          # attached by the FSM, not by prose
    assert "/research-scope" in a["next_step"]["next_action"]
    assert "2026-06-08-grdr-efficiency-figures" in a["next_step"]["next_action"]
    assert a["next_step"]["awaits_user"] is True


def test_run_front_door_emits_next_step(tmp_path):
    _scaffold_plan(tmp_path, "2026-06-08-grdr-efficiency-figures",
                   "H1: GRDR total latency <= every ANN baseline at a matched candidate budget.")
    (tmp_path / "research_html" / "index.html").write_text("<html></html>", encoding="utf-8")
    (tmp_path / "research_html" / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "research_html" / "data" / "research-packages.js").write_text(
        "window.RESEARCH_PACKAGES = [];\n", encoding="utf-8")
    import scope_ssot  # noqa: E402
    log = tmp_path / "outputs" / "_scope" / "transitions.jsonl"
    scope_ssot.propose_transition({"id": "project/grdr", "level": "project", "parents": [],
                                   "version": 1, "status": "ACTIVE",
                                   "spec": {}, "source": "t"},
                                  op="create", gate="USER_ONLY", log_path=log)
    res = admission.run_front_door(tmp_path, context={})
    assert res["state"] == "NO_DIRECTION"
    assert res["actions"][0]["next_step"]["next_action"].strip()


def test_build_actions_without_root_stays_raw():
    # back-compat: no root => no enrichment (keeps the pure contract other admission tests rely on)
    assert admission.build_admission_actions("NOT_READY", {})[0] == {"type": "RUN_READINESS", "control_mode": "AUTONOMOUS"}
