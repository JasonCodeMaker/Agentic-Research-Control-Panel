"""Admission layer for /research-run.

A small deterministic state machine that runs before package execution. If the project is not ready to
run, it returns a handoff to the skill that owns the missing prerequisite. It never forms scope, commits
Scope SSOT nodes, or materializes package surfaces itself.
"""

import re
import sys
import json
from pathlib import Path

_PIPE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PIPE / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import scope_ssot  # noqa: E402
import driver  # noqa: E402

CONTROL_MODES = ("SUPERVISED", "CHECKPOINTED", "DEFERRED", "AUTONOMOUS")
DEFAULT_CONTROL_MODE = "AUTONOMOUS"

STATES = (
    "NO_DASHBOARD", "NO_PROJECT", "NO_DIRECTION", "NO_TASK",
    "NO_PACKAGE", "NOT_READY", "READY",
)

ACTION_TYPES = {
    "INIT_DASHBOARD", "HANDOFF_PROJECT", "HANDOFF_DIRECTION", "HANDOFF_TASK",
    "HANDOFF_PACKAGE", "RUN_READINESS", "ENTER_RUN_LOOP", "AWAIT_TRIAGE_DECISION",
}

# State that belongs to another skill -> (scope level, action type, handoff command).
_HANDOFF_STATES = {
    "NO_PROJECT":   ("project",   "HANDOFF_PROJECT",   "/research-onboard"),
    "NO_DIRECTION": ("direction", "HANDOFF_DIRECTION", "/research-brainstorm"),
    "NO_TASK":      ("task",      "HANDOFF_TASK",      "/research-scope"),
}


def _active(nodes, level):
    """Active scope nodes of a given level in the folded SSOT projection."""
    return [n for n in nodes.values() if n.get("level") == level and n.get("status") == "ACTIVE"]


def _scope_records_and_nodes(root):
    records = scope_ssot.read_log(Path(root) / "outputs" / "_scope" / "transitions.jsonl")
    return records, scope_ssot.fold(records)


def _package_summary(root, *, pkg_id=None, direction_id=None):
    inv = Path(root) / "research_html" / "data" / "research-packages.js"
    if not inv.exists():
        return None
    text = inv.read_text(encoding="utf-8")
    if pkg_id and f'id: "{pkg_id}"' not in text and f"id: '{pkg_id}'" not in text:
        return None
    if direction_id and f'sourceDirection: "{direction_id}"' not in text:
        return None
    return {"id": pkg_id, "sourceDirection": direction_id}


def _pending_triage(root):
    path = Path(root) / "outputs" / "_scope" / "triage.jsonl"
    if not path.exists():
        return []
    latest = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("id"):
            latest[rec["id"]] = rec
    return [rec for rec in latest.values() if rec.get("status") == "pending"]


def _triage_target_id(item):
    proposed = item.get("proposed_node") if isinstance(item.get("proposed_node"), dict) else {}
    return item.get("node_id") or proposed.get("id")


def _triage_parents(item):
    proposed = item.get("proposed_node") if isinstance(item.get("proposed_node"), dict) else {}
    parents = item.get("parents") or proposed.get("parents") or []
    return parents if isinstance(parents, list) else []


def _relevant_pending(pending, *, project, direction, tasks):
    project_id = project.get("id") if project else None
    direction_id = direction.get("id") if direction else None
    task_ids = {task.get("id") for task in tasks}
    chain = {item for item in [project_id, direction_id, *task_ids] if item}
    out = []
    for item in pending:
        target = _triage_target_id(item)
        parents = set(_triage_parents(item))
        level = item.get("level")
        if target in chain:
            out.append(item)
        elif level == "task" and direction_id and direction_id in parents:
            out.append(item)
        elif level == "direction" and target == direction_id:
            out.append(item)
        elif level == "project" and target == project_id:
            out.append(item)
    return sorted(out, key=lambda item: item.get("id", ""))


def build_scope_context(root, *, pkg_id=None):
    """Agent-facing Scope summary for the front door and dispatch context."""
    records, nodes = _scope_records_and_nodes(root)
    projects = _active(nodes, "project")
    directions = _active(nodes, "direction")
    direction = directions[0] if directions else None
    project = None
    if direction:
        for parent in direction.get("parents", []):
            candidate = nodes.get(parent)
            if candidate and candidate.get("level") == "project" and candidate.get("status") == "ACTIVE":
                project = candidate
                break
    if project is None and projects:
        project = projects[0]
    tasks = [
        n for n in _active(nodes, "task")
        if not direction or direction.get("id") in (n.get("parents") or [])
    ]
    tasks.sort(key=lambda n: n.get("id", ""))
    direction_id = direction.get("id") if direction else None
    package = _package_summary(root, pkg_id=pkg_id, direction_id=direction_id) if direction_id else None
    pending_scope = _relevant_pending(_pending_triage(root), project=project, direction=direction, tasks=tasks)
    return {
        "global_scope_version": scope_ssot.global_version(records),
        "project": _summarize_node(project),
        "direction": _summarize_node(direction),
        "tasks": [_summarize_node(t) for t in tasks],
        "package": package,
        "pending_scope": pending_scope,
    }


