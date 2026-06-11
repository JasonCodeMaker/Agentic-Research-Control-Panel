import csv
import json
import subprocess
import sys
from pathlib import Path

from lib import package_facts


ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "skills" / "research-op" / "scripts" / "research_op.py"


def _run(args, cwd):
    return subprocess.run(
        [sys.executable, str(CLI)] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def _write_inventory(root: Path, pkg: str, status: str) -> None:
    data = root / "research_html" / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "research-packages.js").write_text(
        "window.RESEARCH_PACKAGES = [\n"
        f"  {{ id: '{pkg}', category: 'in-progress', status: '{status}', methodsTried: [], experiments: [{{ id: 'P1', status: 'RUNNING' }}] }},\n"
        "];\n",
        encoding="utf-8",
    )


def _write_tracker(root: Path, pkg: str) -> None:
    path = root / "research_html" / "packages" / pkg / "tracker.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """<html><body>
<article id="live-check"><table data-table="live-check"><tbody data-table-body="live-check"></tbody></table>
<table data-table="live-check-history"><tbody data-table-body="live-check-history"></tbody></table></article>
<article data-card="resource-allocation"><table data-table="resource-allocation"><tbody data-table-body="resource-allocation"></tbody></table></article>
<time data-field="last-updated">2026-06-01</time>
</body></html>
""",
        encoding="utf-8",
    )


def _fact_back(root: Path, pkg: str) -> None:
    (root / "research_html" / "data" / "packages" / pkg).mkdir(parents=True, exist_ok=True)


def _write_results(root: Path, pkg: str) -> None:
    path = root / "research_html" / "packages" / pkg / "results.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """<html><body>
<section data-section="user-zone" id="user-zone">
  <section class="result-blocks" data-list="result-blocks" id="result-blocks"></section>
</section>
<table data-table="result-gate" data-fact-projection="results">
  <tbody data-table-body="result-gate"></tbody>
