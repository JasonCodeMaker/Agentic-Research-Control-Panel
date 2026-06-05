"""Stages 1-6 role-wiring gates: the driver-side helpers that build research-op envelopes and apply
the deterministic libs, proven against the *real* research-op gates (validate.py) and the verifier.

Each helper emits a `{op, target, payload}` envelope that must pass both driver.validate_mutation
(Stage 0 routing) and validate.validate (the real reject-before-write gate).
"""

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "research-auto" / "scripts"
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "research-op" / "scripts"))
import pytest  # noqa: E402
import driver  # noqa: E402
import roles  # noqa: E402
import validate  # noqa: E402

IMPL_STATE = {"category": "in-progress", "status": "IMPLEMENTATION_REVIEW"}
RESULT_STATE = {"category": "in-progress", "status": "RESULT_ANALYSIS"}


def _gate(env, state):
    """Run a built envelope through the real research-op gate; return the Reject (or None)."""
    return validate.validate("pkg", env["op"], env["target"], env["payload"], state)


# ---- Stage 1: code role + IMPLEMENTATION_REVIEW two-layer review ----

def test_reviewer_verdict_refuses_self_review():
    with pytest.raises(ValueError):
        roles.build_reviewer_verdict("impl:coder", "impl:coder", result="sound",
                                     scope_version=1, artifact_id="a1")


def test_launch_envelope_sound_distinct_passes_gate():
    v = roles.build_reviewer_verdict("impl:coder", "codex:judge", result="sound",
                                     scope_version=1, artifact_id="a1")
    env = roles.launch_update_envelope(v)
    assert driver.validate_mutation(env) == []
    assert _gate(env, IMPL_STATE) is None


def test_launch_envelope_unsound_blocked_by_gate():
    v = roles.build_reviewer_verdict("impl:coder", "codex:judge", result="needs-revision",
                                     scope_version=1, artifact_id="a1")
    env = roles.launch_update_envelope(v)
    rej = _gate(env, IMPL_STATE)
    assert rej is not None and rej.rule == "launch-acquits"


def test_launch_envelope_same_judge_blocked_by_gate():
    # a manually-forged same-judge verdict (bypassing the constructor) is still caught by the gate
    v = {"producer": "impl:coder", "judge": "impl:coder", "result": "sound",
         "scope_version": 1, "artifact_id": "a1"}
    env = roles.launch_update_envelope(v)
    rej = _gate(env, IMPL_STATE)
    assert rej is not None and rej.rule == "launch-acquits"


# ---- Stage 2: real run + artifact protocol (measured comes only from the artifact) ----

def test_read_metric_artifact_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        roles.read_metric_artifact(tmp_path / "nope.json")


def test_verdict_from_artifact_only(tmp_path):
    art = tmp_path / "exp.json"
    art.write_text('{"artifact_id": "e1", "measured": 0.91}', encoding="utf-8")
    a = roles.read_metric_artifact(art)
    env = roles.verdict_update_envelope(a, "measured >= 0.80")
    assert env["payload"]["measured"] == 0.91   # read from disk, not a prompt
    assert env["payload"]["verdict"] == "pass"


def test_tampered_artifact_flips_verdict(tmp_path):
    art = tmp_path / "exp.json"
    art.write_text('{"artifact_id": "e1", "measured": 0.50}', encoding="utf-8")
    env = roles.verdict_update_envelope(roles.read_metric_artifact(art), "measured >= 0.80")
    assert env["payload"]["verdict"] == "fail"


# ---- Stage 3: L2 cross-model jury over runtime artifacts ----

def _verdict(producer, judge, result="sound"):
    return {"producer": producer, "judge": judge, "result": result,
            "scope_version": 1, "artifact_id": "e1"}


def _acquit(verdict, level):
    return roles.acquit_update_envelope(
        verdict, level, termination_message="meets gate", adoption_path="CLAUDE.md#best",
        ack_token="T1:ack")


