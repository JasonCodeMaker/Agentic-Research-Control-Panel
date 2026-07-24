"""Validation and CSV decoding for schema-backed Result tables."""

from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import math
import re
from typing import Any, Mapping
from urllib.parse import urlparse


RESULT_SCHEMA_VERSION = 1
RESULT_TABLE_TYPES = {"main", "ablation"}
RESULT_MEASUREMENT_STATUSES = {"MEASURED", "UNDEFINED", "FAILED"}
RESULT_REFERENCE_STATUSES = {"REPORTED", "NOT_REPORTED"}
RESULT_CELL_STATUSES = RESULT_MEASUREMENT_STATUSES | RESULT_REFERENCE_STATUSES
_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]*")


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _identifier(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not _ID_PATTERN.fullmatch(value):
        raise ValueError(f"{label} must match {_ID_PATTERN.pattern!r}")
    return value


def validate_result_schema(value: Any) -> dict[str, Any]:
    """Return one normalized Result schema or raise on ambiguity."""
    if not isinstance(value, Mapping):
        raise ValueError("resultSchema must be an object")
    if set(value) != {"version", "tables"}:
        raise ValueError("resultSchema must contain only version and tables")
    if value.get("version") != RESULT_SCHEMA_VERSION:
        raise ValueError(
            f"resultSchema version must be {RESULT_SCHEMA_VERSION}"
        )
    raw_tables = value.get("tables")
    if not isinstance(raw_tables, list) or not raw_tables:
        raise ValueError("resultSchema tables must be a non-empty list")

    tables: list[dict[str, Any]] = []
    table_ids: set[str] = set()
    for table_index, raw_table in enumerate(raw_tables):
        if not isinstance(raw_table, Mapping):
            raise ValueError(f"resultSchema table {table_index} must be an object")
        if set(raw_table) != {
            "id",
            "type",
            "title",
            "rowLabel",
            "rows",
            "columns",
        }:
            raise ValueError(
                f"resultSchema table {table_index} has unknown or missing fields"
            )
        table_id = _identifier(
            raw_table.get("id"),
            label=f"resultSchema table {table_index} id",
        )
        if table_id in table_ids:
            raise ValueError(f"duplicate resultSchema table id: {table_id}")
        table_ids.add(table_id)
        table_type = raw_table.get("type")
        if table_type not in RESULT_TABLE_TYPES:
            raise ValueError(
                f"resultSchema table {table_id} type must be main or ablation"
            )
        title = raw_table.get("title")
        row_label = raw_table.get("rowLabel")
        if not isinstance(title, str) or not title.strip():
            raise ValueError(f"resultSchema table {table_id} needs a title")
        if not isinstance(row_label, str) or not row_label.strip():
            raise ValueError(f"resultSchema table {table_id} needs rowLabel")

        raw_rows = raw_table.get("rows")
        if not isinstance(raw_rows, list) or not raw_rows:
            raise ValueError(
                f"resultSchema table {table_id} rows must be non-empty"
            )
        rows: list[dict[str, Any]] = []
        row_ids: set[str] = set()
        selectors: set[str] = set()
        for row_index, raw_row in enumerate(raw_rows):
            if not isinstance(raw_row, Mapping):
                raise ValueError(
                    f"resultSchema table {table_id} row {row_index} is invalid"
                )
            is_reference = set(raw_row) == {"id", "label", "reference"}
            if not is_reference and set(raw_row) != {
                "id",
                "label",
                "selector",
            }:
                raise ValueError(
                    f"resultSchema table {table_id} row {row_index} is invalid"
                )
            row_id = _identifier(
                raw_row.get("id"),
                label=f"resultSchema table {table_id} row id",
            )
            if row_id in row_ids:
                raise ValueError(
                    f"duplicate row id in resultSchema table {table_id}: {row_id}"
                )
            row_ids.add(row_id)
            label = raw_row.get("label")
            if not isinstance(label, str) or not label.strip():
                raise ValueError(
                    f"resultSchema table {table_id} row {row_id} needs a label"
                )
            if is_reference:
                raw_reference = raw_row.get("reference")
                if not isinstance(raw_reference, Mapping) or set(
                    raw_reference
                ) != {"citation", "url", "values"}:
                    raise ValueError(
                        f"resultSchema table {table_id} row {row_id} "
                        "reference is invalid"
                    )
                citation = raw_reference.get("citation")
                url = raw_reference.get("url")
                values = raw_reference.get("values")
                parsed_url = urlparse(url) if isinstance(url, str) else None
                if not isinstance(citation, str) or not citation.strip():
                    raise ValueError(
                        f"resultSchema table {table_id} row {row_id} "
                        "reference needs citation"
                    )
                if (
                    parsed_url is None
                    or parsed_url.scheme != "https"
                    or not parsed_url.netloc
                ):
                    raise ValueError(
                        f"resultSchema table {table_id} row {row_id} "
                        "reference needs an https URL"
                    )
                if not isinstance(values, Mapping) or not values:
                    raise ValueError(
                        f"resultSchema table {table_id} row {row_id} "
                        "reference needs values"
                    )
                normalized_values: dict[str, int | float] = {}
                for metric, value in values.items():
                    if (
                        not isinstance(metric, str)
                        or not metric.strip()
                        or isinstance(value, bool)
                        or not isinstance(value, (int, float))
                        or not math.isfinite(float(value))
                    ):
                        raise ValueError(
                            f"resultSchema table {table_id} row {row_id} "
                            "reference values must map metrics to finite numbers"
                        )
                    normalized_values[metric.strip()] = value
                rows.append(
                    {
                        "id": row_id,
                        "label": label.strip(),
                        "reference": {
                            "citation": citation.strip(),
                            "url": url,
                            "values": normalized_values,
                        },
                    }
                )
                continue

            selector = raw_row.get("selector")
            if not isinstance(selector, Mapping) or not selector:
                raise ValueError(
                    f"resultSchema table {table_id} row {row_id} needs selector"
                )
            normalized_selector: dict[str, str] = {}
            for key, selected in selector.items():
                if (
                    not isinstance(key, str)
                    or not key.strip()
                    or isinstance(selected, (dict, list))
                    or selected is None
                ):
                    raise ValueError(
                        f"resultSchema table {table_id} row {row_id} "
                        "selector must contain scalar values"
                    )
                normalized_selector[key.strip()] = str(selected)
            selector_key = _canonical_json(normalized_selector)
            if selector_key in selectors:
                raise ValueError(
                    f"duplicate selector in resultSchema table {table_id}"
                )
            selectors.add(selector_key)
            rows.append(
                {
                    "id": row_id,
                    "label": label.strip(),
                    "selector": normalized_selector,
                }
            )

        raw_columns = raw_table.get("columns")
        if not isinstance(raw_columns, list) or not raw_columns:
            raise ValueError(
                f"resultSchema table {table_id} columns must be non-empty"
            )
        columns: list[dict[str, Any]] = []
        column_ids: set[str] = set()
        metrics: set[str] = set()
        for column_index, raw_column in enumerate(raw_columns):
            if not isinstance(raw_column, Mapping):
                raise ValueError(
                    f"resultSchema table {table_id} column {column_index} "
                    "must be an object"
                )
            if not {"id", "label", "metric", "unit"}.issubset(raw_column) or (
                set(raw_column)
                - {"id", "label", "metric", "unit", "nullable"}
            ):
                raise ValueError(
                    f"resultSchema table {table_id} column {column_index} "
                    "has unknown or missing fields"
                )
            column_id = _identifier(
                raw_column.get("id"),
                label=f"resultSchema table {table_id} column id",
            )
            if column_id in column_ids:
                raise ValueError(
                    f"duplicate column id in resultSchema table {table_id}: "
                    f"{column_id}"
                )
            column_ids.add(column_id)
            label = raw_column.get("label")
            metric = raw_column.get("metric")
            unit = raw_column.get("unit")
            if not isinstance(label, str) or not label.strip():
                raise ValueError(
                    f"resultSchema table {table_id} column {column_id} "
                    "needs a label"
                )
            if not isinstance(metric, str) or not metric.strip():
                raise ValueError(
                    f"resultSchema table {table_id} column {column_id} "
                    "needs a metric"
                )
            if metric in metrics:
                raise ValueError(
                    f"duplicate metric in resultSchema table {table_id}: {metric}"
                )
            metrics.add(metric)
            if not isinstance(unit, str) or not unit.strip():
                raise ValueError(
                    f"resultSchema table {table_id} column {column_id} "
                    "needs a unit"
                )
            nullable = raw_column.get("nullable", False)
            if not isinstance(nullable, bool):
                raise ValueError(
                    f"resultSchema table {table_id} column {column_id} "
                    "nullable must be boolean"
                )
            columns.append(
                {
                    "id": column_id,
                    "label": label.strip(),
                    "metric": metric.strip(),
                    "unit": unit.strip(),
                    "nullable": nullable,
                }
            )
        for row in rows:
            reference = row.get("reference")
            if reference is None:
                continue
            unknown = set(reference["values"]) - metrics
            if unknown:
                raise ValueError(
                    f"resultSchema table {table_id} row {row['id']} "
                    f"references unknown metrics: {', '.join(sorted(unknown))}"
                )
        tables.append(
            {
                "id": table_id,
                "type": table_type,
                "title": title.strip(),
                "rowLabel": row_label.strip(),
                "rows": rows,
                "columns": columns,
            }
        )
    return {"version": RESULT_SCHEMA_VERSION, "tables": tables}


def result_schema_sha256(value: Any) -> str:
    schema = validate_result_schema(value)
    return hashlib.sha256(_canonical_json(schema).encode("utf-8")).hexdigest()


def result_schema_from_context(
    context: Mapping[str, Any],
) -> dict[str, Any] | None:
    raw = context.get("result_schema")
    if raw is None:
        if context.get("result_schema_sha256") is not None:
            raise ValueError(
                "run context has result_schema_sha256 without result_schema"
            )
        return None
    schema = validate_result_schema(raw)
    if context.get("result_schema_sha256") != result_schema_sha256(schema):
        raise ValueError("run context result_schema does not match its sha256")
    return schema


def result_table_fieldnames(table: Mapping[str, Any]) -> list[str]:
    fields = ["row_id"]
    for column in table["columns"]:
        column_id = str(column["id"])
        fields.extend(
            [
                column_id,
                f"{column_id}__status",
                f"{column_id}__reason",
            ]
        )
    return fields


def _metric_value(
    raw: str,
    *,
    status: str,
    nullable: bool,
    reason: str,
    cell: str,
) -> int | float | None:
    if status not in RESULT_CELL_STATUSES:
        raise ValueError(f"{cell} has unknown status {status!r}")
    stripped = raw.strip()
    if status in {"MEASURED", "REPORTED"}:
        try:
            value = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{cell} numeric value must be numeric") from exc
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
        ):
            raise ValueError(f"{cell} numeric value must be finite")
        if status == "REPORTED" and not reason.strip():
            raise ValueError(f"{cell} reported value needs a citation")
        return value
    if status == "UNDEFINED" and not nullable:
        raise ValueError(f"{cell} is not nullable but has status {status}")
    if stripped not in {"", "null"}:
        raise ValueError(f"{cell} {status.lower()} value must be null")
    if not reason.strip():
        raise ValueError(f"{cell} {status.lower()} value needs a reason")
    return None


