import subprocess
import sys
from pathlib import Path

import pytest

from lib import package_facts


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills" / "research-package" / "scripts" / "render_package_projection.py"


def _write_results_shell(root: Path, pkg: str) -> Path:
    path = root / "research_html" / "packages" / pkg / "results.html"
    path.parent.mkdir(parents=True, exist_ok=True)
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


def _write_tracker_shell(root: Path, pkg: str) -> Path:
    path = root / "research_html" / "packages" / pkg / "tracker.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """<!doctype html>
<html><body>
<article id="live-check" data-card="live-check-user">
  <table class="data-table" data-table="live-check">
    <tbody data-table-body="live-check"></tbody>
  </table>
  <table class="data-table" data-table="live-check-history">
    <tbody data-table-body="live-check-history"></tbody>
  </table>
</article>
<article data-card="resource-allocation">
  <table class="data-table" data-table="resource-allocation">
    <tbody data-table-body="resource-allocation"></tbody>
  </table>
</article>
</body></html>
""",
        encoding="utf-8",
    )
    return path


def _write_fact_backed_package(root: Path, pkg: str) -> tuple[Path, Path]:
    results_path = _write_results_shell(root, pkg)
    tracker_path = _write_tracker_shell(root, pkg)
    paths = package_facts.fact_paths(pkg, root=root)

    package_facts.upsert_csv_rows(
        paths.tables_dir / "result_table_P1.csv",
        package_facts.RESULT_COLUMNS,
        [
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
        ],
    )
    package_facts.upsert_csv_rows(
        paths.tables_dir / "result_gate.csv",
        package_facts.RESULT_COLUMNS,
        [
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
        ],
    )
    package_facts.upsert_csv_rows(
        paths.tables_dir / "live_checks.csv",
        package_facts.LIVE_CHECK_COLUMNS,
        [
            {
                "row_id": "P1:r1",
                "time": "2026-06-11T10:01:00+10:00",
                "exp_id": "P1",
                "run_id": "r1",
                "agent": "codex",
                "run_state": "RUNNING",
                "last_log": "initial log",
                "progress": "1/2",
                "metrics": "Recall@1=42.1",
                "resource": "gpu0",
                "artifacts": "outputs/pkg/summary.json",
                "eta": "soon",
                "action": "CONTINUE_RUN",
                "next_check": "later",
            }
        ],
    )
    package_facts.upsert_csv_rows(
        paths.tables_dir / "resource_allocation.csv",
        package_facts.RESOURCE_ALLOCATION_COLUMNS,
        [
            {
                "row_id": "P1:alloc",
                "exp_id": "P1",
                "purpose": "run latest",
                "target": "cuda:0",
                "status": "RUNNING",
                "runtime_root": "outputs/latest",
            }
        ],
    )
    return results_path, tracker_path


def _run_projection(root: Path, pkg: str, page: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo-root",
            str(root),
            "--pkg",
            pkg,
            "--page",
            page,
        ],
        capture_output=True,
        text=True,
    )


def test_renders_all_pages_and_records_page_projections(tmp_path):
    pkg = "2026-06-11-demo"
    results_path, tracker_path = _write_fact_backed_package(tmp_path, pkg)

    result = _run_projection(tmp_path, pkg, "all")

    assert result.returncode == 0, result.stderr + result.stdout
    results_text = results_path.read_text(encoding="utf-8")
    tracker_text = tracker_path.read_text(encoding="utf-8")
    assert 'data-source-row="result_table_P1:current_best"' in results_text
    assert 'data-source-row="result_gate:P1_gate"' in results_text
    assert 'data-source-row="live_checks:P1:r1"' in tracker_text
    assert 'data-source-row="resource_allocation:P1:alloc"' in tracker_text

    facts = package_facts.load_facts_js(pkg, root=tmp_path)
    pages = facts["projections"]["pages"]
    assert pages["results.html"]["renderer"] == "render_result_facts.py"
    assert set(pages["results.html"]["sources"]) == {
        "tables/result_gate.csv",
        "tables/result_table_P1.csv",
    }
    assert pages["tracker.html"]["renderer"] == "render_tracker_facts.py"
    assert set(pages["tracker.html"]["sources"]) == {
        "tables/live_checks.csv",
        "tables/resource_allocation.csv",
    }
    package_facts.assert_page_projection_fresh(pkg, "results.html", root=tmp_path)
    package_facts.assert_page_projection_fresh(pkg, "tracker.html", root=tmp_path)


def test_tracker_source_drift_fails_until_tracker_projection_is_rerendered(tmp_path):
    pkg = "2026-06-11-demo"
    _write_fact_backed_package(tmp_path, pkg)
    assert _run_projection(tmp_path, pkg, "all").returncode == 0
    paths = package_facts.fact_paths(pkg, root=tmp_path)

    package_facts.upsert_csv_rows(
        paths.tables_dir / "live_checks.csv",
        package_facts.LIVE_CHECK_COLUMNS,
        [{"row_id": "P1:r1", "time": "2026-06-11T10:02:00+10:00", "run_state": "COMPLETED"}],
    )

    with pytest.raises(package_facts.FactError, match="stale source"):
        package_facts.assert_page_projection_fresh(pkg, "tracker.html", root=tmp_path)

    result = _run_projection(tmp_path, pkg, "tracker")

    assert result.returncode == 0, result.stderr + result.stdout
    package_facts.assert_page_projection_fresh(pkg, "tracker.html", root=tmp_path)


def test_page_results_updates_only_results_projection_entry(tmp_path):
    pkg = "2026-06-11-demo"
    _write_fact_backed_package(tmp_path, pkg)
    assert _run_projection(tmp_path, pkg, "all").returncode == 0
    before = package_facts.load_facts_js(pkg, root=tmp_path)["projections"]["pages"]
    tracker_before = before["tracker.html"]
    results_source_before = before["results.html"]["sources"]["tables/result_table_P1.csv"]
    paths = package_facts.fact_paths(pkg, root=tmp_path)

    package_facts.upsert_csv_rows(
        paths.tables_dir / "result_table_P1.csv",
        package_facts.RESULT_COLUMNS,
        [{"row_id": "current_best", "value": "43.0"}],
    )
    result = _run_projection(tmp_path, pkg, "results")

    assert result.returncode == 0, result.stderr + result.stdout
    after = package_facts.load_facts_js(pkg, root=tmp_path)["projections"]["pages"]
    assert after["tracker.html"] == tracker_before
    assert after["results.html"]["sources"]["tables/result_table_P1.csv"] != results_source_before


def test_unknown_page_exits_2(tmp_path):
    pkg = "2026-06-11-demo"
    _write_fact_backed_package(tmp_path, pkg)

    result = _run_projection(tmp_path, pkg, "unknown")

    assert result.returncode == 2
