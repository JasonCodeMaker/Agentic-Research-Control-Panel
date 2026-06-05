"""Step 6 — event → Rule candidate induction (§10.2)."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

from self_evolve import induce  # noqa: E402
from self_evolve import schema  # noqa: E402


def _event(etype="test-failure-fixed"):
    return {"schema_version": schema.EVENT_SCHEMA, "event_id": "evt_1", "type": etype,
            "source": "research-op", "subject": "metric implementation",
            "idempotency_key": "k", "observed_at": "2026-06-05T00:00:00+10:00"}


def _draft():
    return {
        "id": "rule.verify-metric-contract",
        "title": "Verify metric semantics before accepting a claim",
        "description": "Prevents metric-name ambiguity from becoming a claim.",
        "content": "If a custom metric changes, validate its contract before accepting the result.",
        "scope": {"project": "*", "packages": ["*"], "task_types": ["metric-change"]},
    }


def test_induce_produces_valid_rule_with_provenance_and_digest():
    rule = induce.induce_rule(_event(), _draft())
    assert schema.validate_rule(rule) is True
    assert rule["provenance"]["source_event_ids"] == ["evt_1"]
    assert rule["content_digest"].startswith("sha256:")
    # failure-derived profile demands a measured oracle
    assert "original_reproduction" in rule["validation_policy"]["required_oracles"]


def test_user_correction_profile_uses_correction_integrity():
    rule = induce.induce_rule(_event("user-correction"), _draft())
    assert "correction_integrity" in rule["validation_policy"]["required_oracles"]
    assert "original_reproduction" not in rule["validation_policy"]["required_oracles"]


def test_recipe_workflow_profile_is_advisory():
    rule = induce.induce_rule(_event("workflow-repeated"), _draft())
    req = rule["validation_policy"]["required_oracles"]
    assert "faithfulness" in req and "original_reproduction" not in req


def test_default_risk_is_advisory_context():
    assert induce.induce_rule(_event(), _draft())["risk_class"] == "R1-context"


def test_draft_declared_r3_is_preserved_for_parking():
    d = _draft()
    d["risk_class"] = "R3-project-exec"
    assert induce.induce_rule(_event(), d)["risk_class"] == "R3-project-exec"


def test_unknown_event_type_rejected():
    with pytest.raises(schema.SchemaViolation):
        induce.induce_rule(_event("mystery"), _draft())


def test_incomplete_draft_rejected():
    d = _draft()
    del d["content"]
    with pytest.raises(KeyError):
        induce.induce_rule(_event(), d)


def test_user_correction_prompt_warns_against_generalizing():
    assert "do NOT generalize" in induce.build_prompt(_event("user-correction"))