def parse_result_table_csv(
    table: Mapping[str, Any],
    content: str | bytes,
) -> list[dict[str, Any]]:
    """Decode one derived table CSV and enforce the frozen row/column shape."""
    text = content.decode("utf-8") if isinstance(content, bytes) else content
    reader = csv.DictReader(io.StringIO(text))
    expected_fields = result_table_fieldnames(table)
    if reader.fieldnames != expected_fields:
        raise ValueError(
            f"result table {table['id']} header mismatch: "
            f"expected {expected_fields}, got {reader.fieldnames}"
        )
    source_rows = list(reader)
    expected_rows = table["rows"]
    if len(source_rows) != len(expected_rows):
        raise ValueError(
            f"result table {table['id']} row count mismatch: "
            f"expected {len(expected_rows)}, got {len(source_rows)}"
        )
    decoded: list[dict[str, Any]] = []
    seen: set[str] = set()
    for expected, source in zip(expected_rows, source_rows, strict=True):
        row_id = str(source.get("row_id") or "")
        if row_id != expected["id"] or row_id in seen:
            raise ValueError(
                f"result table {table['id']} row order/id mismatch: {row_id!r}"
            )
        seen.add(row_id)
        row: dict[str, Any] = {
            "row_id": row_id,
            "row": expected["label"],
            "_cells": {},
        }
        if "reference" in expected:
            row["_reference"] = copy.deepcopy(expected["reference"])
        for column in table["columns"]:
            column_id = column["id"]
            status = str(source[f"{column_id}__status"] or "").upper()
            reason = str(source[f"{column_id}__reason"] or "")
            cell = f"{table['id']}/{row_id}/{column_id}"
            allowed_statuses = (
                RESULT_REFERENCE_STATUSES
                if "reference" in expected
                else RESULT_MEASUREMENT_STATUSES
            )
            if status not in allowed_statuses:
                raise ValueError(
                    f"{cell} has status {status!r} for the wrong row type"
                )
            row[column_id] = _metric_value(
                str(source[column_id] or ""),
                status=status,
                nullable=bool(column["nullable"]),
                reason=reason,
                cell=cell,
            )
            row["_cells"][column_id] = {
                "status": status,
                "reason": reason,
            }
        decoded.append(row)
    return decoded


