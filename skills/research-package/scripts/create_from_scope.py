#!/usr/bin/env python3
"""Materialize one active Direction and its accepted Scope Experiments."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

PIPELINE_ROOT = Path(__file__).resolve().parents[3]
for candidate in (
    PIPELINE_ROOT,
    PIPELINE_ROOT / "lib",
    Path(__file__).resolve().parent,
    PIPELINE_ROOT / "skills" / "research-brainstorm" / "scripts",
    PIPELINE_ROOT / "skills" / "research-op" / "scripts",
):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from lib.research_state import ResearchPaths, StateQuery  # noqa: E402
import brainstorm  # noqa: E402
import create_research_package  # noqa: E402
import management  # noqa: E402


def _slug_from_direction_id(direction_id: str) -> str:
    return create_research_package.slugify(direction_id.rsplit("/", 1)[-1])


def _metric_label(metric: Any) -> str:
    if isinstance(metric, dict):
        return str(metric.get("name") or json.dumps(metric, sort_keys=True))
    if isinstance(metric, list):
        return ", ".join(str(item) for item in metric)
    return str(metric)


def _baseline_label(baselines: Any) -> str:
    if isinstance(baselines, list):
        return "; ".join(str(item) for item in baselines) or "unmeasured"
    return str(baselines or "unmeasured")


def _pending_matches_direction(item: dict[str, Any], direction_id: str) -> bool:
    proposed = item.get("proposed_node")
    if isinstance(proposed, dict):
        if proposed.get("id") == direction_id:
            return True
        parents = proposed.get("parents")
        if isinstance(parents, list) and direction_id in parents:
            return True
    return item.get("node_id") == direction_id


def _scope_experiments(
    state: dict[str, Any],
    direction_id: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    records = (
        state["aggregates"]["experiment"]
        if "aggregates" in state
        else state.get("experiments", {})
    )
    for aggregate_id, record in records.items():
        if not isinstance(record, dict):
            continue
        if record.get("package_id") not in (None, ""):
            continue
        if record.get("direction_id") != direction_id:
            continue
        if record.get("scope_status") != "ACTIVE":
            continue
        rows.append(
            {
                "aggregate_id": aggregate_id,
                "record": copy.deepcopy(record),
            }
        )
    return sorted(
        rows,
        key=lambda item: str(
            item["record"].get("id") or item["aggregate_id"]
        ),
    )


def _experiment_rows(
    package_id: str,
    scope_experiments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Bind accepted Experiments without copying their canonical specs."""
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(scope_experiments):
        accepted = item["record"]
        accepted_id = str(accepted.get("id") or item["aggregate_id"])
        spec = accepted.get("spec") if isinstance(accepted.get("spec"), dict) else {}
        missing = [
            field
            for field in ("purpose", "config_ref", "gate", "control_mode")
            if not isinstance(spec.get(field), str) or not spec[field].strip()
        ]
        if missing:
            raise SystemExit(
                f"Accepted Scope Experiment {accepted_id} is missing spec fields: "
                + ", ".join(missing)
            )
        local_id = f"P{index}"
        row: dict[str, Any] = {
            "scope_experiment_id": item["aggregate_id"],
            "local_id": local_id,
            "output": (
                f".research/experiments/{package_id}/{local_id}/"
                "<run-id>/result.json"
            ),
            "status": "READY",
            "measures": True,
            "requiresCode": False,
            "complex": False,
        }
        # Scope did not state a dependency, so this projection does not add one.
        rows.append(row)
    return rows


def _coerce_paths(
    paths: ResearchPaths | None = None,
    *,
    workspace: str | Path = ".",
    research_root: str | Path | None = None,
) -> ResearchPaths:
    if paths is not None:
        return paths
    return ResearchPaths.resolve(
        workspace=workspace,
        research_root=research_root,
    )


