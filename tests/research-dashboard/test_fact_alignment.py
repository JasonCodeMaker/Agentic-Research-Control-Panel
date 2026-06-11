import subprocess
import sys
from pathlib import Path

from lib import package_facts


ROOT = Path(__file__).resolve().parents[2]
LINT = ROOT / "skills" / "research-dashboard" / "assets" / "dashboard" / "scripts" / "learnings_lint.py"


def _write_dashboard(root: Path, pkg: str, result_html: str, *, tracker_html: str = "", methods_tried: str = "[]"):
    data = root / "research_html" / "data"
    data.mkdir(parents=True)
    (data / "schema.js").write_text("window.RESEARCH_STATUS_SCHEMA = {};\n", encoding="utf-8")
    (data / "research-packages.js").write_text(
        f'window.RESEARCH_PACKAGES = [{{ id: "{pkg}", category: "in-progress", status: "RESULT_ANALYSIS", methodsTried: {methods_tried} }}];\n',
        encoding="utf-8",
    )
    scripts = root / "research_html" / "scripts"
    scripts.mkdir(parents=True)
    package_dir = root / "research_html" / "packages" / pkg
    package_dir.mkdir(parents=True)
    (package_dir / "results.html").write_text(result_html, encoding="utf-8")
    if tracker_html:
        (package_dir / "tracker.html").write_text(tracker_html, encoding="utf-8")


def test_fact_alignment_passes_when_source_row_exists(tmp_path):
    pkg = "2026-06-11-demo"
    _write_dashboard(tmp_path, pkg, '''
<html><body>
<article data-fact-projection="results" data-source="tables/result_table_P1.csv" data-fact-revision="sha256:x">
  <span data-source-row="result_table_P1:current_best">42.1</span>
</article>
</body></html>
''')
    paths = package_facts.fact_paths(pkg, root=tmp_path)
    package_facts.upsert_csv_rows(paths.tables_dir / "result_table_P1.csv", package_facts.RESULT_COLUMNS, [
        {"row_id": "current_best", "exp_id": "P1", "metric": "Recall@1", "value": "42.1", "validity": "VALID"}
    ])
    package_facts.record_page_projection(
        pkg,
        "results.html",
        ["tables/result_table_P1.csv"],
        tmp_path / "research_html" / "packages" / pkg / "results.html",
        "render_result_facts.py",
        root=tmp_path,
    )

    result = subprocess.run([
        sys.executable, str(LINT),
        "fact-alignment",
        "--pkg", pkg,
        "--repo-root", str(tmp_path),
    ], capture_output=True, text=True)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "errors=0" in result.stdout
    assert "migration-state=partial" in result.stdout


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


def test_fact_alignment_resolves_tracker_source_rows(tmp_path):
    pkg = "2026-06-11-demo"
    _write_dashboard(tmp_path, pkg, "<html><body></body></html>", tracker_html='''
<html><body>
<table data-fact-projection="tracker" data-source="tables/live_checks.csv" data-fact-revision="sha256:x">
  <tbody data-table-body="live-check">
    <tr data-source-row="live_checks:P1:P1-r1"><td>RUNNING</td></tr>
  </tbody>
</table>
</body></html>
''')
    paths = package_facts.fact_paths(pkg, root=tmp_path)
    package_facts.upsert_csv_rows(paths.tables_dir / "live_checks.csv", package_facts.LIVE_CHECK_COLUMNS, [
        {"row_id": "P1:P1-r1", "exp_id": "P1", "run_id": "P1-r1", "run_state": "RUNNING"}
    ])
    package_facts.record_page_projection(
        pkg,
        "tracker.html",
        ["tables/live_checks.csv"],
        tmp_path / "research_html" / "packages" / pkg / "tracker.html",
        "render_tracker_facts.py",
        root=tmp_path,
    )

    result = subprocess.run([
        sys.executable, str(LINT),
        "fact-alignment",
        "--pkg", pkg,
        "--repo-root", str(tmp_path),
    ], capture_output=True, text=True)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "fact-source-row-missing" not in result.stdout


def test_fact_alignment_fails_when_tracker_source_row_is_missing(tmp_path):
    pkg = "2026-06-11-demo"
    _write_dashboard(tmp_path, pkg, "<html><body></body></html>", tracker_html='''
<html><body>
<table data-source="tables/live_checks.csv" data-fact-revision="sha256:x">
  <tbody data-table-body="live-check">
    <tr data-source-row="live_checks:P1:missing"><td>RUNNING</td></tr>
  </tbody>
</table>
</body></html>
''')
    paths = package_facts.fact_paths(pkg, root=tmp_path)
    package_facts.upsert_csv_rows(paths.tables_dir / "live_checks.csv", package_facts.LIVE_CHECK_COLUMNS, [
        {"row_id": "P1:P1-r1", "exp_id": "P1", "run_id": "P1-r1", "run_state": "RUNNING"}
    ])

    result = subprocess.run([
        sys.executable, str(LINT),
        "fact-alignment",
        "--pkg", pkg,
        "--repo-root", str(tmp_path),
    ], capture_output=True, text=True)

    assert result.returncode == 1
    assert "fact-source-row-missing" in result.stdout


