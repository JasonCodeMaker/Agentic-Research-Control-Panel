"""Canonical experiment and run storage under ``.research/experiments``."""

from __future__ import annotations

from typing import Any

from .status import (
    RUNNING_STATUSES,
    TERMINAL_STATUSES,
    canonical_status,
    exit_status,
    is_terminal,
)

__all__ = [
    "LaunchResult",
    "PreparedRun",
    "RUNNING_STATUSES",
    "ReconcileResult",
    "TERMINAL_STATUSES",
    "canonical_status",
    "extract_result",
    "exit_status",
    "is_terminal",
    "launch_run",
    "open_runs",
    "prepare_run",
    "reconcile_runs",
    "run_summary",
]


def __getattr__(name: str) -> Any:
    """Load command modules lazily so ``python -m`` has no double-import warning."""
    if name in {"LaunchResult", "PreparedRun", "launch_run", "prepare_run"}:
        from . import launch

        return getattr(launch, name)
    if name in {"ReconcileResult", "reconcile_runs"}:
        from . import reconcile

        return getattr(reconcile, name)
    if name in {"open_runs", "run_summary"}:
        from . import report

        return getattr(report, name)
    if name == "extract_result":
        from . import extract

        return extract.extract_result
    raise AttributeError(name)
