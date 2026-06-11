"""Step 7 — Rule Store → Context Pack derived export (plan §13.1 / D7)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

import context_pack.build as cb  # noqa: E402
from self_evolve import schema, store  # noqa: E402


def _seed_rule_store(se_root, rule_id, content, authority):
    """Promote one rule to RULE_ACTIVE with a sealed release + admission label."""
    rule = {
        "schema_version": schema.RULE_SCHEMA, "id": rule_id, "version": "1.0.0",
        "title": "t", "description": "d", "content": content,
        "scope": {"project": "*", "packages": ["*"], "task_types": ["x"]},
        "risk_class": "R1_CONTEXT", "provenance": {"generated_by": "rule-inducer-v1"},
        "validation_policy": {"required_oracles": ["faithfulness", "conflict"]},
    }
    rel = se_root / "rules" / "releases" / rule_id / "1.0.0" / "rule.json"
    rel.parent.mkdir(parents=True, exist_ok=True)
    rel.write_text(json.dumps(rule), encoding="utf-8")
    log = se_root / "rules" / "transitions.jsonl"
    chain = [("OBSERVED", "CANDIDATE"), ("CANDIDATE", "VALIDATING"),
             ("VALIDATING", "PROVISIONAL"), ("PROVISIONAL", "RULE_ACTIVE")]
    for frm, to in chain:
        t = {"schema_version": schema.TRANSITION_SCHEMA, "transition_id": f"{rule_id}-{to}",
             "store": "rule", "entity_id": rule_id, "entity_version": "1.0.0",
             "expected_from_state": frm, "to_state": to, "op": "promote",
             "risk_class": "R1_CONTEXT", "idempotency_key": f"{rule_id}:{to}"}
        if to == "RULE_ACTIVE":
            t["admission"] = authority
        store.append_transition(log, t)


def test_load_rule_store_orders_proven_before_advisory(tmp_path):
    se = tmp_path / "_selfevolve"
    _seed_rule_store(se, "rule.advisory", "advisory content", "TENTATIVELY_ADMITTED")
    _seed_rule_store(se, "rule.proven", "proven content", "FULLY_ADMITTED")
    actives = cb.load_rule_store_active(str(se))
    assert [r["authority"] for r in actives] == ["FULLY_ADMITTED", "TENTATIVELY_ADMITTED"]


def _registry(root):
    text = (Path(root) / "data" / "rules.js").read_text(encoding="utf-8")
    return json.loads(text[len("window.RESEARCH_RULES = "):].rstrip().rstrip(";"))


def test_export_writes_derived_registry_rows(tmp_path):
    se = tmp_path / "_selfevolve"
    _seed_rule_store(se, "rule.proven", "always verify the metric contract", "FULLY_ADMITTED")
    root = tmp_path / "research_html"
    n = cb.export_learned_rules(str(se), str(root))
    assert n == 1
    rows = _registry(root)
    assert len(rows) == 1 and rows[0]["origin"] == "selfevolve"
    assert rows[0]["text"] == "always verify the metric contract"


def test_export_is_idempotent_replace_not_append(tmp_path):
    se = tmp_path / "_selfevolve"
    _seed_rule_store(se, "rule.proven", "rule one", "FULLY_ADMITTED")
    root = tmp_path / "research_html"
    cb.export_learned_rules(str(se), str(root))
    cb.export_learned_rules(str(se), str(root))  # second run must not duplicate
    assert len(_registry(root)) == 1


def test_export_disambiguates_colliding_selfevolve_rule_ids(tmp_path):
    se = tmp_path / "_selfevolve"
    prefix = "same prefix rule content with enough repeated words to collide before suffix "
    _seed_rule_store(se, "rule.alpha", prefix + "alpha", "FULLY_ADMITTED")
    _seed_rule_store(se, "rule.beta", prefix + "beta", "TENTATIVELY_ADMITTED")
    root = tmp_path / "research_html"
    cb.export_learned_rules(str(se), str(root))
    ids = [r["id"] for r in _registry(root)]
    assert len(ids) == len(set(ids)) == 2


def test_export_preserves_non_selfevolve_rows(tmp_path):
    se = tmp_path / "_selfevolve"
    _seed_rule_store(se, "rule.proven", "rule one", "FULLY_ADMITTED")
    root = tmp_path / "research_html"
    (root / "data").mkdir(parents=True)
    (root / "data" / "rules.js").write_text(
        'window.RESEARCH_RULES = [{"id": "PRJ-keep", "level": "project", "kind": "constraint",'
        '"title": "k", "text": "k", "rationale": "k", "source": "user", "origin": "user",'
        '"status": "ACTIVE", "addedAt": "2026-06-11"}];\n')
    cb.export_learned_rules(str(se), str(root))
    ids = {r["id"] for r in _registry(root)}
    assert "PRJ-keep" in ids and any(i.startswith("PRJ-se-") for i in ids)


def test_export_refuses_malformed_registry_without_clobbering(tmp_path):
    se = tmp_path / "_selfevolve"
    _seed_rule_store(se, "rule.proven", "rule one", "FULLY_ADMITTED")
    root = tmp_path / "research_html"
    (root / "data").mkdir(parents=True)
    bad = "window.BAD_RULES = [];\n"
    (root / "data" / "rules.js").write_text(bad)
    try:
        cb.export_learned_rules(str(se), str(root))
    except ValueError:
        pass
    else:
        raise AssertionError("expected malformed registry to be refused")
    assert (root / "data" / "rules.js").read_text() == bad


def test_empty_rule_store_writes_empty_registry(tmp_path):
    root = tmp_path / "research_html"
    assert cb.export_learned_rules(str(tmp_path / "_selfevolve"), str(root)) == 0
    assert _registry(root) == []


def test_active_only_no_release_skipped(tmp_path):
    se = tmp_path / "_selfevolve"
    # candidate that never reached RULE_ACTIVE → not exported
    log = se / "rules" / "transitions.jsonl"
    t = {"schema_version": schema.TRANSITION_SCHEMA, "transition_id": "c1", "store": "rule",
         "entity_id": "rule.draft", "entity_version": "1.0.0", "expected_from_state": "OBSERVED",
         "to_state": "CANDIDATE", "op": "create", "risk_class": "R1_CONTEXT",
         "idempotency_key": "rule.draft:CANDIDATE"}
    store.append_transition(log, t)
    assert cb.load_rule_store_active(str(se)) == []
