"""(category, status, op, target) legality table.

Generated from references/matrix.md (spec section 4). When you change a row in
the matrix, change it here. The CLI looks up legality via is_legal().
"""

# 14-cell (category, status) state machine — must match schema.js. Brainstorm is
# no longer a package category: pre-package ideas live on the dashboard brainstorm
# lane (data/brainstorms.js) and are not research-op surfaces.
STATES = {
    "in-progress": ["CONTEXT_LOADED", "IMPLEMENTING", "IMPLEMENTATION_REVIEW",
                    "READY_TO_LAUNCH", "EXPERIMENT_RUNNING", "LIVE_ANALYSIS",
                    "RESULT_ANALYSIS", "NEXT_ACTION_READY", "BLOCKED"],
    "success":     ["ADOPTED_PENDING_ACK", "ADOPTED", "SUPERSEDED"],
    "fail":        ["ARCHIVED", "ARCHIVED_REOPENABLE"],
}

# Targets the matrix recognizes.
TARGETS = {
    # Inventory targets (paint multiple HTML surfaces via renderers)
    "status", "activeGate", "primaryMetricVsGate", "lastAction", "lastUpdated",
    "openRuns", "currentBlocker", "terminationMessage", "adoptionPath",
    "supersededBy", "reopenTrigger", "experiments-row", "experiments-status",
    "methodsTried",
    # HTML in-place targets (single-home, no painter)
    "tracker-live-check-row", "tracker-resource-allocation-row",
    "tracker-impl-review-row", "tracker-chosen-route",
    "results-gate-row", "results-block", "results-verdict",
    "analysis-rule", "analysis-insight",
    "doc-file", "doc-card",
    "ack-slot",
    "last-updated-time",
}

# Insert legality: target -> set of (category, status) cells where the Insert is allowed.
INSERT_LEGAL = {
    "experiments-row": {
        ("in-progress", s) for s in ("CONTEXT_LOADED", "IMPLEMENTING", "READY_TO_LAUNCH")
    },
    "methodsTried": (
        {("in-progress", s) for s in ("RESULT_ANALYSIS", "NEXT_ACTION_READY")}
        | {("success", s)  for s in STATES["success"]}
        | {("fail", s)     for s in STATES["fail"]}
    ),
    "tracker-live-check-row": {
        ("in-progress", s) for s in ("EXPERIMENT_RUNNING", "LIVE_ANALYSIS")
    },
    "tracker-resource-allocation-row": {
        ("in-progress", s) for s in ("READY_TO_LAUNCH", "EXPERIMENT_RUNNING")
    },
    "tracker-impl-review-row": {
        ("in-progress", s) for s in ("IMPLEMENTATION_REVIEW", "IMPLEMENTING")
    },
    "results-gate-row": {
        ("in-progress", s) for s in ("EXPERIMENT_RUNNING", "LIVE_ANALYSIS", "RESULT_ANALYSIS")
    },
    "results-block": {
        ("in-progress", "RESULT_ANALYSIS")
    },
    "analysis-rule": {("in-progress", s) for s in STATES["in-progress"]},
    "analysis-insight": {("in-progress", s) for s in STATES["in-progress"]},
    "doc-file": {("in-progress", s) for s in STATES["in-progress"]},
    "doc-card": {("in-progress", s) for s in STATES["in-progress"]},
    "tracker-chosen-route": {("in-progress", "NEXT_ACTION_READY")},
}

# Update legality: target -> set of cells where update is allowed.
# Lane-crossing status updates require T1 ack; that's checked in validate.py, not here.
UPDATE_LEGAL = {
    "status": (
        {(c, s) for c, statuses in STATES.items() for s in statuses}
        - {("success", "ADOPTED"), ("fail", "ARCHIVED")}  # terminal-frozen
    ),
    "activeGate":           {("in-progress", s) for s in STATES["in-progress"]},
    "primaryMetricVsGate":  {("in-progress", s) for s in STATES["in-progress"]},
    "lastAction":           {("in-progress", s) for s in STATES["in-progress"]},
    "lastUpdated":          {(c, s) for c, statuses in STATES.items() for s in statuses},
    "openRuns":             {("in-progress", s) for s in STATES["in-progress"]},
    "currentBlocker":       {("in-progress", s) for s in STATES["in-progress"]},
    "experiments-status":   {("in-progress", s) for s in STATES["in-progress"]},
    "terminationMessage":   {("success", s) for s in STATES["success"]} | {("fail", s) for s in STATES["fail"]},
    "adoptionPath":         {("success", "ADOPTED_PENDING_ACK"), ("success", "ADOPTED")},
    "supersededBy":         {("success", "SUPERSEDED")},
    "reopenTrigger":        {("fail", "ARCHIVED_REOPENABLE")},
    "ack-slot":             {(c, s) for c, statuses in STATES.items() for s in statuses},
    "results-verdict":      {("in-progress", "RESULT_ANALYSIS")},
    "last-updated-time":    {(c, s) for c, statuses in STATES.items() for s in statuses},
}

# Delete legality: target -> set of cells where delete is allowed.
DELETE_LEGAL = {
    "experiments-row": {
        ("in-progress", s) for s in ("CONTEXT_LOADED", "IMPLEMENTING")
    },
    "tracker-live-check-row":    {("in-progress", s) for s in STATES["in-progress"]},
    "tracker-impl-review-row":   {("in-progress", "IMPLEMENTING")},
    "methodsTried":              {("in-progress", s) for s in STATES["in-progress"]},
    "doc-file":                  {("in-progress", s) for s in STATES["in-progress"]},
    "doc-card":                  {("in-progress", s) for s in STATES["in-progress"]},
    # results-block and inventory-entry are intentionally never legal — see spec D7, D8.
}

# Check is universal — every (category, status) cell allows it.
CHECK_LEGAL = {(c, s) for c, statuses in STATES.items() for s in statuses}


def is_legal(category: str, status: str, op: str, target: str | None) -> bool:
    """Return True iff (category, status, op, target) is a legal mutation.

    target may be None only when op == "check" (universal across all cells).
    """
    cell = (category, status)
    if op == "check":
        return cell in CHECK_LEGAL
    if op == "insert":
        return cell in INSERT_LEGAL.get(target, set())
    if op == "update":
        return cell in UPDATE_LEGAL.get(target, set())
    if op == "delete":
        return cell in DELETE_LEGAL.get(target, set())
    return False
