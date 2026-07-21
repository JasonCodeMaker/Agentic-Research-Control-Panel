"""Compatibility import for the central research-state mutation policy.

The policy owner is ``lib.research_state.policy``. This module remains only
because existing research-op handlers and one-release compatibility tests
import ``transitions`` by filename.
"""

from __future__ import annotations

import sys
from pathlib import Path


PIPELINE_ROOT = Path(__file__).resolve().parents[3]
if str(PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(PIPELINE_ROOT))

from lib.research_state.policy import (  # noqa: E402,F401
    DELETE_LEGAL,
    INSERT_LEGAL,
    STATES,
    TARGETS,
    UPDATE_LEGAL,
)

__all__ = [
    "CHECK_LEGAL",
    "DELETE_LEGAL",
    "INSERT_LEGAL",
    "RETIRED_TARGETS",
    "STATES",
    "TARGETS",
    "UPDATE_LEGAL",
    "is_legal",
]


RETIRED_TARGETS = {
    "package-invariant": "use --target rule (level=package, kind=binding)",
    "analysis-rule": "use --target rule (level=package, kind=lesson)",
}

CHECK_LEGAL = {
    (category, status)
    for category, statuses in STATES.items()
    for status in statuses
}


def is_legal(category: str, status: str, op: str, target: str | None) -> bool:
    """Compatibility lookup over the frozen legacy cell representation."""
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
