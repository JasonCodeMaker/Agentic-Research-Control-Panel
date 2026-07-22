#!/usr/bin/env python3
"""Activate one reviewed Draft Package from ratified Scope.

The no-draft materialization path remains for older workspaces.
"""

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
    PIPELINE_ROOT / "skills" / "research-op" / "scripts",
):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from lib.research_state import ResearchPaths, StateQuery  # noqa: E402
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


SOURCE_BRAINSTORM_FIELDS = (
    "title",
    "abstract",
    "idea",
    "idea_snapshot",
    "page_language",
    "created_at",
    "updated_at",
    "revision",
)


def _resolve_source_brainstorms(
    paths: ResearchPaths,
    materialization: dict[str, Any],
    explicit_json: str | None,
) -> list[dict[str, Any]]:
    declared = materialization.get("source_brainstorm_ids") or []
    if not isinstance(declared, list) or not all(
        isinstance(item, str) and item for item in declared
    ):
        raise SystemExit("Direction source Brainstorm provenance is malformed")
    explicit: list[str] | None = None
    if explicit_json is not None:
        explicit = json.loads(explicit_json)
        if not isinstance(explicit, list) or not all(
            isinstance(item, str) and item for item in explicit
        ):
            raise SystemExit("--source-brainstorms must be a JSON list of ids")
        explicit = list(dict.fromkeys(explicit))
    if declared and explicit is not None and explicit != declared:
        raise SystemExit(
            "--source-brainstorms must exactly match the accepted Direction "
            "proposal provenance"
        )
    source_ids = declared or explicit or []
    view = StateQuery(paths).brainstorms(include_archived=False)["data"]
    records = {
        str(row["id"]): row
        for row in view["items"]
        if isinstance(row, dict) and row.get("id")
    }
    missing = [idea_id for idea_id in source_ids if idea_id not in records]
    if missing:
        raise SystemExit(
            "Unknown, archived, or already converted source Brainstorms: "
            + ", ".join(missing)
        )
    return [
        {
            "aggregate_id": idea_id,
            "aggregate_version": int(view["versions"].get(idea_id, 0)),
            "record": copy.deepcopy(records[idea_id]),
        }
        for idea_id in source_ids
    ]


