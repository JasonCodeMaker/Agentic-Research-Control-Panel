"""Stage 0.5 front-door admission: /research-auto becomes the post-init front door — it may DISCOVER
that Step-3 formation is missing and RUN the formation roles, but it must never ratify Triage or
materialize a package from pending proposals. Formation capability lives in auto; commit authority
stays with the user / Triage.
"""

import sys
from pathlib import Path

_PIPE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PIPE / "skills" / "research-auto" / "scripts"))
sys.path.insert(0, str(_PIPE / "lib"))
import admission  # noqa: E402
import scope_ssot  # noqa: E402


# ---- fixtures ----

def _dashboard(root, *, inventory="window.RESEARCH_PACKAGES = [];\n"):
    (root / "research_html").mkdir(parents=True, exist_ok=True)
    (root / "research_html" / "index.html").write_text("<html></html>", encoding="utf-8")
    (root / "research_html" / "data").mkdir(parents=True, exist_ok=True)
    (root / "research_html" / "data" / "research-packages.js").write_text(inventory, encoding="utf-8")


def _log(root):
    return root / "outputs" / "_scope" / "transitions.jsonl"


def _project(root):
    scope_ssot.propose_transition(
        {"id": "project/main", "level": "project", "parents": [], "version": 1, "status": "active",
         "yardstick": {"north_star": "trustworthy auto research", "contribution_spine": "SSOT+gates",
                       "non_goals": "none"}, "provenance": "triage:p1"},
        op="create", gate="user", log_path=_log(root), trigger="t", cause="c")


def _direction(root):
    scope_ssot.propose_transition(
        {"id": "dir/d1", "level": "direction", "parents": ["project/main"], "version": 1,
         "status": "active",
         "yardstick": {"hypothesis": "X improves recall", "metric": {"name": "recall", "dir": "higher"},
                       "baselines": ["b0"], "success_predicate": "measured >= 0.80"},
         "provenance": "triage:d1"},
        op="create", gate="user+xmodel-audit", log_path=_log(root), trigger="t", cause="c")


def _task(root):
    scope_ssot.propose_transition(
        {"id": "task/d1/m1", "level": "task", "parents": ["dir/d1"], "version": 1, "status": "active",
         "yardstick": {"experiment": "validate", "config_ref": "scope:dir/d1#m1",
                       "gate_predicate": "measured >= 0.80", "autonomy_level": "supervised"},
         "provenance": "triage:m1"},
        op="create", gate="agent+async-ack", log_path=_log(root), trigger="t", cause="c")


# ---- state detection ----

def test_state_A_dashboard_missing(tmp_path):
    assert admission.detect_admission_state(tmp_path) == "A"


def test_state_B_no_project(tmp_path):
    _dashboard(tmp_path)
    assert admission.detect_admission_state(tmp_path) == "B"


def test_state_C_project_no_direction(tmp_path):
    _dashboard(tmp_path); _project(tmp_path)
    assert admission.detect_admission_state(tmp_path) == "C"


def test_state_E_direction_task_no_package(tmp_path):
    _dashboard(tmp_path); _project(tmp_path); _direction(tmp_path); _task(tmp_path)
    assert admission.detect_admission_state(tmp_path) == "E"


def test_state_G_full_and_ready(tmp_path):
    _dashboard(tmp_path, inventory='window.RESEARCH_PACKAGES = [{id: "p1", sourceScopeNode: "dir/d1"}];\n')
    _project(tmp_path); _direction(tmp_path); _task(tmp_path)
    assert admission.detect_admission_state(tmp_path, readiness_ok=True) == "G"


# ---- plan's six required tests ----

def test_1_no_project_proposes_and_never_commits(tmp_path):
    _dashboard(tmp_path)
    state = admission.detect_admission_state(tmp_path)
    actions = admission.build_admission_actions(state, {})
    assert actions[0]["type"] == "propose_project"
    assert not _log(tmp_path).exists()          # no scope-transition committed


def test_2_no_direction_proposes_no_package(tmp_path):
    _dashboard(tmp_path); _project(tmp_path)
    actions = admission.build_admission_actions(admission.detect_admission_state(tmp_path), {})
    assert actions[0]["type"] == "propose_direction"
    assert not any(a["type"] == "materialize_package" for a in actions)
    assert not (tmp_path / "research_html" / "packages").exists()


def test_3_pending_triage_does_not_duplicate(tmp_path):
    _dashboard(tmp_path); _project(tmp_path)
    ctx = {"pending": [{"id": "tri-1", "level": "direction"}]}
    actions = admission.build_admission_actions(admission.detect_admission_state(tmp_path), ctx)
    assert actions[0]["type"] == "block_for_user_disposal"
    assert not any(a["type"] == "propose_direction" for a in actions)


