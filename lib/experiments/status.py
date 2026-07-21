"""Canonical run-status handling and one-release legacy aliases."""

from __future__ import annotations

from typing import Any

from lib.research_state.schema import load_schema, status_group


RUNNING_STATUSES = status_group("run", "active")
TERMINAL_STATUSES = status_group("run", "terminal")


def canonical_status(value: Any) -> str:
    """Return one canonical run status or reject the unknown value."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"run status must be a non-empty string, got {value!r}")
    raw = value.strip()
    schema = load_schema()
    canonical = schema["compatibility"]["run_status"].get(raw, raw)
    allowed = set(schema["enums"]["run_status"])
    if canonical not in allowed:
        raise ValueError(f"unknown run status: {value!r}")
    return canonical


def is_terminal(value: Any) -> bool:
    try:
        return canonical_status(value) in TERMINAL_STATUSES
    except ValueError:
        return False


def exit_status(exit_code: int | None) -> str:
    if exit_code == 0:
        return "COMPLETED"
    if exit_code is not None and exit_code < 0:
        return "HALTED"
    return "FAILED"
