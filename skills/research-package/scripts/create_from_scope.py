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
sys.path.insert(0, str(PIPELINE_ROOT / "skills" / "research-brainstorm" / "scripts"))

import brainstorm  # noqa: E402
import create_research_package  # noqa: E402
import context_pack.build as context_pack_build  # noqa: E402
import scope_ssot  # noqa: E402


def _esc(value) -> str:
    return (str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _write_brainstorm_provenance(root: Path, package_id: str, name: str, ideas: list[dict]) -> Path:
    """Freeze the source brainstorm idea(s) a package was converted from as its brainstorm.html."""
    cards = "\n".join(
        '<article class="module-card"><h2>{title}</h2><p>{idea}</p>'
        '<div class="kv-grid"><div class="k">Idea id</div><div>{bid}</div>{metric}</div></article>'.format(
            title=_esc(i.get("title", i["id"])), idea=_esc(i.get("idea", "")), bid=_esc(i["id"]),
            metric=('<div class="k">Rough metric</div><div>%s</div>' % _esc(i["rough_metric"]))
            if i.get("rough_metric") else "")
        for i in ideas)
    html = (
        '<!doctype html>\n<html lang="en">\n<head>\n  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'  <title>{_esc(name)} - Brainstorm provenance</title>\n'
        '  <link rel="stylesheet" href="../../assets/research.css">\n</head>\n'
        f'<body data-page="brainstorm" data-package-id="{_esc(package_id)}">\n  <div class="shell">\n'
        '    <header class="masthead" data-section="masthead">\n      <div class="eyebrow">brainstorm provenance</div>\n'
        f'      <h1>Brainstorm &mdash; {_esc(name)}</h1>\n'
        '      <p class="lead">Frozen record of the pre-package idea(s) this package was converted from. '
        'These ideas left the brainstorm lane on conversion.</p>\n'
        '      <div class="toolbar"><a class="pill" href="index.html">Overview</a></div>\n    </header>\n'
        f'    <section data-section="source-ideas" id="source-ideas" aria-label="Source ideas">\n{cards}\n    </section>\n'
        '  </div>\n</body>\n</html>\n'
    )
    path = root / "packages" / package_id / "brainstorm.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return path


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
        if node.get("status") != "ACTIVE":
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
    # Readiness flags per milestone kind (requiresCode, complex): does the phase need a
    # code change / a pipeline doc? Conservative defaults the PM refines at plan time.
    flags_by_suffix = {
        "baseline-validity": (False, False),
        "main-hypothesis": (True, True),
        "mechanism-validation": (True, True),
        "robustness-validation": (True, False),
        "failure-boundary": (False, False),
    }
    rows = []
    for idx, item in enumerate(milestones):
        node = item["node"]
        suffix = node["id"].rsplit("/", 1)[-1]
        suffix_key = suffix.split("-", 1)[-1] if "-" in suffix else suffix
        requires_code, complex_phase = flags_by_suffix.get(suffix_key, (False, False))
        exp_id = f"P{idx}"
        rows.append({
            "id": exp_id,
            "purpose": purpose_by_suffix.get(suffix_key, "Validate milestone"),
            "after": [] if idx == 0 else [f"P{idx - 1}"],
            "output": f"outputs/{package_id}/{exp_id}/result.json",
            "gate": node["spec"]["gate"],
            "status": "queued",
            "measures": True,
            "requiresCode": requires_code,
            "complex": complex_phase,
            "docsAnchor": f"docs/pipeline.html#p{idx}" if complex_phase else "docs/index.html",
            "sourceTask": node["id"],
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
    p.add_argument("--transitions", default="outputs/_scope/transitions.jsonl",
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
    p.add_argument("--no-change-boundary", default="SSOT spec fields are the source of truth",
                   dest="no_change_boundary")
    p.add_argument("--source-path", default="", dest="source_path")
    p.add_argument("--artifact-root", default="", dest="artifact_root")
    p.add_argument("--next-action", default="Plan validation tasks from the accepted direction spec",
                   dest="next_action")
    p.add_argument("--scope", default="index,plan,implementation,results,tracker,docs,_agent")
    p.add_argument("--status", default="CONTEXT_LOADED")
    p.add_argument("--contribution-spine-flag", default="", dest="contribution_spine_flag")
    p.add_argument("--source-brainstorms", default="[]", dest="source_brainstorms",
                   help="JSON list of brainstorm idea ids this package converts from; "
                        "consumed (removed from the lane) and frozen into brainstorm.html provenance")
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
    if node.get("status") != "ACTIVE":
        raise SystemExit(f"Direction must be active before materialization, got status={node.get('status')!r}")

    scope_ssot.validate_node(node)
    spec = node["spec"]
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

    source_brainstorms = json.loads(args.source_brainstorms)
    scope = args.scope
    # brainstorm.html is provenance-only — written directly by _write_brainstorm_provenance,
    # not a STAGE_PAGES entry; do not inject it into scope.

    hypothesis = str(spec["hypothesis"])
    metric = _metric_label(spec["metric"])
    success_gate = str(spec["success_gate"])
    milestone_provenance = [
        {
            "id": item["node"]["id"],
            "scopeVersion": item["record"]["scope_version"],
            "txn": item["record"]["transaction_id"],
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
        "--baseline", _baseline_label(spec["baselines"]),
        "--budget", args.budget,
        "--no-change-boundary", args.no_change_boundary,
        "--next-action", args.next_action,
        "--scope", scope,
        "--status", args.status,
        "--contribution-spine-flag", args.contribution_spine_flag,
        "--direction", hypothesis,
        "--active-gate", success_gate,
        "--primary-metric-vs-gate", f"{metric} vs {success_gate}",
        "--last-action", f"materialized from {args.direction_id}",
        "--open-runs", "none",
        "--experiments-json", json.dumps(_experiment_rows(package_id, milestones), ensure_ascii=False),
        "--source-direction", args.direction_id,
        "--source-version", str(record["scope_version"]),
        "--source-change", str(record["transaction_id"]),
        "--source-tasks", json.dumps(milestone_provenance, ensure_ascii=False),
    ]
    if args.source_path:
        create_args.extend(["--source-path", args.source_path])
    if args.artifact_root:
        create_args.extend(["--artifact-root", args.artifact_root])
    if args.force:
        create_args.append("--force")

    pkg_name = args.name or direction_slug.replace("-", " ").title()
    rc = create_research_package.main(create_args)
    if rc == 0 and source_brainstorms:
        ideas = brainstorm.consume_brainstorms(root, source_brainstorms)
        _write_brainstorm_provenance(root, package_id, pkg_name, ideas)
    if rc == 0:
        context_pack_build.build(str(root), package_id, transitions_path=args.transitions)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
