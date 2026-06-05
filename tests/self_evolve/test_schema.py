"""Step 1 — schema validators + digest stability (plan §17.4)."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

from self_evolve import schema  # noqa: E402


def _rule(**over):
    base = {
        "schema_version": schema.RULE_SCHEMA,
        "id": "rule.verify-metric-contract",
        "version": "1.0.0",
        "title": "Verify metric semantics before accepting a claim",
        "description": "Prevents metric-name ambiguity from becoming a research claim.",
        "content": "If a custom metric changes, validate its contract before accepting the result.",
        "scope": {"project": "*", "packages": ["*"], "task_types": ["metric-change"]},
        "risk_class": "R1-context",
        "provenance": {"generated_by": "rule-inducer-v1", "source_event_ids": ["evt_1"]},
        "validation_policy": {"required_oracles": ["faithfulness", "conflict"]},
    }
    base.update(over)
    return base


def _transition(**over):
    base = {
        "schema_version": schema.TRANSITION_SCHEMA,
        "transition_id": "trn_1",
        "store": "rule",
        "entity_id": "rule.verify-metric-contract",
        "entity_version": "1.0.0",
        "expected_from_state": "provisional",
        "to_state": "active",
        "op": "promote",
        "risk_class": "R1-context",
        "idempotency_key": "promote:rule.verify-metric-contract:1.0.0:active",
    }
    base.update(over)
    return base


# --- digests ---

def test_content_digest_is_key_order_stable():
    a = {"b": 2, "a": 1, "content_digest": "sha256:ignore"}
    b = {"a": 1, "b": 2}
    assert schema.content_digest(a) == schema.content_digest(b)


def test_content_digest_changes_with_content():
    assert schema.content_digest({"a": 1}) != schema.content_digest({"a": 2})


# --- rule ---

def test_valid_rule_passes():
    assert schema.validate_rule(_rule()) is True


def test_rule_rejects_wrong_schema_version():
    with pytest.raises(schema.SchemaViolation):
        schema.validate_rule(_rule(schema_version="x"))


def test_rule_rejects_missing_content():
    with pytest.raises(schema.SchemaViolation):
        schema.validate_rule(_rule(content=""))


def test_rule_rejects_unbounded_scope_empty_task_types():
    with pytest.raises(schema.SchemaViolation):
        schema.validate_rule(_rule(scope={"project": "*", "packages": ["*"], "task_types": []}))


def test_rule_rejects_missing_packages():
    with pytest.raises(schema.SchemaViolation):
        schema.validate_rule(_rule(scope={"project": "*", "task_types": ["x"]}))


def test_rule_rejects_illegal_risk():
    with pytest.raises(schema.SchemaViolation):
        schema.validate_rule(_rule(risk_class="R9-nope"))


def test_rule_rejects_missing_provenance():
    with pytest.raises(schema.SchemaViolation):
        schema.validate_rule(_rule(provenance={}))


def test_rule_rejects_empty_required_oracles():
    with pytest.raises(schema.SchemaViolation):
        schema.validate_rule(_rule(validation_policy={"required_oracles": []}))


# --- transition ---

def test_valid_transition_passes():
    assert schema.validate_transition(_transition()) is True


def test_transition_rejects_bad_store():
    with pytest.raises(schema.SchemaViolation):
        schema.validate_transition(_transition(store="widget"))


def test_transition_rejects_missing_concurrency_field():
    t = _transition()
    del t["expected_from_state"]
    with pytest.raises(schema.SchemaViolation):
        schema.validate_transition(t)


# --- event / evidence ---

def test_valid_event_passes():
    e = {
        "schema_version": schema.EVENT_SCHEMA, "event_id": "evt_1",
        "type": "test-failure-fixed", "source": "research-op",
        "idempotency_key": "k", "observed_at": "2026-06-05T00:00:00+10:00",
    }
    assert schema.validate_event(e) is True


def test_evidence_rejects_bad_oracle_result():
    ev = {
        "schema_version": schema.EVIDENCE_SCHEMA, "evidence_id": "evd_1",
        "entity_id": "rule.x", "entity_version": "1.0.0", "stage": "regression",
        "oracle": {"id": "o", "result": "maybe"},
    }
    with pytest.raises(schema.SchemaViolation):
        schema.validate_evidence(ev)
