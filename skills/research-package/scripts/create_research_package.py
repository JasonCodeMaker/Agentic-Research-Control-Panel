#!/usr/bin/env python3
"""Create Package and Experiment aggregates in management state."""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any

PIPELINE_ROOT = Path(__file__).resolve().parents[3]
for candidate in (
    PIPELINE_ROOT,
    PIPELINE_ROOT / "lib",
    PIPELINE_ROOT / "skills" / "research-op" / "scripts",
):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from lib.research_state import ResearchPaths  # noqa: E402
from lib.research_state import policy as state_policy  # noqa: E402
import management  # noqa: E402


CATEGORIES = {"in-progress", "success", "fail"}
STAGE_PAGES = (
    "index",
    "plan",
    "implementation",
    "results",
    "analysis",
    "tracker",
    "docs",
    "_agent",
)
STAGE_PAGE_SET = set(STAGE_PAGES)
ALWAYS_PRESENT = ("index", "tracker", "docs", "_agent")


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "research-package"


def default_id(name: str) -> str:
    return f"{dt.date.today().isoformat()}-{slugify(name)}"


def parse_scope(raw: str, _category: str = "in-progress") -> list[str]:
    keys = list(STAGE_PAGES) if raw == "all" else [
        item.strip() for item in raw.split(",") if item.strip()
    ]
    for key in ALWAYS_PRESENT:
        if key not in keys:
            keys.append(key)
    unknown = sorted(set(keys) - STAGE_PAGE_SET)
    if unknown:
        raise SystemExit(f"Unknown scope key(s): {', '.join(unknown)}")
    return keys


def parse_experiments_json(raw: str) -> list[dict[str, Any]]:
    if not raw:
        return []
    parsed = json.loads(raw)
    if not isinstance(parsed, list) or not all(
        isinstance(row, dict) for row in parsed
    ):
        raise SystemExit("--experiments must be a JSON list of objects.")
    return copy.deepcopy(parsed)


def exp_measures(exp: dict[str, Any]) -> bool:
    return bool(exp.get("measures", True))


