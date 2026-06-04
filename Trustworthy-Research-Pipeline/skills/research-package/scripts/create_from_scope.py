#!/usr/bin/env python3
"""Materialize an accepted SSOT Direction plus Milestones as a research package.

This bridge intentionally reads only the committed Scope SSOT transition log. Pending
Triage proposals are not materialized, because a package is a visible dashboard
surface and must come from an accepted direction and accepted high-level validation
milestones.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PIPELINE_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PIPELINE_ROOT / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import create_research_package  # noqa: E402
import scope_ssot  # noqa: E402


def _slug_from_direction_id(direction_id: str) -> str:
    tail = direction_id.rsplit("/", 1)[-1]
    return create_research_package.slugify(tail)


def _metric_label(metric) -> str:
    if isinstance(metric, dict):
        if metric.get("name"):
            return str(metric["name"])
        return json.dumps(metric, sort_keys=True, ensure_ascii=False)
    if isinstance(metric, list):
        return ", ".join(str(m) for m in metric)
    return str(metric)


def _baseline_label(baselines) -> str:
    if isinstance(baselines, list):
        return "; ".join(str(b) for b in baselines) if baselines else "unmeasured"
    if baselines:
        return str(baselines)
    return "unmeasured"


def _latest_record(direction_id: str, records: list[dict]) -> dict | None:
    hist = scope_ssot.history(direction_id, records)
    return hist[-1] if hist else None


def _latest_records_by_node(records: list[dict]) -> dict[str, dict]:
    latest = {}
    for rec in records:
        latest[rec["node_id"]] = rec
    return latest


def _child_milestones(direction_id: str, records: list[dict]) -> list[dict]:
    projection = scope_ssot.fold(records)
    latest = _latest_records_by_node(records)
    milestones = []
    for node_id, node in projection.items():
        if node.get("level") != "task":
            continue
        if direction_id not in node.get("parents", []):
            continue
        if node.get("status") != "active":
            continue
        milestones.append({"node": node, "record": latest[node_id]})
    milestones.sort(key=lambda item: item["node"]["id"])
    return milestones


def _experiment_rows(package_id: str, milestones: list[dict]) -> list[dict]:
    purpose_by_suffix = {
        "baseline-validity": "Verify baseline",
        "main-hypothesis": "Run main validation",
        "mechanism-validation": "Run mechanism ablation",
        "robustness-validation": "Run robustness checks",
        "failure-boundary": "Register failure boundary",
    }
    rows = []
    for idx, item in enumerate(milestones):
        node = item["node"]
        suffix = node["id"].rsplit("/", 1)[-1]
        suffix_key = suffix.split("-", 1)[-1] if "-" in suffix else suffix
        exp_id = f"P{idx}"
        rows.append({
            "id": exp_id,
            "purpose": purpose_by_suffix.get(suffix_key, "Validate milestone"),
            "after": [] if idx == 0 else [f"P{idx - 1}"],
            "output": f"var/research/{package_id}/{exp_id}/result.json",
            "gate": node["yardstick"]["gate_predicate"],
            "status": "pending",
            "docsAnchor": "docs/index.html",
            "parentTask": node["id"],
        })
    return rows


def _inventory_contains(root: Path, package_id: str) -> bool:
    data_path = root / "data" / "research-packages.js"
    if not data_path.exists():
        raise FileNotFoundError(f"Missing {data_path}. Set up the dashboard first.")
    text = data_path.read_text(encoding="utf-8")
    return f'id: "{package_id}"' in text or f"id: '{package_id}'" in text


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--direction-id", required=True,
                   help="committed SSOT direction node id, e.g. dir/retrieval-v2")
    p.add_argument("--root", default="research_html", help="research_html root")
    p.add_argument("--transitions", default="var/research/_scope/transitions.jsonl",
                   help="committed Scope SSOT transition log")
    p.add_argument("--id", default="", help="package id; default YYYY-MM-DD-<direction-slug>")
    p.add_argument("--name", default="", help="package name; default derived from direction id")
    p.add_argument("--category", default="in-progress",
                   choices=sorted(create_research_package.CATEGORIES))
    p.add_argument("--tag", default="scope")
    p.add_argument("--tag-meaning", default="Materialized from an accepted Scope SSOT Direction",
                   dest="tag_meaning")
    p.add_argument("--problem", default="", help="problem text; default from direction hypothesis")
    p.add_argument("--objective", default="", help="objective text; default from direction hypothesis")
    p.add_argument("--motivation", default="Accepted Scope SSOT direction materialized as a package")
    p.add_argument("--budget", default="unmeasured")
    p.add_argument("--no-change-boundary", default="SSOT yardstick fields are the source of truth",
                   dest="no_change_boundary")
    p.add_argument("--source-path", default="", dest="source_path")
    p.add_argument("--artifact-root", default="", dest="artifact_root")
    p.add_argument("--next-action", default="Plan validation tasks from the accepted direction yardstick",
                   dest="next_action")
    p.add_argument("--scope", default="index,plan,tracker,docs,_agent")
    p.add_argument("--status", default="CONTEXT_LOADED")
    p.add_argument("--contribution-spine-flag", default="", dest="contribution_spine_flag")
    p.add_argument("--force", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root)
    records = scope_ssot.read_log(args.transitions)
    record = _latest_record(args.direction_id, records)
    if record is None:
        raise SystemExit(f"Committed direction not found in {args.transitions}: {args.direction_id}")

    node = record.get("node")
    if not node:
        raise SystemExit(f"Transition for {args.direction_id} does not carry a node snapshot")
    if node.get("level") != "direction":
        raise SystemExit(f"--direction-id must point to a direction node, got level={node.get('level')!r}")
    if node.get("status") != "active":
        raise SystemExit(f"Direction must be active before materialization, got status={node.get('status')!r}")

    scope_ssot.validate_node(node)
    yardstick = node["yardstick"]
    direction_slug = _slug_from_direction_id(args.direction_id)
    package_id = args.id or create_research_package.default_id(direction_slug)
    if _inventory_contains(root, package_id) or (root / "packages" / package_id).exists():
        raise SystemExit(f"Package already exists or is already inventoried: {package_id}")
    milestones = _child_milestones(args.direction_id, records)
    if not milestones:
        raise SystemExit(
            f"No accepted high-level validation milestones found for {args.direction_id}. "
            "Run research-scope/scripts/plan_milestones.py and commit the accepted task nodes first."
        )

    hypothesis = str(yardstick["hypothesis"])
    metric = _metric_label(yardstick["metric"])
    success_predicate = str(yardstick["success_predicate"])
    milestone_provenance = [
        {
            "id": item["node"]["id"],
            "scopeVersion": item["record"]["scope_version"],
            "txn": item["record"]["txn_id"],
        }
        for item in milestones
    ]
    create_args = [
        "--root", str(root),
        "--id", package_id,
        "--name", args.name or direction_slug.replace("-", " ").title(),
        "--category", args.category,
        "--tag", args.tag,
        "--tag-meaning", args.tag_meaning,
        "--problem", args.problem or hypothesis,
        "--objective", args.objective or hypothesis,
        "--motivation", args.motivation,
        "--hypothesis", hypothesis,
        "--primary-metric", metric,
        "--baseline", _baseline_label(yardstick["baselines"]),
        "--budget", args.budget,
        "--no-change-boundary", args.no_change_boundary,
        "--next-action", args.next_action,
        "--scope", args.scope,
        "--status", args.status,
        "--contribution-spine-flag", args.contribution_spine_flag,
        "--direction", hypothesis,
        "--active-gate", success_predicate,
        "--primary-metric-vs-gate", f"{metric} vs {success_predicate}",
        "--last-action", f"materialized from {args.direction_id}",
        "--open-runs", "none",
        "--experiments-json", json.dumps(_experiment_rows(package_id, milestones), ensure_ascii=False),
        "--source-scope-node", args.direction_id,
        "--source-scope-version", str(record["scope_version"]),
        "--source-scope-txn", str(record["txn_id"]),
        "--source-scope-milestones", json.dumps(milestone_provenance, ensure_ascii=False),
    ]
    if args.source_path:
        create_args.extend(["--source-path", args.source_path])
    if args.artifact_root:
        create_args.extend(["--artifact-root", args.artifact_root])
    if args.force:
        create_args.append("--force")

    return create_research_package.main(create_args)


if __name__ == "__main__":
    raise SystemExit(main())
