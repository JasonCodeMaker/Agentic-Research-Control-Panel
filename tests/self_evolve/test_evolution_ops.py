"""Step 5 — evolution-* op handlers + CLI _selfevolve exemption (§9.7)."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "skills" / "research-op" / "scripts"))

from ops import evolution  # noqa: E402
from self_evolve import schema, store  # noqa: E402

CLI = ROOT / "skills" / "research-op" / "scripts" / "research_op.py"


def _event(**over):
    base = {"schema_version": schema.EVENT_SCHEMA, "event_id": "evt_1",
            "type": "test-failure-fixed", "source": "research-op", "subject": "metric",
            "idempotency_key": "k1", "observed_at": "2026-06-05T00:00:00+10:00"}
    base.update(over)
    return base


def _rule(**over):
    base = {
        "schema_version": schema.RULE_SCHEMA, "id": "rule.x", "version": "1.0.0",
        "title": "t", "description": "d", "content": "verify the metric contract",
        "scope": {"project": "*", "packages": ["*"], "task_types": ["metric-change"]},
        "risk_class": "R1_CONTEXT", "provenance": {"generated_by": "rule-inducer-v1"},
        "validation_policy": {"required_oracles": ["faithfulness", "conflict"]},
    }
    base.update(over)
    base["content_digest"] = schema.content_digest(base)
    return base


def _transition(frm, to, **over):
    base = {
        "schema_version": schema.TRANSITION_SCHEMA, "transition_id": f"trn-{to}",
        "store": "rule", "entity_id": "rule.x", "entity_version": "1.0.0",
        "expected_from_state": frm, "to_state": to, "op": "promote",
        "risk_class": "R1_CONTEXT", "idempotency_key": f"rule.x:1.0.0:{to}",
        "approval_ref": None,
    }
    base.update(over)
    return base


# --- module-level handlers ---

def test_observe_appends_and_dedups(tmp_path):
    st, files, _ = evolution.run("evolution-observe", _event(), tmp_path)
    assert st == "PASSED"
    st2, _, _ = evolution.run("evolution-observe", _event(), tmp_path)  # same idempotency_key
    assert st2 == "skipped"
    assert len((tmp_path / "events" / "events.jsonl").read_text().splitlines()) == 1


def test_observe_rejects_bad_event(tmp_path):
    with pytest.raises(evolution.EvolutionReject) as e:
        evolution.run("evolution-observe", {"schema_version": "x"}, tmp_path)
    assert e.value.rule == "event-schema"


def test_create_seals_candidate_and_records_transition(tmp_path):
    st, files, _ = evolution.run("evolution-create", _rule(), tmp_path)
    assert st == "PASSED"
    assert (tmp_path / "rules" / "candidates" / "rule.x" / "1.0.0" / "rule.json").exists()
    assert store.current_state(store.read_log(tmp_path / "rules" / "transitions.jsonl"),
                               "rule.x", "1.0.0") == "CANDIDATE"


def test_full_promotion_to_active_seals_release(tmp_path):
    evolution.run("evolution-create", _rule(), tmp_path)
    for frm, to in [("CANDIDATE", "VALIDATING"), ("VALIDATING", "PROVISIONAL"),
                    ("PROVISIONAL", "RULE_ACTIVE")]:
        evolution.run("evolution-transition", _transition(frm, to), tmp_path)
    assert store.active_version(store.read_log(tmp_path / "rules" / "transitions.jsonl"),
                               "rule.x") == "1.0.0"
    assert (tmp_path / "rules" / "releases" / "rule.x" / "1.0.0" / "rule.json").exists()


def test_illegal_edge_rejected(tmp_path):
    evolution.run("evolution-create", _rule(), tmp_path)
    with pytest.raises(evolution.EvolutionReject) as e:
        evolution.run("evolution-transition", _transition("CANDIDATE", "RULE_ACTIVE",
                      transition_id="t-skip", idempotency_key="skip"), tmp_path)
    assert e.value.rule == "illegal-edge"


def test_r3_promotion_to_active_parked_without_approval(tmp_path):
    with pytest.raises(evolution.EvolutionReject) as e:
        evolution.run("evolution-transition",
                      _transition("PROVISIONAL", "RULE_ACTIVE", risk_class="R3_PROJECT_EXEC"), tmp_path)
    assert e.value.rule == "needs-approval"


def test_project_then_check_consistent(tmp_path):
    evolution.run("evolution-create", _rule(), tmp_path)
    evolution.run("evolution-project", {}, tmp_path)
    st, _, _ = evolution.run("evolution-check", {}, tmp_path)
    assert st == "PASSED"


def test_check_detects_projection_drift(tmp_path):
    evolution.run("evolution-create", _rule(), tmp_path)
    evolution.run("evolution-project", {}, tmp_path)
    # advance state after projecting → projection is now stale
    evolution.run("evolution-transition", _transition("CANDIDATE", "VALIDATING"), tmp_path)
    with pytest.raises(evolution.EvolutionReject) as e:
        evolution.run("evolution-check", {}, tmp_path)
    assert "projection-drift" in e.value.detail


# --- CLI: _selfevolve needs no inventory ---

def test_cli_selfevolve_observe_without_inventory(tmp_path):
    """The whole point of the exemption: no research_html/research-packages.js exists."""
    env = {"RESEARCH_RUNTIME_ROOT": str(tmp_path / "outputs"), "PATH": "/usr/bin:/bin"}
    import os
    env = {**os.environ, **env}
    r = subprocess.run(
        [sys.executable, str(CLI), "--pkg", "_selfevolve", "--op", "evolution-observe",
         "--payload", json.dumps(_event())],
        cwd=tmp_path, capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (tmp_path / "outputs" / "_selfevolve" / "events" / "events.jsonl").exists()
    audit = (tmp_path / "outputs" / "_selfevolve" / "_actions.jsonl").read_text()
    assert '"validation": "PASSED"' in audit
