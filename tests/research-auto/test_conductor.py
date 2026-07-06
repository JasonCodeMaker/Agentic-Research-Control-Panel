"""Conductor for /research-auto: deterministic campaign routing over one Direction.

The conductor owns gate parsing/evaluation, the typed campaign ledger, the cycle router, and the
authority guard. It never writes a package surface, never writes the SSOT, never disposes Triage.
"""

import json
import sys
from pathlib import Path

_PIPE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PIPE / "skills" / "research-auto" / "scripts"))
sys.path.insert(0, str(_PIPE / "lib"))
import conductor  # noqa: E402
import scope_ssot  # noqa: E402


# ---- fixtures ----

def _direction_node():
    return {"id": "dir/d1", "level": "direction", "parents": ["project/main"], "version": 1,
            "status": "ACTIVE",
            "spec": {"hypothesis": "X improves recall", "metric": {"name": "R@1"},
                          "baselines": ["b0=42.3"], "success_gate": "R@1 >= 48"},
            "source": "triage:d1"}


def _cycle_record(**over):
    rec = {"cycle": 1, "direction_id": "dir/d1", "pkg_id": "2026-06-12-d1", "exp_id": "P1",
           "hypothesis": "X improves recall", "verdict": "FAIL", "measured": "46.1",
           "gate_eval": "FAIL", "evidence": "outputs/2026-06-12-d1/P1/result.json",
           "next_action": "DESIGN_EXPERIMENT"}
    rec.update(over)
    return rec


def _registry(root, body):
    data = root / "research_html" / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "research-packages.js").write_text(body, encoding="utf-8")


def _commit_direction(root):
    scope_ssot.propose_transition(
        _direction_node(), op="create", gate="USER_CROSS_MODEL_AUDIT",
        log_path=root / "outputs" / "_scope" / "transitions.jsonl", trigger="t", cause="c")


# ---- gate parsing + evaluation ----

def test_parse_gate_ge():
    assert conductor.parse_gate("R@1 >= 48 on held-out seed") == {"cmp": ">=", "threshold": 48.0}


def test_parse_gate_le():
    assert conductor.parse_gate("val loss <= 0.5") == {"cmp": "<=", "threshold": 0.5}


def test_parse_gate_strict_forms():
    assert conductor.parse_gate("accuracy > 0.8")["cmp"] == ">"
    assert conductor.parse_gate("latency < 120")["cmp"] == "<"


def test_parse_gate_measured_form():
    assert conductor.parse_gate("measured >= 0.80") == {"cmp": ">=", "threshold": 0.80}


def test_parse_gate_unparseable_raises():
    try:
        conductor.parse_gate("beats the baseline convincingly")
    except conductor.GateUnparseable:
        return
    raise AssertionError("expected GateUnparseable")


def test_evaluate_gate():
    assert conductor.evaluate_gate(48.2, "R@1 >= 48") == "PASS"
    assert conductor.evaluate_gate("47.9", "R@1 >= 48") == "FAIL"
    assert conductor.evaluate_gate(0.4, "loss <= 0.5") == "PASS"


# ---- campaign ledger (reject-before-write) ----

def test_append_cycle_rejects_missing_field(tmp_path):
    ledger = tmp_path / "campaign.jsonl"
    rec = _cycle_record()
    del rec["measured"]
    try:
        conductor.append_cycle(ledger, rec)
    except ValueError:
        assert not ledger.exists()
        return
    raise AssertionError("expected ValueError for missing field")


def test_append_cycle_rejects_blank_field(tmp_path):
    try:
        conductor.append_cycle(tmp_path / "c.jsonl", _cycle_record(evidence="  "))
    except ValueError:
        return
    raise AssertionError("expected ValueError for blank field")


def test_append_cycle_rejects_bad_verdict(tmp_path):
    try:
        conductor.append_cycle(tmp_path / "c.jsonl", _cycle_record(verdict="WIN"))
    except ValueError:
        return
    raise AssertionError("expected ValueError for illegal verdict")


def test_append_cycle_rejects_bad_gate_eval(tmp_path):
    try:
        conductor.append_cycle(tmp_path / "c.jsonl", _cycle_record(gate_eval="MAYBE"))
    except ValueError:
        return
    raise AssertionError("expected ValueError for illegal gate_eval")