</table>
<time data-field="last-updated" datetime="2026-06-01">2026-06-01</time>
</body></html>
""",
        encoding="utf-8",
    )


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _last_action(root: Path, pkg: str) -> dict:
    log = root / "outputs" / pkg / "_actions.jsonl"
    return json.loads(log.read_text(encoding="utf-8").splitlines()[-1])


def test_fact_backed_live_check_insert_writes_csv_renders_tracker_and_audits(tmp_path):
    pkg = "test-pkg"
    _write_inventory(tmp_path, pkg, "EXPERIMENT_RUNNING")
    _write_tracker(tmp_path, pkg)
    _fact_back(tmp_path, pkg)
    payload = {
        "row_id": "P1:r1",
        "time": "2026-06-11T10:00:00+10:00",
        "exp_id": "P1",
        "run_id": "r1",
        "agent": "codex",
        "run_state": "RUNNING",
        "last_log": "log line",
        "progress": "2/10",
        "metrics": "Recall@1=42.1",
        "resource": "gpu0",
        "artifacts": "outputs/eval.json",
        "eta": "unknown",
        "action": "CONTINUE_RUN",
        "next_check": "2026-06-11T10:30:00+10:00",
    }

    result = _run([
        "--pkg", pkg,
        "--op", "insert",
        "--target", "tracker-live-check-row",
        "--payload", json.dumps(payload),
    ], cwd=tmp_path)

    assert result.returncode == 0, result.stderr + result.stdout
    csv_path = tmp_path / "research_html" / "data" / "packages" / pkg / "tables" / "live_checks.csv"
    assert _rows(csv_path)[0]["row_id"] == "P1:r1"
    tracker = (tmp_path / "research_html" / "packages" / pkg / "tracker.html").read_text(encoding="utf-8")
    assert 'data-source-row="live_checks:P1:r1"' in tracker
    files = _last_action(tmp_path, pkg)["files_touched"]
    assert str(csv_path) in files or str(csv_path.relative_to(tmp_path)) in files
    assert "research_html/packages/test-pkg/tracker.html" in files


def test_fact_backed_resource_insert_writes_csv_renders_tracker_and_audits(tmp_path):
    pkg = "test-pkg"
    _write_inventory(tmp_path, pkg, "EXPERIMENT_RUNNING")
    _write_tracker(tmp_path, pkg)
    _fact_back(tmp_path, pkg)
    payload = {
        "row_id": "P1:r1",
        "exp_id": "P1",
        "purpose": "main run",
        "dependency": "P0",
        "target": "cuda:0",
        "capacity": "1 GPU",
        "assigned": "codex",
        "reason": "launch",
        "agent": "codex",
        "command_cwd_env": "python train.py",
        "session_job": "tmux",
        "runtime_root": "outputs/test-pkg/runs/r1",
        "log_path": "logs/r1.log",
        "expected_duration": "30m",
        "status": "RUNNING",
    }

    result = _run([
        "--pkg", pkg,
        "--op", "insert",
        "--target", "tracker-resource-allocation-row",
        "--payload", json.dumps(payload),
    ], cwd=tmp_path)

    assert result.returncode == 0, result.stderr + result.stdout
    csv_path = tmp_path / "research_html" / "data" / "packages" / pkg / "tables" / "resource_allocation.csv"
    assert _rows(csv_path)[0]["purpose"] == "main run"
    tracker = (tmp_path / "research_html" / "packages" / pkg / "tracker.html").read_text(encoding="utf-8")
    assert 'data-source-row="resource_allocation:P1:r1"' in tracker
    files = _last_action(tmp_path, pkg)["files_touched"]
    assert str(csv_path) in files or str(csv_path.relative_to(tmp_path)) in files
    assert "research_html/packages/test-pkg/tracker.html" in files


def test_fact_backed_methodstried_insert_uses_source_ref_and_syncs_projection(tmp_path):
    pkg = "test-pkg"
    _write_inventory(tmp_path, pkg, "RESULT_ANALYSIS")
    _fact_back(tmp_path, pkg)
    paths = package_facts.fact_paths(pkg, root=tmp_path)
    package_facts.upsert_csv_rows(paths.tables_dir / "result_table_P1.csv", package_facts.RESULT_COLUMNS, [
        {
            "row_id": "current_best",
            "exp_id": "P1",
            "metric": "Recall@1",
            "value": "42.1",
            "unit": "%",
            "verdict": "PASS",
            "source_artifact": "outputs/test-pkg/runs/r1/summary.json",
        }
    ])
    payload = {
        "exp_id": "P1",
        "source_ref": "result_table_P1:current_best",
        "method": "P1 reranker",
        "hypothesis": "Reranking improves Recall@1",
        "gate": "Recall@1 > 40.0",
    }

    result = _run([
        "--pkg", pkg,
        "--op", "insert",
        "--target", "methodsTried",
        "--payload", json.dumps(payload),
    ], cwd=tmp_path)

    assert result.returncode == 0, result.stderr + result.stdout
    methods_csv = paths.tables_dir / "methods_tried.csv"
    assert _rows(methods_csv)[0]["measured"] == "Recall@1=42.1%"
    registry = (tmp_path / "research_html" / "data" / "research-packages.js").read_text(encoding="utf-8")
    assert '"method": "P1 reranker"' in registry
    assert '"source_table"' not in registry
    files = _last_action(tmp_path, pkg)["files_touched"]
    assert str(methods_csv) in files or str(methods_csv.relative_to(tmp_path)) in files
    assert "research_html/data/research-packages.js" in files


def test_fact_backed_checkpoint_saved_event_writes_result_facts_and_completes(tmp_path):
    pkg = "test-pkg"
    _write_inventory(tmp_path, pkg, "RESULT_ANALYSIS")
    _write_tracker(tmp_path, pkg)
    _write_results(tmp_path, pkg)
    _fact_back(tmp_path, pkg)

    result = _run([
        "--pkg", pkg,
        "--event", "CHECKPOINT_SAVED",
        "--payload", json.dumps({
            "exp_id": "P1",
            "artifact": "outputs/test-pkg/runs/r1/checkpoint.pt",
            "measured": "Recall@1=42.1",
        }),
    ], cwd=tmp_path)

    assert result.returncode == 0, result.stderr + result.stdout
    result_gate = tmp_path / "research_html" / "data" / "packages" / pkg / "tables" / "result_gate.csv"
    rows = _rows(result_gate)
    assert rows[0]["row_id"] == "P1_gate"
    assert rows[0]["metric"] == "Recall@1"
    assert rows[0]["value"] == "42.1"
    assert rows[0]["source_artifact"] == "outputs/test-pkg/runs/r1/checkpoint.pt"
    results = (tmp_path / "research_html" / "packages" / pkg / "results.html").read_text(encoding="utf-8")
    assert 'data-source-row="result_gate:P1_gate"' in results
    assert "update:results-verdict" not in result.stdout
    assert _last_action(tmp_path, pkg)["validation"] == "PASSED"


def test_fact_backed_results_gate_insert_accepts_canonical_fact_validity_enum(tmp_path):
    pkg = "test-pkg"
    _write_inventory(tmp_path, pkg, "RESULT_ANALYSIS")
    _write_results(tmp_path, pkg)
    _fact_back(tmp_path, pkg)

    result = _run([
        "--pkg", pkg,
        "--op", "insert",
        "--target", "results-gate-row",
        "--payload", json.dumps({
            "row_id": "P1_diag",
            "exp_id": "P1",
            "validity": "DIAGNOSTIC_ONLY",
            "baseline": "40.0",
            "plan_gate": "Recall@1",
            "observed_metric": "Recall@1=39.0",
            "budget_use": "1 GPU hour",
            "seed_status": "seed 1",
            "artifact_completeness": "ok",
            "verdict": "INCONCLUSIVE",
            "reason": "diagnostic pass",
            "source_artifact": "outputs/test-pkg/runs/r1/summary.json",
        }),
    ], cwd=tmp_path)

    assert result.returncode == 0, result.stderr + result.stdout
    result_gate = tmp_path / "research_html" / "data" / "packages" / pkg / "tables" / "result_gate.csv"
    assert _rows(result_gate)[0]["validity"] == "DIAGNOSTIC_ONLY"
    assert 'data-source-row="result_gate:P1_diag"' in (
        tmp_path / "research_html" / "packages" / pkg / "results.html"
    ).read_text(encoding="utf-8")
