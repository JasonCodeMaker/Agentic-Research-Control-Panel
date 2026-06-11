# Whole Pipeline Fact System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Phase 1 of the lightweight fact system: package result tables are stored as CSV facts, content metadata is stored as JS facts, `results.html` is rendered from those facts, and lint rejects stale or hand-written result projections.

**Architecture:** Add a small stdlib-only `lib/package_facts` module for JS/CSV fact paths, CSV upserts, source row references, revision hashes, and HTML source-marker checks. Add a generic extractor CLI that reads real JSON artifacts into result CSVs, a renderer CLI that projects CSV facts into `results.html`, and a `fact-alignment` lint mode wired through `research-op --op check`. Existing packages are grandfathered unless they contain fact-backed projection markers.

**Tech Stack:** Python 3.13 stdlib, CSV, JSON, existing `research-op`, existing `learnings_lint.py`, existing pytest suite, browser-readable `window.PACKAGE_FACTS` JS files.

---

## Scope Check

This plan implements Phase 1 only: result table facts and `results.html` projection. It does not migrate tracker ledgers, `methodsTried[]`, learnings, Context Pack, or every existing package. Those are Phase 2 and Phase 3 in the approved design.

## File Structure

- Create `lib/package_facts/__init__.py`: shared helpers for fact paths, required CSV columns, JS fact serialization, CSV read/write/upsert, SHA-256 revisions, and HTML source-marker validation.
- Create `skills/research-package/scripts/extract_result_table.py`: CLI extractor from real JSON experiment artifacts into `research_html/data/packages/<pkg>/tables/result_table_<exp>.csv`, plus extractor manifest JSON.
- Create `skills/research-package/scripts/render_result_facts.py`: CLI renderer from package CSV/JS facts into the fact-backed section of `results.html`.
- Modify `skills/research-dashboard/assets/dashboard/scripts/learnings_lint.py`: add `fact-alignment` lint mode and include it in `all`.
- Modify `skills/research-op/scripts/ops/check.py`: route `--scope fact-alignment` to the dashboard lint.
- Modify `skills/research-package/templates/results.html`: include a stable fact-backed result section anchor for new packages.
- Modify `skills/research-package/references/package-contract.md`: document JS/CSV Phase 1 result-table fact contract.
- Add tests under `tests/package_facts/` and `tests/research-dashboard/`.

---

### Task 1: Package Fact Helpers

**Files:**
- Create: `lib/package_facts/__init__.py`
- Test: `tests/package_facts/test_schema.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/package_facts/test_schema.py`:

```python
import csv
import json
import re
from pathlib import Path

import pytest

from lib import package_facts


def test_fact_paths_are_package_scoped(tmp_path):
    paths = package_facts.fact_paths("2026-06-11-demo", root=tmp_path)
    assert paths.facts_js == tmp_path / "research_html" / "data" / "packages" / "2026-06-11-demo.facts.js"
    assert paths.tables_dir == tmp_path / "research_html" / "data" / "packages" / "2026-06-11-demo" / "tables"
    assert paths.extractors_dir == tmp_path / "research_html" / "data" / "packages" / "2026-06-11-demo" / "extractors"


def test_write_and_load_facts_js_round_trip(tmp_path):
    facts = {
        "schemaVersion": 1,
        "packageId": "2026-06-11-demo",
        "updatedAt": "2026-06-11",
        "pages": {"results": {"headlineFact": "result_table_P1:best"}},
    }
    path = package_facts.write_facts_js("2026-06-11-demo", facts, root=tmp_path)
    text = path.read_text(encoding="utf-8")
    assert 'window.PACKAGE_FACTS["2026-06-11-demo"]' in text
    assert package_facts.load_facts_js("2026-06-11-demo", root=tmp_path) == facts


def test_csv_upsert_preserves_existing_rows_and_updates_by_row_id(tmp_path):
    path = tmp_path / "table.csv"
    columns = package_facts.RESULT_COLUMNS
    package_facts.upsert_csv_rows(path, columns, [
        {"row_id": "a", "exp_id": "P1", "metric": "Recall@1", "value": "41.0"},
        {"row_id": "b", "exp_id": "P1", "metric": "Recall@5", "value": "71.0"},
    ])
    package_facts.upsert_csv_rows(path, columns, [
        {"row_id": "a", "exp_id": "P1", "metric": "Recall@1", "value": "42.0"},
    ])
    rows = package_facts.read_csv_rows(path)
    assert [r["row_id"] for r in rows] == ["a", "b"]
    assert rows[0]["value"] == "42.0"
    assert rows[1]["value"] == "71.0"
    with path.open(newline="", encoding="utf-8") as f:
        assert next(csv.reader(f)) == columns


def test_upsert_requires_row_id(tmp_path):
    with pytest.raises(package_facts.FactError, match="row_id"):
        package_facts.upsert_csv_rows(tmp_path / "table.csv", package_facts.RESULT_COLUMNS, [
            {"exp_id": "P1", "metric": "Recall@1", "value": "42.0"},
        ])


def test_source_ref_and_revision(tmp_path):
    path = tmp_path / "table.csv"
    path.write_text("row_id,value\\nbest,42.0\\n", encoding="utf-8")
    assert package_facts.source_ref("result_table_P1", "best") == "result_table_P1:best"
    digest = package_facts.file_revision(path)
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", digest)


def test_find_csv_row_by_source_ref(tmp_path):
    table = tmp_path / "result_table_P1.csv"
    table.write_text("row_id,value\\nbest,42.0\\n", encoding="utf-8")
    row = package_facts.find_row_by_ref(tmp_path, "result_table_P1:best")
    assert row["value"] == "42.0"
```

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```bash
python3 -m pytest -q tests/package_facts/test_schema.py
```