def planned_result_table(table: Mapping[str, Any]) -> dict[str, Any]:
    """Project an empty but fully shaped table before measurements exist."""
    columns = [{"key": "row", "label": table["rowLabel"]}]
    columns.extend(
        {"key": column["id"], "label": column["label"]}
        for column in table["columns"]
    )
    rows = []
    has_reference = False
    for schema_row in table["rows"]:
        row: dict[str, Any] = {
            "row_id": schema_row["id"],
            "row": schema_row["label"],
            "_cells": {},
        }
        reference = schema_row.get("reference")
        if reference is not None:
            has_reference = True
            row["_reference"] = copy.deepcopy(reference)
        for column in table["columns"]:
            metric = column["metric"]
            if reference is not None and metric in reference["values"]:
                row[column["id"]] = reference["values"][metric]
                row["_cells"][column["id"]] = {
                    "status": "REPORTED",
                    "reason": reference["citation"],
                }
            elif reference is not None:
                row[column["id"]] = None
                row["_cells"][column["id"]] = {
                    "status": "NOT_REPORTED",
                    "reason": f"Not reported in {reference['citation']}",
                }
            else:
                row[column["id"]] = None
                row["_cells"][column["id"]] = {
                    "status": "PENDING",
                    "reason": "Awaiting evaluation",
                }
        rows.append(row)
    projected = {
        "id": table["id"],
        "type": table["type"],
        "title": table["title"],
        "state": "planned",
        "columns": columns,
        "rows": rows,
    }
    if has_reference:
        projected["stateReason"] = (
            "Reported reference values are shown; local cells await evaluation."
        )
    return projected


def project_verified_result_table(
    table: Mapping[str, Any],
    rows: list[dict[str, Any]],
    *,
    run_id: str,
    source_uri: str,
    source_sha256: str,
) -> dict[str, Any]:
    projected = planned_result_table(table)
    projected.update(
        {
            "state": "verified",
            "rows": copy.deepcopy(rows),
            "runId": run_id,
            "sourceUri": source_uri,
            "sourceSha256": source_sha256,
        }
    )
    return projected
