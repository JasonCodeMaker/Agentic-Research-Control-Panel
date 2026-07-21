"""Package mutation policy with exact compatibility to the legacy matrix."""

from __future__ import annotations

from typing import Any

from .schema import compatibility_map, enum, require_enum


STATES = {
    "in-progress": [
        *enum("package_phase"),
        "BLOCKED",
        "STOPPED",
    ],
    "success": [
        status
        for status in enum("package_status_compat")
        if status in {"ADOPTED_UNCONFIRMED", "ADOPTED", "WIN_SUPERSEDED"}
    ],
    "fail": [
        status
        for status in enum("package_status_compat")
        if status in {"ARCHIVED", "ARCHIVED_CONDITIONAL"}
    ],
}
ACTIVE_PHASES = set(enum("package_phase"))
_TERMINAL_STATUS = compatibility_map("package_terminal_status")
SUCCESS_STATUS = {
    lifecycle: status
    for status, lifecycle in _TERMINAL_STATUS.items()
    if lifecycle in {"ADOPTED_UNCONFIRMED", "ADOPTED", "SUPERSEDED"}
}
FAIL_STATUS = {
    lifecycle: status
    for status, lifecycle in _TERMINAL_STATUS.items()
    if lifecycle in {"ARCHIVED", "ARCHIVED_CONDITIONAL"}
}

ALL_IN_PROGRESS = set(STATES["in-progress"])
ALL_SUCCESS = set(SUCCESS_STATUS.values())
ALL_FAIL = set(FAIL_STATUS.values())

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


def _cells(category: str, statuses: set[str]) -> set[tuple[str, str]]:
    return {(category, status) for status in statuses}


INSERT_LEGAL = {
    "experiments-row": _cells(
        "in-progress", {"CONTEXT_LOADED", "IMPLEMENTING", "READY_TO_LAUNCH"}
    ),
    "methodsTried": (
        _cells("in-progress", {"RESULT_ANALYSIS", "NEXT_ACTION_READY"})
        | _cells("success", ALL_SUCCESS)
        | _cells("fail", ALL_FAIL)
    ),
    "tracker-live-check-row": _cells(
        "in-progress", {"EXPERIMENT_RUNNING", "LIVE_ANALYSIS"}
    ),
    "tracker-resource-allocation-row": _cells(
        "in-progress", {"READY_TO_LAUNCH", "EXPERIMENT_RUNNING"}
    ),
    "tracker-impl-review-row": _cells(
        "in-progress", {"IMPLEMENTATION_REVIEW", "IMPLEMENTING"}
    ),
    "results-gate-row": _cells(
        "in-progress", {"EXPERIMENT_RUNNING", "LIVE_ANALYSIS", "RESULT_ANALYSIS"}
    ),
    "results-block": _cells("in-progress", {"RESULT_ANALYSIS"}),
    "analysis-insight": _cells("in-progress", ALL_IN_PROGRESS),
    "rule": _cells("in-progress", ALL_IN_PROGRESS),
    "doc-file": _cells("in-progress", ALL_IN_PROGRESS),
    "doc-card": _cells("in-progress", ALL_IN_PROGRESS),
    "tracker-chosen-route": _cells("in-progress", {"NEXT_ACTION_READY"}),
}

UPDATE_LEGAL = {
    "status": (
        _cells("in-progress", ALL_IN_PROGRESS)
        | _cells("success", ALL_SUCCESS)
        | _cells("fail", ALL_FAIL)
    )
    - {("success", "ADOPTED"), ("fail", "ARCHIVED")},
    "activeGate": _cells("in-progress", ALL_IN_PROGRESS),
    "primaryMetricVsGate": _cells("in-progress", ALL_IN_PROGRESS),
    "lastAction": _cells("in-progress", ALL_IN_PROGRESS),
    "lastUpdated": (
        _cells("in-progress", ALL_IN_PROGRESS)
        | _cells("success", ALL_SUCCESS)
        | _cells("fail", ALL_FAIL)
    ),
    "openRuns": _cells("in-progress", ALL_IN_PROGRESS),
    "currentBlocker": _cells("in-progress", ALL_IN_PROGRESS),
    "objectiveContract": _cells("in-progress", ALL_IN_PROGRESS),
    "experiments-row": _cells(
        "in-progress", {"CONTEXT_LOADED", "IMPLEMENTING", "READY_TO_LAUNCH"}
    ),
    "experiments-status": _cells("in-progress", ALL_IN_PROGRESS),
    "terminationMessage": (
        _cells("success", ALL_SUCCESS)
        | _cells("fail", ALL_FAIL)
        | _cells("in-progress", {"STOPPED"})
    ),
    "adoptionPath": _cells("success", {"ADOPTED_UNCONFIRMED", "ADOPTED"}),
    "supersededBy": _cells("success", {"WIN_SUPERSEDED"}),
    "reopenTrigger": _cells("fail", {"ARCHIVED_CONDITIONAL"}),
    "approval-ack-slot": (
        _cells("in-progress", ALL_IN_PROGRESS)
        | _cells("success", ALL_SUCCESS)
        | _cells("fail", ALL_FAIL)
    ),
    "results-gate-row": _cells("in-progress", ALL_IN_PROGRESS),
    "results-block": _cells(
        "in-progress",
        {"EXPERIMENT_RUNNING", "LIVE_ANALYSIS", "RESULT_ANALYSIS", "NEXT_ACTION_READY"},
    ),
    "results-verdict": _cells("in-progress", {"RESULT_ANALYSIS"}),
    "last-updated-time": (
        _cells("in-progress", ALL_IN_PROGRESS)
        | _cells("success", ALL_SUCCESS)
        | _cells("fail", ALL_FAIL)
    ),
    "rule": _cells("in-progress", ALL_IN_PROGRESS),
}