def test_append_cycle_gate_pass_requires_verdict_pass(tmp_path):
    try:
        conductor.append_cycle(tmp_path / "c.jsonl",
                               _cycle_record(verdict="INCONCLUSIVE", gate_eval="PASS"))
    except ValueError:
        return
    raise AssertionError("a non-PASS verdict must not clear the campaign gate")


def test_append_and_read_roundtrip(tmp_path):
    ledger = tmp_path / "campaign.jsonl"
    written = conductor.append_cycle(ledger, _cycle_record())
    assert written["ts"]
    rows = conductor.read_ledger(ledger)
    assert len(rows) == 1 and rows[0]["pkg_id"] == "2026-06-12-d1"


def test_ledger_path_slug(tmp_path):
    p = conductor.ledger_path(tmp_path, "dir/retrieval-v2")
    assert p == tmp_path / "outputs" / "_auto" / "retrieval-v2" / "campaign.jsonl"


# ---- campaign status ----

def test_campaign_status_empty():
    s = conductor.campaign_status([], max_cycles=5)
    assert s == {"cycles_used": 0, "gate_met": False, "budget_exhausted": False, "last": None}


def test_campaign_status_gate_met():
    recs = [_cycle_record(), _cycle_record(cycle=2, verdict="PASS", gate_eval="PASS",
                                           measured="48.4", next_action="SUCCESS_EXIT")]
    s = conductor.campaign_status(recs, max_cycles=5)
    assert s["gate_met"] and s["cycles_used"] == 2 and not s["budget_exhausted"]
    assert s["last"]["gate_eval"] == "PASS"


def test_campaign_status_budget_exhausted():
    recs = [_cycle_record(), _cycle_record(cycle=2)]
    s = conductor.campaign_status(recs, max_cycles=2)
    assert s["budget_exhausted"] and not s["gate_met"]


# ---- router precedence ----

def _route(**over):
    kw = dict(direction_committed=True, pending_direction=False,
              status=conductor.campaign_status([], max_cycles=5),
              open_pkg="2026-06-12-d1", has_executable_exp=True,
              no_candidate=False, dial="AUTONOMOUS", gate_parseable=True)
    kw.update(over)
    return conductor.next_action(**kw)


def test_route_form_direction():
    a = _route(direction_committed=False, open_pkg=None)
    assert a["type"] == "FORM_DIRECTION" and "/research-brainstorm" in a["handoff"]


def test_route_await_ratification():
    a = _route(direction_committed=False, pending_direction=True, open_pkg=None)
    assert a["type"] == "AWAIT_RATIFICATION"


def test_route_ask_user_on_unparseable_gate():
    assert _route(gate_parseable=False)["type"] == "ASK_USER"


def test_route_success_exit_beats_everything_after_commit():
    status = conductor.campaign_status([_cycle_record(verdict="PASS", gate_eval="PASS")], max_cycles=1)
    a = _route(status=status)
    assert a["type"] == "SUCCESS_EXIT"


def test_route_halt_budget():
    status = conductor.campaign_status([_cycle_record(), _cycle_record(cycle=2)], max_cycles=2)
    assert _route(status=status)["type"] == "HALT_BUDGET"


def test_route_halt_no_candidate():
    assert _route(no_candidate=True)["type"] == "HALT_NO_CANDIDATE"


def test_route_materialize_package():
    a = _route(open_pkg=None, has_executable_exp=False)
    assert a["type"] == "MATERIALIZE_PACKAGE" and "/research-package" in a["delegate"]


def test_route_run_package():
    a = _route()
    assert a["type"] == "RUN_PACKAGE" and "/research-run" in a["delegate"]


def test_route_design_experiment():
    a = _route(has_executable_exp=False)
    assert a["type"] == "DESIGN_EXPERIMENT" and "/research-op" in a["delegate"]


def test_every_route_renders_next_step():
    actions = [
        _route(direction_committed=False, open_pkg=None),
        _route(direction_committed=False, pending_direction=True, open_pkg=None),
        _route(gate_parseable=False),
        _route(status=conductor.campaign_status(
            [_cycle_record(verdict="PASS", gate_eval="PASS")], max_cycles=5)),
        _route(status=conductor.campaign_status(
            [_cycle_record(), _cycle_record(cycle=2)], max_cycles=2)),
        _route(no_candidate=True),
        _route(open_pkg=None),
        _route(),
        _route(has_executable_exp=False),
    ]
    for a in actions:
        step = a["next_step"]
        for field in ("headline", "next_action", "offer", "awaits_user", "details"):
            assert field in step, f"{a['type']} next_step missing {field}"
        assert isinstance(step["awaits_user"], bool)


