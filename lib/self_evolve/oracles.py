"""The 6 v1 Rule oracles + tiered admission resolver (plan §11.2).

Pure and deterministic: every oracle consumes already-gathered evidence (the LLM-judge
verdict and any re-run results are computed by the op handler and injected here). This
keeps D4 intact — effectiveness is decided only by measured oracles (original-reproduction
/ regression-delta), never by an LLM judgment.
"""

from self_evolve import schema

ORACLES = ("schema_scope", "faithfulness", "correction_integrity",
           "original_reproduction", "regression_smoke", "conflict")


ORACLE_PASS, ORACLE_FAIL, ORACLE_INCONCLUSIVE, ORACLE_ERROR = schema.ORACLE_RESULTS


def schema_scope(rule):
    """schema + bounded-scope gate."""
    try:
        schema.validate_rule(rule)
        return ORACLE_PASS
    except schema.SchemaViolation:
        return ORACLE_FAIL


def faithfulness(judge):
    """LLM-judge entailment verdict (injected): is the Rule entailed by its cited source?"""
    if judge is None:
        return ORACLE_INCONCLUSIVE
    return ORACLE_PASS if judge.get("entailed") else ORACLE_FAIL


def correction_integrity(rule, *, source_excerpt=None, source_task_types=None):
    """Exact user correction preserved and scope not silently widened beyond it."""
    if source_excerpt and source_excerpt not in rule.get("content", ""):
        return ORACLE_FAIL
    if source_task_types is not None:
        rule_tt = set(rule.get("scope", {}).get("task_types", []))
        if not rule_tt.issubset(set(source_task_types)):
            return ORACLE_FAIL
    return ORACLE_PASS


def original_reproduction(repro):
    """Measured: the failure reproduced before the Rule-guided fix and is gone after."""
    if not repro:
        return ORACLE_INCONCLUSIVE
    return ORACLE_PASS if repro.get("before") == "fail" and repro.get("after") == "pass" else ORACLE_FAIL


def regression_smoke(report):
    """No protected existing case regressed."""
    if report is None:
        return ORACLE_INCONCLUSIVE
    return ORACLE_FAIL if report.get("regressions") else ORACLE_PASS


def conflict(conflict_set):
    """No unresolved conflict with a higher-authority active entry."""
    return ORACLE_FAIL if conflict_set else ORACLE_PASS


def resolve_admission(results):
    """Map oracle results → admission outcome (§11.2).

    Returns one of: 'REJECTED' | 'INCONCLUSIVE' | 'TENTATIVELY_ADMITTED' | 'FULLY_ADMITTED'.
    Any failing oracle rejects. Effectiveness (proven) requires a measured oracle pass;
    otherwise a clean candidate is TENTATIVELY_ADMITTED (active, reduced priority, never floor).
    """
    vals = list(results.values())
    if any(v == ORACLE_FAIL for v in vals):
        return "REJECTED"
    if any(v == ORACLE_ERROR for v in vals):
        return "INCONCLUSIVE"

    def ok(name):
        return results.get(name) == ORACLE_PASS

    base = ok("schema_scope") and ok("conflict") and (ok("faithfulness") or ok("correction_integrity"))
    if not base:
        return "INCONCLUSIVE"
    if ok("original_reproduction"):
        return "FULLY_ADMITTED"
    if ok("regression_smoke"):
        return "TENTATIVELY_ADMITTED"
    return "INCONCLUSIVE"
