import subprocess
import sys
import textwrap
from pathlib import Path

from lib import package_facts


ROOT = Path(__file__).resolve().parents[2]
APPEND_SCRIPT = ROOT / "skills" / "research-package" / "scripts" / "append_methods_tried_fact.py"
SYNC_SCRIPT = ROOT / "skills" / "research-package" / "scripts" / "sync_methods_tried_projection.py"
PKG = "2026-06-11-methods-demo"


def _run(script: Path, repo_root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script), "--repo-root", str(repo_root), "--pkg", PKG, *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _write_registry(repo_root: Path) -> Path:
    path = repo_root / "research_html" / "data" / "research-packages.js"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        textwrap.dedent(
            f"""\
            window.RESEARCH_PACKAGES = [
              {{
                id: "{PKG}",
                name: "Methods Demo",
                category: "in-progress",
                methodsTried: [
                  {{ method: "legacy", hypothesis: "old", gate: "old gate", measured: "old metric", verdict: "FAIL", evidencePath: "old/path.json" }},
                ],
                experiments: [{{ id: "P1", status: "COMPLETED" }}],
              }},
              {{
                id: "other-pkg",
                name: "Other Package",
                methodsTried: [
                  {{ method: "keep legacy", hypothesis: "stay", gate: "stay", measured: "stay", verdict: "PASS", evidencePath: "other/path.json" }},
                ],
              }},
            ];
            """
        ),
        encoding="utf-8",
    )
    return path


def test_append_methods_tried_from_result_row_and_syncs_registry_projection(tmp_path):
    paths = package_facts.fact_paths(PKG, root=tmp_path)
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
                "verdict": "PASS",
                "source_artifact": "outputs/pkg/run/summary.json",
            }
        ],
    )
    registry = _write_registry(tmp_path)

    result = _run(
        APPEND_SCRIPT,
        tmp_path,
        "--exp-id",
        "P1",
        "--source-ref",
        "result_table_P1:current_best",
        "--method",
        "P1 reranker",
        "--hypothesis",
        "Reranking improves Recall@1",
        "--gate",
        "Recall@1 > 40.0",
    )
    assert result.returncode == 0, result.stderr

    rows = package_facts.read_csv_rows(paths.tables_dir / "methods_tried.csv")
    assert len(rows) == 1
    assert rows[0]["measured"] == "Recall@1=42.1%"
    assert rows[0]["verdict"] == "PASS"
    assert rows[0]["source_table"] == "result_table_P1"
    assert rows[0]["source_row"] == "current_best"
    assert rows[0]["evidencePath"] == "outputs/pkg/run/summary.json"

    result = _run(SYNC_SCRIPT, tmp_path)
    assert result.returncode == 0, result.stderr

    text = registry.read_text(encoding="utf-8")
    selected_block = text.split(f'id: "{PKG}"', 1)[1].split('id: "other-pkg"', 1)[0]
    assert '"method": "P1 reranker"' in selected_block
    assert '"hypothesis": "Reranking improves Recall@1"' in selected_block
    assert '"gate": "Recall@1 > 40.0"' in selected_block
    assert '"measured": "Recall@1=42.1%"' in selected_block
    assert '"verdict": "PASS"' in selected_block
    assert '"evidencePath": "outputs/pkg/run/summary.json"' in selected_block
    assert '"source_table"' not in selected_block
    assert '"source_row"' not in selected_block
    assert '"source_artifact"' not in selected_block
    assert 'method: "keep legacy"' in text


def test_append_methods_tried_rejects_manual_pass_source_rows(tmp_path):
    paths = package_facts.fact_paths(PKG, root=tmp_path)
    package_facts.upsert_csv_rows(
        paths.tables_dir / "result_table_P1.csv",
        package_facts.RESULT_COLUMNS + ["source_type"],
        [
            {
                "row_id": "manual_best",
                "exp_id": "P1",
                "metric": "Recall@1",
                "value": "42.1",
                "unit": "%",
                "verdict": "PASS",
                "source_artifact": "outputs/pkg/run/summary.json",
                "source_type": "manual",
            }
        ],
    )

    result = _run(
        APPEND_SCRIPT,
        tmp_path,
        "--exp-id",
        "P1",
        "--source-ref",
        "result_table_P1:manual_best",
        "--method",
        "manual reranker",
        "--hypothesis",
        "Manual row should not certify PASS",
        "--gate",
        "Recall@1 > 40.0",
    )
    assert result.returncode == 2
    assert "manual PASS" in result.stderr
    assert not (paths.tables_dir / "methods_tried.csv").exists()