def materialization_status(
    *,
    direction_id: str,
    package_id: str,
    paths: ResearchPaths | None = None,
    workspace: str | Path = ".",
    research_root: str | Path | None = None,
) -> dict[str, Any]:
    """Explain readiness from committed management state only."""
    resolved = _coerce_paths(
        paths,
        workspace=workspace,
        research_root=research_root,
    )
    view = StateQuery(resolved).materialization(
        direction_id,
        package_id,
    )["data"]
    direction = view["direction"]
    package_exists = bool(view["package_exists"])
    package = {
        "state": "exists" if package_exists else "absent",
        "id": package_id,
    }
    pending = [
        copy.deepcopy(item)
        for item in view["pending"]
        if isinstance(item, dict)
        and item.get("disposition") == "PENDING"
        and _pending_matches_direction(item, direction_id)
    ]
    if not isinstance(direction, dict):
        pending_direction = [
            item
            for item in pending
            if item.get("level") == "direction"
            or (item.get("proposed_node") or {}).get("level") == "direction"
        ]
        if pending_direction:
            return {
                "materializable": False,
                "direction": {
                    "state": "pending",
                    "id": direction_id,
                    "pending": [item["id"] for item in pending_direction],
                },
                "experiments": {"state": "blocked", "count": 0},
                "package": package,
                "nextSkill": "/research-scope",
                "nextAction": (
                    "Accept, revise, or reject the pending Direction before "
                    "creating a package."
                ),
            }
        return {
            "materializable": False,
            "direction": {"state": "missing", "id": direction_id},
            "experiments": {"state": "blocked", "count": 0},
            "package": package,
            "nextSkill": "/research-brainstorm",
            "nextAction": "Shape and ratify a Direction before creating a package.",
        }
    if direction.get("level") not in (None, "direction"):
        return {
            "materializable": False,
            "direction": {
                "state": "wrong_level",
                "id": direction_id,
                "level": direction.get("level"),
            },
            "experiments": {"state": "blocked", "count": 0},
            "package": package,
            "nextSkill": "/research-scope",
            "nextAction": "Use a committed Direction id.",
        }
    if direction.get("status") != "ACTIVE":
        return {
            "materializable": False,
            "direction": {
                "state": "inactive",
                "id": direction_id,
                "status": direction.get("status"),
            },
            "experiments": {"state": "blocked", "count": 0},
            "package": package,
            "nextSkill": "/research-scope",
            "nextAction": "Reopen or revise the Direction before materialization.",
        }
    experiments = _scope_experiments(view, direction_id)
    if not experiments:
        pending_experiments = [
            item
            for item in pending
            if item.get("level") == "experiment"
            or (item.get("proposed_node") or {}).get("level") == "experiment"
        ]
        experiment_state = "pending" if pending_experiments else "missing"
        result: dict[str, Any] = {
            "materializable": False,
            "direction": {
                "state": "committed",
                "id": direction_id,
                "version": direction.get("version"),
            },
            "experiments": {"state": experiment_state, "count": 0},
            "package": package,
            "nextSkill": "/research-scope",
            "nextAction": (
                "Accept, revise, or reject pending Scope Experiments before "
                "materialization."
                if pending_experiments
                else "Propose and ratify Scope Experiments before materialization."
            ),
        }
        if pending_experiments:
            result["experiments"]["pending"] = [
                item["id"] for item in pending_experiments
            ]
        return result
    if package_exists:
        return {
            "materializable": False,
            "direction": {
                "state": "committed",
                "id": direction_id,
                "version": direction.get("version"),
            },
            "experiments": {
                "state": "committed",
                "count": len(experiments),
                "ids": [item["record"]["id"] for item in experiments],
            },
            "package": package,
            "nextSkill": "/research-run",
            "nextAction": f"/research-run {package_id}",
        }
    return {
        "materializable": True,
        "direction": {
            "state": "committed",
            "id": direction_id,
            "version": direction.get("version"),
        },
        "experiments": {
            "state": "committed",
            "count": len(experiments),
            "ids": [item["record"]["id"] for item in experiments],
        },
        "package": package,
        "nextSkill": "/research-package",
        "nextAction": f"/research-package from-scope {direction_id}",
    }


