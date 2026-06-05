"""Step 7 — Rule Store → Context Pack derived export (plan §13.1 / D7)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

import context_pack.build as cb  # noqa: E402
from self_evolve import schema, store  # noqa: E402


def _seed_rule_store(se_root, rule_id, content, authority):
    """Promote one rule to active with a sealed release + admission label."""
    rule = {
        "schema_version": schema.RULE_SCHEMA, "id": rule_id, "version": "1.0.0",
        "title": "t", "description": "d", "content": content,
        "scope": {"project": "*", "packages": ["*"], "task_types": ["x"]},
        "risk_class": "R1-context", "provenance": {"generated_by": "rule-inducer-v1"},
        "validation_policy": {"required_oracles": ["faithfulness", "conflict"]},
    }
    rel = se_root / "rules" / "releases" / rule_id / "1.0.0" / "rule.json"
    rel.parent.mkdir(parents=True, exist_ok=True)
    rel.write_text(json.dumps(rule), encoding="utf-8")
    log = se_root / "rules" / "transitions.jsonl"
    chain = [("observed", "candidate"), ("candidate", "validating"),
             ("validating", "provisional"), ("provisional", "active")]
    for frm, to in chain:
        t = {"schema_version": schema.TRANSITION_SCHEMA, "transition_id": f"{rule_id}-{to}",
             "store": "rule", "entity_id": rule_id, "entity_version": "1.0.0",
             "expected_from_state": frm, "to_state": to, "op": "promote",
             "risk_class": "R1-context", "idempotency_key": f"{rule_id}:{to}"}
        if to == "active":
            t["admission"] = authority
        store.append_transition(log, t)


def test_load_rule_store_orders_proven_before_advisory(tmp_path):
    se = tmp_path / "_selfevolve"
    _seed_rule_store(se, "rule.advisory", "advisory content", "advisory-admitted")
    _seed_rule_store(se, "rule.proven", "proven content", "proven-effective")
    actives = cb.load_rule_store_active(str(se))
    assert [r["authority"] for r in actives] == ["proven-effective", "advisory-admitted"]


def test_export_writes_derived_learned_rules(tmp_path):
    se = tmp_path / "_selfevolve"
    _seed_rule_store(se, "rule.proven", "always verify the metric contract", "proven-effective")
    learned = tmp_path / "_learned" / "rules.md"
    n = cb.export_learned_rules(str(se), str(learned))
    assert n == 1
    assert "- always verify the metric contract" in learned.read_text()


def test_export_is_idempotent_overwrite_not_append(tmp_path):
    se = tmp_path / "_selfevolve"
    _seed_rule_store(se, "rule.proven", "rule one", "proven-effective")
    learned = tmp_path / "_learned" / "rules.md"
    cb.export_learned_rules(str(se), str(learned))
    cb.export_learned_rules(str(se), str(learned))  # second run must not duplicate
    assert learned.read_text().count("- rule one") == 1


def test_empty_rule_store_writes_empty_file(tmp_path):
    learned = tmp_path / "_learned" / "rules.md"
    assert cb.export_learned_rules(str(tmp_path / "_selfevolve"), str(learned)) == 0
    assert learned.read_text() == ""


def test_active_only_no_release_skipped(tmp_path):
    se = tmp_path / "_selfevolve"
    # candidate that never reached active → not exported
    log = se / "rules" / "transitions.jsonl"
    t = {"schema_version": schema.TRANSITION_SCHEMA, "transition_id": "c1", "store": "rule",
         "entity_id": "rule.draft", "entity_version": "1.0.0", "expected_from_state": "observed",
         "to_state": "candidate", "op": "create", "risk_class": "R1-context",
         "idempotency_key": "rule.draft:candidate"}
    store.append_transition(log, t)
    assert cb.load_rule_store_active(str(se)) == []
