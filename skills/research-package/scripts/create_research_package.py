#!/usr/bin/env python3
"""Create an initial research package and add it to research-packages.js."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import string
from pathlib import Path


CATEGORIES = {"brainstorm", "in-progress", "success", "fail"}

# Stage pages and their template paths (relative to research-package/templates/)
# and emitted output paths (relative to packages/<id>/).
STAGE_PAGES: dict[str, tuple[str, str]] = {
    "index": ("index.html", "index.html"),
    "plan": ("plan.html", "plan.html"),
    "implementation": ("implementation.html", "implementation.html"),
    "results": ("results.html", "results.html"),
    "analysis": ("analysis.html", "analysis.html"),
    "next-action": ("next-action.html", "next-action.html"),
    "tracker": ("tracker.html", "tracker.html"),
    "brainstorm": ("brainstorm.html", "brainstorm.html"),
    "docs": ("docs/index.html", "docs/index.html"),
    "_agent": ("_agent/context.html", "_agent/context.html"),
}

ALWAYS_PRESENT = ["index", "tracker", "docs", "_agent"]
ALL_SCOPE_KEYS = list(STAGE_PAGES.keys())


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "research-package"


def default_id(name: str) -> str:
    return f"{dt.date.today().isoformat()}-{slugify(name)}"


def js_value(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def js_object(items: dict[str, object]) -> str:
    lines = ["{"]
    for key, value in items.items():
        if isinstance(value, list):
            rendered = "[" + ", ".join(js_value(v) for v in value) + "]"
        else:
            rendered = js_value(value)
        lines.append(f"  {key}: {rendered},")
    lines.append("}")
    return "\n".join(lines)


def write_file(path: Path, text: str, force: bool) -> bool:
    if path.exists() and not force:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def parse_scope(raw: str, category: str) -> list[str]:
    if raw == "all":
        keys = list(ALL_SCOPE_KEYS)
    else:
        keys = [s.strip() for s in raw.split(",") if s.strip()]
    # Always include the always-present pages.
    for k in ALWAYS_PRESENT:
        if k not in keys:
            keys.append(k)
    # Brainstorm only matters for brainstorm-category packages.
    if category == "brainstorm" and "brainstorm" not in keys:
        keys.append("brainstorm")
    if category != "brainstorm" and "brainstorm" in keys:
        keys.remove("brainstorm")
    # Validate.
    for k in keys:
        if k not in STAGE_PAGES:
            raise SystemExit(f"Unknown scope key: {k}")
    return keys


def render_template(templates_dir: Path, template_rel: str, mapping: dict[str, str]) -> str:
    template_path = templates_dir / template_rel
    if not template_path.exists():
        raise FileNotFoundError(f"Missing template: {template_path}")
    raw = template_path.read_text(encoding="utf-8")
    return string.Template(raw).safe_substitute(mapping)


def template_mapping(args: argparse.Namespace, package_id: str, doc_title: str = "") -> dict[str, str]:
    return {
        "package_id": package_id,
        "name": args.name,
        "category": args.category,
        "tag": args.tag,
        "tag_meaning": args.tag_meaning,
        "problem": args.problem,
        "objective": args.objective,
        "motivation": args.motivation,
        "hypothesis": args.hypothesis,
        "primary_metric": args.primary_metric,
        "baseline": args.baseline,
        "budget": args.budget,
        "no_change_boundary": args.no_change_boundary,
        "source_path": args.source_path,
        "artifact_root": args.artifact_root,
        "next_action": args.next_action,
        "last_updated": args.last_updated,
        "doc_title": doc_title or "Source document",
    }


def append_inventory(root: Path, package_id: str, args: argparse.Namespace, pages: list[str]) -> bool:
    data_path = root / "data" / "research-packages.js"
    if not data_path.exists():
        raise FileNotFoundError(f"Missing {data_path}. Set up the dashboard first.")
    text = data_path.read_text(encoding="utf-8")
    if f'id: "{package_id}"' in text or f"id: '{package_id}'" in text:
        return False

    page_slugs = [p for p in pages if p not in {"_agent"}]

    item = {
        "id": package_id,
        "name": args.name,
        "category": args.category,
        "tag": args.tag,
        "tagMeaning": args.tag_meaning,
        "sourcePath": args.source_path,
        "runtime": args.artifact_root,
        "detailPath": f"packages/{package_id}/",
        "problem": args.problem,
        "objective": args.objective,
        "motivation": args.motivation,
        "hypothesis": args.hypothesis,
        "noChangeBoundary": args.no_change_boundary,
        "status": args.status,
        "contributionSpineFlag": args.contribution_spine_flag,
        "direction": args.direction,
        "activeGate": args.active_gate,
        "primaryMetricVsGate": args.primary_metric_vs_gate,
        "lastDecision": args.last_decision,
        "lastDecisionEvidencePath": args.last_decision_evidence_path,
        "nextRoute": args.next_route,
        "currentBlocker": args.current_blocker,
        "lastAction": args.last_action,
        "openRuns": args.open_runs,
        "lastUpdated": args.last_updated,
        "pages": page_slugs,
    }
    rendered = js_object(item)

    compact_empty = "window.RESEARCH_PACKAGES = [];"
    if compact_empty in text:
        text = text.replace(compact_empty, "window.RESEARCH_PACKAGES = [\n  " + rendered.replace("\n", "\n  ") + ",\n];")
        data_path.write_text(text, encoding="utf-8")
        return True

    marker = "window.RESEARCH_PACKAGES = ["
    start = text.find(marker)
    if start == -1:
        raise ValueError("Could not find window.RESEARCH_PACKAGES array.")
    end = text.find("\n];", start)
    if end == -1:
        raise ValueError("Could not find end of window.RESEARCH_PACKAGES array.")

    insertion = "\n  " + rendered.replace("\n", "\n  ") + ","
    text = text[:end] + insertion + text[end:]
    data_path.write_text(text, encoding="utf-8")
    return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="research_html", help="research_html root")
    parser.add_argument("--id", default="", help="package id, default is date plus slugified name")
    parser.add_argument("--name", required=True)
    parser.add_argument("--category", required=True, choices=sorted(CATEGORIES))
    parser.add_argument("--tag", required=True)
    parser.add_argument("--tag-meaning", required=True, dest="tag_meaning")
    parser.add_argument("--problem", required=True)
    parser.add_argument("--objective", required=True)
    parser.add_argument("--motivation", required=True)
    parser.add_argument("--hypothesis", default="", help="required for non-brainstorm packages; optional for brainstorm")
    parser.add_argument("--primary-metric", default="", dest="primary_metric", help="required for non-brainstorm packages; optional for brainstorm")
    parser.add_argument("--baseline", default="unmeasured")
    parser.add_argument("--budget", default="unmeasured")
    parser.add_argument("--no-change-boundary", default="unmeasured", dest="no_change_boundary")
    parser.add_argument("--source-path", default="", dest="source_path")
    parser.add_argument("--artifact-root", default="", dest="artifact_root")
    parser.add_argument("--next-action", required=True, dest="next_action")
    parser.add_argument("--scope", default="index,tracker,docs,_agent", help="comma list of stage pages or 'all'")
    # `--status` is the canonical flag (matches data/schema.js); `--workflow-state`
    # is kept as a backwards-compat alias for callers that predate the rename.
    parser.add_argument("--status", default="", dest="status",
                        help="(category, status) state from research_html/data/schema.js")
    parser.add_argument("--workflow-state", default="", dest="status_legacy",
                        help="deprecated alias for --status; --status wins if both are passed")
    parser.add_argument("--contribution-spine-flag", default="", dest="contribution_spine_flag",
                        help="id from RESEARCH_CONTRIBUTION_SPINE in schema.js (e.g. multi-view-encoder)")
    parser.add_argument("--direction", default="", dest="direction",
                        help="one-sentence research direction (required for brainstorm packages)")
    parser.add_argument("--active-gate", default="", dest="active_gate")
    parser.add_argument("--primary-metric-vs-gate", default="", dest="primary_metric_vs_gate")
    parser.add_argument("--last-decision", default="", dest="last_decision")
    parser.add_argument("--last-decision-evidence-path", default="", dest="last_decision_evidence_path")
    parser.add_argument("--next-route", default="", dest="next_route")
    parser.add_argument("--current-blocker", default="", dest="current_blocker")
    parser.add_argument("--last-action", default="", dest="last_action")
    parser.add_argument("--open-runs", default="", dest="open_runs")
    parser.add_argument("--last-updated", default=dt.date.today().isoformat(), dest="last_updated")
    parser.add_argument("--force", action="store_true", help="overwrite existing package html files")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    # Resolve the legacy --workflow-state alias.
    if not args.status and getattr(args, "status_legacy", ""):
        args.status = args.status_legacy
    root = Path(args.root)
    package_id = args.id or default_id(args.name)
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z0-9][a-z0-9-]*", package_id):
        raise SystemExit("Package id must look like YYYY-MM-DD-slug.")
    if not args.source_path:
        args.source_path = f"research/active/{package_id}/"
    if not args.artifact_root:
        args.artifact_root = f"artifacts/research/{package_id}/"
    if args.category != "brainstorm":
        if not args.hypothesis:
            raise SystemExit("--hypothesis is required when --category is not brainstorm.")
        if not args.primary_metric:
            raise SystemExit("--primary-metric is required when --category is not brainstorm.")
    if not args.hypothesis:
        args.hypothesis = "unmeasured"
    if not args.primary_metric:
        args.primary_metric = "unmeasured"

    pages = parse_scope(args.scope, args.category)
    package_root = root / "packages" / package_id
    # Templates ship with this skill, not with the user's project tree.
    templates_dir = Path(__file__).resolve().parent.parent / "templates"
    mapping = template_mapping(args, package_id)

    written: list[Path] = []
    for slug in pages:
        template_rel, output_rel = STAGE_PAGES[slug]
        rendered = render_template(templates_dir, template_rel, mapping)
        out_path = package_root / output_rel
        if write_file(out_path, rendered, args.force):
            written.append(out_path)

    inventory_updated = append_inventory(root, package_id, args, pages)

    print(f"package_id={package_id}")
    print(f"package_root={package_root}")
    print(f"pages_scaffolded={','.join(pages)}")
    print(f"files_written={len(written)}")
    for path in written:
        print(path)
    print(f"inventory_updated={inventory_updated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
