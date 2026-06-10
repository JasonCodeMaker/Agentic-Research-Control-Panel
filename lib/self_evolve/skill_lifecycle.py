"""Skill lifecycle state machine (plan §7.2). Pure: legal-edge table + guards.

Distinct from the Rule lifecycle: a Skill is an executable artifact, so installation,
canary, suspension, and rollback are first-class states with human gates between them.
"""

SKILL_STATES = (
    "OBSERVED", "CANDIDATE", "VALIDATING", "SKILL_REJECTED", "VALIDATED",
    "AWAITING_INSTALL_APPROVAL", "INSTALLING", "INSTALL_FAILED",
    "CANARY", "SKILL_ACTIVE", "SUSPENDED", "SKILL_SUPERSEDED", "RETIRED",
)

SKILL_EDGES = frozenset({
    ("OBSERVED", "CANDIDATE"),
    ("CANDIDATE", "VALIDATING"),
    ("VALIDATING", "SKILL_REJECTED"),
    ("VALIDATING", "VALIDATED"),
    ("VALIDATED", "AWAITING_INSTALL_APPROVAL"),
    ("AWAITING_INSTALL_APPROVAL", "CANDIDATE"),
    ("AWAITING_INSTALL_APPROVAL", "INSTALLING"),
    ("INSTALLING", "CANARY"),
    ("INSTALLING", "INSTALL_FAILED"),
    ("INSTALL_FAILED", "AWAITING_INSTALL_APPROVAL"),
    ("CANARY", "SKILL_ACTIVE"),
    ("CANARY", "SUSPENDED"),
    ("SKILL_ACTIVE", "SUSPENDED"),
    ("SKILL_ACTIVE", "SKILL_SUPERSEDED"),
    ("SUSPENDED", "CANARY"),
    ("SUSPENDED", "RETIRED"),
    ("SKILL_SUPERSEDED", "CANARY"),
    ("SKILL_REJECTED", "CANDIDATE"),
})

# States in which the installed Skill may actually run.
DEPLOYED_STATES = frozenset({"CANARY", "SKILL_ACTIVE"})

# Transitions that REMOVE authority — always allowed automatically (§7.2).
AUTHORITY_REMOVING = frozenset({("CANARY", "SUSPENDED"), ("SKILL_ACTIVE", "SUSPENDED")})

# Transitions that GRANT or RESTORE authority — never automatic without approval (§8/§12).
APPROVAL_REQUIRED = frozenset({
    ("AWAITING_INSTALL_APPROVAL", "INSTALLING"),  # install
    ("SUSPENDED", "CANARY"),                       # restoration
    ("SKILL_SUPERSEDED", "CANARY"),                # rollback (unless pre-authorized)
})


class IllegalTransition(Exception):
    """Raised when a (from_state, to_state) edge is not in the Skill legal-edge table."""


def is_legal(from_state, to_state):
    return (from_state, to_state) in SKILL_EDGES


def validate_edge(from_state, to_state):
    """Reject-before-write guard for Skill transitions."""
    if from_state not in SKILL_STATES:
        raise IllegalTransition(f"unknown from_state {from_state!r}")
    if to_state not in SKILL_STATES:
        raise IllegalTransition(f"unknown to_state {to_state!r}")
    if not is_legal(from_state, to_state):
        raise IllegalTransition(f"illegal Skill edge {from_state!r} -> {to_state!r}")
    return True


def requires_approval(from_state, to_state):
    """True iff this edge grants/restores authority and so needs an explicit approval."""
    return (from_state, to_state) in APPROVAL_REQUIRED