def test_fact_alignment_fails_when_methods_projection_is_stale(tmp_path):
    pkg = "2026-06-11-demo"
    _write_dashboard(
        tmp_path,
        pkg,
        "<html><body></body></html>",
        methods_tried='[{ method: "P1 reranker", hypothesis: "h", gate: "g", measured: "old", verdict: "PASS", evidencePath: "e.json" }]',
    )
    paths = package_facts.fact_paths(pkg, root=tmp_path)
    package_facts.upsert_csv_rows(paths.tables_dir / "methods_tried.csv", package_facts.METHODS_TRIED_COLUMNS, [
        {
            "row_id": "P1:method",
            "exp_id": "P1",
            "method": "P1 reranker",
            "hypothesis": "h",
            "gate": "g",
            "measured": "new",
            "verdict": "PASS",
            "evidencePath": "e.json",
        }
    ])

    result = subprocess.run([
        sys.executable, str(LINT),
        "fact-alignment",
        "--pkg", pkg,
        "--repo-root", str(tmp_path),
    ], capture_output=True, text=True)

    assert result.returncode == 1
    assert "methods-projection-stale" in result.stdout


def test_fact_alignment_fails_when_duplicate_display_values_use_different_row_ids(tmp_path):
    pkg = "2026-06-11-demo"
    _write_dashboard(tmp_path, pkg, '''
<html><body>
<article data-source="tables/result_table_P1.csv" data-fact-revision="sha256:x">
  <span data-source-row="result_table_P1:best">42.1</span>
  <span data-source-row="result_table_P1:copied">42.1</span>
</article>
</body></html>
''')
    paths = package_facts.fact_paths(pkg, root=tmp_path)
    package_facts.upsert_csv_rows(paths.tables_dir / "result_table_P1.csv", package_facts.RESULT_COLUMNS, [
        {"row_id": "best", "exp_id": "P1", "metric": "Recall@1", "value": "42.1", "validity": "VALID"},
        {"row_id": "copied", "exp_id": "P1", "metric": "Recall@1", "value": "42.1", "validity": "VALID"},
    ])

    result = subprocess.run([
        sys.executable, str(LINT),
        "fact-alignment",
        "--pkg", pkg,
        "--repo-root", str(tmp_path),
    ], capture_output=True, text=True)

    assert result.returncode == 1
    assert "fact-duplicate-display-row-mismatch" in result.stdout


def test_fact_alignment_fails_when_result_table_lacks_extractor_manifest(tmp_path):
    pkg = "2026-06-11-demo"
    _write_dashboard(tmp_path, pkg, '''
<html><body>
<article data-source="tables/result_table_P1.csv" data-fact-revision="sha256:x">
  <span data-source-row="result_table_P1:best">42.1</span>
</article>
</body></html>
''')
    paths = package_facts.fact_paths(pkg, root=tmp_path)
    package_facts.upsert_csv_rows(paths.tables_dir / "result_table_P1.csv", package_facts.RESULT_COLUMNS, [
        {
            "row_id": "best",
            "exp_id": "P1",
            "metric": "Recall@1",
            "value": "42.1",
            "validity": "VALID",
            "extractor": "extract_result_table.py",
        }
    ])

    result = subprocess.run([
        sys.executable, str(LINT),
        "fact-alignment",
        "--pkg", pkg,
        "--repo-root", str(tmp_path),
    ], capture_output=True, text=True)

    assert result.returncode == 1
    assert "extractor-manifest-missing" in result.stdout


def test_fact_alignment_warns_for_legacy_package_without_fact_dir(tmp_path):
    pkg = "2026-06-11-demo"
    _write_dashboard(tmp_path, pkg, "<html><body><p>legacy html</p></body></html>")

    result = subprocess.run([
        sys.executable, str(LINT),
        "fact-alignment",
        "--pkg", pkg,
        "--repo-root", str(tmp_path),
    ], capture_output=True, text=True)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "fact-no-projection" in result.stdout