Expected: import failure for `lib.package_facts`.

- [ ] **Step 3: Implement the helper module**

Create `lib/package_facts/__init__.py`:

```python
"""Lightweight JS + CSV fact helpers for research packages."""

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
        "window.PACKAGE_FACTS = window.PACKAGE_FACTS || {};\\n"
        f"window.PACKAGE_FACTS[{json.dumps(pkg)}] = {payload};\\n"
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
    pat = re.compile(r"window\\.PACKAGE_FACTS\\[" + re.escape(json.dumps(pkg)) + r"\\]\\s*=\\s*(\\{.*\\});\\s*$", re.DOTALL)
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
```

- [ ] **Step 4: Run the helper tests**

Run:

```bash
python3 -m pytest -q tests/package_facts/test_schema.py
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 1**

Run:

```bash
git add lib/package_facts/__init__.py tests/package_facts/test_schema.py
git commit -m "Add package fact schema helpers"
```

---

### Task 2: JSON Artifact to Result CSV Extractor

**Files:**
- Create: `skills/research-package/scripts/extract_result_table.py`
- Test: `tests/package_facts/test_extract_result_table.py`

- [ ] **Step 1: Write the failing extractor tests**

Create `tests/package_facts/test_extract_result_table.py`:

```python
import csv
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills" / "research-package" / "scripts" / "extract_result_table.py"


