"""Pure self-evolution read model over unified management state.

This module deliberately owns no filesystem projection.  The interface
builder may consume :func:`build_projection`, but only ``lib.interface`` may
write browser-facing files.
"""

import copy
from pathlib import Path
from typing import Any, Mapping

try:
    from ..research_state import EventStore
except ImportError:
    from research_state import EventStore  # type: ignore

try:
    from . import state as memory, store
except ImportError:
    from self_evolve import state as memory, store  # type: ignore


class ConsistencyError(Exception):
    """Raised when a projection does not equal the fold of its authoritative stores."""


def _fold_states(log_path):
    folded = store.fold(store.read_log(log_path))
    return {f"{eid}@{ver}": st for (eid, ver), st in folded.items()}


def build_projection(
    research,
    *,
    skill_root=None,
    state_snapshot: Mapping[str, Any] | None = None,
):
    """Deterministic projection; Rule memory comes only from management state."""
    paths = memory.resolve_paths(research)
    current = (
        copy.deepcopy(dict(state_snapshot))
        if state_snapshot is not None
        else EventStore(paths).state()
    )
    rules = {
        key: value.get("lifecycle_state") or value.get("status")
        for key, value in sorted(current["aggregates"]["rule"].items())
    }
    skills = (
        _fold_states(Path(skill_root) / "skills" / "transitions.jsonl")
        if skill_root is not None
        else {}
    )
    pending = sorted(k for k, st in skills.items() if st == "AWAITING_INSTALL_APPROVAL")
    suspended = sorted(k for k, st in skills.items() if st == "SUSPENDED")
    return {
        "rules": rules,
        "skills": skills,
        "pending_approvals": pending,
        "suspended_skills": suspended,
        "counts": {"rules": len(rules), "skills": len(skills),
                   "active_rules": sum(1 for s in rules.values() if s == "RULE_ACTIVE"),
                   "active_skills": sum(1 for s in skills.values() if s in ("SKILL_ACTIVE", "CANARY"))},
    }


def assert_consistent(research, projection, *, skill_root=None):
    """Fail closed if the projection drifts from the authoritative fold (§13.3)."""
    fresh = build_projection(research, skill_root=skill_root)
    if projection.get("rules") != fresh["rules"]:
        raise ConsistencyError("projection-drift: rules")
    if projection.get("skills") != fresh["skills"]:
        raise ConsistencyError("projection-drift: skills")
    return True