def test_jury_request_paths_only():
    req = roles.build_jury_request(["a/diff.patch", "a/exp.json"], "faithful?", judge_model="codex")
    assert req["artifact_paths"] == ["a/diff.patch", "a/exp.json"]
    assert "codex" == req["judge_model"]


def test_autonomous_cross_family_acquits():
    env = _acquit(_verdict("claude:coder", "codex:judge"), "autonomous")
    assert _gate(env, RESULT_STATE) is None


def test_autonomous_same_family_blocked():
    env = _acquit(_verdict("claude:coder", "claude:judge"), "autonomous")
    rej = _gate(env, RESULT_STATE)
    assert rej is not None and rej.rule == "acquit-judge-independent"


def test_autonomous_unsound_blocked():
    env = _acquit(_verdict("claude:coder", "codex:judge", result="unsound"), "autonomous")
    rej = _gate(env, RESULT_STATE)
    assert rej is not None and rej.rule == "acquit-judge-independent"


def test_supervised_same_family_allowed():
    env = _acquit(_verdict("claude:coder", "claude:judge"), "supervised")
    assert _gate(env, RESULT_STATE) is None


# ---- Stage 4: dial revert + run monitor ----

def test_dial_revert_emits_supervised_envelopes():
    tasks = [{"id": "task/a", "autonomy_level": "autonomous"},
             {"id": "task/b", "autonomy_level": "autonomous"}]
    transition = {"level": "direction", "dial_revert": ["task/a"]}
    reverted, envs = roles.dial_revert(tasks, transition)
    assert reverted[0]["autonomy_level"] == "supervised" and reverted[0]["locked"] is True
    assert reverted[1]["autonomy_level"] == "autonomous"        # not in dial_revert
    assert len(envs) == 1 and envs[0]["op"] == "scope-transition"
    assert driver.validate_mutation(envs[0]) == []


def test_monitor_run_routes_states():
    assert roles.monitor_run("running", exp_id="e1") == []
    completed = roles.monitor_run("completed", exp_id="e1")
    assert completed[0]["payload"]["to_status"] == "RESULT_ANALYSIS"
    failed = roles.monitor_run("vanished", exp_id="e1")
    assert failed[0]["payload"]["to_status"] == "BLOCKED"
    assert any(e["target"] == "currentBlocker" for e in failed)


# ---- Stage 5: heavy R2/R3 deterministic gates ----

def test_screen_citations_rejects_unresolved():
    cites = [{"id": "c1", "source_id": "s1"}, {"id": "c2", "source_id": "s_missing"}]
    verified, rejected = roles.screen_citations(cites, source_ids=["s1"])
    assert verified == ["c1"] and rejected == ["c2"]


def test_filter_banned_drops_banned_idea():
    assert roles.filter_banned(["i1", "i2"], [{"id": "i2"}]) == ["i1"]


# ---- Stage 6: self-learning proposer (read-only) + applier (human-gated) ----

def test_reflection_detects_doom_and_thrash():
    actions = [{"op": "update", "target": "status", "rule": "verdict-mechanical",
                "validation": "rejected"}] * 3
    transitions = [{"node_id": "dir/x", "op": "revise"}] * 3
    findings = roles.run_reflection(actions=actions, transitions=transitions, cross_failures=[])
    kinds = {f["kind"] for f in findings}
    assert "doom-loop" in kinds and "scope-thrash" in kinds


def test_apply_refuses_without_human_token(tmp_path):
    pdir = tmp_path / "pending" / "p1"
    pdir.mkdir(parents=True)
    (pdir / "proposal.json").write_text('{"suggested_diff": "rule x", "status": "pending"}', encoding="utf-8")
    rules = tmp_path / "rules.md"; rules.write_text("", encoding="utf-8")
    with pytest.raises(PermissionError):
        roles.land_proposal(pdir, human_token="", jury_verdict="sound", rules_path=rules)
