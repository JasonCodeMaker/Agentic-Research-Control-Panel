"""State-backed admission for ``/research-run``.

Admission reads management state through ``StateQuery``.  The generated
interface is never an execution prerequisite and is not inspected here.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

PIPELINE_ROOT = Path(__file__).resolve().parents[3]
if str(PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(PIPELINE_ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.research_state import ResearchPaths, StateQuery, UpgradeRequired  # noqa: E402

import driver  # noqa: E402


CONTROL_MODES = ("SUPERVISED", "CHECKPOINTED", "DEFERRED", "AUTONOMOUS")
DEFAULT_CONTROL_MODE = "AUTONOMOUS"
STATES = (
    "NO_PROJECT",
    "NO_DIRECTION",
    "NO_EXPERIMENT",
    "NO_PACKAGE",
    "NOT_READY",
    "READY",
)
ACTION_TYPES = {
    "HANDOFF_PROJECT",
    "HANDOFF_DIRECTION",
    "HANDOFF_EXPERIMENT",
    "HANDOFF_PACKAGE",
    "RUN_READINESS",
    "ENTER_RUN_LOOP",
    "AWAIT_TRIAGE_DECISION",
}
_HANDOFF_STATES = {
    "NO_PROJECT": ("project", "HANDOFF_PROJECT", "/research-onboard"),
    "NO_DIRECTION": ("direction", "HANDOFF_DIRECTION", "/research-brainstorm"),
    "NO_EXPERIMENT": ("experiment", "HANDOFF_EXPERIMENT", "/research-scope"),
}


def _paths(
    root: str | Path | ResearchPaths,
    *,
    research_root: str | Path | None = None,
) -> ResearchPaths:
    if isinstance(root, ResearchPaths):
        if research_root is not None:
            raise ValueError("research_root cannot accompany ResearchPaths")
        return root
    return ResearchPaths.resolve(workspace=root, research_root=research_root)


def _empty_context() -> dict[str, Any]:
    return {
        "source_seq": 0,
        "source_hash": "",
        "project": None,
        "direction": None,
        "experiments": [],
        "package": None,
        "pending_proposals": [],
    }


def _active(records: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        record
        for _, record in sorted(records.items())
        if isinstance(record, dict) and record.get("status", "ACTIVE") == "ACTIVE"
    ]


def _package_direction(package: dict[str, Any] | None) -> str | None:
    if not package:
        return None
    value = package.get("direction_id") or package.get("sourceDirection")
    return str(value) if value else None


def _direction_project(direction: dict[str, Any] | None) -> str | None:
    if not direction:
        return None
    value = direction.get("project_id")
    if value:
        return str(value)
    parents = direction.get("parents") or []
    return str(parents[0]) if parents else None


def _experiment_direction(experiment: dict[str, Any]) -> str | None:
    value = experiment.get("direction_id")
    return str(value) if value else None


def _target_id(proposal: dict[str, Any]) -> str | None:
    proposed = proposal.get("proposed_node")
    if not isinstance(proposed, dict):
        proposed = {}
    value = (
        proposal.get("aggregate_id")
        or proposal.get("node_id")
        or proposed.get("id")
    )
    return str(value) if value else None


def _relevant_pending(
    proposals: dict[str, dict[str, Any]],
    *,
    project: dict[str, Any] | None,
    direction: dict[str, Any] | None,
    experiments: list[dict[str, Any]],
    package: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    subjects = {
        str(value)
        for value in (
            project.get("id") if project else None,
            direction.get("id") if direction else None,
            package.get("id") if package else None,
            *(item.get("id") for item in experiments),
        )
        if value
    }
    selected = []
    for _, proposal in sorted(proposals.items()):
        if not isinstance(proposal, dict) or proposal.get("disposition") != "PENDING":
            continue
        proposed = proposal.get("proposed_node")
        parents = set(proposal.get("parents") or [])
        if isinstance(proposed, dict):
            parents.update(proposed.get("parents") or [])
        if (
            proposal.get("package_id") in subjects
            or _target_id(proposal) in subjects
            or parents.intersection(subjects)
        ):
            selected.append(proposal)
    return selected


def build_research_context(
    root: str | Path | ResearchPaths,
    *,
    pkg_id: str | None = None,
    research_root: str | Path | None = None,
) -> dict[str, Any]:
    """Return one hash-stamped admission snapshot without reading interface files."""
    paths = _paths(root, research_root=research_root)
    if paths.load_version() is None:
        markers = paths.legacy_markers()
        if markers:
            raise UpgradeRequired(
                "upgrade-required: /research-run does not support legacy state; "
                + ", ".join(str(path) for path in markers)
            )
        return _empty_context()

    query = StateQuery(paths)
    snapshots = {
        aggregate: query.show(aggregate)
        for aggregate in ("project", "direction", "experiment", "package", "proposal")
    }
    stamps = {
        (snapshot["source_seq"], snapshot["source_hash"])
        for snapshot in snapshots.values()
    }
    if len(stamps) != 1:
        raise RuntimeError("research state changed while admission was being read")
    source_seq, source_hash = next(iter(stamps))

    packages = snapshots["package"]["data"]
    if pkg_id is not None and pkg_id not in packages:
        raise KeyError(f"unknown package: {pkg_id}")
    package = packages.get(pkg_id) if pkg_id else None
    active_directions = _active(snapshots["direction"]["data"])
    direction_id = _package_direction(package)
    direction = (
        snapshots["direction"]["data"].get(direction_id)
        if direction_id
        else (active_directions[0] if active_directions else None)
    )
    if pkg_id is None and package is None and direction:
        direction_id = str(direction.get("id"))
        package = next(
            (
                item
                for _, item in sorted(packages.items())
                if isinstance(item, dict)
                and _package_direction(item) == direction_id
                and item.get("lifecycle", "ACTIVE") == "ACTIVE"
            ),
            None,
        )
    project_id = _direction_project(direction)
    projects = snapshots["project"]["data"]
    active_projects = _active(projects)
    project = (
        projects.get(project_id)
        if project_id
        else (active_projects[0] if active_projects else None)
    )

    experiments = [
        {**item, "aggregate_id": aggregate_id}
        for aggregate_id, item in sorted(
            snapshots["experiment"]["data"].items()
        )
        if isinstance(item, dict)
        and (
            (
                item.get("package_id") == package.get("id")
                if package
                else direction
                and _experiment_direction(item) == str(direction.get("id"))
            )
        )
    ]
    pending = _relevant_pending(
        snapshots["proposal"]["data"],
        project=project,
        direction=direction,
        experiments=experiments,
        package=package,
    )
    return {
        "source_seq": source_seq,
        "source_hash": source_hash,
        "project": project,
        "direction": direction,
        "experiments": experiments,
        "package": package,
        "pending_proposals": pending,
    }


def _admission_state(
    context: dict[str, Any],
    *,
    readiness_ok: bool | None,
) -> str:
    """Classify one already-stamped context without performing a second read."""
    if context["project"] is None:
        return "NO_PROJECT"
    if context["direction"] is None:
        return "NO_DIRECTION"
    if not context["experiments"]:
        return "NO_EXPERIMENT"
    if context["package"] is None:
        return "NO_PACKAGE"
    return "READY" if readiness_ok else "NOT_READY"


def detect_admission_state(
    root: str | Path | ResearchPaths,
    *,
    readiness_ok: bool | None = None,
    pkg_id: str | None = None,
    research_root: str | Path | None = None,
) -> str:
    context = build_research_context(
        root,
        pkg_id=pkg_id,
        research_root=research_root,
    )
    return _admission_state(context, readiness_ok=readiness_ok)


def _requested_control_mode(context: dict[str, Any]) -> str:
    experiment = context.get("experiment") or {}
    spec = experiment.get("spec") or {}
    return (
        context.get("control_mode")
        or context.get("dial")
        or spec.get("control_mode")
        or DEFAULT_CONTROL_MODE
    )


def _raw_admission_actions(
    state: str,
    context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    context = context or {}
    if state in _HANDOFF_STATES:
        level, action_type, handoff = _HANDOFF_STATES[state]
        pending = [
            proposal
            for proposal in context.get("pending", [])
            if proposal.get("level") == level
            or (
                isinstance(proposal.get("proposed_node"), dict)
                and proposal["proposed_node"].get("level") == level
            )
        ]
        if pending:
            return [
                {
                    "type": "AWAIT_TRIAGE_DECISION",
                    "level": level,
                    "pending": [item["id"] for item in pending],
                    "message": f"A {level} proposal is waiting for disposition.",
                }
            ]
        return [
            {
                "type": action_type,
                "level": level,
                "handoff": handoff,
                "message": (
                    f"/research-run requires a materialized package with an "
                    f"executable Experiment. Use {handoff} for the missing {level}."
                ),
            }
        ]
    if state == "NO_PACKAGE":
        return [
            {
                "type": "HANDOFF_PACKAGE",
                "handoff": "/research-package",
                "sourceDirection": context.get("direction_id"),
                "message": "The Direction and Experiment exist, but no package is materialized.",
            }
        ]
    if state == "NOT_READY":
        return [
            {
                "type": "RUN_READINESS",
                "control_mode": _requested_control_mode(context),
            }
        ]
    if state == "READY":
        return [{"type": "ENTER_RUN_LOOP"}]
    raise ValueError(f"unknown admission state: {state!r}")


def detect_seed_direction(
    root: str | Path | ResearchPaths,
    *,
    research_root: str | Path | None = None,
) -> dict[str, Any]:
    """Return state-backed brainstorm candidates for a Direction handoff."""
    paths = _paths(root, research_root=research_root)
    if paths.load_version() is None:
        return {"found": False, "source": None, "idea": None, "candidates": []}
    snapshot = StateQuery(paths).show("brainstorm")
    candidates = [
        str(item.get("id") or key)
        for key, item in sorted(snapshot["data"].items(), reverse=True)
        if isinstance(item, dict) and item.get("status") != "ARCHIVED"
    ]
    if not candidates:
        return {"found": False, "source": None, "idea": None, "candidates": []}
    idea = candidates[0]
    return {
        "found": True,
        "idea": idea,
        "source": f"brainstorm/{idea}",
        "candidates": candidates,
        "source_seq": snapshot["source_seq"],
        "source_hash": snapshot["source_hash"],
    }


def build_admission_actions(
    state: str,
    context: dict[str, Any] | None = None,
    *,
    root: str | Path | ResearchPaths | None = None,
) -> list[dict[str, Any]]:
    actions = _raw_admission_actions(state, context)
    if root is None:
        return actions
    if state == "NO_DIRECTION":
        seed = detect_seed_direction(root)
        if seed["found"]:
            actions[0]["seed"] = seed
    for action in actions:
        action["next_step"] = render_next_step(action)
    return actions


def render_next_step(
    action: dict[str, Any],
    *,
    root: str | Path | ResearchPaths | None = None,
) -> dict[str, Any]:
    action_type = action.get("type")
    if action_type == "HANDOFF_PROJECT":
        headline = "No Project objective is committed."
        next_action = "/research-onboard"
        offer = "Commit the Project objective before starting package execution."
        awaits_user = True
    elif action_type == "HANDOFF_DIRECTION":
        seed = action.get("seed")
        if seed is None and root is not None:
            candidate = detect_seed_direction(root)
            seed = candidate if candidate["found"] else None
        if seed:
            headline = f"Brainstorm {seed['idea']} exists but is not a committed Direction."
            next_action = f"/research-scope propose-direction {seed['idea']}"
        else:
            headline = "The Project has no active Direction."
            next_action = "/research-brainstorm"
        offer = "Commit a Direction, then return to /research-run."
        awaits_user = True
    elif action_type == "HANDOFF_EXPERIMENT":
        headline = "The Direction has no executable Experiment."
        next_action = "/research-scope"
        offer = "Define and ratify an Experiment spec before execution."
        awaits_user = True
    elif action_type == "HANDOFF_PACKAGE":
        direction_id = action.get("sourceDirection")
        headline = "The Direction and Experiment exist, but no package is materialized."
        next_action = (
            f"/research-package from-scope {direction_id}"
            if direction_id
            else "/research-package from-scope <direction-id>"
        )
        offer = "Materialize the package, then return to /research-run."
        awaits_user = True
    elif action_type == "RUN_READINESS":
        mode = action.get("control_mode", DEFAULT_CONTROL_MODE)
        headline = f"The package needs readiness validation at {mode} control."
        next_action = "Run the structured readiness checks for the selected Experiment."
        offer = "Resolve each reported blocker before launch."
        awaits_user = False
    elif action_type == "AWAIT_TRIAGE_DECISION":
        level = action.get("level", "proposal")
        headline = f"A pending {level} proposal affects this run."
        next_action = "Accept or reject the proposal through Triage."
        offer = "Execution resumes after the proposal has a disposition."
        awaits_user = True
    elif action_type == "ENTER_RUN_LOOP":
        headline = "The package is admitted for execution."
        next_action = "Run or monitor the next eligible Experiment."
        offer = "The loop can continue without an interface projection."
        awaits_user = False
    else:
        raise ValueError(f"cannot render next step for action type: {action_type!r}")
    return {
        "type": action_type,
        "headline": headline,
        "next_action": next_action,
        "offer": offer,
        "awaits_user": awaits_user,
        "details": action.get("message") or f"admission action: {action_type}",
    }


def validate_admission_action(action: dict[str, Any]) -> dict[str, Any] | None:
    reasons = []
    action_type = action.get("type")
    if action_type is not None and action_type not in ACTION_TYPES:
        reasons.append(f"unknown action type: {action_type!r}")
    if action.get("decision") in {"accept", "reject", "ACCEPTED", "REJECTED"}:
        reasons.append("proposal disposition belongs to the user")
    if action_type == "RUN_READINESS":
        mode = action.get("control_mode")
        if mode not in CONTROL_MODES:
            reasons.append(
                f"invalid control mode: {mode!r}; expected one of {list(CONTROL_MODES)}"
            )
    for mutation in action.get("mutations", []):
        if isinstance(mutation, dict) and mutation.get("op") == "scope-transition":
            reasons.append("scope transitions cannot be committed by /research-run")
        else:
            reasons.extend(
                f"mutation: {error}"
                for error in driver.validate_mutation(mutation)
            )
    if reasons:
        return {"rejected": True, "type": action_type, "reasons": reasons}
    return None


def run_front_door(
    root: str | Path | ResearchPaths,
    *,
    pkg_id: str | None = None,
    experiment: dict[str, Any] | None = None,
    role_sequence: list[str] | None = None,
    adapters: dict[str, Any] | None = None,
    readiness_ok: bool | None = None,
    context: dict[str, Any] | None = None,
    research_root: str | Path | None = None,
) -> dict[str, Any]:
    """Enter the run loop or return the single owning handoff."""
    paths = _paths(root, research_root=research_root)
    research_context = build_research_context(paths, pkg_id=pkg_id)
    state = _admission_state(research_context, readiness_ok=readiness_ok)
    action_context = dict(context or {})
    action_context["pending"] = research_context["pending_proposals"]
    if research_context["direction"]:
        action_context.setdefault(
            "direction_id",
            research_context["direction"]["id"],
        )
    if research_context["experiments"]:
        action_context.setdefault(
            "experiment",
            research_context["experiments"][0],
        )
    if state in {"READY", "NOT_READY"} and research_context["pending_proposals"]:
        action = {
            "type": "AWAIT_TRIAGE_DECISION",
            "level": "research",
            "pending": [
                item["id"] for item in research_context["pending_proposals"]
            ],
            "message": "A pending proposal affects the active research chain.",
        }
        action["next_step"] = render_next_step(action)
        return {
            "entered": False,
            "state": state,
            "research_context": research_context,
            "actions": [action],
        }
    if state == "READY":
        package_id = str(research_context["package"]["id"])
        selected = experiment
        if selected is None:
            selected = next(
                (
                    item
                    for item in research_context["experiments"]
                    if item.get("package_id") == package_id
                ),
                research_context["experiments"][0],
            )
        aggregate_id, canonical_experiment = driver.resolve_bound_experiment(
            {
                str(item["aggregate_id"]): item
                for item in research_context["experiments"]
            },
            package_id,
            selected,
        )
        selected = {
            **canonical_experiment,
            "aggregate_id": aggregate_id,
        }
        tick_context = {
            **action_context,
            "research_context": research_context,
            "source_seq": research_context["source_seq"],
            "source_hash": research_context["source_hash"],
            "sourceDirection": research_context["direction"]["id"],
            "sourceExperiment": aggregate_id,
        }
        return {
            "entered": True,
            "state": "READY",
            "research_context": research_context,
            "tick": driver.run_tick(
                package_id,
                selected,
                role_sequence or [],
                adapters or {},
                context=tick_context,
                paths=paths,
            ),
        }
    actions = build_admission_actions(state, action_context, root=paths)
    return {
        "entered": False,
        "state": state,
        "research_context": research_context,
        "actions": actions,
    }
