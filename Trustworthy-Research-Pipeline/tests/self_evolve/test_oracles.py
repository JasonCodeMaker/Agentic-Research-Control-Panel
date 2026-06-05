"""Step 4 — Rule oracles + tiered admission resolver (§11.2)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

from self_evolve import oracles as o  # noqa: E402
from self_evolve import schema  # noqa: E402


def _rule(**over):
    base = {
        "schema_version": schema.RULE_SCHEMA, "id": "rule.x", "version": "1.0.0",
        "title": "t", "description": "d", "content": "verify the metric contract first",
        "scope": {"project": "*", "packages": ["*"], "task_types": ["metric-change"]},
        "risk_class": "R1-context",
        "provenance": {"generated_by": "rule-inducer-v1"},
        "validation_policy": {"required_oracles": ["faithfulness", "conflict"]},
    }
    base.update(over)
    return base


# --- individual oracles ---

def test_schema_scope_pass_fail():
    assert o.schema_scope(_rule()) == "pass"
    assert o.schema_scope(_rule(content="")) == "fail"


def test_faithfulness():
    assert o.faithfulness({"entailed": True}) == "pass"
    assert o.faithfulness({"entailed": False}) == "fail"
    assert o.faithfulness(None) == "inconclusive"


def test_correction_integrity_preserves_excerpt():
    assert o.correction_integrity(_rule(), source_excerpt="metric contract") == "pass"
    assert o.correction_integrity(_rule(), source_excerpt="something else") == "fail"


def test_correction_integrity_rejects_scope_widening():
    # rule scopes to metric-change; correction was only about 'metric-change' → ok
    assert o.correction_integrity(_rule(), source_task_types=["metric-change"]) == "pass"
    # rule widened to an extra task type beyond the correction
    wide = _rule(scope={"project": "*", "packages": ["*"], "task_types": ["metric-change", "everything"]})
    assert o.correction_integrity(wide, source_task_types=["metric-change"]) == "fail"


def test_original_reproduction():
    assert o.original_reproduction({"before": "fail", "after": "pass"}) == "pass"
    assert o.original_reproduction({"before": "fail", "after": "fail"}) == "fail"
    assert o.original_reproduction(None) == "inconclusive"


def test_regression_and_conflict():
    assert o.regression_smoke({"regressions": []}) == "pass"
    assert o.regression_smoke({"regressions": ["test_a"]}) == "fail"
    assert o.conflict([]) == "pass"
    assert o.conflict(["rule.y"]) == "fail"


# --- admission resolver ---

def test_any_fail_rejects():
    assert o.resolve_admission({"schema_scope": "pass", "conflict": "fail"}) == "rejected"


def test_proven_effective_with_reproduction():
    res = {"schema_scope": "pass", "faithfulness": "pass", "conflict": "pass",
           "original_reproduction": "pass", "regression_smoke": "pass"}
    assert o.resolve_admission(res) == "proven-effective"


def test_advisory_admitted_recipe_rule():
    # success-derived recipe rule: no measured effectiveness oracle, but clean
    res = {"schema_scope": "pass", "faithfulness": "pass", "conflict": "pass",
           "regression_smoke": "pass"}
    assert o.resolve_admission(res) == "advisory-admitted"


def test_correction_rule_advisory_via_integrity():
    res = {"schema_scope": "pass", "correction_integrity": "pass", "conflict": "pass",
           "regression_smoke": "pass"}
    assert o.resolve_admission(res) == "advisory-admitted"


def test_missing_base_is_inconclusive():
    res = {"schema_scope": "pass", "conflict": "pass", "regression_smoke": "pass"}
    # no faithfulness or correction_integrity → base unmet
    assert o.resolve_admission(res) == "inconclusive"


def test_error_is_inconclusive_not_rejected():
    res = {"schema_scope": "pass", "faithfulness": "pass", "conflict": "pass",
           "regression_smoke": "error"}
    assert o.resolve_admission(res) == "inconclusive"
