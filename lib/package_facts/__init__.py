"""Lightweight JS and CSV fact helpers for research packages."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


RESULT_COLUMNS = [
    "row_id",
    "exp_id",
    "metric",
    "value",
    "unit",
    "split",
    "baseline",
    "verdict",
    "validity",
    "source_artifact",
    "source_mtime",
    "extractor",
    "extracted_at",
]

VALID_RESULT_VALIDITY = {"VALID", "PARTIAL", "RESULT_FAIL", "UNMEASURED", "DIAGNOSTIC_ONLY", "MISSING"}
VALID_EXPERIMENT_VERDICT = {"PASS", "FAIL", "INCONCLUSIVE", "DIAGNOSTIC", ""}


class FactError(RuntimeError):
    """Raised when package fact data is malformed."""


@dataclass(frozen=True)
class FactPaths:
    root: Path
    pkg: str
    package_data_dir: Path
    facts_js: Path
    tables_dir: Path
    extractors_dir: Path


def fact_paths(pkg: str, root: Path | str = Path(".")) -> FactPaths:
    root = Path(root)
    base = root / "research_html" / "data" / "packages"
    package_data_dir = base / pkg
    return FactPaths(
        root=root,
        pkg=pkg,
        package_data_dir=package_data_dir,
        facts_js=base / f"{pkg}.facts.js",
        tables_dir=package_data_dir / "tables",
        extractors_dir=package_data_dir / "extractors",
    )


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def facts_js_text(pkg: str, facts: dict) -> str:
    payload = json.dumps(facts, indent=2, sort_keys=True, ensure_ascii=False)
    return (
        "window.PACKAGE_FACTS = window.PACKAGE_FACTS || {};\n"
        f"window.PACKAGE_FACTS[{json.dumps(pkg)}] = {payload};\n"
    )


def write_facts_js(pkg: str, facts: dict, root: Path | str = Path(".")) -> Path:
    path = fact_paths(pkg, root=root).facts_js
    atomic_write(path, facts_js_text(pkg, facts))
    return path


def load_facts_js(pkg: str, root: Path | str = Path(".")) -> dict:
    path = fact_paths(pkg, root=root).facts_js
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    pat = re.compile(
        r"window\.PACKAGE_FACTS\[" + re.escape(json.dumps(pkg)) + r"\]\s*=\s*(\{.*\});\s*$",
        re.DOTALL,
    )
    match = pat.search(text)
    if not match:
        raise FactError(f"cannot parse package facts JS: {path}")
    return json.loads(match.group(1))


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _normalize_row(columns: list[str], row: dict) -> dict[str, str]:
    row_id = str(row.get("row_id", "")).strip()
    if not row_id:
        raise FactError("CSV fact row requires non-empty row_id")
    normalized = {col: str(row.get(col, "")) for col in columns}
    normalized["row_id"] = row_id
    return normalized


def upsert_csv_rows(path: Path, columns: list[str], rows: Iterable[dict]) -> Path:
    if "row_id" not in columns:
        raise FactError("columns must include row_id")
    existing = read_csv_rows(path)
    by_id = {str(row.get("row_id", "")): row for row in existing if row.get("row_id")}
    order = [str(row.get("row_id")) for row in existing if row.get("row_id")]
    for raw in rows:
        row = _normalize_row(columns, raw)
        if row["row_id"] not in by_id:
            order.append(row["row_id"])
        by_id[row["row_id"]] = row
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row_id in order:
            writer.writerow({col: by_id[row_id].get(col, "") for col in columns})
    os.replace(tmp, path)
    return path


def file_revision(path: Path) -> str:
    data = path.read_bytes()
    return "sha256:" + hashlib.sha256(data).hexdigest()


def source_ref(table_id: str, row_id: str) -> str:
    if not table_id or not row_id:
        raise FactError("source_ref requires table_id and row_id")
    return f"{table_id}:{row_id}"


def split_source_ref(ref: str) -> tuple[str, str]:
    table_id, sep, row_id = ref.partition(":")
    if not sep or not table_id or not row_id:
        raise FactError(f"invalid source row ref: {ref!r}")
    return table_id, row_id


def find_row_by_ref(tables_dir: Path, ref: str) -> dict[str, str]:
    table_id, row_id = split_source_ref(ref)
    table_path = tables_dir / f"{table_id}.csv"
    for row in read_csv_rows(table_path):
        if row.get("row_id") == row_id:
            return row
    raise FactError(f"source row not found: {ref}")
