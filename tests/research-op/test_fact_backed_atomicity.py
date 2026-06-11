import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from lib import package_facts


ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "skills" / "research-op" / "scripts" / "research_op.py"
PROPAGATE = ROOT / "skills" / "research-dashboard" / "assets" / "dashboard" / "scripts" / "propagate_apply.py"


def _run(args, cwd):
    return subprocess.run(
        [sys.executable, str(CLI)] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def _write_inventory(root: Path, pkg: str, status: str, *, malformed: bool = False) -> None:
    data = root / "research_html" / "data"
    data.mkdir(parents=True, exist_ok=True)
    if malformed:
        text = (
            "window.RESEARCH_PACKAGES = [\n"
            f"  {{ id: '{pkg}', category: 'in-progress', status: '{status}', methodsTried: []\n"
            "];\n"
        )
    else:
        text = (
            "window.RESEARCH_PACKAGES = [\n"
            f"  {{ id: '{pkg}', category: 'in-progress', status: '{status}', methodsTried: [] }},\n"
            "];\n"
        )
    (data / "research-packages.js").write_text(text, encoding="utf-8")


def _fact_back(root: Path, pkg: str) -> None:
    (root / "research_html" / "data" / "packages" / pkg).mkdir(parents=True, exist_ok=True)


def _write_invalid_tracker(root: Path, pkg: str) -> Path:
    path = root / "research_html" / "packages" / pkg / "tracker.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """<html><body>
<article id="live-check">
  <table data-table="live-check"><tbody data-table-body="live-check"></tbody></table>
</article>
<time data-field="last-updated">2026-06-01</time>
</body></html>
""",
        encoding="utf-8",
    )
    return path


def _actions_log(root: Path, pkg: str) -> Path:
    return root / "outputs" / pkg / "_actions.jsonl"


def test_fact_backed_live_check_insert_does_not_publish_csv_when_rendering_fails(tmp_path):
    pkg = "test-pkg"
    _write_inventory(tmp_path, pkg, "EXPERIMENT_RUNNING")
    _fact_back(tmp_path, pkg)
    tracker = _write_invalid_tracker(tmp_path, pkg)
    tracker_before = tracker.read_text(encoding="utf-8")
    csv_path = package_facts.table_csv_path(pkg, "live_checks", root=tmp_path)

    result = _run([
        "--pkg", pkg,
        "--op", "insert",
        "--target", "tracker-live-check-row",
        "--payload", json.dumps({
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
        }),
    ], cwd=tmp_path)

    assert result.returncode != 0
    assert not csv_path.exists()
    assert tracker.read_text(encoding="utf-8") == tracker_before
    assert not _actions_log(tmp_path, pkg).exists()


def test_fact_backed_methodstried_insert_does_not_publish_csv_when_projection_sync_fails(tmp_path):
    pkg = "test-pkg"
    _write_inventory(tmp_path, pkg, "RESULT_ANALYSIS", malformed=True)
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
    methods_csv = paths.tables_dir / "methods_tried.csv"

    result = _run([
        "--pkg", pkg,
        "--op", "insert",
        "--target", "methodsTried",
        "--payload", json.dumps({
            "exp_id": "P1",
            "source_ref": "result_table_P1:current_best",
            "method": "P1 reranker",
            "hypothesis": "Reranking improves Recall@1",
            "gate": "Recall@1 > 40.0",
        }),
    ], cwd=tmp_path)

    assert result.returncode != 0
    assert not methods_csv.exists()
    assert not _actions_log(tmp_path, pkg).exists()


def test_fact_backed_result_gate_update_rejects_direct_projected_html_edit(tmp_path):
    pkg = "test-pkg"
    _write_inventory(tmp_path, pkg, "RESULT_ANALYSIS")
    _fact_back(tmp_path, pkg)
    results = tmp_path / "research_html" / "packages" / pkg / "results.html"
    results.parent.mkdir(parents=True, exist_ok=True)
    results.write_text(
        """<html><body>
<table data-table="result-gate" data-fact-projection="results">
  <tbody data-table-body="result-gate">
    <tr data-exp-id="P1">
      <td data-field="exp-id">P1</td>
      <td data-field="baseline">old baseline</td>
      <td data-field="plan-gate">old gate</td>
    </tr>
  </tbody>
</table>
</body></html>""",
        encoding="utf-8",
    )
    before = results.read_text(encoding="utf-8")

    result = _run([
        "--pkg", pkg,
        "--op", "update",
        "--target", "results-gate-row",
        "--payload", json.dumps({"exp_id": "P1", "cells": {"baseline": "new baseline"}}),
    ], cwd=tmp_path)

    assert result.returncode != 0
    assert "must update results-gate-row through CSV facts" in result.stderr + result.stdout
    assert results.read_text(encoding="utf-8") == before
    assert not _actions_log(tmp_path, pkg).exists()


def _load_propagate_apply():
    spec = importlib.util.spec_from_file_location("propagate_apply_atomicity", PROPAGATE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_propagate_apply_does_not_publish_partial_surfaces_or_sidecar_on_write_failure(tmp_path, monkeypatch):
    pkg = "2026-06-11-demo"
    _fact_back(tmp_path, pkg)
    registry = tmp_path / "research_html" / "data" / "research-packages.js"
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(
        """window.RESEARCH_PACKAGES = [
  {
    id: "2026-06-11-demo",
    category: "in-progress",
    status: "RESULT_ANALYSIS",
    lastAction: "",
    lastUpdated: "",
    primaryMetricVsGate: "",
    activeGate: "",
    experiments: [
      {
        id: "P1",
        purpose: "run",
        status: "RUNNING",
      },
    ],
    methodsTried: [
    ],
  },
];
""",
        encoding="utf-8",
    )
    results = tmp_path / "research_html" / "packages" / pkg / "results.html"
    tracker = tmp_path / "research_html" / "packages" / pkg / "tracker.html"
    results.parent.mkdir(parents=True, exist_ok=True)
    results.write_text(
        """<html><body>
<table><tr id="P1-row">
<td data-field="observed-metric">old</td>
<td data-field="budget-use">old</td>
<td data-field="artifact-completeness">old</td>
<td data-decision>old</td>
</tr></table>
</body></html>""",
        encoding="utf-8",
    )
    tracker.write_text('<html><body><div data-field="last-action">old</div></body></html>', encoding="utf-8")
    manifest = tmp_path / "outputs" / pkg / "manifests" / "verdict.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps(
            {
                "event": "VERDICT_FINALIZED",
                "exp_id": "P1",
                "row_anchor": "P1-row",
                "measured": {"Recall@1": "42.1"},
                "verdict": "PASS",
                "lastActionPhrase": "P1 passed",
                "hypothesis": "h",
                "gate": "g",
                "evidencePath": "outputs/demo.json",
            }
        ),
        encoding="utf-8",
    )
    before = {
        registry: registry.read_text(encoding="utf-8"),
        results: results.read_text(encoding="utf-8"),
        tracker: tracker.read_text(encoding="utf-8"),
    }
    real_write_text = Path.write_text

    def fail_tracker_projection(path, *args, **kwargs):
        if path.parent == tracker.parent and "tracker.html" in path.name:
            raise OSError("simulated projection write failure")
        return real_write_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_tracker_projection)
    propagate_apply = _load_propagate_apply()

    try:
        propagate_apply.apply_one(manifest, tmp_path, write=True)
    except OSError as exc:
        assert "simulated projection write failure" in str(exc)
    else:
        raise AssertionError("expected simulated projection write failure")

    assert registry.read_text(encoding="utf-8") == before[registry]
    assert results.read_text(encoding="utf-8") == before[results]
    assert tracker.read_text(encoding="utf-8") == before[tracker]
    assert not Path(str(manifest) + ".applied").exists()
