"""Self-evolution dashboard projection (plan §13.2/§13.3). Pure + deterministic.

The dashboard reads only research_html/data/self-evolution.{json,js}, which are deterministically
rebuilt from the authoritative stores. Consistency oracles fail closed on any fold/projection drift.
"""

import json
from pathlib import Path

from self_evolve import store


class ConsistencyError(Exception):
    """Raised when a projection does not equal the fold of its authoritative stores."""


def _fold_states(log_path):
    folded = store.fold(store.read_log(log_path))
    return {f"{eid}@{ver}": st for (eid, ver), st in folded.items()}


def build_projection(selfevolve_root):
    """Deterministic projection of rule + skill states and pending human gates."""
    root = Path(selfevolve_root)
    rules = _fold_states(root / "rules" / "transitions.jsonl")
    skills = _fold_states(root / "skills" / "transitions.jsonl")
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


def assert_consistent(selfevolve_root, projection):
    """Fail closed if the projection drifts from the authoritative fold (§13.3)."""
    fresh = build_projection(selfevolve_root)
    if projection.get("rules") != fresh["rules"]:
        raise ConsistencyError("projection-drift: rules")
    if projection.get("skills") != fresh["skills"]:
        raise ConsistencyError("projection-drift: skills")
    return True


def write_projection(selfevolve_root, dashboard_root):
    """Rebuild + write self-evolution.json and .js (derived, never hand-edited). Returns the projection."""
    proj = build_projection(selfevolve_root)
    blob = json.dumps(proj, indent=2, ensure_ascii=False, sort_keys=True)
    data = Path(dashboard_root) / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "self-evolution.json").write_text(blob + "\n", encoding="utf-8")
    (data / "self-evolution.js").write_text(
        "window.RESEARCH_SELF_EVOLUTION = " + blob + ";\n", encoding="utf-8")
    return proj
