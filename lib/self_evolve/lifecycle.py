"""Rule lifecycle state machine (plan §7.1). Pure: legal-edge table + guards.

`OBSERVED` is an event-derived signal group; from `CANDIDATE` onward a state belongs to
an immutable entity version. A changed Rule is a new version, never an in-place mutation.
"""

RULE_STATES = (
    "OBSERVED", "CANDIDATE", "VALIDATING", "PROVISIONAL", "RULE_ACTIVE",
    "RULE_SUPERSEDED", "INVALIDATED", "ARCHIVED_CONDITIONAL", "RULE_REJECTED",
)

# Directed legal edges (from_state -> to_state) for a Rule version.
RULE_EDGES = frozenset({
    ("OBSERVED", "CANDIDATE"),
    ("CANDIDATE", "VALIDATING"),
    ("VALIDATING", "RULE_REJECTED"),
    ("VALIDATING", "PROVISIONAL"),
    ("PROVISIONAL", "RULE_ACTIVE"),
    ("PROVISIONAL", "INVALIDATED"),
    ("RULE_ACTIVE", "RULE_SUPERSEDED"),
    ("RULE_ACTIVE", "INVALIDATED"),
    ("INVALIDATED", "ARCHIVED_CONDITIONAL"),
    ("ARCHIVED_CONDITIONAL", "CANDIDATE"),
    ("RULE_REJECTED", "CANDIDATE"),
})

# States whose entries may be retrieved into the Context Pack.
RETRIEVABLE_STATES = frozenset({"RULE_ACTIVE"})

# Terminal-for-this-version states (no onward edge). ARCHIVED_CONDITIONAL is a quasi-terminal
# with a conditional re-entry edge back to CANDIDATE, so it is NOT listed here.
TERMINAL_STATES = frozenset({"RULE_SUPERSEDED", "RULE_REJECTED"})


class IllegalTransition(Exception):
    """Raised when a (from_state, to_state) edge is not in the legal-edge table."""


def is_legal(from_state, to_state):
    """True iff the edge exists in the Rule legal-edge table."""
    return (from_state, to_state) in RULE_EDGES


def validate_edge(from_state, to_state):
    """Reject-before-write guard: raise IllegalTransition on an unknown edge."""
    if from_state not in RULE_STATES:
        raise IllegalTransition(f"unknown from_state {from_state!r}")
    if to_state not in RULE_STATES:
        raise IllegalTransition(f"unknown to_state {to_state!r}")
    if not is_legal(from_state, to_state):
        raise IllegalTransition(f"illegal Rule edge {from_state!r} -> {to_state!r}")
    return True