def _summarize_node(node):
    if not node:
        return None
    return {
        "id": node.get("id"),
        "level": node.get("level"),
        "version": node.get("version"),
        "status": node.get("status"),
        "spec": node.get("spec", {}),
    }


def _package_for_direction(root, direction_ids):
    """True iff the inventory carries a package materialized from one of these committed directions."""
    inv = Path(root) / "research_html" / "data" / "research-packages.js"
    if not inv.exists():
        return False
    text = inv.read_text(encoding="utf-8")
    return any(f'sourceDirection: "{did}"' in text for did in direction_ids)


def _requested_control_mode(context):
    """Control mode requested by context, defaulting to Autonomous as the front-door policy."""
    proposal = context.get("task_proposal") or {}
    spec = proposal.get("spec") or {}
    return context.get("control_mode") or context.get("dial") or spec.get("control_mode") or DEFAULT_CONTROL_MODE


def detect_admission_state(root, *, readiness_ok=None):
    """Inspect the project and return the admission state (see the front-door state machine)."""
    root = Path(root)
    if not (root / "research_html" / "index.html").exists():
        return "NO_DASHBOARD"  # dashboard scaffolding is an init op, not a run-loop mutation
    _, nodes = _scope_records_and_nodes(root)
    if not _active(nodes, "project"):
        return "NO_PROJECT"
    if not _active(nodes, "direction"):
        return "NO_DIRECTION"
    if not _active(nodes, "task"):
        return "NO_TASK"
    if not _package_for_direction(root, [n["id"] for n in _active(nodes, "direction")]):
        return "NO_PACKAGE"
    if not readiness_ok:
        return "NOT_READY"
    return "READY"