def _build_brainstorm_transfer(
    package_id: str,
    source_rows: list[dict[str, Any]],
    experiment_ids: list[str],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, dict[str, Any]],
    list[dict[str, Any]],
]:
    source_records: list[dict[str, Any]] = []
    docs: list[dict[str, Any]] = []
    interface_notes: dict[str, dict[str, Any]] = {}
    consumptions: list[dict[str, Any]] = []
    for row in source_rows:
        idea_id = str(row["aggregate_id"])
        record = row["record"]
        note = record.get("document_note")
        if not isinstance(note, dict):
            raise SystemExit(
                f"Source Brainstorm {idea_id} has no governed document_note"
            )
        slug = create_research_package.slugify(idea_id)
        document_path = f"docs/{slug}.html"
        descriptor = {
            "id": idea_id,
            "sourceKind": "brainstorm-proposal",
            "ownership": "package",
            "sourceVersion": int(row["aggregate_version"]),
            "documentPath": document_path,
            "document_note": copy.deepcopy(note),
            "convertedInto": package_id,
        }
        for field in SOURCE_BRAINSTORM_FIELDS:
            if record.get(field) is not None:
                descriptor[field] = copy.deepcopy(record[field])
        source_records.append(descriptor)
        interface_notes[document_path] = copy.deepcopy(note)
        updated = str(
            record.get("updated_at") or record.get("created_at") or ""
        )[:10]
        docs.append(
            {
                "id": slug,
                "title": record.get("title") or idea_id,
                "tldr": record.get("abstract") or record.get("idea") or "unmeasured",
                "topics": ["source-proposal", "brainstorm"],
                "relatedPages": ["plan.html"],
                "citedByExperiments": list(experiment_ids),
                "preview": record.get("idea") or "",
                "href": f"{slug}.html",
                "lastUpdated": updated,
            }
        )
        consumptions.append(
            {
                "aggregate_id": idea_id,
                "expected_version": int(row["aggregate_version"]),
                "document_path": document_path,
                "document_note": copy.deepcopy(note),
            }
        )
    groups = []
    if docs:
        groups.append(
            {
                "id": "source-proposal",
                "kind": "reference",
                "title": "Source proposal" if len(docs) == 1 else "Source proposals",
                "rationale": (
                    "Historical proposal context transferred into this Package. "
                    "Ratified Direction and Experiment Scope remain authoritative."
                ),
                "lead": (
                    "The original draft is retained here as Package-owned context, "
                    "not as an active Brainstorm."
                ),
                "docs": docs,
            }
        )
    return source_records, groups, interface_notes, consumptions


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
    package_lifecycle = view.get("package_lifecycle")
    package = {
        "state": (
            "draft"
            if package_lifecycle == "DRAFT"
            else "active"
            if package_exists
            else "absent"
        ),
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
    source_package = view.get("source_package")
    if isinstance(source_package, dict) and source_package.get("id") != package_id:
        return {
            "materializable": False,
            "direction": {
                "state": "committed",
                "id": direction_id,
                "version": direction.get("version"),
            },
            "experiments": {"state": "blocked", "count": 0},
            "package": package,
            "nextSkill": "/research-package",
            "nextAction": (
                "Activate the reviewed Draft Package with --id "
                f"{source_package.get('id')}"
            ),
        }
    if package_lifecycle == "DRAFT" and not view.get("draft_binding_valid"):
        return {
            "materializable": False,
            "direction": {
                "state": "committed",
                "id": direction_id,
                "version": direction.get("version"),
            },
            "experiments": {"state": "blocked", "count": 0},
            "package": package,
            "nextSkill": "/research-scope",
            "nextAction": (
                "The accepted Scope does not match the current Draft Package "
                "revision. Re-review and ratify the refined draft."
            ),
        }
    missing_sources = view.get("missing_source_brainstorms") or []
    if missing_sources and not package_exists:
        return {
            "materializable": False,
            "direction": {
                "state": "committed",
                "id": direction_id,
                "version": direction.get("version"),
            },
            "experiments": {"state": "blocked", "count": 0},
            "package": package,
            "nextSkill": "/research-brainstorm",
            "nextAction": (
                "Restore or explicitly resolve the accepted Direction's source "
                "Brainstorm before Package materialization: "
                + ", ".join(str(item) for item in missing_sources)
            ),
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
    if package_exists and package_lifecycle != "DRAFT":
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
        "nextAction": (
            f"Activate Draft Package {package_id} from ratified Scope"
            if package_lifecycle == "DRAFT"
            else f"/research-package from-scope {direction_id}"
        ),
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
    parser.add_argument("--motivation", default="")
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
        default=None,
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
    activating_draft = materialization.get("package_lifecycle") == "DRAFT"
    source_rows = (
        []
        if activating_draft
        else _resolve_source_brainstorms(
            paths,
            materialization,
            args.source_brainstorms,
        )
    )
    experiment_ids = [str(item["aggregate_id"]) for item in scope_experiments]
    (
        source_records,
        docs_groups,
        interface_notes,
        brainstorm_consumptions,
    ) = _build_brainstorm_transfer(package_id, source_rows, experiment_ids)
    draft = materialization.get("draft_package")
    if activating_draft and not isinstance(draft, dict):
        raise SystemExit("Draft Package disappeared before activation")
    name = args.name or (
        str(draft.get("name") or draft.get("title"))
        if isinstance(draft, dict)
        else direction_slug.replace("-", " ").title()
    )
    pages = (
        copy.deepcopy(draft.get("pages"))
        if isinstance(draft, dict) and isinstance(draft.get("pages"), list)
        else create_research_package.parse_scope(args.scope, args.category)
    )
    problem = args.problem or (
        str(draft.get("problem") or "") if isinstance(draft, dict) else ""
    )
    motivation = args.motivation or (
        str(draft.get("motivation") or "") if isinstance(draft, dict) else ""
    )
    objective = args.objective or (
        str(draft.get("objective") or "") if isinstance(draft, dict) else ""
    )
    missing_intent = [
        label
        for label, value in (
            ("--problem", problem),
            ("--motivation", motivation),
            ("--objective", objective),
        )
        if not value.strip()
    ]
    if missing_intent:
        raise SystemExit(
            "Package activation requires explicit Research Intent fields: "
            + ", ".join(missing_intent)
        )
    draft_hypothesis = (
        str(draft.get("hypothesis") or "").strip()
        if isinstance(draft, dict)
        else ""
    )
    if (
        draft_hypothesis
        and " ".join(draft_hypothesis.split()).casefold()
        != " ".join(hypothesis.split()).casefold()
    ):
        raise SystemExit(
            "Draft Package Hypothesis must match the accepted Direction hypothesis"
        )
    record: dict[str, Any] = copy.deepcopy(draft) if isinstance(draft, dict) else {}
    record.update({
        "id": package_id,
        "slug": package_id,
        "name": name,
        "lifecycle": "ACTIVE",
        "phase": args.status,
        "blocker": None,
        "tag": args.tag,
        "tagMeaning": args.tag_meaning,
        "problem": problem,
        "objective": objective,
        "motivation": motivation,
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
                "id": str(item["aggregate_id"]),
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
        "docsGroups": docs_groups,
        "executionAuthorized": True,
    })
    if activating_draft:
        record["scopeBinding"] = {
            "source_package": copy.deepcopy(materialization["source_package"]),
            "direction_id": args.direction_id,
            "direction_version": direction.get("version"),
            "experiment_ids": list(experiment_ids),
        }
        record["lastAction"] = f"activated from ratified Scope {args.direction_id}"
    if interface_notes:
        record["interface_notes"] = interface_notes
    if activating_draft:
        package_event, experiment_events = management.commit_package_activate(
            paths,
            record,
            _experiment_rows(package_id, scope_experiments),
            entry_skill="research-package",
        )
    else:
        package_event, experiment_events = management.commit_package_create(
            paths,
            record,
            _experiment_rows(package_id, scope_experiments),
            brainstorm_consumptions,
            entry_skill="research-package",
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
                "source_brainstorms_converted": [
                    row["aggregate_id"] for row in source_rows
                ],
                "activated_from_draft": activating_draft,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
