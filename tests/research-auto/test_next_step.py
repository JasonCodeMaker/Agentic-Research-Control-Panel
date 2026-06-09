"""Next-Smooth-Step contract (Issue 2). Two things must hold and be guarded against the REAL chain:
  1. detect_seed_direction reads the shape the generator actually emits — a populated plan-invariants
     hypothesis in packages/<id>/plan.html (NOT a synthetic registry objectiveContract) — so it would
     have caught the session-b07d0f85 turn-3 failure (a direction sitting in plan.html, FSM said "none").
  2. The FSM itself (build_admission_actions / run_front_door) BAKES the seed + rendered next_step into
     the action at the real entry path — the smart part is not left to the agent reading SKILL prose.
"""

import sys
from pathlib import Path

_PIPE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PIPE / "skills" / "research-auto" / "scripts"))
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
    for state in ("A", "B", "C", "D", "E", "F", "G"):
        ctx = {"direction_id": "direction/x", "source_txn": "txn1"} if state == "E" else None
        step = _render(state, ctx)
        for key in ("headline", "next_action", "offer", "awaits_user", "details"):
            assert key in step, f"state {state}: missing {key}"
        assert step["headline"].strip(), f"state {state}: empty headline"
        assert step["next_action"].strip(), f"state {state}: empty next_action"
        assert isinstance(step["awaits_user"], bool)


def test_drafting_states_offer_one_tap_continue():
    step = _render("D")
    assert step["awaits_user"] is False
    assert "go" in step["offer"].lower()


def test_disposal_state_awaits_user():
    step = _render("D", {"pending": [{"id": "p1", "level": "task"}]})
    assert step["awaits_user"] is True
    assert "accept" in step["offer"].lower() or "reject" in step["offer"].lower()


def test_dashboard_handoff_points_at_the_command():
    step = _render("A")
    assert step["awaits_user"] is True
    assert "/research-dashboard" in step["next_action"]


def test_enter_loop_headline_is_plain_not_fsm_jargon():
    assert "State G" not in _render("G")["headline"]


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
    a = admission.build_admission_actions("C", {}, root=tmp_path)[0]
    assert a["type"] == "propose_direction"
    assert a["seed"]["found"] is True                          # attached by the FSM, not by prose
    assert "2026-06-08-grdr-efficiency-figures" in a["next_step"]["next_action"]
    assert a["next_step"]["awaits_user"] is False


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
                                   "version": 1, "status": "active",
                                   "yardstick": {}, "provenance": "t"},
                                  op="create", gate="user", log_path=log)
    res = admission.run_front_door(tmp_path, context={})
    assert res["state"] == "C"
    assert res["actions"][0]["next_step"]["next_action"].strip()


def test_build_actions_without_root_stays_raw():
    # back-compat: no root => no enrichment (keeps the pure contract other admission tests rely on)
    assert admission.build_admission_actions("F", {})[0] == {"type": "run_readiness", "dial": "autonomous"}
