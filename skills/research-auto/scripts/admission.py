"""Stage 0.5 front-door admission layer — the post-init front door for /research-auto.

A small deterministic state machine (A-G) that runs BEFORE the experiment loop. If the project is not
yet ready to run, it drives the Step-3 formation roles (R1-R3) up to the existing human gates, then
stops. The boundary is strict: formation capability lives in auto, but commit authority stays with the
user / Triage — this layer may PROPOSE through Triage, never ratify or materialize from pending state.
"""

import re
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


def build_admission_actions(state, context=None, *, root=None):
    """Map an admission state to the next front-door action(s). When `root` is given (the real entry
    path) the actions are ENRICHED deterministically: at State C an on-disk drafted direction is attached
    as `seed`, and every action carries its rendered plain-language `next_step`. The smart parts are baked
    into the FSM here — not left to the agent reading prose — so /research-auto's actual output already
    holds the seed + next step. With `root=None` the raw actions are returned unchanged (pure/back-compat).
    """
    actions = _raw_admission_actions(state, context)
    if root is None:
        return actions
    if state == "C":
        seed = detect_seed_direction(root)
        if seed.get("found"):
            for a in actions:
                if a.get("type") == "propose_direction":
                    a["seed"] = seed
    for a in actions:
        try:
            a["next_step"] = render_next_step(a, root=root)
        except ValueError:
            pass
    return actions


def _raw_admission_actions(state, context=None):
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


_SEED_PLACEHOLDERS = {"", "$hypothesis", "unmeasured", "tbd", "n/a", "hypothesis"}


def _hypothesis_filled(raw_html):
    """True iff a plan-invariants hypothesis cell carries real content, not the scaffold placeholder."""
    text = re.sub(r"<[^>]+>", " ", raw_html)          # strip tags
    text = re.sub(r"&[a-z]+;", " ", text)             # strip entities
    # The cell leads with the "Hypothesis" label span; drop it before judging substance.
    text = re.sub(r"^\s*hypothesis\b", "", text.strip(), flags=re.I).strip()
    return text.lower() not in _SEED_PLACEHOLDERS and len(text) >= 12


def detect_seed_direction(root):
    """Find a direction already drafted on disk but not yet committed to the SSOT — a package whose
    plan.html carries a populated objectiveContract (the painted plan-invariants hypothesis line, the
    real shape `create_from_scope`/`create_research_package` emit). At State C this lets the front door
    PROPOSE that plan as the direction instead of asking the user to re-supply what plan.html already
    holds (the session-b07d0f85 turn-3 failure). Newest package id (date-prefixed) wins; ties are
    surfaced in `candidates` so render_next_step can offer the alternates.
    """
    pkgs_dir = Path(root) / "research_html" / "packages"
    if not pkgs_dir.exists():
        return {"found": False, "source": None, "pkg": None, "candidates": []}
    candidates = []
    for plan in sorted(pkgs_dir.glob("*/plan.html"), reverse=True):  # date-prefixed id → newest first
        html = plan.read_text(encoding="utf-8", errors="ignore")
        m = re.search(r'data-invariant="hypothesis"[^>]*>(.*?)</li>', html, re.S)
        if m and _hypothesis_filled(m.group(1)):
            candidates.append(plan.parent.name)
    if not candidates:
        return {"found": False, "source": None, "pkg": None, "candidates": []}
    pkg = candidates[0]
    return {"found": True, "pkg": pkg, "source": f"packages/{pkg}/plan.html", "candidates": candidates}


# Per-action-type next-step copy: (headline, next_action template, offer, awaits_user).
_NEXT_STEP = {
    "handoff_dashboard_init": (
        "No research dashboard exists here yet.",
        "Run /research-dashboard to scaffold research_html/, then re-run /research-auto.",
        "This one's yours to run — /research-dashboard sets up the surfaces I write to.", True),
    "propose_project": (
        "No project objective is committed yet.",
        "I'll draft a Project objective from the workspace and send it to Triage for your ratify.",
        "Reply `go` and I'll draft + propose it; or tell me the objective and I'll use yours.", False),
    "propose_task": (
        "Direction is committed — the next move is the first milestone (a Task).",
        "I'll draft the Task milestone (default autonomy: autonomous) and send it to Triage for your ratify.",
        "Reply `go` and I'll draft + propose the Task; or set the autonomy level first.", False),
    "materialize_package": (
        "Direction and Task are committed, but no package exists yet.",
        "I'll materialize the package from the committed scope (create_from_scope).",
        "Reply `go` and I'll create the package surfaces.", False),
    "enter_auto_loop": (
        "Everything's ready — the experiment loop can start.",
        "I'll enter the production loop and run the next eligible experiment.",
        "Reply `go` to start the loop, or name a specific experiment to run first.", False),
}


def render_next_step(action, *, root=None):
    """Translate an admission action into a plain-language next step: where we are, the one smoothest next
    action, and a continue/await affordance. The user-facing headline never carries a raw FSM label.
    """
    t = action.get("type")
    if t == "propose_direction":
        seed = action.get("seed")
        if seed is None and root is not None:
            s = detect_seed_direction(root)
            seed = s if s.get("found") else None
        if seed and seed.get("found"):
            n = len(seed.get("candidates") or [seed["pkg"]])
            headline = f"A direction is already drafted on disk ({seed['source']}) but not yet committed."
            next_action = (f"I'll propose the direction from {seed['source']} ({seed['pkg']}) to Triage "
                           "for your ratify.")
            offer = ("Reply `go` to propose it as-is, or tell me what to change first."
                     if n == 1 else
                     f"Reply `go` to propose it, or name another of the {n} drafted plans to use instead.")
        else:
            headline = "Project is committed, but there's no active research direction yet."
            next_action = "I'll shape a direction (search + ideate) and propose it to Triage for your ratify."
            offer = "Reply `go` to let me draft one, or point me at a plan/brainstorm to seed it."
        awaits_user = False
    elif t == "run_readiness":
        dial = action.get("dial", "autonomous")
        headline = f"The package needs a readiness check before the loop can run unattended (dial: {dial})."
        next_action = f"I'll run the readiness preflight at the {dial} dial and close any gaps it reports."
        offer = "Reply `go` to run readiness + repair; or drop the dial to supervised for a lighter bar."
        awaits_user = False
    elif t == "block_for_user_disposal":
        level = action.get("level", "proposal")
        headline = f"A {level} proposal is waiting in Triage."
        next_action = (f"Accept or reject the pending {level} proposal — commit authority is yours, "
                       "not the loop's.")
        offer = "Reply `accept` or `reject` (with edits if you want changes)."
        awaits_user = True
    elif t in _NEXT_STEP:
        headline, next_action, offer, awaits_user = _NEXT_STEP[t]
    else:
        raise ValueError(f"cannot render next step for action type: {t!r}")
    return {"type": t, "headline": headline, "next_action": next_action, "offer": offer,
            "awaits_user": awaits_user, "details": action.get("message") or f"admission action: {t}"}


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
            "actions": build_admission_actions(state, context, root=root)}
