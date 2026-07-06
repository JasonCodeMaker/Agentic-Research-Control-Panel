"""Admission for /research-run: it only runs an existing scoped package.

If setup, scope, task, or package materialization is missing, it returns a handoff action to the owning
skill instead of forming scope or creating package surfaces itself.
"""

import sys
from pathlib import Path

_PIPE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PIPE / "skills" / "research-run" / "scripts"))
sys.path.insert(0, str(_PIPE / "lib"))
import admission  # noqa: E402
import scope_ssot  # noqa: E402
from tests.scope_fixtures import direction_node, project_node, task_node  # noqa: E402


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
        project_node(),
        op="create", gate="USER_ONLY", log_path=_log(root), trigger="t", cause="c")


def _direction(root):
    scope_ssot.propose_transition(
        direction_node("dir/d1", source="triage:d1"),
        op="create", gate="USER_CROSS_MODEL_AUDIT", log_path=_log(root), trigger="t", cause="c")


def _task(root):
    scope_ssot.propose_transition(
        task_node("task/d1/m1", parent="dir/d1", source="triage:m1",
                  config="scope:dir/d1#m1", control_mode="SUPERVISED"),
        op="create", gate="AGENT_DEFERRED_ACK", log_path=_log(root), trigger="t", cause="c")


def _pending(root, item):
    path = root / "outputs" / "_scope" / "triage.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(__import__("json").dumps({**item, "status": "pending"}) + "\n", encoding="utf-8")


# ---- state detection ----

def test_state_NO_DASHBOARD_missing(tmp_path):
    assert admission.detect_admission_state(tmp_path) == "NO_DASHBOARD"


def test_state_NO_PROJECT(tmp_path):
    _dashboard(tmp_path)
    assert admission.detect_admission_state(tmp_path) == "NO_PROJECT"


def test_state_NO_DIRECTION(tmp_path):
    _dashboard(tmp_path); _project(tmp_path)
    assert admission.detect_admission_state(tmp_path) == "NO_DIRECTION"


def test_state_NO_PACKAGE(tmp_path):
    _dashboard(tmp_path); _project(tmp_path); _direction(tmp_path); _task(tmp_path)
    assert admission.detect_admission_state(tmp_path) == "NO_PACKAGE"


def test_state_READY_full_and_ready(tmp_path):
    _dashboard(tmp_path, inventory='window.RESEARCH_PACKAGES = [{id: "p1", sourceDirection: "dir/d1"}];\n')
    _project(tmp_path); _direction(tmp_path); _task(tmp_path)
    assert admission.detect_admission_state(tmp_path, readiness_ok=True) == "READY"


def test_scope_context_summary_is_returned_for_ready_package(tmp_path):
    _dashboard(
        tmp_path,
        inventory=(
            'window.RESEARCH_PACKAGES = [{id: "p1", sourceDirection: "dir/d1", '
            'sourceVersion: "1", sourceTasks: [{id: "task/d1/m1"}], '
            'experiments: [{id: "P0", sourceTask: "task/d1/m1"}]}];\n'
        ),
    )
    _project(tmp_path); _direction(tmp_path); _task(tmp_path)
    node = direction_node("dir/d1", source="triage:d1")
    adapters = {
        "scope": lambda ctx: {
            "agent_role": "scope",
            "assigned_scope": "dir/d1",
            "global_scope_version": ctx["global_scope_version"],
            "sourceDirection": "dir/d1",
            "sourceTask": "task/d1/m1",
            "status": "ROLE_OK",
            "evidence": ["e"],
            "blockers": [],
            "recommended_next_action": "go",
        }
    }
    result = admission.run_front_door(tmp_path, pkg_id="p1", scope_node=node,
                                      role_sequence=["scope"], adapters=adapters,
                                      readiness_ok=True)
    ctx = result["scope_context"]
    assert ctx["global_scope_version"] == 3
    assert ctx["project"]["id"] == "project/main"
    assert ctx["direction"]["id"] == "dir/d1"
    assert ctx["tasks"][0]["id"] == "task/d1/m1"
    assert ctx["package"]["sourceDirection"] == "dir/d1"
    assert result["tick"]["role_returns"][0]["global_scope_version"] == 3


def test_scope_context_summary_is_returned_for_handoff(tmp_path):
    _dashboard(tmp_path)
    _project(tmp_path)
    result = admission.run_front_door(tmp_path)
    assert result["entered"] is False
    assert result["state"] == "NO_DIRECTION"
    assert result["scope_context"]["global_scope_version"] == 1
    assert result["scope_context"]["project"]["id"] == "project/main"


def test_relevant_pending_scope_blocks_ready_run(tmp_path):
    _dashboard(tmp_path, inventory='window.RESEARCH_PACKAGES = [{id: "p1", sourceDirection: "dir/d1"}];\n')
    _project(tmp_path); _direction(tmp_path); _task(tmp_path)
    _pending(tmp_path, {"id": "triage-dir", "level": "direction", "node_id": "dir/d1"})
    node = direction_node("dir/d1", source="triage:d1")
    adapters = {"scope": lambda ctx: (_ for _ in ()).throw(AssertionError("dispatch should not run"))}

    result = admission.run_front_door(tmp_path, pkg_id="p1", scope_node=node,
                                      role_sequence=["scope"], adapters=adapters,
                                      readiness_ok=True)

    assert result["entered"] is False
    assert result["state"] == "READY"
    assert result["actions"][0]["type"] == "AWAIT_TRIAGE_DECISION"
    assert result["actions"][0]["pending"] == ["triage-dir"]
    assert result["scope_context"]["pending_scope"][0]["id"] == "triage-dir"


