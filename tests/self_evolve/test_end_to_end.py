"""Step 8 — end-to-end in-band Rule Store path + v1 DoD (plan §14 Phase 0/1).

Simulates what an in-band turn does: observe → induce → create → oracle → evidence →
R1 auto-promote → project/check → Context-Pack export → scope-change invalidation.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "skills" / "research-op" / "scripts"))

import context_pack.build as cb  # noqa: E402
from ops import evolution  # noqa: E402
from self_evolve import induce, oracles, schema, store  # noqa: E402


def _failure_event():
    return {"schema_version": schema.EVENT_SCHEMA, "event_id": "evt_42",
            "type": "test-failure-fixed", "source": "research-op",
            "subject": "metric implementation", "idempotency_key": "tf:before:after",
            "observed_at": "2026-06-05T00:00:00+10:00"}


def _draft():
    return {
        "id": "rule.verify-metric-contract",
        "title": "Verify metric semantics before accepting a claim",
        "description": "Prevents metric-name ambiguity from becoming a claim.",
        "content": "If a custom metric changes, validate its contract before accepting the result.",
        "scope": {"project": "*", "packages": ["*"], "task_types": ["metric-change"]},
    }


def _evidence(eid, ver, stage, result):
    return {"schema_version": schema.EVIDENCE_SCHEMA, "evidence_id": f"evd_{stage}",
            "entity_id": eid, "entity_version": ver, "stage": stage,
            "oracle": {"id": f"{stage}-v1", "result": result}}


def _transition(eid, ver, frm, to, **over):
    base = {"schema_version": schema.TRANSITION_SCHEMA, "transition_id": f"{eid}-{to}",
            "store": "rule", "entity_id": eid, "entity_version": ver,
            "expected_from_state": frm, "to_state": to, "op": "promote",
            "risk_class": "R1_CONTEXT", "idempotency_key": f"{eid}:{ver}:{to}"}
    base.update(over)
    return base


def test_failure_to_active_to_contextpack(tmp_path):
    se = tmp_path / "_selfevolve"
    learned = tmp_path / "_learned" / "rules.md"

    # 1. observe
    st, _, _ = evolution.run("evolution-observe", _failure_event(), se)
    assert st == "PASSED"

    # 2. induce candidate (LLM draft injected) + 3. create
    rule = induce.induce_rule(_failure_event(), _draft())
    eid, ver = rule["id"], rule["version"]
    evolution.run("evolution-create", rule, se)

    # 4. run the failure-derived oracle profile (measured repro present → FULLY_ADMITTED)
    results = {
        "schema_scope": oracles.schema_scope(rule),
        "faithfulness": oracles.faithfulness({"entailed": True}),
        "original_reproduction": oracles.original_reproduction({"before": "fail", "after": "pass"}),
        "regression_smoke": oracles.regression_smoke({"regressions": []}),
        "conflict": oracles.conflict([]),
    }
    admission = oracles.resolve_admission(results)
    assert admission == "FULLY_ADMITTED"

    # 5. record evidence for each oracle
    for stage, res in results.items():
        evolution.run("evolution-evidence-add", _evidence(eid, ver, stage, res), se)

    # 6. R1 auto-promote candidate → RULE_ACTIVE, stamping the admission authority
    for frm, to in [("CANDIDATE", "VALIDATING"), ("VALIDATING", "PROVISIONAL")]:
        evolution.run("evolution-transition", _transition(eid, ver, frm, to), se)
    evolution.run("evolution-transition",
                  _transition(eid, ver, "PROVISIONAL", "RULE_ACTIVE", admission=admission), se)
    assert store.active_version(store.read_log(se / "rules" / "transitions.jsonl"), eid) == ver

    # 7. project + check consistent
    evolution.run("evolution-project", {}, se)
    assert evolution.run("evolution-check", {}, se)[0] == "PASSED"

    # 8. derived export reaches the Context Pack
    cb.export_learned_rules(str(se), str(learned))
    assert rule["content"] in learned.read_text()
    actives = cb.load_rule_store_active(str(se))
    assert actives[0]["authority"] == "FULLY_ADMITTED"

    # 9. scope change invalidates the rule → drops from active + export
    evolution.run("evolution-transition",
                  _transition(eid, ver, "RULE_ACTIVE", "INVALIDATED",
                              transition_id=f"{eid}-inv", idempotency_key=f"{eid}:{ver}:INVALIDATED",
                              op="invalidate", reason="scope changed"), se)
    assert store.active_version(store.read_log(se / "rules" / "transitions.jsonl"), eid) is None
    cb.export_learned_rules(str(se), str(learned))
    assert learned.read_text() == ""


def test_failed_repro_rejects_admission():
    # DoD: a failing regression/repro blocks activation (resolves to rejected)
    results = {"schema_scope": "ORACLE_PASS", "faithfulness": "ORACLE_PASS",
               "original_reproduction": "ORACLE_FAIL", "regression_smoke": "ORACLE_PASS",
               "conflict": "ORACLE_PASS"}
    assert oracles.resolve_admission(results) == "REJECTED"
