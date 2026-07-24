#!/usr/bin/env python3
"""Extract frozen Result tables from one comprehensive metric CSV."""

from __future__ import annotations

import argparse
import csv
import io
import json
from pathlib import Path
from typing import Any, Mapping

from lib.experiments.contracts import (
    file_evidence_ref,
    verify_evidence_ref,
    verify_run_files,
)
from lib.research_state.io import read_json, write_bytes_atomic, write_json_atomic
from lib.research_state.paths import ResearchPaths, add_research_root_argument
from lib.result_schema import (
    RESULT_MEASUREMENT_STATUSES,
    parse_result_table_csv,
    result_schema_from_context,
    result_schema_sha256,
    result_table_fieldnames,
)


EXTRACTOR_VERSION = 1
SOURCE_FIELDS = {"metric", "value", "unit", "status", "reason"}


def _run_files(
    paths: ResearchPaths,
    run_dir: Path,
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    resolved = run_dir.resolve()
    run = read_json(resolved / "run.json")
    context = read_json(resolved / "context.json")
    if not isinstance(run, dict) or not isinstance(context, dict):
        raise ValueError("run.json and context.json must be objects")
    expected = paths.run_dir(
        str(run["package_id"]),
        str(run.get("experiment_local_id") or run["experiment_id"]),
        str(run["run_id"]),
    ).resolve()
    if resolved != expected:
        raise ValueError("run directory does not match run.json identifiers")
    verify_run_files(run, context)
    return resolved, run, context


def _source_rows(source: Path) -> list[dict[str, str]]:
    with source.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        missing = sorted(SOURCE_FIELDS - fields)
        if missing:
            raise ValueError(
                f"metric source CSV is missing fields: {', '.join(missing)}"
            )
        return [dict(row) for row in reader]


def _matches(
    row: Mapping[str, str],
    selector: Mapping[str, str],
    metric: str,
) -> bool:
    return row.get("metric") == metric and all(
        str(row.get(key, "")) == expected
        for key, expected in selector.items()
    )


def _table_csv(
    table: Mapping[str, Any],
    source_rows: list[dict[str, str]],
) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=result_table_fieldnames(table),
        lineterminator="\n",
    )
    writer.writeheader()
    for schema_row in table["rows"]:
        output: dict[str, str] = {"row_id": schema_row["id"]}
        reference = schema_row.get("reference")
        for column in table["columns"]:
            if reference is not None:
                metric = column["metric"]
                citation = reference["citation"]
                if metric in reference["values"]:
                    output[column["id"]] = json.dumps(
                        reference["values"][metric]
                    )
                    output[f"{column['id']}__status"] = "REPORTED"
                    output[f"{column['id']}__reason"] = citation
                else:
                    output[column["id"]] = ""
                    output[f"{column['id']}__status"] = "NOT_REPORTED"
                    output[f"{column['id']}__reason"] = (
                        f"Not reported in {citation}"
                    )
                continue
            matches = [
                row
                for row in source_rows
                if _matches(row, schema_row["selector"], column["metric"])
            ]
            cell = f"{table['id']}/{schema_row['id']}/{column['id']}"
            if len(matches) != 1:
                raise ValueError(
                    f"{cell} expected exactly one source row, got {len(matches)}"
                )
            match = matches[0]
            if match.get("unit") != column["unit"]:
                raise ValueError(
                    f"{cell} unit mismatch: expected {column['unit']!r}, "
                    f"got {match.get('unit')!r}"
                )
            status = str(match.get("status") or "").upper()
            if status not in RESULT_MEASUREMENT_STATUSES:
                raise ValueError(f"{cell} has unknown status {status!r}")
            output[column["id"]] = str(match.get("value") or "")
            output[f"{column['id']}__status"] = status
            output[f"{column['id']}__reason"] = str(
                match.get("reason") or ""
            )
        writer.writerow(output)
    content = stream.getvalue().encode("utf-8")
    parse_result_table_csv(table, content)
    return content


def extract_result_tables(
    paths: ResearchPaths,
    run_dir: Path,
    *,
    source_csv: Path,
) -> Path:
    """Write deterministic per-table CSVs and one provenance manifest."""
    resolved_run_dir, run, context = _run_files(paths, run_dir)
    schema = result_schema_from_context(context)
    if schema is None:
        raise ValueError("run context has no frozen result_schema")
    source = source_csv.resolve()
    source_ref = file_evidence_ref(
        paths,
        run,
        source,
        selector={"role": "comprehensive-metrics"},
    )
    rows = _source_rows(source)
    output_dir = resolved_run_dir / "files" / "result-tables"
    table_entries: list[dict[str, Any]] = []
    for table in schema["tables"]:
        path = output_dir / f"{table['id']}.csv"
        content = _table_csv(table, rows)
        write_bytes_atomic(path, content)
        artifact = file_evidence_ref(
            paths,
            run,
            path,
            selector={"table_id": table["id"]},
        )
        table_entries.append(
            {
                "id": table["id"],
                "rows": len(table["rows"]),
                "artifact": artifact,
            }
        )
    manifest = {
        "schema_version": 1,
        "kind": "result-table-extraction",
        "run_id": run["run_id"],
        "package_id": run["package_id"],
        "experiment_id": run["experiment_id"],
        "result_schema_sha256": result_schema_sha256(schema),
        "extractor": {
            "module": "lib.experiments.result_tables",
            "version": EXTRACTOR_VERSION,
        },
        "source": source_ref,
        "tables": table_entries,
    }
    manifest_path = output_dir / "manifest.json"
    write_json_atomic(manifest_path, manifest)
    verify_result_table_manifest(
        paths,
        run,
        context,
        manifest_path,
    )
    return manifest_path