DELETE_LEGAL = {
    "experiments-row": _cells("in-progress", {"CONTEXT_LOADED", "IMPLEMENTING"}),
    "tracker-live-check-row": _cells("in-progress", ALL_IN_PROGRESS),
    "tracker-impl-review-row": _cells("in-progress", {"IMPLEMENTING"}),
    "methodsTried": _cells("in-progress", ALL_IN_PROGRESS),
    "doc-file": _cells("in-progress", ALL_IN_PROGRESS),
    "doc-card": _cells("in-progress", ALL_IN_PROGRESS),
    "rule": _cells(
        "in-progress", {"CONTEXT_LOADED", "IMPLEMENTING", "READY_TO_LAUNCH"}
    ),
}


def legacy_cell(
    lifecycle: str,
    phase: str | None,
    blocker: dict[str, Any] | None,
) -> tuple[str, str]:
    require_enum("package_lifecycle", lifecycle)
    if lifecycle == "ACTIVE":
        if blocker is not None:
            return ("in-progress", "BLOCKED")
        if phase not in ACTIVE_PHASES:
            raise ValueError("ACTIVE package without blocker requires a valid phase")
        return ("in-progress", str(phase))
    if lifecycle == "STOPPED":
        return ("in-progress", "STOPPED")
    if lifecycle in SUCCESS_STATUS:
        return ("success", SUCCESS_STATUS[lifecycle])
    if lifecycle in FAIL_STATUS:
        return ("fail", FAIL_STATUS[lifecycle])
    raise ValueError(f"unmappable package lifecycle: {lifecycle!r}")


def is_legal(
    lifecycle: str,
    phase: str | None,
    blocker: dict[str, Any] | None,
    operation: str,
    target: str | None,
) -> bool:
    """Return policy parity for one orthogonal package state."""
    cell = legacy_cell(lifecycle, phase, blocker)
    if operation == "check":
        return True
    if operation == "insert":
        return cell in INSERT_LEGAL.get(str(target), set())
    if operation == "update":
        return cell in UPDATE_LEGAL.get(str(target), set())
    if operation == "delete":
        return cell in DELETE_LEGAL.get(str(target), set())
    return False


def from_legacy(category: str, status: str, record: dict[str, Any] | None = None) -> dict[str, Any]:
    """Translate one legacy card state without inventing a blocked phase."""
    record = record or {}
    if category == "in-progress":
        if status == "BLOCKED":
            blocker = record.get("blocker") or {
                "code": "LEGACY_BLOCKER",
                "summary": str(record.get("currentBlocker") or "Imported blocked state"),
            }
            return {"lifecycle": "ACTIVE", "phase": None, "blocker": blocker}
        if status == "STOPPED":
            return {"lifecycle": "STOPPED", "phase": None, "blocker": None}
        if status in ACTIVE_PHASES:
            return {"lifecycle": "ACTIVE", "phase": status, "blocker": None}
    if category == "success":
        reverse = {value: key for key, value in SUCCESS_STATUS.items()}
        if status in reverse:
            return {"lifecycle": reverse[status], "phase": None, "blocker": None}
    if category == "fail":
        reverse = {value: key for key, value in FAIL_STATUS.items()}
        if status in reverse:
            return {"lifecycle": reverse[status], "phase": None, "blocker": None}
    raise ValueError(f"unknown legacy package state: {(category, status)!r}")


def to_legacy(record: dict[str, Any]) -> dict[str, str]:
    category, status = legacy_cell(
        str(record.get("lifecycle")),
        record.get("phase"),
        record.get("blocker"),
    )
    return {"category": category, "status": status}
