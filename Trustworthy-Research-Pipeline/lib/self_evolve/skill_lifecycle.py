"""Skill lifecycle state machine (plan §7.2). Pure: legal-edge table + guards.

Distinct from the Rule lifecycle: a Skill is an executable artifact, so installation,
canary, suspension, and rollback are first-class states with human gates between them.
"""

SKILL_STATES = (
    "observed", "candidate", "validating", "rejected", "validated",
    "awaiting_install_approval", "installing", "install_failed",
    "canary", "active", "suspended", "superseded", "retired",
)

SKILL_EDGES = frozenset({
    ("observed", "candidate"),
    ("candidate", "validating"),
    ("validating", "rejected"),
    ("validating", "validated"),
    ("validated", "awaiting_install_approval"),
    ("awaiting_install_approval", "candidate"),
    ("awaiting_install_approval", "installing"),
    ("installing", "canary"),
    ("installing", "install_failed"),
    ("install_failed", "awaiting_install_approval"),
    ("canary", "active"),
    ("canary", "suspended"),
    ("active", "suspended"),
    ("active", "superseded"),
    ("suspended", "canary"),
    ("suspended", "retired"),
    ("superseded", "canary"),
    ("rejected", "candidate"),
})

# States in which the installed Skill may actually run.
DEPLOYED_STATES = frozenset({"canary", "active"})

# Transitions that REMOVE authority — always allowed automatically (§7.2).
AUTHORITY_REMOVING = frozenset({("canary", "suspended"), ("active", "suspended")})

# Transitions that GRANT or RESTORE authority — never automatic without approval (§8/§12).
APPROVAL_REQUIRED = frozenset({
    ("awaiting_install_approval", "installing"),  # install
    ("suspended", "canary"),                      # restoration
    ("superseded", "canary"),                     # rollback (unless pre-authorized)
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
