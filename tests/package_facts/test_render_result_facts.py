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