def test_task_proposal_defaults_to_autonomous_and_surfaces_choices(tmp_path):
    _dashboard(tmp_path); _project(tmp_path); _direction(tmp_path)
    actions = admission.build_admission_actions(admission.detect_admission_state(tmp_path), {})
    assert actions[0]["type"] == "propose_task"
    assert actions[0]["autonomy_level"] == "autonomous"
    assert actions[0]["proposal"]["yardstick"]["autonomy_level"] == "autonomous"
    assert actions[0]["autonomy_choices"] == ["supervised", "checkpoints", "async", "autonomous"]


def test_task_proposal_context_can_override_default_autonomy(tmp_path):
    _dashboard(tmp_path); _project(tmp_path); _direction(tmp_path)
    ctx = {"autonomy_level": "async",
           "task_proposal": {"yardstick": {"experiment": "validate"}}}
    actions = admission.build_admission_actions(admission.detect_admission_state(tmp_path), ctx)
    assert actions[0]["autonomy_level"] == "async"
    assert actions[0]["proposal"]["yardstick"]["autonomy_level"] == "async"


def test_task_proposal_override_updates_existing_yardstick_autonomy(tmp_path):
    _dashboard(tmp_path); _project(tmp_path); _direction(tmp_path)
    ctx = {"autonomy_level": "async",
           "task_proposal": {"yardstick": {"experiment": "validate", "autonomy_level": "supervised"}}}
    actions = admission.build_admission_actions(admission.detect_admission_state(tmp_path), ctx)
    assert actions[0]["autonomy_level"] == "async"
    assert actions[0]["proposal"]["yardstick"]["autonomy_level"] == "async"


def test_readiness_default_dial_is_autonomous(tmp_path):
    _dashboard(tmp_path, inventory='window.RESEARCH_PACKAGES = [{id: "p1", sourceScopeNode: "dir/d1"}];\n')
    _project(tmp_path); _direction(tmp_path); _task(tmp_path)
    actions = admission.build_admission_actions(admission.detect_admission_state(tmp_path), {})
    assert actions[0] == {"type": "run_readiness", "dial": "autonomous"}


def test_invalid_autonomy_level_rejected():
    assert admission.validate_admission_action(
        {"type": "propose_task", "autonomy_level": "reckless"}) is not None
    assert admission.validate_admission_action(
        {"type": "run_readiness", "dial": "reckless"}) is not None


def test_autonomy_mismatch_rejected():
    rej = admission.validate_admission_action({
        "type": "propose_task",
        "autonomy_level": "async",
        "proposal": {"yardstick": {"autonomy_level": "supervised"}},
    })
    assert rej is not None and any("mismatch" in r for r in rej["reasons"])


def test_4_materialize_reads_committed_only():
    committed = {"type": "materialize_package", "from": "committed", "sourceScopeTxn": "txn-abc"}
    assert admission.validate_admission_action(committed) is None
    pending = {"type": "materialize_package", "from": "pending"}
    rej = admission.validate_admission_action(pending)
    assert rej is not None and any("committed" in r for r in rej["reasons"])


def test_5_ready_package_enters_loop(tmp_path):
    _dashboard(tmp_path, inventory='window.RESEARCH_PACKAGES = [{id: "p1", sourceScopeNode: "dir/d1"}];\n')
    _project(tmp_path); _direction(tmp_path); _task(tmp_path)
    node = {"id": "dir/d1", "level": "direction", "parents": ["project/main"], "version": 1,
            "status": "active",
            "yardstick": {"hypothesis": "X improves recall", "metric": {"name": "recall", "dir": "higher"},
                          "baselines": ["b0"], "success_predicate": "measured >= 0.80"},
            "provenance": "triage:d1"}
    adapters = {"scope": lambda ctx: {"agent_role": "scope", "assigned_scope": "dir/d1", "status": "ok",
                                      "evidence": ["e"], "blockers": [], "recommended_next_action": "go"}}
    result = admission.run_front_door(tmp_path, pkg_id="p1", scope_node=node,
                                      role_sequence=["scope"], adapters=adapters, readiness_ok=True)
    assert result["entered"] is True
    assert result["tick"]["rejection"] is None


def test_6_authority_cannot_be_smuggled():
    # a disposal decision
    assert admission.validate_admission_action({"type": "propose_direction", "decision": "accept"}) is not None
    # an SSOT commit disguised as a role mutation
    smuggle_commit = {"type": "propose_direction",
                      "mutations": [{"op": "scope-transition", "target": "dir/d1", "payload": {}}]}
    rej = admission.validate_admission_action(smuggle_commit)
    assert rej is not None and any("scope-transition" in r for r in rej["reasons"])
    # a direct package write
    smuggle_write = {"type": "propose_direction",
                     "mutations": [{"op": "write_file", "target": "research_html/packages/p1/results.html",
                                    "payload": {}}]}
    assert admission.validate_admission_action(smuggle_write) is not None