def test_extracts_metric_from_real_json_artifact(tmp_path):
    artifact = tmp_path / "outputs" / "2026-06-11-demo" / "runs" / "P1-r1" / "summary.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text(json.dumps({
        "metrics": {"Recall@1": 42.1},
        "split": "test",
        "checkpoint": "ckpt/best.pt",
    }), encoding="utf-8")

    result = subprocess.run([
        sys.executable, str(SCRIPT),
        "--repo-root", str(tmp_path),
        "--pkg", "2026-06-11-demo",
        "--exp-id", "P1",
        "--input", str(artifact.relative_to(tmp_path)),
        "--metric", "Recall@1",
        "--value-key", "metrics.Recall@1",
        "--row-id", "current_best",
        "--split-key", "split",
        "--validity", "VALID",
        "--verdict", "PASS",
    ], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr + result.stdout
    csv_path = tmp_path / "research_html" / "data" / "packages" / "2026-06-11-demo" / "tables" / "result_table_P1.csv"
    rows = list(csv.DictReader(csv_path.open(newline="", encoding="utf-8")))
    assert rows[0]["row_id"] == "current_best"
    assert rows[0]["metric"] == "Recall@1"
    assert rows[0]["value"] == "42.1"
    assert rows[0]["split"] == "test"
    assert rows[0]["source_artifact"] == "outputs/2026-06-11-demo/runs/P1-r1/summary.json"
    assert rows[0]["extractor"] == "extract_result_table.py"

    manifest = tmp_path / "research_html" / "data" / "packages" / "2026-06-11-demo" / "extractors" / "P1.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["inputs"] == ["outputs/2026-06-11-demo/runs/P1-r1/summary.json"]
    assert payload["output_csv"] == "research_html/data/packages/2026-06-11-demo/tables/result_table_P1.csv"


def test_missing_metric_key_fails_closed(tmp_path):
    artifact = tmp_path / "outputs" / "2026-06-11-demo" / "runs" / "P1-r1" / "summary.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text(json.dumps({"metrics": {}}), encoding="utf-8")

    result = subprocess.run([
        sys.executable, str(SCRIPT),
        "--repo-root", str(tmp_path),
        "--pkg", "2026-06-11-demo",
        "--exp-id", "P1",
        "--input", str(artifact.relative_to(tmp_path)),
        "--metric", "Recall@1",
        "--value-key", "metrics.Recall@1",
        "--row-id", "current_best",
    ], capture_output=True, text=True)

    assert result.returncode == 2
    assert "metrics.Recall@1" in result.stderr
    csv_path = tmp_path / "research_html" / "data" / "packages" / "2026-06-11-demo" / "tables" / "result_table_P1.csv"
    assert not csv_path.exists()
```

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```bash
python3 -m pytest -q tests/package_facts/test_extract_result_table.py
```

Expected: failure because `extract_result_table.py` does not exist.

- [ ] **Step 3: Implement the extractor CLI**

Create `skills/research-package/scripts/extract_result_table.py`:

```python
#!/usr/bin/env python3
"""Extract one result-table CSV row from a real JSON experiment artifact."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

PIPELINE_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PIPELINE_ROOT))

from lib import package_facts  # noqa: E402


def _nested_get(data: dict, dotted: str):
    current = data
    for part in dotted.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            raise package_facts.FactError(f"missing key path: {dotted}")
    return current


def _optional_nested_get(data: dict, dotted: str | None) -> str:
    if not dotted:
        return ""
    try:
        value = _nested_get(data, dotted)
    except package_facts.FactError:
        return ""
    return str(value)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo-root", default=".")
    p.add_argument("--pkg", required=True)
    p.add_argument("--exp-id", required=True)
    p.add_argument("--input", required=True, dest="input_path")
    p.add_argument("--metric", required=True)
    p.add_argument("--value-key", required=True)
    p.add_argument("--row-id", required=True)
    p.add_argument("--unit", default="")
    p.add_argument("--split", default="")
    p.add_argument("--split-key", default="")
    p.add_argument("--baseline", default="")
    p.add_argument("--validity", default="VALID", choices=sorted(package_facts.VALID_RESULT_VALIDITY))
    p.add_argument("--verdict", default="INCONCLUSIVE", choices=sorted(v for v in package_facts.VALID_EXPERIMENT_VERDICT if v))
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.repo_root)
    input_rel = Path(args.input_path)
    input_abs = root / input_rel
    try:
        data = json.loads(input_abs.read_text(encoding="utf-8"))
        value = _nested_get(data, args.value_key)
    except (OSError, json.JSONDecodeError, package_facts.FactError) as exc:
        print(f"extract_result_table: {exc}", file=sys.stderr)
        return 2

    paths = package_facts.fact_paths(args.pkg, root=root)
    output_csv = paths.tables_dir / f"result_table_{args.exp_id}.csv"
    source_mtime = dt.datetime.fromtimestamp(input_abs.stat().st_mtime, dt.UTC).isoformat()
    extracted_at = dt.datetime.now(dt.UTC).astimezone().isoformat(timespec="seconds")
    split = args.split or _optional_nested_get(data, args.split_key)
    row = {
        "row_id": args.row_id,
        "exp_id": args.exp_id,
        "metric": args.metric,
        "value": str(value),
        "unit": args.unit,
        "split": split,
        "baseline": args.baseline,
        "verdict": args.verdict,
        "validity": args.validity,
        "source_artifact": str(input_rel),
        "source_mtime": source_mtime,
        "extractor": "extract_result_table.py",
        "extracted_at": extracted_at,
    }
    package_facts.upsert_csv_rows(output_csv, package_facts.RESULT_COLUMNS, [row])

    manifest = {
        "exp_id": args.exp_id,
        "inputs": [str(input_rel)],
        "extractor": "extract_result_table.py",
        "output_csv": str(output_csv.relative_to(root)),
        "generated_at": extracted_at,
    }
    paths.extractors_dir.mkdir(parents=True, exist_ok=True)
    (paths.extractors_dir / f"{args.exp_id}.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\\n",
        encoding="utf-8",
    )
    print(f"wrote {output_csv.relative_to(root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the extractor tests**

Run:

```bash
python3 -m pytest -q tests/package_facts/test_extract_result_table.py
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 2**

Run:

```bash
git add skills/research-package/scripts/extract_result_table.py tests/package_facts/test_extract_result_table.py
git commit -m "Add JSON artifact result extractor"
```

---

### Task 3: Render Result Facts Into Results HTML

**Files:**
- Create: `skills/research-package/scripts/render_result_facts.py`
- Test: `tests/package_facts/test_render_result_facts.py`

- [ ] **Step 1: Write the failing renderer tests**

Create `tests/package_facts/test_render_result_facts.py`:

```python
import csv
import subprocess
import sys
from pathlib import Path

from lib import package_facts


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills" / "research-package" / "scripts" / "render_result_facts.py"


def _write_results_shell(root: Path, pkg: str):
    path = root / "research_html" / "packages" / pkg / "results.html"
    path.parent.mkdir(parents=True)
    path.write_text(
        """<!doctype html>
<html><body>
<section data-section="user-zone" id="user-zone">
  <section class="result-blocks" data-list="result-blocks" id="result-blocks"></section>
</section>
<details data-audience="agent">
  <table class="data-table" data-table="result-gate">
    <tbody data-table-body="result-gate"></tbody>
  </table>
</details>
<footer><time data-field="last-updated" datetime="2026-06-01">2026-06-01</time></footer>
</body></html>
""",
        encoding="utf-8",
    )
    return path


def test_renders_result_gate_and_fact_backed_result_section(tmp_path):
    pkg = "2026-06-11-demo"
    results_path = _write_results_shell(tmp_path, pkg)
    paths = package_facts.fact_paths(pkg, root=tmp_path)
    package_facts.upsert_csv_rows(paths.tables_dir / "result_table_P1.csv", package_facts.RESULT_COLUMNS, [
        {
            "row_id": "current_best",
            "exp_id": "P1",
            "metric": "Recall@1",
            "value": "42.1",
            "unit": "%",
            "split": "test",
            "baseline": "40.0",
            "validity": "VALID",
            "verdict": "PASS",
            "source_artifact": "outputs/pkg/summary.json",
            "source_mtime": "2026-06-11T00:00:00+00:00",
            "extractor": "extract_result_table.py",
            "extracted_at": "2026-06-11T00:01:00+00:00",
        }
    ])
    package_facts.upsert_csv_rows(paths.tables_dir / "result_gate.csv", package_facts.RESULT_COLUMNS, [
        {
            "row_id": "P1_gate",
            "exp_id": "P1",
            "metric": "Recall@1",
            "value": "42.1",
            "baseline": "40.0",
            "validity": "VALID",
            "verdict": "PASS",
            "source_artifact": "outputs/pkg/summary.json",
            "source_mtime": "2026-06-11T00:00:00+00:00",
            "extractor": "extract_result_table.py",
            "extracted_at": "2026-06-11T00:01:00+00:00",
        }
    ])

    result = subprocess.run([
        sys.executable, str(SCRIPT),
        "--repo-root", str(tmp_path),
        "--pkg", pkg,
    ], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr + result.stdout
    text = results_path.read_text(encoding="utf-8")
    assert 'data-source="tables/result_table_P1.csv"' in text
    assert 'data-source-row="result_table_P1:current_best"' in text
    assert 'data-source-row="result_gate:P1_gate"' in text
    assert "Recall@1" in text
    assert "42.1" in text
    assert 'datetime="2026-06-11"' in text
```

- [ ] **Step 2: Run the renderer tests and verify they fail**

Run:

```bash
python3 -m pytest -q tests/package_facts/test_render_result_facts.py
```

Expected: failure because `render_result_facts.py` does not exist.

- [ ] **Step 3: Implement the renderer CLI**

Create `skills/research-package/scripts/render_result_facts.py`:

```python
#!/usr/bin/env python3
"""Render package result CSV facts into results.html."""

from __future__ import annotations

import argparse
import html
import re
import sys
from datetime import date
from pathlib import Path

PIPELINE_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PIPELINE_ROOT))

from lib import package_facts  # noqa: E402


def esc(value) -> str:
    return html.escape(str(value or ""), quote=True)


def render_gate_rows(rows: list[dict]) -> str:
    out = []
    for row in rows:
        exp_id = row.get("exp_id", "")
        ref = package_facts.source_ref("result_gate", row["row_id"])
        out.append(
            '            <tr id="gate-{low}" data-exp-id="{exp}" data-source-row="{ref}" data-ack="result-pass" data-ack-value="">'
            '<td data-field="exp-id">{exp}</td>'
            '<td data-validity="{validity}">{validity}</td>'
            '<td data-field="baseline">{baseline}</td>'
            '<td data-field="plan-gate">{metric}</td>'
            '<td data-field="observed-metric">{metric}={value}{unit}</td>'
            '<td data-field="budget-use">unmeasured</td>'
            '<td data-field="seed-status">{split}</td>'
            '<td data-field="artifact-completeness"><code>{artifact}</code></td>'
            '<td data-decision data-field="verdict">{verdict}</td>'
            '<td data-field="reason">fact-backed row {row_id}</td></tr>'.format(
                low=esc(exp_id.lower()),
                exp=esc(exp_id),
                ref=esc(ref),
                validity=esc(row.get("validity") or "UNMEASURED"),
                baseline=esc(row.get("baseline") or "unmeasured"),
                metric=esc(row.get("metric") or "unmeasured"),
                value=esc(row.get("value") or "unmeasured"),
                unit=esc(row.get("unit") or ""),
                split=esc(row.get("split") or "unmeasured"),
                artifact=esc(row.get("source_artifact") or "unmeasured"),
                verdict=esc(row.get("verdict") or "INCONCLUSIVE"),
                row_id=esc(row.get("row_id") or ""),
            )
        )
    return "\\n".join(out)


def render_result_article(table_path: Path, rows: list[dict]) -> str:
    table_id = table_path.stem
    revision = package_facts.file_revision(table_path)
    body_rows = []
    for row in rows:
        ref = package_facts.source_ref(table_id, row["row_id"])
        body_rows.append(
            "              <tr data-source-row=\"{ref}\">"
            "<td>{split}</td><td>{metric}</td><td>{value}{unit}</td><td><code>{artifact}</code></td>"
            "</tr>".format(
                ref=esc(ref),
                split=esc(row.get("split") or "unmeasured"),
                metric=esc(row.get("metric") or "unmeasured"),
                value=esc(row.get("value") or "unmeasured"),
                unit=esc(row.get("unit") or ""),
                artifact=esc(row.get("source_artifact") or "unmeasured"),
            )
        )
    exp_id = rows[0].get("exp_id", table_id.replace("result_table_", "")) if rows else table_id
    return """        <article class="result-block" id="result-slot-{low}" data-result-block data-exp-id="{exp}" data-phase-id="{exp}" data-source="tables/{name}" data-fact-revision="{revision}">
          <h2>{exp} &mdash; fact-backed result table</h2>
          <p class="block-summary">Rendered from <code>tables/{name}</code>.</p>
          <table class="data-table block-main-table" data-table="{table_id}" data-exp-id="{exp}">
            <thead><tr><th>Split</th><th>Metric</th><th>Value</th><th>Artifact</th></tr></thead>
            <tbody data-table-body="{table_id}">
{rows}
            </tbody>
          </table>
        </article>""".format(
        low=esc(str(exp_id).lower()),
        exp=esc(exp_id),
        name=esc(table_path.name),
        revision=esc(revision),
        table_id=esc(table_id),
        rows="\\n".join(body_rows),
    )


def replace_result_gate(text: str, rows_html: str) -> str:
    pat = re.compile(r'(<tbody[^>]*data-table-body="result-gate"[^>]*>)(.*?)(</tbody>)', re.DOTALL)
    if not pat.search(text):
        raise package_facts.FactError("results.html missing result-gate tbody")
    return pat.sub(lambda m: m.group(1) + "\\n" + rows_html + "\\n          " + m.group(3), text, count=1)


def replace_result_blocks(text: str, articles_html: str) -> str:
    pat = re.compile(r'(<section[^>]*data-list="result-blocks"[^>]*>)(.*?)(</section>)', re.DOTALL)
    if not pat.search(text):
        raise package_facts.FactError("results.html missing data-list=result-blocks section")
    return pat.sub(lambda m: m.group(1) + "\\n" + articles_html + "\\n      " + m.group(3), text, count=1)


def bump_last_updated(text: str) -> str:
    today = date.today().isoformat()
    new = re.sub(
        r'(<time[^>]*data-field="last-updated"[^>]*datetime=")[^"]*("[^>]*>)[^<]*(</time>)',
        rf"\\g<1>{today}\\g<2>{today}\\g<3>",
        text,
        count=1,
    )
    return new


def render(pkg: str, root: Path) -> Path:
    paths = package_facts.fact_paths(pkg, root=root)
    results_path = root / "research_html" / "packages" / pkg / "results.html"
    if not results_path.exists():
        raise package_facts.FactError(f"missing results.html for {pkg}")
    gate_rows = package_facts.read_csv_rows(paths.tables_dir / "result_gate.csv")
    table_paths = sorted(paths.tables_dir.glob("result_table_*.csv"))
    articles = [render_result_article(p, package_facts.read_csv_rows(p)) for p in table_paths]
    text = results_path.read_text(encoding="utf-8")
    if gate_rows:
        text = replace_result_gate(text, render_gate_rows(gate_rows))
    if articles:
        text = replace_result_blocks(text, "\\n".join(articles))
    text = bump_last_updated(text)
    results_path.write_text(text, encoding="utf-8")
    return results_path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo-root", default=".")
    p.add_argument("--pkg", required=True)
    args = p.parse_args(argv)
    try:
        path = render(args.pkg, Path(args.repo_root))
    except package_facts.FactError as exc:
        print(f"render_result_facts: {exc}", file=sys.stderr)
        return 2
    print(f"rendered {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the renderer tests**

Run:

```bash
python3 -m pytest -q tests/package_facts/test_render_result_facts.py
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 3**

Run:

```bash
git add skills/research-package/scripts/render_result_facts.py tests/package_facts/test_render_result_facts.py
git commit -m "Render result pages from CSV facts"
```

---

### Task 4: New Package Results Template Source Anchors

**Files:**
- Modify: `skills/research-package/templates/results.html`
- Test: extend `tests/research-package/test_task_spine_derivation.py`

- [ ] **Step 1: Write the failing template test**

Add this assertion near the end of `test_scaffold_derives_task_blocks_from_spine` in `tests/research-package/test_task_spine_derivation.py` after `results = ...` is loaded:

```python
    assert 'data-list="result-blocks"' in results
    assert 'data-fact-projection="results"' in results
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
python3 -m pytest -q tests/research-package/test_task_spine_derivation.py::test_scaffold_derives_task_blocks_from_spine
```

Expected: failure for missing `data-fact-projection="results"`.

- [ ] **Step 3: Add the projection marker to the template**

In `skills/research-package/templates/results.html`, change:

```html
      <section class="result-blocks" data-list="result-blocks" id="result-blocks" aria-label="Result blocks">
```

to:

```html
      <section class="result-blocks" data-list="result-blocks" data-fact-projection="results" id="result-blocks" aria-label="Result blocks">
```

- [ ] **Step 4: Run the focused test**

Run:

```bash
python3 -m pytest -q tests/research-package/test_task_spine_derivation.py::test_scaffold_derives_task_blocks_from_spine
```

Expected: pass.

- [ ] **Step 5: Commit Task 4**

Run:

```bash
git add skills/research-package/templates/results.html tests/research-package/test_task_spine_derivation.py
git commit -m "Mark result sections as fact projections"
```

---

### Task 5: Fact-Alignment Lint

**Files:**
- Modify: `skills/research-dashboard/assets/dashboard/scripts/learnings_lint.py`
- Test: `tests/research-dashboard/test_fact_alignment.py`

- [ ] **Step 1: Write the failing fact-alignment tests**

Create `tests/research-dashboard/test_fact_alignment.py`:

```python
import subprocess
import sys
from pathlib import Path

from lib import package_facts


ROOT = Path(__file__).resolve().parents[2]
LINT = ROOT / "skills" / "research-dashboard" / "assets" / "dashboard" / "scripts" / "learnings_lint.py"


def _write_dashboard(root: Path, pkg: str, result_html: str):
    data = root / "research_html" / "data"
    data.mkdir(parents=True)
    (data / "schema.js").write_text("window.RESEARCH_STATUS_SCHEMA = {};\\n", encoding="utf-8")
    (data / "research-packages.js").write_text(
        f'window.RESEARCH_PACKAGES = [{{ id: "{pkg}", category: "in-progress", status: "RESULT_ANALYSIS" }}];\\n',
        encoding="utf-8",
    )
    scripts = root / "research_html" / "scripts"
    scripts.mkdir(parents=True)
    package_dir = root / "research_html" / "packages" / pkg
    package_dir.mkdir(parents=True)
    (package_dir / "results.html").write_text(result_html, encoding="utf-8")


def test_fact_alignment_passes_when_source_row_exists(tmp_path):
    pkg = "2026-06-11-demo"
    _write_dashboard(tmp_path, pkg, '''
<html><body>
<article data-source="tables/result_table_P1.csv" data-fact-revision="sha256:x">
  <span data-source-row="result_table_P1:current_best">42.1</span>
</article>
</body></html>
''')
    paths = package_facts.fact_paths(pkg, root=tmp_path)
    package_facts.upsert_csv_rows(paths.tables_dir / "result_table_P1.csv", package_facts.RESULT_COLUMNS, [
        {"row_id": "current_best", "exp_id": "P1", "metric": "Recall@1", "value": "42.1", "validity": "VALID"}
    ])

    result = subprocess.run([
        sys.executable, str(LINT),
        "fact-alignment",
        "--pkg", pkg,
        "--repo-root", str(tmp_path),
    ], capture_output=True, text=True)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "errors=0" in result.stdout


def test_fact_alignment_fails_when_source_row_is_missing(tmp_path):
    pkg = "2026-06-11-demo"
    _write_dashboard(tmp_path, pkg, '''
<html><body>
<article data-source="tables/result_table_P1.csv" data-fact-revision="sha256:x">
  <span data-source-row="result_table_P1:missing">42.1</span>
</article>
</body></html>
''')
    paths = package_facts.fact_paths(pkg, root=tmp_path)
    package_facts.upsert_csv_rows(paths.tables_dir / "result_table_P1.csv", package_facts.RESULT_COLUMNS, [
        {"row_id": "current_best", "exp_id": "P1", "metric": "Recall@1", "value": "42.1", "validity": "VALID"}
    ])

    result = subprocess.run([
        sys.executable, str(LINT),
        "fact-alignment",
        "--pkg", pkg,
        "--repo-root", str(tmp_path),
    ], capture_output=True, text=True)

    assert result.returncode == 1
    assert "fact-source-row-missing" in result.stdout


def test_fact_alignment_fails_manual_pass(tmp_path):
    pkg = "2026-06-11-demo"
    _write_dashboard(tmp_path, pkg, '''
<html><body>
<article data-source="tables/result_table_P1.csv" data-fact-revision="sha256:x">
  <span data-source-row="result_table_P1:manual_best">42.1</span>
</article>
</body></html>
''')
    paths = package_facts.fact_paths(pkg, root=tmp_path)
    columns = package_facts.RESULT_COLUMNS + ["source_type"]
    package_facts.upsert_csv_rows(paths.tables_dir / "result_table_P1.csv", columns, [
        {
            "row_id": "manual_best",
            "exp_id": "P1",
            "metric": "Recall@1",
            "value": "42.1",
            "validity": "VALID",
            "verdict": "PASS",
            "source_type": "manual",
        }
    ])

    result = subprocess.run([
        sys.executable, str(LINT),
        "fact-alignment",
        "--pkg", pkg,
        "--repo-root", str(tmp_path),
    ], capture_output=True, text=True)

    assert result.returncode == 1
    assert "manual-pass-forbidden" in result.stdout
```

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```bash
python3 -m pytest -q tests/research-dashboard/test_fact_alignment.py
```

Expected: CLI rejects unknown command `fact-alignment`.

- [ ] **Step 3: Add fact-alignment helpers to `learnings_lint.py`**

In `skills/research-dashboard/assets/dashboard/scripts/learnings_lint.py`, add a resolver near the existing imports and assign the module once:

```python
def _load_package_facts_module():
    candidates = [
        Path(__file__).resolve().parents[5],  # source tree: skills/research-dashboard/assets/dashboard/scripts
        Path(__file__).resolve().parents[2],  # installed dashboard: research_html/scripts
    ]
    for root in candidates:
        if (root / "lib" / "package_facts").exists():
            sys.path.insert(0, str(root))
            from lib import package_facts
            return package_facts
    raise ImportError("cannot locate lib/package_facts")


package_facts = _load_package_facts_module()
```

Add these functions before the CLI `main` function:

```python
DATA_SOURCE = re.compile(r'data-source\\s*=\\s*"([^"]+)"')
DATA_SOURCE_ROW = re.compile(r'data-source-row\\s*=\\s*"([^"]+)"')


def lint_fact_alignment(data: dict, pkg_filter: str | None = None, repo_root: Path | None = None) -> Report:
    root = repo_root or REPO_ROOT
    rep = Report("fact-alignment — JS/CSV fact projection")
    packages = data.get("packages") or []
    for pkg in packages:
        pid = pkg.get("id", "(no-id)")
        if pkg_filter and pid != pkg_filter:
            continue
        package_dir = root / "research_html" / "packages" / pid
        results = package_dir / "results.html"
        if not results.exists():
            continue
        text = results.read_text(encoding="utf-8", errors="ignore")
        if "data-source" not in text and "data-source-row" not in text:
            rep.add(Violation(pid, "fact-no-projection", "no fact-backed result projection found", "warning"))
            continue
        paths = package_facts.fact_paths(pid, root=root)
        for source in DATA_SOURCE.findall(text):
            source_path = paths.package_data_dir / source if source.startswith("tables/") else root / source
            if not source_path.exists():
                rep.add(Violation(pid, "fact-source-missing", f"data-source={source!r} does not exist", "error"))
        for ref in DATA_SOURCE_ROW.findall(text):
            try:
                table_id, row_id = package_facts.split_source_ref(ref)
                row = package_facts.find_row_by_ref(paths.tables_dir, ref)
            except package_facts.FactError as exc:
                rep.add(Violation(pid, "fact-source-row-missing", str(exc), "error"))
                continue
            if row.get("source_type") == "manual" and row.get("verdict") == "PASS":
                rep.add(Violation(pid, "manual-pass-forbidden", f"{table_id}:{row_id} is manual but verdict=PASS", "error"))
    return rep
```

- [ ] **Step 4: Wire the CLI command**

In the CLI parser setup in `learnings_lint.py`, add:

```python
    p = sub.add_parser("fact-alignment"); p.add_argument("--pkg"); p.add_argument("--repo-root", type=Path)
```

In the command dispatch, add:

```python
    if args.cmd == "fact-alignment":
        rep = lint_fact_alignment(data, pkg_filter=args.pkg, repo_root=args.repo_root)
        print(rep.render(strict=args.strict))
        return 1 if rep.errors() or (args.strict and rep.warnings()) else 0
```

In the `all` command, after alignment, run:

```python
        r5 = lint_fact_alignment(data, pkg_filter=args.pkg)
        print(); print(r5.render(strict=args.strict))
```

and make the `all` return code include `r5.errors()`.

- [ ] **Step 5: Run the fact-alignment tests**

Run:

```bash
python3 -m pytest -q tests/research-dashboard/test_fact_alignment.py
```

Expected: all tests pass.

- [ ] **Step 6: Run existing dashboard lint tests**

Run:

```bash
python3 -m pytest -q tests/research-dashboard/test_binding_rules_lint.py tests/research-dashboard/test_scope_provenance_lint.py
```

Expected: all tests pass.

- [ ] **Step 7: Commit Task 5**

Run:

```bash
git add skills/research-dashboard/assets/dashboard/scripts/learnings_lint.py tests/research-dashboard/test_fact_alignment.py
git commit -m "Add fact alignment lint"
```

---

### Task 6: Research-Op Check Wiring

**Files:**
- Modify: `skills/research-op/scripts/ops/check.py`
- Test: `tests/research-op/test_cli.py`

- [ ] **Step 1: Add a failing CLI test**

Add this test to `tests/research-op/test_cli.py` after `test_check_scope_alignment_invokes_alignment_lint`:

```python
def test_check_scope_fact_alignment_invokes_fact_lint(tmp_package):
    lint = tmp_package / "research_html" / "scripts" / "learnings_lint.py"
    lint.write_text(
        "#!/usr/bin/env python3\\n"
        "import json, pathlib, sys\\n"
        "pathlib.Path('lint_args.json').write_text(json.dumps(sys.argv[1:]))\\n",
        encoding="utf-8",
    )
    r = _run(["--pkg", "test-pkg", "--op", "check", "--scope", "fact-alignment"], cwd=tmp_package)
    assert r.returncode == 0, r.stderr + r.stdout
    assert json.loads((tmp_package / "lint_args.json").read_text()) == ["fact-alignment", "--pkg", "test-pkg"]
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
python3 -m pytest -q tests/research-op/test_cli.py::test_check_scope_fact_alignment_invokes_fact_lint
```

Expected: failure because `check.py` routes the unknown scope to `lint-status`.

- [ ] **Step 3: Add the `fact-alignment` branch**

In `skills/research-op/scripts/ops/check.py`, change the scope routing block to include:

```python
    elif scope == "fact-alignment":
        lint_args += ["fact-alignment", "--pkg", pkg]
```

Also change:

```python
    if scope in {"all", "alignment", "alignment-terminal"}:
```

to:

```python
    if scope in {"all", "alignment", "alignment-terminal", "fact-alignment"}:
```

- [ ] **Step 4: Run the focused test**

Run:

```bash
python3 -m pytest -q tests/research-op/test_cli.py::test_check_scope_fact_alignment_invokes_fact_lint
```

Expected: pass.

- [ ] **Step 5: Run the research-op CLI tests**

Run:

```bash
python3 -m pytest -q tests/research-op/test_cli.py
```

Expected: all tests pass.

- [ ] **Step 6: Commit Task 6**

Run:

```bash
git add skills/research-op/scripts/ops/check.py tests/research-op/test_cli.py
git commit -m "Wire fact alignment through research-op check"
```

---

### Task 7: Documentation Contract Update

**Files:**
- Modify: `skills/research-package/references/package-contract.md`
- Modify: `skills/research-package/references/results-page-pattern.md`
- Test: no unit test; use `git diff --check` and targeted grep checks.

- [ ] **Step 1: Update package contract**

In `skills/research-package/references/package-contract.md`, add this section after `Inventory schema (additive)`:

```markdown
## Package fact layer (Phase 1)

Result table facts for new or structurally touched result sections live under
`research_html/data/packages/`:

```text
research_html/data/packages/<pkg>.facts.js
research_html/data/packages/<pkg>/tables/result_gate.csv
research_html/data/packages/<pkg>/tables/result_table_<exp_id>.csv
research_html/data/packages/<pkg>/extractors/<exp_id>.json
```

Rules:

- JavaScript facts own repeated content facts such as headline references,
  objective summaries, projection revisions, and page-level summaries.
- CSV files own table facts. Result tables, result-gate rows, and headline
  metric cards must reference the same CSV `row_id` when they display the same
  value.
- Experiment result CSVs are generated from real runtime artifacts by extractor
  scripts whenever the artifact format is machine-readable.
- Manual CSV rows must carry `source_type=manual`, `source_note`, and
  `verified_by`; they do not support `PASS` verdicts by default.
- HTML result sections are projections. Fact-backed sections carry
  `data-source`, `data-source-row`, and `data-fact-revision` markers.
- `research-op --op check --scope fact-alignment` validates fact-backed result
  projections.
```
```

- [ ] **Step 2: Update results page pattern**

In `skills/research-package/references/results-page-pattern.md`, add this paragraph after the opening description:

```markdown
For new or structurally touched result sections, the preferred data source is
the Phase-1 package fact layer: CSV table facts under
`research_html/data/packages/<pkg>/tables/` plus optional content facts in
`research_html/data/packages/<pkg>.facts.js`. The page pattern still describes
the browser shape, but repeated result values should be rendered from CSV rows
and marked with `data-source-row`, not copied by hand into HTML.
```

- [ ] **Step 3: Run documentation checks**

Run:

```bash
rg -n "Package fact layer|data-source-row|fact-alignment" skills/research-package/references/package-contract.md skills/research-package/references/results-page-pattern.md
git diff --check
```

Expected: `rg` prints the new references; `git diff --check` prints nothing and exits 0.

- [ ] **Step 4: Commit Task 7**

Run:

```bash
git add skills/research-package/references/package-contract.md skills/research-package/references/results-page-pattern.md
git commit -m "Document package fact layer contract"
```

---

### Task 8: Integration Verification

**Files:**
- No source edits expected unless a preceding task failed.

- [ ] **Step 1: Run focused package fact tests**

Run:

```bash
python3 -m pytest -q tests/package_facts tests/research-dashboard/test_fact_alignment.py
```

Expected: all tests pass.

- [ ] **Step 2: Run affected existing tests**

Run:

```bash
python3 -m pytest -q tests/research-package tests/research-op/test_cli.py tests/research-dashboard
```

Expected: all tests pass.

- [ ] **Step 3: Run full suite if the focused suite passes**

Run:

```bash
python3 -m pytest -q tests
```

Expected: all tests pass. If this command fails because the environment lacks an optional tool such as `node`, record the exact failure and the focused test results.

- [ ] **Step 4: Inspect final diff**

Run:

```bash
git status --short
git diff --stat
git diff --check
```

Expected: status shows only intended files; diff stat matches this plan; `git diff --check` exits 0.

- [ ] **Step 5: Final commit if any verification fixes were needed**

If Step 3 or Step 4 required small fixes, commit them:

```bash
git add lib/package_facts skills/research-package skills/research-dashboard skills/research-op tests
git commit -m "Stabilize result fact layer"
```

If no fixes were needed after Task 7, do not create an empty commit.

---

## Self-Review Notes

Spec coverage:

- JS content facts: Task 1 creates JS fact helpers; Task 7 documents the contract.
- CSV table facts: Task 1 defines CSV helpers and result columns; Task 2 writes CSV from real artifacts.
- Experiment-derived result tables: Task 2 reads JSON runtime artifacts and fails closed on missing metric keys.
- HTML projection: Task 3 renders `results.html` from CSV; Task 4 marks new result sections as fact projections.
- Propagation direction: Task 6 creates the `research-op check` entry point; direct event rewiring remains outside Phase 1.
- Validation and stop-gate basis: Task 5 adds fact-alignment lint.
- Migration discipline: Task 7 documents grandfathering and preferred behavior for new or touched result sections.

Known Phase 1 boundary:

- `methodsTried[]`, tracker CSV ledgers, and full manifest transactional apply are not implemented here. They need separate Phase 2 tasks after result facts are proven in package pages.