# ---- plan's six required tests ----

def test_1_no_project_hands_off_and_never_commits(tmp_path):
    _dashboard(tmp_path)
    state = admission.detect_admission_state(tmp_path)
    actions = admission.build_admission_actions(state, {})
    assert actions[0]["type"] == "HANDOFF_PROJECT"
    assert actions[0]["handoff"] in {"/research-onboard", "/research-scope"}
    assert not _log(tmp_path).exists()          # no scope-transition committed


def test_2_no_direction_hands_off_no_package(tmp_path):
    _dashboard(tmp_path); _project(tmp_path)
    actions = admission.build_admission_actions(admission.detect_admission_state(tmp_path), {})
    assert actions[0]["type"] == "HANDOFF_DIRECTION"
    assert actions[0]["handoff"] == "/research-brainstorm"
    assert not any(a["type"] == "MATERIALIZE_PACKAGE" for a in actions)
    assert not (tmp_path / "research_html" / "packages").exists()


def test_3_pending_triage_waits_instead_of_running(tmp_path):
    _dashboard(tmp_path); _project(tmp_path)
    ctx = {"pending": [{"id": "tri-1", "level": "direction"}]}
    actions = admission.build_admission_actions(admission.detect_admission_state(tmp_path), ctx)
    assert actions[0]["type"] == "AWAIT_TRIAGE_DECISION"
    assert not any(a["type"] == "HANDOFF_DIRECTION" for a in actions)


def test_no_task_hands_off_to_scope_milestones(tmp_path):
    _dashboard(tmp_path); _project(tmp_path); _direction(tmp_path)
    actions = admission.build_admission_actions(admission.detect_admission_state(tmp_path), {})
    assert actions[0]["type"] == "HANDOFF_TASK"
    assert actions[0]["handoff"] == "/research-scope"


def test_no_package_hands_off_to_package_materializer(tmp_path):
    _dashboard(tmp_path); _project(tmp_path); _direction(tmp_path); _task(tmp_path)
    actions = admission.build_admission_actions(admission.detect_admission_state(tmp_path), {})
    assert actions[0]["type"] == "HANDOFF_PACKAGE"
    assert actions[0]["handoff"] == "/research-package"


def test_readiness_default_control_mode_is_autonomous(tmp_path):
    _dashboard(tmp_path, inventory='window.RESEARCH_PACKAGES = [{id: "p1", sourceDirection: "dir/d1"}];\n')
    _project(tmp_path); _direction(tmp_path); _task(tmp_path)
    actions = admission.build_admission_actions(admission.detect_admission_state(tmp_path), {})
    assert actions[0] == {"type": "RUN_READINESS", "control_mode": "AUTONOMOUS"}


def test_invalid_control_mode_rejected_for_readiness():
    assert admission.validate_admission_action(
        {"type": "RUN_READINESS", "control_mode": "reckless"}) is not None


def test_5_ready_package_enters_loop(tmp_path):
    _dashboard(tmp_path, inventory='window.RESEARCH_PACKAGES = [{id: "p1", sourceDirection: "dir/d1"}];\n')
    _project(tmp_path); _direction(tmp_path); _task(tmp_path)
    node = direction_node("dir/d1", source="triage:d1")
    adapters = {"scope": lambda ctx: {"agent_role": "scope", "assigned_scope": "dir/d1",
                                      "global_scope_version": ctx["global_scope_version"],
                                      "sourceDirection": "dir/d1", "sourceTask": "task/d1/m1",
                                      "status": "ROLE_OK", "evidence": ["e"], "blockers": [],
                                      "recommended_next_action": "go"}}
    result = admission.run_front_door(tmp_path, pkg_id="p1", scope_node=node,
                                      role_sequence=["scope"], adapters=adapters, readiness_ok=True)
    assert result["entered"] is True
    assert result["tick"]["rejection"] is None


def test_6_authority_cannot_be_smuggled():
    # a disposal decision
    assert admission.validate_admission_action({"type": "HANDOFF_DIRECTION", "decision": "accept"}) is not None
    # an SSOT commit disguised as a role mutation
    smuggle_commit = {"type": "HANDOFF_DIRECTION",
                      "mutations": [{"op": "scope-transition", "target": "dir/d1", "payload": {}}]}
    rej = admission.validate_admission_action(smuggle_commit)
    assert rej is not None and any("scope-transition" in r for r in rej["reasons"])
    # a direct package write
    smuggle_write = {"type": "HANDOFF_DIRECTION",
                     "mutations": [{"op": "write_file", "target": "research_html/packages/p1/results.html",
                                    "payload": {}}]}
    assert admission.validate_admission_action(smuggle_write) is not None
