"""Stage 0.5 front-door admission layer — the post-init front door for /research-auto.

A small deterministic state machine (A-G) that runs BEFORE the experiment loop. If the project is not
yet ready to run, it drives the Step-3 formation roles (R1-R3) up to the existing human gates, then
stops. The boundary is strict: formation capability lives in auto, but commit authority stays with the
user / Triage — this layer may PROPOSE through Triage, never ratify or materialize from pending state.
"""

import sys
from pathlib import Path

_PIPE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PIPE / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import scope_ssot  # noqa: E402
import driver  # noqa: E402

AUTONOMY_LEVELS = ("supervised", "checkpoints", "async", "autonomous")
DEFAULT_AUTONOMY_LEVEL = "autonomous"

ACTION_TYPES = {
    "handoff_dashboard_init", "propose_project", "propose_direction", "propose_task",
    "materialize_package", "run_readiness", "enter_auto_loop", "block_for_user_disposal",
}

# State that still needs a Triage proposal -> (scope level, proposal action type).
_PROPOSAL_STATES = {
    "B": ("project", "propose_project"),
    "C": ("direction", "propose_direction"),
    "D": ("task", "propose_task"),
}


def _active(nodes, level):
    """Active scope nodes of a given level in the folded SSOT projection."""
    return [n for n in nodes.values() if n.get("level") == level and n.get("status") == "active"]


def _package_for_direction(root, direction_ids):
    """True iff the inventory carries a package materialized from one of these committed directions."""
    inv = Path(root) / "research_html" / "data" / "research-packages.js"
    if not inv.exists():
        return False
    text = inv.read_text(encoding="utf-8")
    return any(f'sourceScopeNode: "{did}"' in text for did in direction_ids)


def _requested_autonomy(context):
    """Autonomy requested by context, defaulting to Autonomous as the front-door policy."""
    proposal = context.get("task_proposal") or {}
    yardstick = proposal.get("yardstick") or {}
    return context.get("autonomy_level") or context.get("dial") or yardstick.get("autonomy_level") or DEFAULT_AUTONOMY_LEVEL


def _proposal_with_autonomy(proposal, autonomy_level):
    """Return a detached task proposal carrying the chosen/default autonomy level."""
    if proposal is None:
        proposal = {}
    out = dict(proposal)
    yardstick = dict(out.get("yardstick") or {})
    yardstick["autonomy_level"] = autonomy_level
    out["yardstick"] = yardstick
    return out


def detect_admission_state(root, *, readiness_ok=None):
    """Inspect the project and return the admission state A-G (see the front-door state machine)."""
    root = Path(root)
    if not (root / "research_html" / "index.html").exists():
        return "A"  # dashboard scaffolding is an init op, not an auto-loop mutation
    records = scope_ssot.read_log(root / "outputs" / "_scope" / "transitions.jsonl")
    nodes = scope_ssot.fold(records)
    if not _active(nodes, "project"):
        return "B"
    if not _active(nodes, "direction"):
        return "C"
    if not _active(nodes, "task"):
        return "D"
    if not _package_for_direction(root, [n["id"] for n in _active(nodes, "direction")]):
        return "E"
    if not readiness_ok:
        return "F"
    return "G"


def build_admission_actions(state, context=None):
    """Map an admission state to the action(s) the front door should take next (no side effects)."""
    context = context or {}
    if state == "A":
        return [{"type": "handoff_dashboard_init",
                 "message": "Run /research-dashboard first — scaffolding is an init op, not an auto mutation."}]
    if state in _PROPOSAL_STATES:
        level, action_type = _PROPOSAL_STATES[state]
        if any(p.get("level") == level for p in context.get("pending", [])):
            return [{"type": "block_for_user_disposal", "level": level,
                     "pending": [p["id"] for p in context["pending"] if p.get("level") == level],
                     "message": f"A {level} proposal is already pending in Triage — waiting on your accept/reject."}]
        if level == "task":
            autonomy_level = _requested_autonomy(context)
            return [{"type": action_type, "level": level, "via": "triage",
                     "proposal": _proposal_with_autonomy(context.get("task_proposal"), autonomy_level),
                     "autonomy_level": autonomy_level,
                     "autonomy_choices": list(AUTONOMY_LEVELS),
                     "message": "Default autonomy_level is autonomous; choose supervised/checkpoints/async/autonomous before accepting if needed."}]
        return [{"type": action_type, "level": level, "via": "triage",
                 "proposal": context.get(f"{level}_proposal")}]
    if state == "E":
        return [{"type": "materialize_package", "from": "committed",
                 "sourceScopeNode": context.get("direction_id"),
                 "sourceScopeTxn": context.get("source_txn")}]
    if state == "F":
        return [{"type": "run_readiness", "dial": _requested_autonomy(context)}]
    if state == "G":
        return [{"type": "enter_auto_loop"}]
    raise ValueError(f"unknown admission state: {state!r}")


def validate_admission_action(action):
    """Reject any action that smuggles commit authority; return None if the action is legal."""
    reasons = []
    t = action.get("type")
    if t is not None and t not in ACTION_TYPES:
        reasons.append(f"unknown action type: {t!r}")
    if action.get("decision") in ("accept", "reject"):
        reasons.append("authority smuggle: a disposal decision (accept/reject) belongs to the user, not the loop")
    if action.get("type") in ("propose_task", "run_readiness"):
        level = action.get("autonomy_level") if action.get("type") == "propose_task" else action.get("dial")
        if level not in AUTONOMY_LEVELS:
            reasons.append(f"invalid autonomy level: {level!r}; expected one of {list(AUTONOMY_LEVELS)}")
        if action.get("type") == "propose_task":
            proposal_level = (action.get("proposal") or {}).get("yardstick", {}).get("autonomy_level")
            if proposal_level is not None and proposal_level != level:
                reasons.append("autonomy mismatch: proposal yardstick must match action autonomy_level")
    for m in action.get("mutations", []):
        if isinstance(m, dict) and m.get("op") == "scope-transition":
            reasons.append("authority smuggle: formation may only PROPOSE via Triage, never commit a scope-transition")
        else:
            reasons += [f"mutation: {e}" for e in driver.validate_mutation(m)]
    if t == "materialize_package" and (action.get("from") == "pending" or not action.get("sourceScopeTxn")):
        reasons.append("materialize_package must read a committed scope transition (sourceScopeTxn), not a pending proposal")
    if reasons:
        return {"rejected": True, "type": t, "reasons": reasons}
    return None


def run_front_door(root, *, pkg_id=None, scope_node=None, role_sequence=None, adapters=None,
                   readiness_ok=None, context=None):
    """Drive the front door: enter the production loop when ready (state G), else return formation actions."""
    state = detect_admission_state(root, readiness_ok=readiness_ok)
    if state == "G":
        return {"entered": True, "state": "G",
                "tick": driver.run_tick(pkg_id, scope_node, role_sequence, adapters, context=context)}
    return {"entered": False, "state": state,
            "actions": build_admission_actions(state, context)}
