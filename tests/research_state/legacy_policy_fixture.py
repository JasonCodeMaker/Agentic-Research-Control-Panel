"""Frozen pre-cutover Package legality matrix.

This fixture intentionally imports no production policy code.  It preserves
the matrix that existed before ``lib.research_state.policy`` became the sole
runtime owner, so the cutover test can detect future permission drift.
"""

STATES = {
    "in-progress": (
        "CONTEXT_LOADED",
        "IMPLEMENTING",
        "IMPLEMENTATION_REVIEW",
        "READY_TO_LAUNCH",
        "EXPERIMENT_RUNNING",
        "LIVE_ANALYSIS",
        "RESULT_ANALYSIS",
        "NEXT_ACTION_READY",
        "BLOCKED",
        "DECISION_ADJUDICATION",
        "STOPPED",
    ),
    "success": ("ADOPTED_UNCONFIRMED", "ADOPTED", "WIN_SUPERSEDED"),
    "fail": ("ARCHIVED", "ARCHIVED_CONDITIONAL"),
}

TARGETS = {
    "status",
    "activeGate",
    "primaryMetricVsGate",
    "lastAction",
    "lastUpdated",
    "openRuns",
    "currentBlocker",
    "terminationMessage",
    "adoptionPath",
    "supersededBy",
    "reopenTrigger",
    "objectiveContract",
    "experiments-row",
    "experiments-status",
    "methodsTried",
    "rule",
    "tracker-live-check-row",
    "tracker-resource-allocation-row",
    "tracker-impl-review-row",
    "tracker-chosen-route",
    "results-gate-row",
    "results-block",
    "results-verdict",
    "analysis-insight",
    "doc-file",
    "doc-card",
    "approval-ack-slot",
    "last-updated-time",
}


def _cells(category, statuses):
    return {(category, status) for status in statuses}


INSERT_LEGAL = {
    "experiments-row": _cells(
        "in-progress", ("CONTEXT_LOADED", "IMPLEMENTING", "READY_TO_LAUNCH")
    ),
    "methodsTried": (
        _cells("in-progress", ("RESULT_ANALYSIS", "NEXT_ACTION_READY"))
        | _cells("success", STATES["success"])
        | _cells("fail", STATES["fail"])
    ),
    "tracker-live-check-row": _cells(
        "in-progress", ("EXPERIMENT_RUNNING", "LIVE_ANALYSIS")
    ),
    "tracker-resource-allocation-row": _cells(
        "in-progress", ("READY_TO_LAUNCH", "EXPERIMENT_RUNNING")
    ),
    "tracker-impl-review-row": _cells(
        "in-progress", ("IMPLEMENTATION_REVIEW", "IMPLEMENTING")
    ),
    "results-gate-row": _cells(
        "in-progress",
        ("EXPERIMENT_RUNNING", "LIVE_ANALYSIS", "RESULT_ANALYSIS"),
    ),
    "results-block": {("in-progress", "RESULT_ANALYSIS")},
    "analysis-insight": _cells("in-progress", STATES["in-progress"]),
    "rule": _cells("in-progress", STATES["in-progress"]),
    "doc-file": _cells("in-progress", STATES["in-progress"]),
    "doc-card": _cells("in-progress", STATES["in-progress"]),
    "tracker-chosen-route": {("in-progress", "NEXT_ACTION_READY")},
}

UPDATE_LEGAL = {
    "status": {
        (category, status)
        for category, statuses in STATES.items()
        for status in statuses
    }
    - {("success", "ADOPTED"), ("fail", "ARCHIVED")},
    "activeGate": _cells("in-progress", STATES["in-progress"]),
    "primaryMetricVsGate": _cells("in-progress", STATES["in-progress"]),
    "lastAction": _cells("in-progress", STATES["in-progress"]),
    "lastUpdated": {
        (category, status)
        for category, statuses in STATES.items()
        for status in statuses
    },
    "openRuns": _cells("in-progress", STATES["in-progress"]),
    "currentBlocker": _cells("in-progress", STATES["in-progress"]),
    "objectiveContract": _cells("in-progress", STATES["in-progress"]),
    "experiments-row": _cells(
        "in-progress", ("CONTEXT_LOADED", "IMPLEMENTING", "READY_TO_LAUNCH")
    ),
    "experiments-status": _cells("in-progress", STATES["in-progress"]),
    "terminationMessage": (
        _cells("success", STATES["success"])
        | _cells("fail", STATES["fail"])
        | {("in-progress", "STOPPED")}
    ),
    "adoptionPath": {
        ("success", "ADOPTED_UNCONFIRMED"),
        ("success", "ADOPTED"),
    },
    "supersededBy": {("success", "WIN_SUPERSEDED")},
    "reopenTrigger": {("fail", "ARCHIVED_CONDITIONAL")},
    "approval-ack-slot": {
        (category, status)
        for category, statuses in STATES.items()
        for status in statuses
    },
    "results-gate-row": _cells("in-progress", STATES["in-progress"]),
    "results-block": _cells(
        "in-progress",
        (
            "EXPERIMENT_RUNNING",
            "LIVE_ANALYSIS",
            "RESULT_ANALYSIS",
            "NEXT_ACTION_READY",
        ),
    ),
    "results-verdict": {("in-progress", "RESULT_ANALYSIS")},
    "last-updated-time": {
        (category, status)
        for category, statuses in STATES.items()
        for status in statuses
    },
    "rule": _cells("in-progress", STATES["in-progress"]),
}

DELETE_LEGAL = {
    "experiments-row": _cells(
        "in-progress", ("CONTEXT_LOADED", "IMPLEMENTING")
    ),
    "tracker-live-check-row": _cells("in-progress", STATES["in-progress"]),
    "tracker-impl-review-row": {("in-progress", "IMPLEMENTING")},
    "methodsTried": _cells("in-progress", STATES["in-progress"]),
    "doc-file": _cells("in-progress", STATES["in-progress"]),
    "doc-card": _cells("in-progress", STATES["in-progress"]),
    "rule": _cells(
        "in-progress", ("CONTEXT_LOADED", "IMPLEMENTING", "READY_TO_LAUNCH")
    ),
}


def is_legal(category, status, operation, target):
    cell = (category, status)
    if operation == "check":
        return category in STATES and status in STATES[category]
    if operation == "insert":
        return cell in INSERT_LEGAL.get(target, set())
    if operation == "update":
        return cell in UPDATE_LEGAL.get(target, set())
    if operation == "delete":
        return cell in DELETE_LEGAL.get(target, set())
    return False
