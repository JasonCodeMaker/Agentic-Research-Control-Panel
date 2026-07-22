from lib.research_state import lifecycle


def _package(state="ACTIVE", *, blocked=False):
    return {
        "id": "pkg",
        "lifecycle": state,
        "blocker": {"summary": "wait"} if blocked else None,
        "executionLease": {"status": "OPEN"},
    }


def test_active_policy_uses_capabilities_instead_of_phase_cells():
    package = _package()
    package["phase"] = "CONTEXT_LOADED"
    assert lifecycle.is_legal(package, "insert", "analysis-insight")
    package["phase"] = "EXPERIMENT_RUNNING"
    assert lifecycle.is_legal(package, "insert", "analysis-insight")
    assert lifecycle.is_legal(package, "update", "abstract")
    assert not lifecycle.is_legal(package, "insert", "experiments-row")


def test_blocked_policy_keeps_analysis_but_rejects_execution_mutations():
    package = _package(blocked=True)
    assert lifecycle.is_legal(package, "insert", "analysis-insight")
    assert not lifecycle.is_legal(package, "update", "experiments-status")


def test_terminal_policy_allows_analysis_and_rule_distillation_only():
    package = _package("ADOPTED")
    assert lifecycle.is_legal(package, "insert", "analysis-insight")
    assert lifecycle.is_legal(package, "insert", "rule")
    assert not lifecycle.is_legal(package, "update", "abstract")
    assert not lifecycle.is_legal(package, "update", "status")
