"""Small capability policy for Packages created by the vNext Scope flow."""

from __future__ import annotations

from typing import Any


DRAFT_TARGETS = {
    "abstract",
    "activeGate",
    "doc-card",
    "doc-file",
    "last-updated-time",
    "lastAction",
    "lastUpdated",
    "objectiveContract",
    "primaryMetricVsGate",
}

ACTIVE_INSERT_TARGETS = {
    "analysis-insight",
    "doc-card",
    "doc-file",
    "methodsTried",
    "results-block",
    "results-gate-row",
    "rule",
    "tracker-chosen-route",
    "tracker-impl-review-row",
    "tracker-live-check-row",
    "tracker-resource-allocation-row",
}

ACTIVE_UPDATE_TARGETS = {
    "abstract",
    "activeGate",
    "approval-ack-slot",
    "currentBlocker",
    "experiments-status",
    "last-updated-time",
    "lastAction",
    "lastUpdated",
    "methodsTried",
    "openRuns",
    "primaryMetricVsGate",
    "results-block",
    "results-gate-row",
    "results-verdict",
    "rule",
    "status",
    "tracker-impl-review-row",
}

ACTIVE_DELETE_TARGETS = {
    "doc-card",
    "doc-file",
    "methodsTried",
    "rule",
    "tracker-impl-review-row",
    "tracker-live-check-row",
}

TERMINAL_INSERT_TARGETS = {"analysis-insight", "methodsTried", "rule"}
TERMINAL_UPDATE_TARGETS = {"last-updated-time", "lastUpdated", "rule"}


def uses_capability_policy(package: dict[str, Any]) -> bool:
    """Execution Lease presence marks Packages governed by the compact policy."""
    return isinstance(package.get("executionLease"), dict)


def is_legal(
    package: dict[str, Any],
    operation: str,
    target: str | None,
) -> bool:
    """Authorize data capabilities without a phase-by-target cross product."""
    if operation == "check":
        return True
    selected = str(target)
    package_lifecycle = package.get("lifecycle")
    if package_lifecycle == "DRAFT":
        return operation in {"insert", "update", "delete"} and selected in DRAFT_TARGETS
    if package_lifecycle == "ACTIVE":
        if package.get("blocker") is not None and selected not in {
            "analysis-insight",
            "currentBlocker",
            "last-updated-time",
            "lastAction",
            "lastUpdated",
            "rule",
            "status",
        }:
            return False
        allowed = {
            "insert": ACTIVE_INSERT_TARGETS,
            "update": ACTIVE_UPDATE_TARGETS,
            "delete": ACTIVE_DELETE_TARGETS,
        }.get(operation, set())
        return selected in allowed
    if package_lifecycle in {
        "ADOPTED_UNCONFIRMED",
        "ADOPTED",
        "SUPERSEDED",
        "ARCHIVED",
        "ARCHIVED_CONDITIONAL",
        "STOPPED",
    }:
        allowed = {
            "insert": TERMINAL_INSERT_TARGETS,
            "update": TERMINAL_UPDATE_TARGETS,
        }.get(operation, set())
        return selected in allowed
    return False