def _write_projected_page(root: Path, pkg: str, page: str, body: str) -> Path:
    path = root / "research_html" / "packages" / pkg / page
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_strict_fact_alignment_passes_for_fresh_page_projection_metadata(tmp_path):
    pkg = "2026-06-11-demo"
    _write_dashboard(tmp_path, pkg, "", tracker_html="")
    paths = package_facts.fact_paths(pkg, root=tmp_path)
    package_facts.upsert_csv_rows(paths.tables_dir / "result_table_P1.csv", package_facts.RESULT_COLUMNS, [
        {"row_id": "best", "exp_id": "P1", "metric": "Recall@1", "value": "42.1"}
    ])
    package_facts.upsert_csv_rows(paths.tables_dir / "live_checks.csv", package_facts.LIVE_CHECK_COLUMNS, [
        {"row_id": "P1:r1", "exp_id": "P1", "run_id": "r1"}
    ])
    results = _write_projected_page(
        tmp_path, pkg, "results.html",
        '<html><body><section data-fact-projection="results" data-source-row="result_table_P1:best">42.1</section></body></html>',
    )
    tracker = _write_projected_page(
        tmp_path, pkg, "tracker.html",
        '<html><body><article data-fact-projection="tracker" data-source-row="live_checks:P1:r1">RUNNING</article></body></html>',
    )
    package_facts.record_page_projection(pkg, "results.html", ["tables/result_table_P1.csv"], results, "render_result_facts.py", root=tmp_path)
    package_facts.record_page_projection(pkg, "tracker.html", ["tables/live_checks.csv"], tracker, "render_tracker_facts.py", root=tmp_path)

    result = subprocess.run([
        sys.executable, str(LINT),
        "--strict",
        "fact-alignment",
        "--pkg", pkg,
        "--repo-root", str(tmp_path),
    ], capture_output=True, text=True)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "errors=0" in result.stdout


def test_strict_fact_alignment_fails_stale_projection_source(tmp_path):
    pkg = "2026-06-11-demo"
    _write_dashboard(tmp_path, pkg, "")
    paths = package_facts.fact_paths(pkg, root=tmp_path)
    csv_path = paths.tables_dir / "result_table_P1.csv"
    package_facts.upsert_csv_rows(csv_path, package_facts.RESULT_COLUMNS, [
        {"row_id": "best", "exp_id": "P1", "metric": "Recall@1", "value": "42.1"}
    ])
    results = _write_projected_page(
        tmp_path, pkg, "results.html",
        '<html><body><section data-fact-projection="results" data-source-row="result_table_P1:best">42.1</section></body></html>',
    )
    package_facts.record_page_projection(pkg, "results.html", ["tables/result_table_P1.csv"], results, "render_result_facts.py", root=tmp_path)
    package_facts.upsert_csv_rows(csv_path, package_facts.RESULT_COLUMNS, [
        {"row_id": "best", "exp_id": "P1", "metric": "Recall@1", "value": "43.0"}
    ])

    result = subprocess.run([
        sys.executable, str(LINT),
        "fact-alignment",
        "--pkg", pkg,
        "--repo-root", str(tmp_path),
    ], capture_output=True, text=True)

    assert result.returncode == 1
    assert "projection-stale-source" in result.stdout


def test_strict_fact_alignment_fails_stale_projection_html(tmp_path):
    pkg = "2026-06-11-demo"
    _write_dashboard(tmp_path, pkg, "")
    paths = package_facts.fact_paths(pkg, root=tmp_path)
    package_facts.upsert_csv_rows(paths.tables_dir / "result_table_P1.csv", package_facts.RESULT_COLUMNS, [
        {"row_id": "best", "exp_id": "P1", "metric": "Recall@1", "value": "42.1"}
    ])
    results = _write_projected_page(
        tmp_path, pkg, "results.html",
        '<html><body><section data-fact-projection="results" data-source-row="result_table_P1:best">42.1</section></body></html>',
    )
    package_facts.record_page_projection(pkg, "results.html", ["tables/result_table_P1.csv"], results, "render_result_facts.py", root=tmp_path)
    results.write_text(results.read_text(encoding="utf-8") + "<p>hand edit</p>", encoding="utf-8")

    result = subprocess.run([
        sys.executable, str(LINT),
        "fact-alignment",
        "--pkg", pkg,
        "--repo-root", str(tmp_path),
    ], capture_output=True, text=True)

    assert result.returncode == 1
    assert "projection-stale-html" in result.stdout


def test_strict_fact_alignment_fails_missing_projection_marker(tmp_path):
    pkg = "2026-06-11-demo"
    _write_dashboard(tmp_path, pkg, "")
    paths = package_facts.fact_paths(pkg, root=tmp_path)
    package_facts.upsert_csv_rows(paths.tables_dir / "result_table_P1.csv", package_facts.RESULT_COLUMNS, [
        {"row_id": "best", "exp_id": "P1", "metric": "Recall@1", "value": "42.1"}
    ])
    results = _write_projected_page(
        tmp_path, pkg, "results.html",
        '<html><body><section data-source-row="result_table_P1:best">42.1</section></body></html>',
    )
    package_facts.record_page_projection(pkg, "results.html", ["tables/result_table_P1.csv"], results, "render_result_facts.py", root=tmp_path)

    result = subprocess.run([
        sys.executable, str(LINT),
        "fact-alignment",
        "--pkg", pkg,
        "--repo-root", str(tmp_path),
    ], capture_output=True, text=True)

    assert result.returncode == 1
    assert "projection-marker-missing" in result.stdout