def prepare_experiments(
    package_id: str,
    experiments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Prepare bindings to accepted Experiments without copying their specs."""
    prepared: list[dict[str, Any]] = []
    for raw in experiments:
        row = copy.deepcopy(raw)
        local_id = str(row.get("local_id") or "").strip()
        scope_experiment_id = row.get("scope_experiment_id")
        missing = []
        if not isinstance(scope_experiment_id, str) or not scope_experiment_id.strip():
            missing.append("scope_experiment_id")
        if not local_id:
            missing.append("local_id")
        if missing:
            label = local_id or "<unknown>"
            raise SystemExit(
                f"Experiment binding {label} is missing fields: "
                + ", ".join(missing)
            )
        forbidden = {
            "id",
            "spec",
            "purpose",
            "config_ref",
            "gate",
            "control_mode",
        }.intersection(row)
        if forbidden:
            raise SystemExit(
                "Experiment.spec is owned by accepted Scope; remove: "
                + ", ".join(sorted(forbidden))
            )
        row.setdefault(
            "output",
            f".research/experiments/{package_id}/{local_id}/"
            "<run-id>/result.json",
        )
        prepared.append(row)
    return prepared


def _canonical_state(args: argparse.Namespace) -> dict[str, Any]:
    status = args.status or "CONTEXT_LOADED"
    if args.category != "in-progress" or status != "CONTEXT_LOADED":
        raise SystemExit(
            "New Packages must use category=in-progress and "
            "status=CONTEXT_LOADED; import historical terminal state through "
            "the explicit migration path."
        )
    record: dict[str, Any] = {}
    if args.current_blocker:
        record["currentBlocker"] = args.current_blocker
    try:
        return state_policy.from_legacy(args.category, status, record)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


def _package_record(
    args: argparse.Namespace,
    package_id: str,
    pages: list[str],
) -> dict[str, Any]:
    canonical = _canonical_state(args)
    source_path = args.source_path or ""
    artifact_root = (
        args.artifact_root
        or f".research/experiments/{package_id}/"
    )
    primary_vs_gate = args.primary_metric_vs_gate or args.primary_metric
    record: dict[str, Any] = {
        "id": package_id,
        "slug": package_id,
        "name": args.name,
        **canonical,
        "tag": args.tag,
        "tagMeaning": args.tag_meaning,
        "sourcePath": source_path,
        "runtime": artifact_root,
        "artifactRoot": artifact_root,
        "problem": args.problem,
        "objective": args.objective,
        "motivation": args.motivation,
        "hypothesis": args.hypothesis,
        "primaryMetric": args.primary_metric,
        "baseline": args.baseline,
        "budget": args.budget,
        "noChangeBoundary": args.no_change_boundary,
        "nextAction": args.next_action or "unmeasured",
        "contributionSpineFlag": args.contribution_spine_flag,
        "direction": args.direction,
        "activeGate": args.active_gate,
        "primaryMetricVsGate": primary_vs_gate,
        "lastDecision": args.last_decision,
        "lastDecisionEvidencePath": args.last_decision_evidence_path,
        "nextRoute": args.next_route,
        "currentBlocker": args.current_blocker,
        "lastAction": args.last_action or "package materialized",
        "openRuns": args.open_runs or "none",
        "lastUpdated": args.last_updated,
        "pages": pages,
        "methodsTried": [],
        "resultGateRows": [],
        "resultBlocks": [],
        "analysisInsights": [],
        "docsGroups": [],
    }
    if args.source_direction:
        record.update(
            {
                "direction_id": args.source_direction,
                "sourceDirection": args.source_direction,
                "sourceVersion": args.source_version,
                "sourceChange": args.source_change,
            }
        )
        if args.source_experiments:
            source_experiments = json.loads(args.source_experiments)
            if not isinstance(source_experiments, list) or not all(
                isinstance(item, dict)
                and isinstance(item.get("id"), str)
                and item["id"].strip()
                and isinstance(item.get("version"), int)
                and item["version"] > 0
                and isinstance(item.get("source"), str)
                and item["source"].strip()
                and set(item) == {"id", "version", "source"}
                for item in source_experiments
            ):
                raise SystemExit(
                    "--source-experiments must be a JSON list of "
                    "{id, version, source} objects"
                )
            record["sourceExperiments"] = copy.deepcopy(source_experiments)
    elif args.source_experiments:
        raise SystemExit("--source-experiments requires --source-direction")
    return record


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--research-root")
    parser.add_argument("--id", default="")
    parser.add_argument("--name", required=True)
    parser.add_argument("--category", required=True, choices=sorted(CATEGORIES))
    parser.add_argument("--tag", required=True)
    parser.add_argument("--tag-meaning", required=True, dest="tag_meaning")
    parser.add_argument("--problem", required=True)
    parser.add_argument("--objective", required=True)
    parser.add_argument("--motivation", required=True)
    parser.add_argument("--hypothesis", required=True)
    parser.add_argument("--primary-metric", required=True, dest="primary_metric")
    parser.add_argument("--baseline", default="unmeasured")
    parser.add_argument("--budget", default="unmeasured")
    parser.add_argument(
        "--no-change-boundary",
        default="unmeasured",
        dest="no_change_boundary",
    )
    parser.add_argument("--source-path", default="", dest="source_path")
    parser.add_argument("--artifact-root", default="", dest="artifact_root")
    parser.add_argument("--next-action", default="", dest="next_action")
    parser.add_argument(
        "--scope",
        default="index,tracker,docs,_agent",
        help="comma list of stage pages or 'all'",
    )
    parser.add_argument("--status", default="")
    parser.add_argument(
        "--contribution-spine-flag",
        default="",
        dest="contribution_spine_flag",
    )
    parser.add_argument("--direction", default="")
    parser.add_argument("--active-gate", default="", dest="active_gate")
    parser.add_argument(
        "--primary-metric-vs-gate",
        default="",
        dest="primary_metric_vs_gate",
    )
    parser.add_argument("--last-decision", default="", dest="last_decision")
    parser.add_argument(
        "--last-decision-evidence-path",
        default="",
        dest="last_decision_evidence_path",
    )
    parser.add_argument("--next-route", default="", dest="next_route")
    parser.add_argument("--current-blocker", default="", dest="current_blocker")
    parser.add_argument("--last-action", default="", dest="last_action")
    parser.add_argument("--open-runs", default="", dest="open_runs")
    parser.add_argument(
        "--last-updated",
        default=dt.date.today().isoformat(),
        dest="last_updated",
    )
    parser.add_argument("--experiments", default="")
    parser.add_argument("--source-direction", default="", dest="source_direction")
    parser.add_argument("--source-version", type=int, dest="source_version")
    parser.add_argument("--source-change", default="", dest="source_change")
    parser.add_argument(
        "--source-experiments",
        default="",
        dest="source_experiments",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    package_id = args.id or default_id(args.name)
    if not re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z0-9][a-z0-9-]*",
        package_id,
    ):
        raise SystemExit("Package id must look like YYYY-MM-DD-slug.")
    pages = parse_scope(args.scope, args.category)
    initial_experiments = prepare_experiments(
        package_id,
        parse_experiments_json(args.experiments),
    )
    experiments = initial_experiments
    result_schemas: dict[str, dict[str, Any]] = {}
    if any(row.get("local_id") and exp_measures(row) for row in experiments):
        if "results" not in pages:
            pages.append("results")
    record = _package_record(args, package_id, pages)
    if result_schemas:
        record["resultSchemas"] = result_schemas
    paths = ResearchPaths.resolve(
        workspace=args.workspace,
        research_root=args.research_root,
    )
    package_event, experiment_events = management.commit_package_create(
        paths,
        record,
        experiments,
        entry_skill="research-package",
    )
    print(
        json.dumps(
            {
                "ok": True,
                "package_id": package_id,
                "aggregate": f"package/{package_id}",
                "event_id": package_event["event_id"],
                "experiments": [
                    {
                        "aggregate": (
                            f"{event['aggregate_type']}/{event['aggregate_id']}"
                        ),
                        "event_id": event["event_id"],
                    }
                    for event in experiment_events
                ],
                "pages": pages,
                "experiment_root": str(paths.experiments / package_id),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
