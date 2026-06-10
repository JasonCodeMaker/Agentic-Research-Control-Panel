"""Phase 4 — worker core + dashboard projection (§14 Phase 4)."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "skills" / "research-op" / "scripts"))

from ops import evolution  # noqa: E402
from self_evolve import dashboard, schema, store, worker  # noqa: E402


def _event(etype="test-failure-fixed", key="k1", eid="evt_1"):
    return {"schema_version": schema.EVENT_SCHEMA, "event_id": eid, "type": etype,
            "source": "research-op", "subject": "s", "idempotency_key": key,
            "observed_at": "2026-06-05T00:00:00+10:00"}


# --- worker ---

def test_trigger_maps_to_job():
    assert worker.map_trigger("test-failure-fixed") == {"store": "rule",
                                                        "job": "reproduce-and-propose-rule"}
    assert worker.map_trigger("workflow-repeated")["store"] == "skill"


def test_unknown_trigger_raises():
    with pytest.raises(worker.UnknownTrigger):
        worker.map_trigger("mystery")


def test_duplicate_events_dedupe_to_one_job():
    jobs = [worker.job_for_event(_event(key="same")), worker.job_for_event(_event(key="same"))]
    assert len(worker.dedupe_jobs(jobs)) == 1


def test_distinct_events_keep_both_jobs():
    jobs = [worker.job_for_event(_event(key="a")), worker.job_for_event(_event(key="b"))]
    assert len(worker.dedupe_jobs(jobs)) == 2


def test_retry_classification():
    assert worker.classify_retry("oracle-fail")["retry"] is False
    assert worker.classify_retry("transient")["retry"] is True
    assert worker.classify_retry("budget-exhaustion")["terminal"] == "pause"


def test_budget_reserve_and_exhaustion_pauses():
    limits = {"llm_tokens": 100, "llm_calls": 5}
    dec, spent = worker.reserve(limits, {"llm_tokens": 0}, {"llm_tokens": 40, "llm_calls": 1})
    assert dec == "reserved" and spent["llm_tokens"] == 40
    dec, result = worker.reserve(limits, {"llm_tokens": 80}, {"llm_tokens": 40})
    assert dec == "pause" and result == "ORACLE_INCONCLUSIVE"  # never silent success


# --- dashboard ---

def _seed_rule_active(se):
    rule = {"schema_version": schema.RULE_SCHEMA, "id": "rule.x", "version": "1.0.0",
            "title": "t", "description": "d", "content": "c",
            "scope": {"project": "*", "packages": ["*"], "task_types": ["x"]},
            "risk_class": "R1_CONTEXT", "provenance": {"generated_by": "g"},
            "validation_policy": {"required_oracles": ["faithfulness", "conflict"]}}
    evolution.run("evolution-create", rule, se)
    for frm, to in [("CANDIDATE", "VALIDATING"), ("VALIDATING", "PROVISIONAL"),
                    ("PROVISIONAL", "RULE_ACTIVE")]:
        evolution.run("evolution-transition",
                      {"schema_version": schema.TRANSITION_SCHEMA, "transition_id": f"t-{to}",
                       "store": "rule", "entity_id": "rule.x", "entity_version": "1.0.0",
                       "expected_from_state": frm, "to_state": to, "op": "promote",
                       "risk_class": "R1_CONTEXT", "idempotency_key": f"rule.x:{to}"}, se)


def test_projection_reflects_active_rule(tmp_path):
    se = tmp_path / "_selfevolve"
    _seed_rule_active(se)
    proj = dashboard.build_projection(se)
    assert proj["rules"]["rule.x@1.0.0"] == "RULE_ACTIVE"
    assert proj["counts"]["active_rules"] == 1


def test_write_projection_is_rebuildable(tmp_path):
    se, dash = tmp_path / "_selfevolve", tmp_path / "research_html"
    _seed_rule_active(se)
    proj = dashboard.write_projection(se, dash)
    on_disk = json.loads((dash / "data" / "self-evolution.json").read_text())
    assert on_disk == proj
    assert "RESEARCH_SELF_EVOLUTION" in (dash / "data" / "self-evolution.js").read_text()


def test_consistency_fails_closed_on_drift(tmp_path):
    se = tmp_path / "_selfevolve"
    _seed_rule_active(se)
    good = dashboard.build_projection(se)
    assert dashboard.assert_consistent(se, good) is True
    tampered = json.loads(json.dumps(good))
    tampered["rules"]["rule.x@1.0.0"] = "INVALIDATED"  # planted drift
    with pytest.raises(dashboard.ConsistencyError):
        dashboard.assert_consistent(se, tampered)
