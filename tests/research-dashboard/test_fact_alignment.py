import subprocess
import sys
from pathlib import Path

from lib import package_facts


ROOT = Path(__file__).resolve().parents[2]
LINT = ROOT / "skills" / "research-dashboard" / "assets" / "dashboard" / "scripts" / "learnings_lint.py"


def _write_dashboard(root: Path, pkg: str, result_html: str):
    data = root / "research_html" / "data"
    data.mkdir(parents=True)
    (data / "schema.js").write_text("window.RESEARCH_STATUS_SCHEMA = {};\n", encoding="utf-8")
    (data / "research-packages.js").write_text(
        f'window.RESEARCH_PACKAGES = [{{ id: "{pkg}", category: "in-progress", status: "RESULT_ANALYSIS" }}];\n',
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
