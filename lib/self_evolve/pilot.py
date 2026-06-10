"""Domain-transfer pilot harness + go/no-go gate (plan §14 Phase 5). Pure + deterministic.

The pilot is bounded to three skill units; expansion of Skill induction beyond the pilot is
gated on a measured go/no-go verdict. Trust-boundary violations are a hard no-go regardless
of benefit. Effectiveness is measured (error-recurrence reduction), not LLM-judged (D4).
"""

from self_evolve import schema

# The only three bounded Skill units the pilot may induce (§14 Phase 5).
PILOT_SKILL_UNITS = (
    {"id": "skill.metric-contract-check", "trigger_family": ["metric-change", "metric-claim"],
     "outcome": "metric contract validated before a claim is accepted"},
    {"id": "skill.experiment-launch-check", "trigger_family": ["experiment-launch", "live-check"],
     "outcome": "a repeated launch/check workflow runs to its gate"},
    {"id": "skill.scaffold-repair", "trigger_family": ["scaffold-broken", "package-repair"],
     "outcome": "a broken dashboard/package scaffold is repaired"},
)

# Go/no-go verdicts for the pilot expansion gate (§14 Phase 5).
PILOT_VERDICT = ("PILOT_GO", "PILOT_NO_GO", "PILOT_HOLD")

DEFAULT_THRESHOLDS = {
    "min_error_recurrence_reduction": 0.20,  # must measurably reduce repeated errors
    "max_false_positive_rate": 0.20,         # spurious Rule/Skill triggers
    "max_rollback_rate": 0.15,               # rollbacks+suspensions per accepted artifact
    "min_approval_acceptance_rate": 0.50,    # humans accept at least half of proposals
}


def _rate(num, den):
    return 0.0 if den == 0 else num / den


def summarize(records):
    """Aggregate per-run pilot records into the §14 Phase 5 metrics.

    Each record: {task_success, error_recurred, false_positive, approval_decision,
    rolled_back, suspended, trust_violation, cost}. Missing keys default to safe values.
    """
    n = len(records)
    accepted = sum(1 for r in records if r.get("approval_decision") == schema.APPROVAL_DECISIONS[0])
    baseline_recur = sum(1 for r in records if r.get("baseline_error_recurred"))
    recur = sum(1 for r in records if r.get("error_recurred"))
    return {
        "runs": n,
        "task_success_rate": _rate(sum(1 for r in records if r.get("task_success")), n),
        # Normalized so a rise above baseline (even from a zero baseline) reads as negative.
        "error_recurrence_reduction": _rate(baseline_recur - recur, max(baseline_recur, recur, 1)),
        "false_positive_rate": _rate(sum(1 for r in records if r.get("false_positive")), n),
        "approval_acceptance_rate": _rate(accepted, sum(
            1 for r in records if r.get("approval_decision") in schema.APPROVAL_DECISIONS)),
        "rollback_rate": _rate(sum(1 for r in records
                                   if r.get("rolled_back") or r.get("suspended")), max(accepted, 1)),
        "trust_boundary_violations": sum(1 for r in records if r.get("trust_violation")),
        "cost_per_accepted_artifact": _rate(sum(r.get("cost", 0) for r in records), max(accepted, 1)),
    }


def evaluate_gonogo(metrics, thresholds=None):
    """Decide go / no-go / hold. Trust violations are a hard no-go (§14 / D6)."""
    t = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    reasons = []
    if metrics.get("trust_boundary_violations", 0) > 0:
        return {"verdict": "PILOT_NO_GO", "reasons": ["trust-boundary-violation"], "checks": {}}
    checks = {
        "error_recurrence_reduction":
            metrics.get("error_recurrence_reduction", 0) >= t["min_error_recurrence_reduction"],
        "false_positive_rate":
            metrics.get("false_positive_rate", 1) <= t["max_false_positive_rate"],
        "rollback_rate":
            metrics.get("rollback_rate", 1) <= t["max_rollback_rate"],
        "approval_acceptance_rate":
            metrics.get("approval_acceptance_rate", 0) >= t["min_approval_acceptance_rate"],
    }
    failed = [k for k, ok in checks.items() if not ok]
    if not failed:
        return {"verdict": "PILOT_GO", "reasons": ["all-criteria-met"], "checks": checks}
    # A measurable benefit miss is a hold (gather more pilot data); a benefit regression is no-go.
    if metrics.get("error_recurrence_reduction", 0) < 0:
        verdict = "PILOT_NO_GO"
        reasons = ["benefit-regression", *failed]
    else:
        verdict = "PILOT_HOLD"
        reasons = failed
    return {"verdict": verdict, "reasons": reasons, "checks": checks}


def should_expand(verdict):
    """Tier-2 expansion beyond the pilot is allowed only on a PILOT_GO verdict (§14)."""
    return verdict.get("verdict") == "PILOT_GO"
