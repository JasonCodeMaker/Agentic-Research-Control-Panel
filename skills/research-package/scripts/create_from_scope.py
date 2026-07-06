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


def _read_triage(triage_path: str | Path) -> list[dict]:
    path = Path(triage_path)
    if not path.exists():
        return []
    latest = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec.get("id"):
            latest[rec["id"]] = {**latest.get(rec["id"], {}), **rec}
    return [rec for rec in latest.values() if rec.get("status") == "pending"]


def _proposal_target(item: dict) -> str | None:
    proposed = item.get("proposed_node") if isinstance(item.get("proposed_node"), dict) else {}
    return item.get("node_id") or proposed.get("id")


def _proposal_parents(item: dict) -> list[str]:
    proposed = item.get("proposed_node") if isinstance(item.get("proposed_node"), dict) else {}
    parents = item.get("parents") or proposed.get("parents") or []
    return parents if isinstance(parents, list) else []


def _pending_direction_items(pending: list[dict], direction_id: str) -> list[dict]:
    return [item for item in pending if _proposal_target(item) == direction_id]


def _pending_task_items(pending: list[dict], direction_id: str) -> list[dict]:
    return [item for item in pending if direction_id in _proposal_parents(item)]


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


def _package_state(root: Path, package_id: str) -> dict:
    try:
        inventoried = _inventory_contains(root, package_id)
    except FileNotFoundError:
        return {"state": "dashboard_missing", "id": package_id}
    if inventoried or (root / "packages" / package_id).exists():
        return {"state": "exists", "id": package_id}
    return {"state": "absent", "id": package_id}


def materialization_status(*, root: Path, direction_id: str, transitions: str | Path,
                           triage: str | Path, package_id: str) -> dict:
    """Explain whether a committed Scope Direction can become a package now."""
    records = scope_ssot.read_log(transitions)
    pending = _read_triage(triage)
    record = _latest_record(direction_id, records)
    package = _package_state(root, package_id)

    if package["state"] == "dashboard_missing":
        return {
            "materializable": False,
            "direction": {"state": "unknown", "id": direction_id},
            "tasks": {"state": "unknown", "count": 0},
            "package": package,
            "nextSkill": "/research-dashboard",
            "nextAction": "Run /research-dashboard before creating package surfaces.",
        }

    if record is None:
        direction_pending = _pending_direction_items(pending, direction_id)
        if direction_pending:
            return {
                "materializable": False,
                "direction": {"state": "pending", "id": direction_id,
                              "pending": [item["id"] for item in direction_pending]},
                "tasks": {"state": "blocked", "count": 0},
                "package": package,
                "nextSkill": "/research-scope",
                "nextAction": "Accept, revise, or reject the pending Direction before creating a package.",
            }
        return {
            "materializable": False,
            "direction": {"state": "missing", "id": direction_id},
            "tasks": {"state": "blocked", "count": 0},
            "package": package,
            "nextSkill": "/research-brainstorm",
            "nextAction": "Shape and ratify a Direction before creating a package.",
        }

    node = record.get("node") or {}
    if node.get("level") != "direction":
        return {
            "materializable": False,
            "direction": {"state": "wrong_level", "id": direction_id, "level": node.get("level")},
            "tasks": {"state": "blocked", "count": 0},
            "package": package,
            "nextSkill": "/research-scope",
            "nextAction": "Use a committed Direction id, not another Scope node id.",
        }
    if node.get("status") != "ACTIVE":
        return {
            "materializable": False,
            "direction": {"state": "inactive", "id": direction_id, "status": node.get("status")},
            "tasks": {"state": "blocked", "count": 0},
            "package": package,
            "nextSkill": "/research-scope",
            "nextAction": "Reopen or revise the Direction before creating a package.",
        }
    scope_ssot.validate_node(node)

    milestones = _child_milestones(direction_id, records)
    if not milestones:
        pending_tasks = _pending_task_items(pending, direction_id)
        task_state = "pending" if pending_tasks else "missing"
        tasks = {"state": task_state, "count": 0}
        if pending_tasks:
            tasks["pending"] = [item["id"] for item in pending_tasks]
        action = ("Accept, revise, or reject the pending validation Tasks before creating a package."
                  if pending_tasks else
                  "Propose and ratify validation Tasks before creating a package.")
        return {
            "materializable": False,
            "direction": {"state": "committed", "id": direction_id,
                          "scopeVersion": record.get("scope_version"),
                          "txn": record.get("transaction_id")},
            "tasks": tasks,
            "package": package,
            "nextSkill": "/research-scope",
            "nextAction": action,
        }

    if package["state"] == "exists":
        return {
            "materializable": False,
            "direction": {"state": "committed", "id": direction_id,
                          "scopeVersion": record.get("scope_version"),
                          "txn": record.get("transaction_id")},
            "tasks": {"state": "committed", "count": len(milestones),
                      "ids": [item["node"]["id"] for item in milestones]},
            "package": package,
            "nextSkill": "/research-run",
            "nextAction": f"/research-run {package_id}",
        }

    return {
        "materializable": True,
        "direction": {"state": "committed", "id": direction_id,
                      "scopeVersion": record.get("scope_version"),
                      "txn": record.get("transaction_id")},
        "tasks": {"state": "committed", "count": len(milestones),
                  "ids": [item["node"]["id"] for item in milestones]},
        "package": package,
        "nextSkill": "/research-package",
        "nextAction": f"/research-package from-scope {direction_id}",
    }


def _print_check(status: dict, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(status, ensure_ascii=False, sort_keys=True))
        return
    print(f"materializable: {str(status['materializable']).lower()}")
    print(f"direction: {status['direction'].get('state')} {status['direction'].get('id')}")
    print(f"tasks: {status['tasks'].get('state')} count={status['tasks'].get('count')}")
    print(f"package: {status['package'].get('state')} {status['package'].get('id')}")
    print(f"next: {status['nextAction']}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--check", action="store_true",
                   help="report whether this Direction can be materialized without writing files")
    p.add_argument("--json", action="store_true", dest="json_output",
                   help="with --check, print machine-readable JSON")
    p.add_argument("--direction-id", required=True,
                   help="committed SSOT direction node id, e.g. dir/retrieval-v2")
    p.add_argument("--root", default="research_html", help="research_html root")
    p.add_argument("--transitions", default="outputs/_scope/transitions.jsonl",
                   help="committed Scope SSOT transition log")
    p.add_argument("--triage", default="outputs/_scope/triage.jsonl",
                   help="Scope Triage queue used only for --check diagnostics")
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
    direction_slug = _slug_from_direction_id(args.direction_id)
    package_id = args.id or create_research_package.default_id(direction_slug)
    if args.check:
        status = materialization_status(
            root=root,
            direction_id=args.direction_id,
            transitions=args.transitions,
            triage=args.triage,
            package_id=package_id,
        )
        _print_check(status, as_json=args.json_output)
        return 0

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
