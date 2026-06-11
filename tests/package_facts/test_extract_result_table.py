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
