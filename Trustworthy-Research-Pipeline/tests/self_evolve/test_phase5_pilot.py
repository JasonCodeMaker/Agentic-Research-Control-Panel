"""Phase 5 — pilot harness + go/no-go gate (§14 Phase 5)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

from self_evolve import pilot  # noqa: E402


def test_pilot_bounded_to_three_units():
    assert len(pilot.PILOT_SKILL_UNITS) == 3
    ids = {u["id"] for u in pilot.PILOT_SKILL_UNITS}
    assert ids == {"skill.metric-contract-check", "skill.experiment-launch-check",
                   "skill.scaffold-repair"}


def _good_run(**over):
    base = {"task_success": True, "baseline_error_recurred": True, "error_recurred": False,
            "false_positive": False, "approval_decision": "approved",
            "rolled_back": False, "suspended": False, "trust_violation": False, "cost": 100}
    base.update(over)
    return base


def test_summary_computes_recurrence_reduction():
    recs = [_good_run(), _good_run(), _good_run(error_recurred=True)]
    m = pilot.summarize(recs)
    # 3 baseline recurrences, 1 remaining → 2/3 reduction
    assert round(m["error_recurrence_reduction"], 2) == 0.67
    assert m["false_positive_rate"] == 0.0


def test_clean_pilot_is_go():
    m = pilot.summarize([_good_run() for _ in range(10)])
    verdict = pilot.evaluate_gonogo(m)
    assert verdict["verdict"] == "go"
    assert pilot.should_expand(verdict) is True


def test_trust_violation_is_hard_no_go():
    recs = [_good_run() for _ in range(10)] + [_good_run(trust_violation=True)]
    verdict = pilot.evaluate_gonogo(pilot.summarize(recs))
    assert verdict["verdict"] == "no-go"
    assert "trust-boundary-violation" in verdict["reasons"]
    assert pilot.should_expand(verdict) is False


def test_high_false_positive_holds():
    recs = [_good_run(false_positive=True) for _ in range(10)]
    verdict = pilot.evaluate_gonogo(pilot.summarize(recs))
    assert verdict["verdict"] == "hold"
    assert "false_positive_rate" in verdict["reasons"]
    assert pilot.should_expand(verdict) is False


def test_benefit_regression_is_no_go():
    # more errors recurred than baseline → negative reduction
    recs = [_good_run(baseline_error_recurred=False, error_recurred=True) for _ in range(10)]
    verdict = pilot.evaluate_gonogo(pilot.summarize(recs))
    assert verdict["verdict"] == "no-go"
    assert "benefit-regression" in verdict["reasons"]


def test_frequent_rollback_holds():
    recs = [_good_run() for _ in range(8)] + [_good_run(rolled_back=True) for _ in range(4)]
    verdict = pilot.evaluate_gonogo(pilot.summarize(recs))
    assert verdict["verdict"] == "hold"
    assert "rollback_rate" in verdict["reasons"]