# ---- authority guard ----

def test_validate_rejects_disposal_smuggle():
    bad = {"type": "RUN_PACKAGE", "decision": "accept"}
    r = conductor.validate_campaign_action(bad)
    assert r["rejected"] and any("disposal" in reason for reason in r["reasons"])


def test_validate_rejects_unknown_type():
    assert conductor.validate_campaign_action({"type": "TAKE_OVER"})["rejected"]


def test_validate_rejects_direction_scope_transition():
    bad = {"type": "DESIGN_EXPERIMENT", "dial": "AUTONOMOUS", "mutations": [
        {"op": "scope-transition", "target": "dir/d1",
         "payload": {"level": "direction", "gate": "USER_CROSS_MODEL_AUDIT"}}]}
    r = conductor.validate_campaign_action(bad)
    assert r["rejected"] and any("direction" in reason for reason in r["reasons"])


def test_validate_rejects_task_transition_wrong_gate():
    bad = {"type": "DESIGN_EXPERIMENT", "dial": "AUTONOMOUS", "mutations": [
        {"op": "scope-transition", "target": "task/d1/m9",
         "payload": {"level": "task", "gate": "USER_ONLY", "deferred_ack": "review M9"}}]}
    assert conductor.validate_campaign_action(bad)["rejected"]


def test_validate_rejects_task_transition_at_supervised_dial():
    bad = {"type": "DESIGN_EXPERIMENT", "dial": "SUPERVISED", "mutations": [
        {"op": "scope-transition", "target": "task/d1/m9",
         "payload": {"level": "task", "gate": "AGENT_DEFERRED_ACK", "deferred_ack": "review M9"}}]}
    r = conductor.validate_campaign_action(bad)
    assert r["rejected"] and any("Triage" in reason for reason in r["reasons"])


def test_validate_rejects_task_transition_without_deferred_ack():
    bad = {"type": "DESIGN_EXPERIMENT", "dial": "AUTONOMOUS", "mutations": [
        {"op": "scope-transition", "target": "task/d1/m9",
         "payload": {"level": "task", "gate": "AGENT_DEFERRED_ACK"}}]}
    assert conductor.validate_campaign_action(bad)["rejected"]


def test_validate_allows_task_transition_away_dial():
    ok = {"type": "DESIGN_EXPERIMENT", "dial": "AUTONOMOUS", "mutations": [
        {"op": "scope-transition", "target": "task/d1/m9",
         "payload": {"level": "task", "gate": "AGENT_DEFERRED_ACK",
                     "deferred_ack": "new milestone M9 awaits your review"}}]}
    assert conductor.validate_campaign_action(ok) is None


def test_validate_rejects_illegal_envelope():
    bad = {"type": "RUN_PACKAGE", "dial": "AUTONOMOUS",
           "mutations": [{"op": "write-file", "target": "results.html", "payload": {}}]}
    assert conductor.validate_campaign_action(bad)["rejected"]


# ---- per-cycle task shaping ----

def test_milestone_task_node_valid():
    node = conductor.milestone_task_node(
        _direction_node(), cycle=3, suffix="M9-reranker-ablation",
        experiment="Ablate the reranker against the committed gate",
        gate="R@1 >= 48", dial="DEFERRED")
    scope_ssot.validate_node(node)
    assert node["parents"] == ["dir/d1"]
    assert node["spec"]["control_mode"] == "DEFERRED"
    assert node["source"].startswith("research-auto:cycle-3")


def test_milestone_task_node_rejects_bad_dial():
    try:
        conductor.milestone_task_node(_direction_node(), cycle=1, suffix="M9",
                                      experiment="x", gate="m >= 1", dial="YOLO")
    except ValueError:
        return
    raise AssertionError("expected ValueError for unknown dial")


# ---- filesystem derivation + CLI ----

def test_detect_open_package_and_executable(tmp_path):
    _registry(tmp_path, '''window.RESEARCH_PACKAGES = [
  {
    id: "2026-06-10-other",
    category: "success",
    sourceDirection: "dir/other",
  },
  {
    id: "2026-06-12-d1",
    category: "in-progress",
    sourceDirection: "dir/d1",
    experiments: [{"id": "P0", "status": "completed"}, {"id": "P1", "status": "queued"}],
  },
];
''')
    pkg, executable = conductor.detect_open_package(tmp_path, "dir/d1")
    assert pkg == "2026-06-12-d1" and executable is True


