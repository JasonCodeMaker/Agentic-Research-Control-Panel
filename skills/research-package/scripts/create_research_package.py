#!/usr/bin/env python3
"""Create an initial research package and add it to research-packages.js."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import string
import sys
from pathlib import Path

PIPELINE_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PIPELINE_ROOT))

from lib import package_facts  # noqa: E402
import render_package_projection  # noqa: E402
from task_spine import derive_task_blocks


# Brainstorm is no longer a package category (pre-package ideas live on the
# dashboard brainstorm lane). brainstorm.html survives only as a per-package
# provenance sub-page, written at conversion by create_from_scope.
CATEGORIES = {"in-progress", "success", "fail"}

# Stage pages and their template paths (relative to research-package/templates/)
# and emitted output paths (relative to packages/<id>/).
STAGE_PAGES: dict[str, tuple[str, str]] = {
    "index": ("index.html", "index.html"),
    "plan": ("plan.html", "plan.html"),
    "implementation": ("implementation.html", "implementation.html"),
    "results": ("results.html", "results.html"),
    "analysis": ("analysis.html", "analysis.html"),
    "tracker": ("tracker.html", "tracker.html"),
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
        "next_action": args.next_action or "unmeasured",
        "last_updated": args.last_updated,
        "doc_title": doc_title or "Source document",
    }


def parse_experiments_json(raw: str) -> list[dict]:
    if not raw:
        return []
    parsed = json.loads(raw)
    if not isinstance(parsed, list):
        raise SystemExit("--experiments must be a JSON list.")
    return parsed


def exp_id(exp: dict) -> str:
    return str(exp.get("id") or "").strip()


def exp_measures(exp: dict) -> bool:
    return bool(exp.get("measures", True))


def now_iso() -> str:
    return dt.datetime.now(dt.UTC).astimezone().isoformat(timespec="seconds")


def placeholder_result_row(exp: dict, args: argparse.Namespace, row_id: str) -> dict[str, str]:
    source_artifact = str(exp.get("output") or args.artifact_root or "")
    return {
        "row_id": row_id,
        "exp_id": exp_id(exp),
        "metric": str(exp.get("gate") or args.primary_metric or "unmeasured"),
        "value": "unmeasured",
        "unit": "",
        "split": "",
        "baseline": str(args.baseline or "unmeasured"),
        "verdict": "INCONCLUSIVE",
        "validity": "UNMEASURED",
        "source_artifact": source_artifact,
        "source_mtime": "",
        "extractor": "",
        "extracted_at": "",
    }


def _schema_key(value: object, fallback: str) -> str:
    text = str(value or "").strip().lower()
    key = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return key or fallback


def _schema_items(raw_items: object, fallback_key: str, fallback_label: str) -> list[dict[str, str]]:
    if not isinstance(raw_items, list) or not raw_items:
        return [{"key": fallback_key, "label": fallback_label}]
    items = []
    for index, item in enumerate(raw_items):
        if isinstance(item, dict):
            label = str(item.get("label") or item.get("name") or item.get("key") or f"Item {index + 1}")
            key = _schema_key(item.get("key") or label, f"item_{index + 1}")
            normalized = {k: str(v) for k, v in item.items() if isinstance(v, (str, int, float, bool))}
            normalized["key"] = key
            normalized["label"] = label
        else:
            label = str(item)
            normalized = {"key": _schema_key(label, f"item_{index + 1}"), "label": label}
        items.append(normalized)
    return items


def normalize_result_schema(exp: dict, args: argparse.Namespace) -> dict:
    eid = exp_id(exp)
    raw = exp.get("resultSchema") if isinstance(exp.get("resultSchema"), dict) else {}
    schema_id = str(raw.get("id") or f"result_schema_{eid}")
    table_id = str(raw.get("tableId") or f"result_table_{eid}")
    metric_label = str(exp.get("gate") or args.primary_metric or "Metric")
    row_axis = raw.get("rowAxis") if isinstance(raw.get("rowAxis"), dict) else {}
    normalized_row_axis = {
        "key": str(row_axis.get("key") or "subject"),
        "label": str(row_axis.get("label") or "Subject"),
        "plannedRows": _schema_items(row_axis.get("plannedRows"), "planned", "Planned"),
    }
    columns = _schema_items(raw.get("columns"), _schema_key(metric_label, "metric"), metric_label)
    normalized_columns = []
    for column in columns:
        col = dict(column)
        col.setdefault("metric", col["label"])
        normalized_columns.append(col)
    return {
        "id": schema_id,
        "expId": eid,
        "tableId": table_id,
        "kind": str(raw.get("kind") or "metric_table"),
        "decisionQuestion": str(raw.get("decisionQuestion") or exp.get("purpose") or metric_label),
        "rowAxis": normalized_row_axis,
        "columns": normalized_columns,
        "primaryGate": raw.get("primaryGate") if isinstance(raw.get("primaryGate"), dict) else {},
        "requiredProvenance": raw.get("requiredProvenance") if isinstance(raw.get("requiredProvenance"), list) else ["source_artifact"],
        "designedBy": str(raw.get("designedBy") or "agent"),
        "schemaVersion": int(raw.get("schemaVersion") or 1),
    }


def materialize_result_schemas(experiments: list[dict], args: argparse.Namespace) -> tuple[list[dict], dict[str, dict]]:
    materialized: list[dict] = []
    schemas: dict[str, dict] = {}
    for exp in experiments:
        item = dict(exp)
        if exp_id(item) and exp_measures(item):
            schema = normalize_result_schema(item, args)
            item["resultSchemaRef"] = schema["id"]
            item.pop("resultSchema", None)
            schemas[schema["id"]] = schema
        materialized.append(item)
    return materialized, schemas


def placeholder_cell_rows(exp: dict, schema: dict, args: argparse.Namespace) -> list[dict[str, str]]:
    rows = []
    source_artifact = str(exp.get("output") or args.artifact_root or "")
    for row_item in schema["rowAxis"]["plannedRows"]:
        for column in schema["columns"]:
            row_key = str(row_item["key"])
            column_key = str(column["key"])
            rows.append({
                "row_id": f"{exp_id(exp)}:{row_key}:{column_key}",
                "exp_id": exp_id(exp),
                "table_id": str(schema["tableId"]),
                "row_key": row_key,
                "row_label": str(row_item["label"]),
                "column_key": column_key,
                "column_label": str(column["label"]),
                "metric": str(column.get("metric") or column["label"]),
                "value": "unmeasured",
                "unit": str(column.get("unit") or ""),
                "dataset": str(column.get("dataset") or ""),
                "split": str(column.get("split") or ""),
                "seed": "",
                "method": str(row_item.get("method") or ""),
                "baseline": str(row_item.get("baseline") or args.baseline or ""),
                "variant": str(row_item.get("variant") or ""),
                "aggregate": str(column.get("aggregate") or ""),
                "n": "",
                "validity": "UNMEASURED",
                "source_artifact": source_artifact,
                "source_mtime": "",
                "extractor": "",
                "extracted_at": "",
            })
    return rows


def initialize_fact_layer(
    repo_root: Path,
    package_id: str,
    args: argparse.Namespace,
    experiments: list[dict],
    result_schemas: dict[str, dict],
) -> list[Path]:
    measurable = [exp for exp in experiments if exp_id(exp) and exp_measures(exp)]
    if not experiments:
        return []

    paths = package_facts.fact_paths(package_id, root=repo_root)
    result_tables = [
        str(result_schemas[str(exp.get("resultSchemaRef"))]["tableId"])
        for exp in measurable
    ]
    package_facts.write_facts_js(
        package_id,
        {
            "schemaVersion": 1,
            "createdByScaffold": True,
            "packageId": package_id,
            "createdAt": now_iso(),
            "experiments": [exp_id(exp) for exp in experiments if exp_id(exp)],
            "resultTables": result_tables,
            "resultSchemas": result_schemas,
            "projections": {"pages": {}},
        },
        root=repo_root,
    )

    touched: list[Path] = [paths.facts_js]
    if measurable:
        gate_rows = [
            placeholder_result_row(exp, args, f"{exp_id(exp)}_gate")
            for exp in measurable
        ]
        package_facts.upsert_csv_rows(paths.tables_dir / "result_gate.csv", package_facts.RESULT_COLUMNS, gate_rows)
        touched.append(paths.tables_dir / "result_gate.csv")
        for exp in measurable:
            schema = result_schemas[str(exp.get("resultSchemaRef"))]
            table_path = paths.tables_dir / f"{schema['tableId']}.csv"
            package_facts.upsert_csv_rows(
                table_path,
                package_facts.RESULT_CELL_COLUMNS,
                placeholder_cell_rows(exp, schema, args),
            )
            touched.append(table_path)

    package_facts.upsert_csv_rows(paths.tables_dir / "live_checks.csv", package_facts.LIVE_CHECK_COLUMNS, [])
    package_facts.upsert_csv_rows(paths.tables_dir / "resource_allocation.csv", package_facts.RESOURCE_ALLOCATION_COLUMNS, [])
    package_facts.upsert_csv_rows(paths.tables_dir / "methods_tried.csv", package_facts.METHODS_TRIED_COLUMNS, [])
    touched.extend([
        paths.tables_dir / "live_checks.csv",
        paths.tables_dir / "resource_allocation.csv",
        paths.tables_dir / "methods_tried.csv",
    ])

    if measurable:
        render_package_projection.render_results(package_id, repo_root)
        touched.extend([repo_root / "research_html" / "packages" / package_id / "results.html", paths.facts_js])
    render_package_projection.render_tracker(package_id, repo_root)
    touched.extend([repo_root / "research_html" / "packages" / package_id / "tracker.html", paths.facts_js])
    return touched


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
    if args.experiments_json:
        item["experiments"] = parse_experiments_json(args.experiments_json)
    if args.source_direction:
        item["sourceDirection"] = args.source_direction
        item["sourceVersion"] = args.source_version
        item["sourceChange"] = args.source_change
        if args.source_tasks:
            item["sourceTasks"] = json.loads(args.source_tasks)
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
    parser.add_argument("--next-action", default="", dest="next_action",
                        help="one-line headline for the chosen-route panel on tracker.html#chosen-route")
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
    parser.add_argument("--experiments-json", "--experiments", default="", dest="experiments_json",
                        help="JSON list of initial experiments[] rows to add to inventory")
    parser.add_argument("--source-direction", default="", dest="source_direction",
                        help="SSOT direction node id that produced this package")
    parser.add_argument("--source-version", default="", dest="source_version",
                        help="SSOT scope version that produced this package")
    parser.add_argument("--source-change", default="", dest="source_change",
                        help="SSOT transition txn id that produced this package")
    parser.add_argument("--source-tasks", default="", dest="source_tasks",
                        help="JSON list of accepted SSOT task node ids")
    parser.add_argument("--force", action="store_true", help="overwrite existing package html files")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
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
    if not args.hypothesis:
        raise SystemExit("--hypothesis is required.")
    if not args.primary_metric:
        raise SystemExit("--primary-metric is required.")
    if not args.primary_metric_vs_gate:
        args.primary_metric_vs_gate = args.primary_metric

    pages = parse_scope(args.scope, args.category)
    experiments = parse_experiments_json(args.experiments_json)
    experiments, result_schemas = materialize_result_schemas(experiments, args)
    if experiments:
        args.experiments_json = json.dumps(experiments, ensure_ascii=False)
    if any(exp_id(exp) and exp_measures(exp) for exp in experiments) and "results" not in pages:
        pages.append("results")
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
    derived = []
    if experiments:
        derived = derive_task_blocks(package_root, experiments)
    fact_files = initialize_fact_layer(root.parent, package_id, args, experiments, result_schemas)

    print(f"package_id={package_id}")
    print(f"package_root={package_root}")
    print(f"pages_scaffolded={','.join(pages)}")
    print(f"files_written={len(written)}")
    for path in written:
        print(path)
    if derived:
        print(f"derived_task_blocks={len(derived)}")
        for path in derived:
            print(path)
    if fact_files:
        print(f"fact_files={len(fact_files)}")
        for path in fact_files:
            print(path)
    print(f"inventory_updated={inventory_updated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
