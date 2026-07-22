"""Read-only projection of imported facts already stored in CURRENT roots."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any


def _source(
    package_id: str,
    relative: str,
    digest: str,
    row_id: str = "",
) -> dict[str, Any]:
    fragment = f"#{row_id}" if row_id else ""
    return {
        "kind": "TABLE_CELL" if row_id else "FILE",
        "uri": (
            f"state://package/{package_id}/legacy_fact_store/files/"
            f"{relative}{fragment}"
        ),
        "sha256": digest,
        "package_id": package_id,
        "legacy_unbound": True,
    }


def legacy_package_fact_projection(
    package: dict[str, Any],
) -> dict[str, Any]:
    """Decode an existing imported snapshot without inventing causal facts.

    This is read compatibility for CURRENT roots created before legacy import
    was retired. It does not discover or import legacy workspace data.
    """
    projected: dict[str, Any] = {
        "methodsTried": [],
        "resultGateRows": [],
        "resultBlocks": [],
        "liveChecks": [],
        "resourceAllocations": [],
        "resultSchemas": {},
        "factPages": {},
    }
    package_id = str(package.get("id") or "")
    legacy = package.get("legacy_fact_store")
    files = legacy.get("files") if isinstance(legacy, dict) else None
    if not package_id or not isinstance(files, dict):
        return projected

    for relative, raw_file in sorted(files.items(), key=lambda item: str(item[0])):
        if not isinstance(raw_file, dict):
            continue
        relative = str(relative)
        digest = str(raw_file.get("sha256") or "")
        data = raw_file.get("data")
        name = Path(relative).name.lower()

        if raw_file.get("format") == "package-facts" and isinstance(data, dict):
            pages = data.get("pages")
            schemas = data.get("resultSchemas")
            if isinstance(pages, dict):
                projected["factPages"] = copy.deepcopy(pages)
            if isinstance(schemas, dict):
                projected["resultSchemas"] = copy.deepcopy(schemas)
            elif isinstance(schemas, list):
                projected["resultSchemas"] = {
                    str(item.get("tableId") or item.get("id")): copy.deepcopy(item)
                    for item in schemas
                    if isinstance(item, dict)
                    and (item.get("tableId") or item.get("id"))
                }
            continue

        if not isinstance(data, list):
            continue
        rows = [row for row in data if isinstance(row, dict)]
        if name == "methods_tried.csv":
            for offset, raw in enumerate(rows, start=1):
                row = copy.deepcopy(raw)
                row_id = str(row.get("row_id") or f"legacy-method-{offset}")
                source = _source(package_id, relative, digest, row_id)
                row.update(
                    {
                        "id": row_id,
                        "row_id": row_id,
                        "legacy_unbound": True,
                        "source_fact": source,
                    }
                )
                row.setdefault("evidence", [source])
                row.setdefault("evidencePath", source["uri"])
                projected["methodsTried"].append(row)
        elif name == "result_gate.csv":
            for offset, raw in enumerate(rows, start=1):
                row = copy.deepcopy(raw)
                row_id = str(row.get("row_id") or f"legacy-gate-{offset}")
                source = _source(package_id, relative, digest, row_id)
                row.update(
                    {
                        "id": row_id,
                        "row_id": row_id,
                        "legacy_unbound": True,
                        "source_fact": source,
                        "evidence": [source],
                        "evidencePath": source["uri"],
                        "observed_metric": row.get("value")
                        or row.get("measured")
                        or "unmeasured",
                        "plan_gate": row.get("plan_gate")
                        or row.get("gate")
                        or row.get("metric")
                        or "unmeasured",
                    }
                )
                projected["resultGateRows"].append(row)
        elif name == "live_checks.csv":
            for offset, raw in enumerate(rows, start=1):
                row = copy.deepcopy(raw)
                row_id = str(row.get("row_id") or f"legacy-live-{offset}")
                row.update(
                    {
                        "id": row_id,
                        "row_id": row_id,
                        "legacy_unbound": True,
                        "source_fact": _source(
                            package_id,
                            relative,
                            digest,
                            row_id,
                        ),
                    }
                )
                projected["liveChecks"].append(row)
        elif name == "resource_allocation.csv":
            for offset, raw in enumerate(rows, start=1):
                row = copy.deepcopy(raw)
                row_id = str(
                    row.get("row_id") or f"legacy-allocation-{offset}"
                )
                row.update(
                    {
                        "id": row_id,
                        "row_id": row_id,
                        "legacy_unbound": True,
                        "source_fact": _source(
                            package_id,
                            relative,
                            digest,
                            row_id,
                        ),
                    }
                )
                projected["resourceAllocations"].append(row)
        elif name.startswith("result_table_") and name.endswith(".csv"):
            if not rows:
                continue
            source = _source(package_id, relative, digest)
            phase_id = str(rows[0].get("exp_id") or Path(name).stem)
            display_rows = [
                {
                    key: copy.deepcopy(value)
                    for key, value in raw.items()
                    if key
                    in {
                        "row_label",
                        "column_label",
                        "metric",
                        "value",
                        "unit",
                        "dataset",
                        "split",
                        "seed",
                        "method",
                        "baseline",
                        "variant",
                        "aggregate",
                        "n",
                        "validity",
                    }
                    and value not in (None, "")
                }
                for raw in rows
            ]
            columns = list(
                dict.fromkeys(key for row in display_rows for key in row)
            )
            projected["resultBlocks"].append(
                {
                    "id": f"legacy::{Path(name).stem}",
                    "phaseId": phase_id,
                    "title": f"{phase_id} — migrated result table",
                    "summary": "Migrated legacy table; no Run identity was inferred.",
                    "detail": source["uri"],
                    "mainTable": {
                        "columns": columns,
                        "rows": display_rows,
                    },
                    "insights": [],
                    "ablations": [],
                    "legacy_unbound": True,
                    "source_fact": source,
                }
            )
    return projected