def build_admission_actions(state, context=None, *, root=None):
    """Map an admission state to the next run action(s).

    When `root` is given (the real entry path), actions are enriched with rendered `next_step` copy. At
    NO_DIRECTION, an on-disk drafted direction can be attached as `seed` to make the handoff smoother, but
    /research-run still does not propose or commit it.
    """
    actions = _raw_admission_actions(state, context)
    if root is None:
        return actions
    if state == "NO_DIRECTION":
        seed = detect_seed_direction(root)
        if seed.get("found"):
            for a in actions:
                if a.get("type") == "HANDOFF_DIRECTION":
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
    if state == "NO_DASHBOARD":
        return [{"type": "INIT_DASHBOARD",
                 "handoff": "/research-dashboard",
                 "message": "Run /research-dashboard first — scaffolding is an init op, not a run mutation."}]
    if state in _HANDOFF_STATES:
        level, action_type, handoff = _HANDOFF_STATES[state]
        if any(p.get("level") == level for p in context.get("pending", [])):
            return [{"type": "AWAIT_TRIAGE_DECISION", "level": level,
                     "pending": [p["id"] for p in context["pending"] if p.get("level") == level],
                     "message": f"A {level} proposal is already pending in Triage — waiting on your accept/reject."}]
        return [{"type": action_type, "level": level, "handoff": handoff,
                 "message": f"/research-run requires an existing package; use {handoff} for the missing {level}."}]
    if state == "NO_PACKAGE":
        return [{"type": "HANDOFF_PACKAGE", "handoff": "/research-package",
                 "sourceDirection": context.get("direction_id"),
                 "sourceChange": context.get("source_txn"),
                 "message": "Committed scope exists, but package materialization belongs to /research-package."}]
    if state == "NOT_READY":
        return [{"type": "RUN_READINESS", "control_mode": _requested_control_mode(context)}]
    if state == "READY":
        return [{"type": "ENTER_RUN_LOOP"}]
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
    """Find a direction already drafted on disk but not yet committed to the SSOT.

    /research-run uses this only to enrich a handoff message; the actual Direction proposal still belongs
    to /research-brainstorm or /research-scope.
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
    "INIT_DASHBOARD": (
        "No research dashboard exists here yet.",
        "Run /research-dashboard to scaffold research_html/, then re-run /research-run.",
        "This one's yours to run — /research-dashboard sets up the surfaces I write to.", True),
    "HANDOFF_PROJECT": (
        "No project objective is committed yet.",
        "Use /research-onboard for an existing repo, or /research-scope if you already know the objective.",
        "/research-run starts after the objective, direction, task, and package exist.", True),
    "HANDOFF_TASK": (
        "Direction is committed, but no executable Task is committed yet.",
        "Use /research-scope to propose and ratify validation milestones before running experiments.",
        "/research-run will continue after the Task and package exist.", True),
    "HANDOFF_PACKAGE": (
        "Direction and Task are committed, but no package exists yet.",
        "Use /research-package to materialize the package from committed Scope state.",
        "/research-run will continue once the package surfaces exist.", True),
    "ENTER_RUN_LOOP": (
        "Everything's ready — the package execution loop can start.",
        "I'll run the next eligible package experiment and keep routing until the package is complete.",
        "Reply `go` to start the loop, or name a specific experiment to run first.", False),
}


def render_next_step(action, *, root=None):
    """Translate an admission action into a plain-language next step: where we are, the one smoothest next
    action, and a continue/await affordance. The user-facing headline never carries a raw FSM label.
    """
    t = action.get("type")
    if t == "HANDOFF_DIRECTION":
        seed = action.get("seed")
        if seed is None and root is not None:
            s = detect_seed_direction(root)
            seed = s if s.get("found") else None
        if seed and seed.get("found"):
            n = len(seed.get("candidates") or [seed["pkg"]])
            headline = f"A direction is already drafted on disk ({seed['source']}) but not yet committed."
            next_action = (f"Use /research-scope to propose the direction from {seed['source']} "
                           f"({seed['pkg']}) to Triage for ratification.")
            offer = ("Run /research-scope for that proposal, or edit the drafted plan first."
                     if n == 1 else
                     f"Choose one of the {n} drafted plans, then run /research-scope.")
        else:
            headline = "Project is committed, but there's no active research direction yet."
            next_action = "Use /research-brainstorm to shape a Direction before running a package."
            offer = "/research-run will continue after the Direction, Task, and package are committed."
        awaits_user = True
    elif t == "RUN_READINESS":
        dial = action.get("dial", "AUTONOMOUS")
        headline = f"The package needs a readiness check before the loop can run unattended (dial: {dial})."
        next_action = f"I'll run the readiness preflight at the {dial} dial and close any gaps it reports."
        offer = "Reply `go` to run readiness + repair; or drop the dial to SUPERVISED for a lighter bar."
        awaits_user = False
    elif t == "AWAIT_TRIAGE_DECISION":
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
    if action.get("decision") in ("accept", "reject", "ACCEPTED", "REJECTED"):
        reasons.append("authority smuggle: a disposal decision belongs to the user, not the loop")
    if action.get("type") == "RUN_READINESS":
        level = action.get("control_mode")
        if level not in CONTROL_MODES:
            reasons.append(f"invalid control mode: {level!r}; expected one of {list(CONTROL_MODES)}")
    for m in action.get("mutations", []):
        if isinstance(m, dict) and m.get("op") == "scope-transition":
            reasons.append("authority smuggle: /research-run never commits a scope-transition")
        else:
            reasons += [f"mutation: {e}" for e in driver.validate_mutation(m)]
    if reasons:
        return {"rejected": True, "type": t, "reasons": reasons}
    return None


def run_front_door(root, *, pkg_id=None, scope_node=None, role_sequence=None, adapters=None,
                   readiness_ok=None, context=None):
    """Drive the front door: enter the package run loop when READY, else return prerequisite handoffs."""
    state = detect_admission_state(root, readiness_ok=readiness_ok)
    scope_context = build_scope_context(root, pkg_id=pkg_id)
    action_context = dict(context or {})
    action_context["pending"] = scope_context.get("pending_scope", [])
    if state in {"READY", "NOT_READY"} and scope_context.get("pending_scope"):
        actions = [{
            "type": "AWAIT_TRIAGE_DECISION",
            "level": "scope",
            "pending": [item["id"] for item in scope_context["pending_scope"]],
            "message": "A pending Scope proposal targets this package's active Scope chain.",
        }]
        for action in actions:
            action["next_step"] = render_next_step(action, root=root)
        return {"entered": False, "state": state, "scope_context": scope_context, "actions": actions}
    if state == "READY":
        tick_context = action_context
        tick_context["scope_context"] = scope_context
        tick_context["global_scope_version"] = scope_context["global_scope_version"]
        if scope_context.get("direction"):
            tick_context["sourceDirection"] = scope_context["direction"]["id"]
        if scope_context.get("tasks"):
            tick_context["sourceTask"] = scope_context["tasks"][0]["id"]
        return {"entered": True, "state": "READY",
                "scope_context": scope_context,
                "tick": driver.run_tick(pkg_id, scope_node, role_sequence, adapters, context=tick_context)}
    return {"entered": False, "state": state,
            "scope_context": scope_context,
            "actions": build_admission_actions(state, action_context, root=root)}