def verify_result_table_manifest(
    paths: ResearchPaths,
    run: dict[str, Any],
    context: dict[str, Any],
    manifest_path: Path,
) -> dict[str, Any]:
    """Verify schema, source, table bytes, and every expected table identity."""
    schema = result_schema_from_context(context)
    if schema is None:
        raise ValueError("run context has no frozen result_schema")
    manifest = read_json(manifest_path)
    if not isinstance(manifest, dict):
        raise ValueError("result table manifest must be an object")
    identities = {
        "run_id": run.get("run_id"),
        "package_id": run.get("package_id"),
        "experiment_id": run.get("experiment_id"),
    }
    if (
        manifest.get("schema_version") != 1
        or manifest.get("kind") != "result-table-extraction"
        or any(manifest.get(key) != value for key, value in identities.items())
    ):
        raise ValueError("result table manifest identity is invalid")
    digest = result_schema_sha256(schema)
    if manifest.get("result_schema_sha256") != digest:
        raise ValueError("result table manifest does not match frozen result_schema")
    extractor = manifest.get("extractor")
    if extractor != {
        "module": "lib.experiments.result_tables",
        "version": EXTRACTOR_VERSION,
    }:
        raise ValueError("result table manifest extractor is unsupported")
    source_ref = manifest.get("source")
    if not isinstance(source_ref, dict):
        raise ValueError("result table manifest source must be an EvidenceRef")
    verify_evidence_ref(paths, source_ref, run=run)

    entries = manifest.get("tables")
    if not isinstance(entries, list):
        raise ValueError("result table manifest tables must be a list")
    expected_ids = [table["id"] for table in schema["tables"]]
    actual_ids = [
        entry.get("id") if isinstance(entry, dict) else None
        for entry in entries
    ]
    if actual_ids != expected_ids:
        raise ValueError(
            "result table manifest must contain every frozen table in order"
        )
    artifacts: list[dict[str, Any]] = []
    for table, entry in zip(schema["tables"], entries, strict=True):
        if not isinstance(entry, dict) or set(entry) != {
            "id",
            "rows",
            "artifact",
        }:
            raise ValueError(
                f"result table manifest entry is invalid: {table['id']}"
            )
        if entry["rows"] != len(table["rows"]):
            raise ValueError(
                f"result table manifest row count is invalid: {table['id']}"
            )
        artifact = entry["artifact"]
        if not isinstance(artifact, dict):
            raise ValueError(
                f"result table artifact must be an EvidenceRef: {table['id']}"
            )
        if artifact.get("selector") != {"table_id": table["id"]}:
            raise ValueError(
                f"result table artifact selector is invalid: {table['id']}"
            )
        path = verify_evidence_ref(paths, artifact, run=run)
        if path is None:
            raise ValueError(f"result table artifact must be local: {table['id']}")
        parse_result_table_csv(table, path.read_bytes())
        artifacts.append(artifact)
    manifest_ref = file_evidence_ref(
        paths,
        run,
        manifest_path,
        selector={"role": "result-table-manifest"},
    )
    return {
        "result_schema_sha256": digest,
        "result_table_manifest_uri": manifest_ref["uri"],
        "result_tables": [
            {"id": table["id"], "uri": artifact["uri"]}
            for table, artifact in zip(schema["tables"], artifacts, strict=True)
        ],
        "evidence": [source_ref, *artifacts, manifest_ref],
    }


def verify_finalized_result_tables(
    paths: ResearchPaths,
    run: dict[str, Any],
    result: Mapping[str, Any],
) -> dict[str, Path]:
    """Verify one finalized Result's manifest and return table artifact paths."""
    context_path = paths.root / str(run.get("context_json") or "")
    context = read_json(context_path)
    if not isinstance(context, dict):
        raise ValueError("run context_json is missing or invalid")
    evidence = result.get("evidence")
    if not isinstance(evidence, list):
        raise ValueError("result evidence must be a list")
    refs = {
        str(ref.get("uri")): ref
        for ref in evidence
        if isinstance(ref, dict) and ref.get("uri")
    }
    manifest_uri = result.get("result_table_manifest_uri")
    if not isinstance(manifest_uri, str) or manifest_uri not in refs:
        raise ValueError("result table manifest is not hash-bound evidence")
    manifest_path = verify_evidence_ref(paths, refs[manifest_uri], run=run)
    if manifest_path is None:
        raise ValueError("result table manifest must be local")
    verified = verify_result_table_manifest(
        paths,
        run,
        context,
        manifest_path,
    )
    for field in (
        "result_schema_sha256",
        "result_table_manifest_uri",
        "result_tables",
    ):
        if result.get(field) != verified[field]:
            raise ValueError(f"result {field} does not match verified manifest")
    paths_by_id: dict[str, Path] = {}
    for table in verified["result_tables"]:
        ref = refs.get(table["uri"])
        if ref is None:
            raise ValueError(
                f"result table is not hash-bound evidence: {table['id']}"
            )
        path = verify_evidence_ref(paths, ref, run=run)
        if path is None:
            raise ValueError(f"result table must be local: {table['id']}")
        paths_by_id[table["id"]] = path
    return paths_by_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default=".")
    add_research_root_argument(parser)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--source", required=True)
    args = parser.parse_args(argv)
    paths = ResearchPaths.resolve(
        workspace=args.workspace,
        research_root=args.research_root,
    )
    manifest = extract_result_tables(
        paths,
        Path(args.run_dir),
        source_csv=Path(args.source),
    )
    print(
        json.dumps(
            {"ok": True, "manifest": str(manifest)},
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