def _print_check(status: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(status, ensure_ascii=False, sort_keys=True))
        return
    print(f"materializable: {str(status['materializable']).lower()}")
    print(
        "direction: "
        f"{status['direction'].get('state')} "
        f"{status['direction'].get('id')}"
    )
    experiments = status["experiments"]
    print(
        "experiments: "
        f"{experiments.get('state')} count={experiments.get('count')}"
    )
    print(f"package: {status['package'].get('state')} {status['package'].get('id')}")
    print(f"next: {status['nextAction']}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("--direction-id", required=True)
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--research-root")
    parser.add_argument("--id", default="")
    parser.add_argument("--name", default="")
    parser.add_argument(
        "--category",
        default="in-progress",
        choices=sorted(create_research_package.CATEGORIES),
    )
    parser.add_argument("--tag", default="scope")
    parser.add_argument(
        "--tag-meaning",
        default="Materialized from an accepted Scope Direction",
        dest="tag_meaning",
    )
    parser.add_argument("--problem", default="")
    parser.add_argument("--objective", default="")
    parser.add_argument(
        "--motivation",
        default="Accepted Scope Direction materialized as a package",
    )
    parser.add_argument("--budget", default="unmeasured")
    parser.add_argument(
        "--no-change-boundary",
        default="Scope spec fields remain authoritative",
        dest="no_change_boundary",
    )
    parser.add_argument("--source-path", default="", dest="source_path")
    parser.add_argument("--artifact-root", default="", dest="artifact_root")
    parser.add_argument(
        "--next-action",
        default="Plan the accepted Scope Experiments",
        dest="next_action",
    )
    parser.add_argument(
        "--scope",
        default="index,plan,implementation,results,tracker,docs,_agent",
    )
    parser.add_argument(
        "--status",
        default="CONTEXT_LOADED",
        choices=("CONTEXT_LOADED",),
        help="compatibility flag; new Packages always start at CONTEXT_LOADED",
    )
    parser.add_argument(
        "--contribution-spine-flag",
        default="",
        dest="contribution_spine_flag",
    )
    parser.add_argument(
        "--source-brainstorms",
        default="[]",
        dest="source_brainstorms",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = ResearchPaths.resolve(
        workspace=args.workspace,
        research_root=args.research_root,
    )
    direction_slug = _slug_from_direction_id(args.direction_id)
    package_id = args.id or create_research_package.default_id(direction_slug)
    status = materialization_status(
        paths=paths,
        direction_id=args.direction_id,
        package_id=package_id,
    )
    if args.check:
        _print_check(status, as_json=args.json_output)
        return 0
    if not status["materializable"]:
        raise SystemExit(status["nextAction"])

    materialization = StateQuery(paths).materialization(
        args.direction_id,
        package_id,
    )["data"]
    direction = copy.deepcopy(materialization["direction"])
    spec = direction.get("spec") if isinstance(direction.get("spec"), dict) else {}
    scope_experiments = _scope_experiments(
        materialization,
        args.direction_id,
    )
    hypothesis = str(spec.get("hypothesis") or "")
    metric = _metric_label(spec.get("metric"))
    success_gate = str(spec.get("success_gate") or "")
    if not hypothesis or not metric or not success_gate:
        raise SystemExit(
            "Active Direction is missing hypothesis, metric, or success_gate"
        )
    source_ids = json.loads(args.source_brainstorms)
    if not isinstance(source_ids, list) or not all(
        isinstance(item, str) for item in source_ids
    ):
        raise SystemExit("--source-brainstorms must be a JSON list of ids")
    active_ideas = {row["id"]: row for row in brainstorm.read_brainstorms(paths)}
    missing_ideas = [idea_id for idea_id in source_ids if idea_id not in active_ideas]
    if missing_ideas:
        raise SystemExit(
            "Unknown or archived source brainstorms: " + ", ".join(missing_ideas)
        )
    source_records = [copy.deepcopy(active_ideas[idea_id]) for idea_id in source_ids]
    name = args.name or direction_slug.replace("-", " ").title()
    pages = create_research_package.parse_scope(args.scope, args.category)
    record: dict[str, Any] = {
        "id": package_id,
        "slug": package_id,
        "name": name,
        "lifecycle": "ACTIVE",
        "phase": args.status,
        "blocker": None,
        "tag": args.tag,
        "tagMeaning": args.tag_meaning,
        "problem": args.problem or hypothesis,
        "objective": args.objective or hypothesis,
        "motivation": args.motivation,
        "hypothesis": hypothesis,
        "primaryMetric": metric,
        "baseline": _baseline_label(spec.get("baselines")),
        "budget": args.budget,
        "noChangeBoundary": args.no_change_boundary,
        "sourcePath": args.source_path,
        "artifactRoot": args.artifact_root
        or f".research/experiments/{package_id}/",
        "runtime": args.artifact_root
        or f".research/experiments/{package_id}/",
        "nextAction": args.next_action,
        "contributionSpineFlag": args.contribution_spine_flag,
        "direction": hypothesis,
        "activeGate": success_gate,
        "primaryMetricVsGate": f"{metric} vs {success_gate}",
        "lastAction": f"materialized from {args.direction_id}",
        "openRuns": "none",
        "lastUpdated": create_research_package.dt.date.today().isoformat(),
        "pages": pages,
        "direction_id": args.direction_id,
        "sourceDirection": args.direction_id,
        "sourceVersion": direction.get("version"),
        "sourceChange": materialization["latest_direction_event_id"],
        "sourceExperiments": [
            {
                "id": item["record"]["id"],
                "version": item["record"].get("scope_version"),
                "source": item["record"].get("scope_source"),
            }
            for item in scope_experiments
        ],
        "sourceBrainstorms": source_records,
        "methodsTried": [],
        "resultGateRows": [],
        "resultBlocks": [],
        "analysisInsights": [],
        "docsGroups": [],
    }
    package_event, experiment_events = management.commit_package_create(
        paths,
        record,
        _experiment_rows(package_id, scope_experiments),
        entry_skill="research-package",
    )
    consumed = brainstorm.consume_brainstorms(
        paths,
        source_ids,
        package_id=package_id,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "package_id": package_id,
                "event_id": package_event["event_id"],
                "experiments": [
                    event["aggregate_id"] for event in experiment_events
                ],
                "source_brainstorms_archived": [
                    row["id"] for row in consumed
                ],
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
