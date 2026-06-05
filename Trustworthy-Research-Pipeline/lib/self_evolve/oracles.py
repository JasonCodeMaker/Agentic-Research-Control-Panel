"""The 6 v1 Rule oracles + tiered admission resolver (plan §11.2).

Pure and deterministic: every oracle consumes already-gathered evidence (the LLM-judge
verdict and any re-run results are computed by the op handler and injected here). This
keeps D4 intact — effectiveness is decided only by measured oracles (original-reproduction
/ regression-delta), never by an LLM judgment.
"""

from self_evolve import schema

ORACLES = ("schema_scope", "faithfulness", "correction_integrity",
           "original_reproduction", "regression_smoke", "conflict")


def schema_scope(rule):
    """schema + bounded-scope gate."""
    try:
        schema.validate_rule(rule)
        return "pass"
    except schema.SchemaViolation:
        return "fail"


def faithfulness(judge):
    """LLM-judge entailment verdict (injected): is the Rule entailed by its cited source?"""
    if judge is None:
        return "inconclusive"
    return "pass" if judge.get("entailed") else "fail"


def correction_integrity(rule, *, source_excerpt=None, source_task_types=None):
    """Exact user correction preserved and scope not silently widened beyond it."""
    if source_excerpt and source_excerpt not in rule.get("content", ""):
        return "fail"
    if source_task_types is not None:
        rule_tt = set(rule.get("scope", {}).get("task_types", []))
        if not rule_tt.issubset(set(source_task_types)):
            return "fail"
    return "pass"


def original_reproduction(repro):
    """Measured: the failure reproduced before the Rule-guided fix and is gone after."""
    if not repro:
        return "inconclusive"
    return "pass" if repro.get("before") == "fail" and repro.get("after") == "pass" else "fail"


def regression_smoke(report):
    """No protected existing case regressed."""
    if report is None:
        return "inconclusive"
    return "fail" if report.get("regressions") else "pass"


def conflict(conflict_set):
    """No unresolved conflict with a higher-authority active entry."""
    return "fail" if conflict_set else "pass"


def resolve_admission(results):
    """Map oracle results → admission outcome (§11.2).

    Returns one of: 'rejected' | 'inconclusive' | 'advisory-admitted' | 'proven-effective'.
    Any failing oracle rejects. Effectiveness (proven) requires a measured oracle pass;
    otherwise a clean candidate is advisory-admitted (active, reduced priority, never floor).
    """
    vals = list(results.values())
    if any(v == "fail" for v in vals):
        return "rejected"
    if any(v == "error" for v in vals):
        return "inconclusive"

    def ok(name):
        return results.get(name) == "pass"

    base = ok("schema_scope") and ok("conflict") and (ok("faithfulness") or ok("correction_integrity"))
    if not base:
        return "inconclusive"
    if ok("original_reproduction") or ok("regression_delta"):
        return "proven-effective"
    if ok("regression_smoke"):
        return "advisory-admitted"
    return "inconclusive"
