"""Rule lifecycle state machine (plan §7.1). Pure: legal-edge table + guards.

`observed` is an event-derived signal group; from `candidate` onward a state belongs to
an immutable entity version. A changed Rule is a new version, never an in-place mutation.
"""

RULE_STATES = (
    "observed", "candidate", "validating", "provisional", "active",
    "superseded", "invalidated", "archived_reopenable", "rejected",
)

# Directed legal edges (from_state -> to_state) for a Rule version.
RULE_EDGES = frozenset({
    ("observed", "candidate"),
    ("candidate", "validating"),
    ("validating", "rejected"),
    ("validating", "provisional"),
    ("provisional", "active"),
    ("provisional", "invalidated"),
    ("active", "superseded"),
    ("active", "invalidated"),
    ("invalidated", "archived_reopenable"),
    ("archived_reopenable", "candidate"),
    ("rejected", "candidate"),
})

# States whose entries may be retrieved into the Context Pack.
RETRIEVABLE_STATES = frozenset({"active"})

# Terminal-for-this-version states (no onward edge except re-evaluation as a new version).
TERMINAL_STATES = frozenset({"superseded", "archived_reopenable", "rejected"})


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
