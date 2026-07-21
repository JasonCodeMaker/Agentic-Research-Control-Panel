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
        "risk_class": "R1_CONTEXT",
        "provenance": {"generated_by": "rule-inducer-v1"},
        "validation_policy": {"required_oracles": ["faithfulness", "conflict"]},
    }
    base.update(over)
    return base


# --- individual oracles ---

def test_schema_scope_pass_fail():
    assert o.schema_scope(_rule()) == "ORACLE_PASS"
    assert o.schema_scope(_rule(content="")) == "ORACLE_FAIL"


def test_faithfulness():
    assert o.faithfulness({"entailed": True}) == "ORACLE_PASS"
    assert o.faithfulness({"entailed": False}) == "ORACLE_FAIL"
    assert o.faithfulness(None) == "ORACLE_INCONCLUSIVE"


def test_correction_integrity_preserves_excerpt():
    assert o.correction_integrity(_rule(), source_excerpt="metric contract") == "ORACLE_PASS"
    assert o.correction_integrity(_rule(), source_excerpt="something else") == "ORACLE_FAIL"


def test_correction_integrity_rejects_scope_widening():
    # rule scopes to metric-change; correction was only about 'metric-change' → ok
    assert o.correction_integrity(_rule(), source_task_types=["metric-change"]) == "ORACLE_PASS"
    # rule widened to an extra task type beyond the correction
    wide = _rule(scope={"project": "*", "packages": ["*"], "task_types": ["metric-change", "everything"]})
    assert o.correction_integrity(wide, source_task_types=["metric-change"]) == "ORACLE_FAIL"


def test_original_reproduction():
    assert o.original_reproduction({"before": "fail", "after": "pass"}) == "ORACLE_PASS"
    assert o.original_reproduction({"before": "fail", "after": "fail"}) == "ORACLE_FAIL"
    assert o.original_reproduction(None) == "ORACLE_INCONCLUSIVE"


def test_regression_and_conflict():
    assert o.regression_smoke({"regressions": []}) == "ORACLE_PASS"
    assert o.regression_smoke({"regressions": ["test_a"]}) == "ORACLE_FAIL"
    assert o.conflict([]) == "ORACLE_PASS"
    assert o.conflict(["rule.y"]) == "ORACLE_FAIL"


# --- admission resolver ---

def test_any_fail_rejects():
    assert o.resolve_admission({"schema_scope": "ORACLE_PASS", "conflict": "ORACLE_FAIL"}) == "REJECTED"


def test_proven_effective_with_reproduction():
    res = {"schema_scope": "ORACLE_PASS", "faithfulness": "ORACLE_PASS", "conflict": "ORACLE_PASS",
           "original_reproduction": "ORACLE_PASS", "regression_smoke": "ORACLE_PASS"}
    assert o.resolve_admission(res) == "FULLY_ADMITTED"


def test_advisory_admitted_recipe_rule():
    # success-derived recipe rule: no measured effectiveness oracle, but clean
    res = {"schema_scope": "ORACLE_PASS", "faithfulness": "ORACLE_PASS", "conflict": "ORACLE_PASS",
           "regression_smoke": "ORACLE_PASS"}
    assert o.resolve_admission(res) == "TENTATIVELY_ADMITTED"


def test_correction_rule_advisory_via_integrity():
    res = {"schema_scope": "ORACLE_PASS", "correction_integrity": "ORACLE_PASS", "conflict": "ORACLE_PASS",
           "regression_smoke": "ORACLE_PASS"}
    assert o.resolve_admission(res) == "TENTATIVELY_ADMITTED"


def test_missing_base_is_inconclusive():
    res = {"schema_scope": "ORACLE_PASS", "conflict": "ORACLE_PASS", "regression_smoke": "ORACLE_PASS"}
    # no faithfulness or correction_integrity → base unmet
    assert o.resolve_admission(res) == "INCONCLUSIVE"


def test_error_is_inconclusive_not_rejected():
    res = {"schema_scope": "ORACLE_PASS", "faithfulness": "ORACLE_PASS", "conflict": "ORACLE_PASS",
           "regression_smoke": "ORACLE_ERROR"}
    assert o.resolve_admission(res) == "INCONCLUSIVE"