def test_detect_open_package_accepts_real_inventory_status_forms(tmp_path):
    _registry(tmp_path, '''window.RESEARCH_PACKAGES = [
  {
    id: "2026-06-12-d1",
    category: "in-progress",
    sourceDirection: "dir/d1",
    experiments: [{ id: "P0", status: "QUEUED" }, {"id": "P1", "status": "running"}],
  },
];
''')
    pkg, executable = conductor.detect_open_package(tmp_path, "dir/d1")
    assert pkg == "2026-06-12-d1" and executable is True


def test_detect_open_package_none_when_terminal(tmp_path):
    _registry(tmp_path, '''window.RESEARCH_PACKAGES = [
  { id: "2026-06-12-d1", category: "fail", sourceDirection: "dir/d1" },
];
''')
    assert conductor.detect_open_package(tmp_path, "dir/d1") == (None, False)


def test_cli_status_routes_run_package(tmp_path, capsys, monkeypatch):
    _registry(tmp_path, '''window.RESEARCH_PACKAGES = [
  {
    id: "2026-06-12-d1",
    category: "in-progress",
    sourceDirection: "dir/d1",
    experiments: [{"id": "P0", "status": "queued"}],
  },
];
''')
    _commit_direction(tmp_path)
    rc = conductor.main(["status", "--root", str(tmp_path), "--direction-id", "dir/d1",
                         "--max-cycles", "5"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["state"]["direction_committed"] is True
    assert out["state"]["open_pkg"] == "2026-06-12-d1"
    assert out["action"]["type"] == "RUN_PACKAGE"


def test_cli_status_awaits_ratification(tmp_path, capsys):
    triage = tmp_path / "outputs" / "_scope" / "triage.jsonl"
    triage.parent.mkdir(parents=True, exist_ok=True)
    triage.write_text(
        json.dumps({"id": "direction-d1", "node_id": "dir/d1", "level": "direction", "status": "pending"}) + "\n",
        encoding="utf-8",
    )
    rc = conductor.main(["status", "--root", str(tmp_path), "--direction-id", "dir/d1",
                         "--max-cycles", "5"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["action"]["type"] == "AWAIT_RATIFICATION"


def test_cli_status_ignores_unrelated_pending_direction(tmp_path, capsys):
    triage = tmp_path / "outputs" / "_scope" / "triage.jsonl"
    triage.parent.mkdir(parents=True, exist_ok=True)
    triage.write_text(
        json.dumps({
            "id": "direction-other",
            "node_id": "dir/other",
            "level": "direction",
            "status": "pending",
            "proposed_node": {"id": "dir/other"},
        }) + "\n",
        encoding="utf-8",
    )
    rc = conductor.main([
        "status",
        "--root", str(tmp_path),
        "--direction-id", "dir/d1",
        "--gate", "R@1 >= 48",
    ])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["action"]["type"] == "FORM_DIRECTION"


def test_cli_gate_eval(capsys):
    rc = conductor.main(["gate-eval", "--measured", "48.2", "--gate", "R@1 >= 48"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["gate_eval"] == "PASS"


def test_cli_append_cycle(tmp_path, capsys):
    rc = conductor.main(["append-cycle", "--root", str(tmp_path), "--direction-id", "dir/d1",
                         "--record", json.dumps(_cycle_record())])
    assert rc == 0
    rows = conductor.read_ledger(conductor.ledger_path(tmp_path, "dir/d1"))
    assert len(rows) == 1 and rows[0]["cycle"] == 1


def test_cli_pack_writes_campaign_bundle(tmp_path):
    bundle = {"attempted": "cycle 1: P1 reranker", "found": "FAIL 46.1 vs >=48",
              "hypothesis_state": "X improves recall — unproven",
              "next_action": "DESIGN_EXPERIMENT", "blocking_decision": "none"}
    rc = conductor.main(["pack", "--root", str(tmp_path), "--direction-id", "dir/d1",
                         "--bundle", json.dumps(bundle)])
    assert rc == 0
    pack_log = tmp_path / "outputs" / "_auto" / "d1" / "_pack.jsonl"
    assert pack_log.exists() and "DESIGN_EXPERIMENT" in pack_log.read_text(encoding="utf-8")
