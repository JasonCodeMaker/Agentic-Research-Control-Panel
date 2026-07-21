"""Step 2 — Rule state machine: every legal edge accepted, illegal rejected (§7.1)."""
import itertools
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

from self_evolve import lifecycle as lc  # noqa: E402


def test_all_declared_edges_are_legal():
    for a, b in lc.RULE_EDGES:
        assert lc.is_legal(a, b)
        assert lc.validate_edge(a, b) is True


def test_full_happy_path_observed_to_active():
    path = ["OBSERVED", "CANDIDATE", "VALIDATING", "PROVISIONAL", "RULE_ACTIVE"]
    for a, b in zip(path, path[1:]):
        assert lc.validate_edge(a, b) is True


def test_invalidate_then_reopen_loops_back_to_candidate():
    for a, b in [("RULE_ACTIVE", "INVALIDATED"), ("INVALIDATED", "ARCHIVED_CONDITIONAL"),
                 ("ARCHIVED_CONDITIONAL", "CANDIDATE")]:
        assert lc.validate_edge(a, b) is True


def test_illegal_skip_edge_rejected():
    with pytest.raises(lc.IllegalTransition):
        lc.validate_edge("CANDIDATE", "RULE_ACTIVE")  # must pass through VALIDATING/PROVISIONAL


def test_cannot_revive_active_from_rejected():
    with pytest.raises(lc.IllegalTransition):
        lc.validate_edge("RULE_REJECTED", "RULE_ACTIVE")


def test_unknown_state_rejected():
    with pytest.raises(lc.IllegalTransition):
        lc.validate_edge("RULE_ACTIVE", "zombie")


def test_no_undeclared_edge_is_legal():
    # Exhaustively: any pair not in the table must be illegal.
    for a, b in itertools.product(lc.RULE_STATES, repeat=2):
        assert lc.is_legal(a, b) == ((a, b) in lc.RULE_EDGES)


def test_only_rule_active_is_retrievable():
    assert lc.RETRIEVABLE_STATES == frozenset({"RULE_ACTIVE"})
