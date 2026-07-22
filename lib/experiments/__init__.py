"""Canonical experiment and run storage under ``.research/experiments``."""

from .status import (
    RUNNING_STATUSES,
    TERMINAL_STATUSES,
    canonical_status,
    exit_status,
    is_terminal,
)

__all__ = [
    "RUNNING_STATUSES",
    "TERMINAL_STATUSES",
    "canonical_status",
    "exit_status",
    "is_terminal",
]
