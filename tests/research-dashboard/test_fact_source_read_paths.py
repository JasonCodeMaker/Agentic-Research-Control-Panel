import sys
from pathlib import Path

from lib import package_facts


SCRIPTS = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "research-dashboard"
    / "assets"
    / "dashboard"
    / "scripts"
)
sys.path.insert(0, str(SCRIPTS))
import learnings_lint  # noqa: E402


def _set_roots(tmp_path, monkeypatch):
    monkeypatch.setattr(learnings_lint, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(learnings_lint, "DASHBOARD_ROOT", tmp_path / "research_html")
    monkeypatch.setattr(learnings_lint, "PACKAGES_DIR", tmp_path / "research_html" / "packages")
    monkeypatch.setattr(learnings_lint, "SCOPE_LOG", tmp_path / "outputs" / "_scope" / "transitions.jsonl")


def _pkg_dir(tmp_path, pkg):
    path = tmp_path / "research_html" / "packages" / pkg
    path.mkdir(parents=True, exist_ok=True)
    return path


def _result_gate_html(exp_id="P1", measured="Recall@1=10%"):
    return f"""<html><body>
<table data-table="result-table-{exp_id}" data-exp-id="{exp_id}"></table>
<table data-table="result-gate">
  <tbody>
    <tr data-exp-id="{exp_id}">
      <td>{exp_id}</td>
      <td><span data-validity="VALID">VALID</span></td>
      <td>40.0</td>
      <td>legacy html gate</td>
      <td>{measured}</td>
      <td>1 GPU-hour</td>
      <td>42</td>
      <td>outputs/html.json</td>
      <td><span data-validity="PASS">PASS</span></td>
      <td>legacy html reason</td>
    </tr>
  </tbody>
</table>
</body></html>"""


def _write_result_gate_csv(tmp_path, pkg, *, value="99", verdict="PASS"):
    paths = package_facts.fact_paths(pkg, root=tmp_path)
    package_facts.upsert_csv_rows(
        paths.tables_dir / "result_gate.csv",
        package_facts.RESULT_COLUMNS,
        [
            {
                "row_id": "P1_gate",
                "exp_id": "P1",
                "metric": "Recall@1",
                "value": value,
                "unit": "%",
                "baseline": "40.0",
                "verdict": verdict,
                "validity": "VALID",
                "source_artifact": "outputs/facts.json",
            }
        ],
    )
    return paths


def test_draft_method_reads_result_gate_csv_before_results_html(tmp_path, monkeypatch):
    _set_roots(tmp_path, monkeypatch)
    pkg = "2026-06-11-demo"
    pdir = _pkg_dir(tmp_path, pkg)
    (pdir / "results.html").write_text(_result_gate_html(measured="Recall@1=10%"), encoding="utf-8")
    _write_result_gate_csv(tmp_path, pkg, value="99")

    drafts = learnings_lint.detect_e1({"id": pkg, "methodsTried": []})

    assert len(drafts) == 1
    assert drafts[0]["draft"]["gate"] == "Recall@1"
    assert drafts[0]["draft"]["measured"] == "Recall@1=99%"
    assert "legacy html" not in drafts[0]["draft"]["hypothesis"]


def test_alignment_result_rows_read_result_gate_csv_before_results_html(tmp_path, monkeypatch):
    _set_roots(tmp_path, monkeypatch)
    pkg = "2026-06-11-demo"
    pdir = _pkg_dir(tmp_path, pkg)
    (pdir / "results.html").write_text(
        '<html><body><table data-table="result-table-P1" data-exp-id="P1"></table></body></html>',
        encoding="utf-8",
    )
    (pdir / "tracker.html").write_text(
        """<html><body>
<ul data-field="todo-list"><li data-exp-id="P1">run P1</li></ul>
<table data-table="resource-allocation"></table>
<table data-table="live-check"></table>
</body></html>""",
        encoding="utf-8",
    )
    _write_result_gate_csv(tmp_path, pkg, value="", verdict="")
    package = {
        "id": pkg,
        "experiments": [
            {
                "id": "P1",
                "purpose": "measure retrieval",
                "gate": "Recall@1",
                "output": "result gate row",
                "measures": True,
                "requiresCode": False,
                "complex": False,
                "status": "pending",
            }
        ],
    }

    rep = learnings_lint.assess_alignment(package, pdir)

    assert "alignment-result-row-missing" not in {v.code for v in rep.violations}


def test_evidence_checks_use_methods_csv_for_fact_backed_and_registry_for_legacy(tmp_path, monkeypatch):
    _set_roots(tmp_path, monkeypatch)
    fact_pkg = "2026-06-11-fact"
    legacy_pkg = "2026-06-11-legacy"
    (tmp_path / "existing.json").write_text("{}", encoding="utf-8")
    package_facts.upsert_csv_rows(
        package_facts.fact_paths(fact_pkg, root=tmp_path).tables_dir / "methods_tried.csv",
        package_facts.METHODS_TRIED_COLUMNS,
        [
            {
                "row_id": "P1:method",
                "exp_id": "P1",
                "method": "P1",
                "hypothesis": "h",
                "gate": "g",
                "measured": "m",
                "verdict": "PASS",
                "evidencePath": "missing-from-csv.json",
            }
        ],
    )
    data = {
        "packages": [
            {
                "id": fact_pkg,
                "lastDecisionEvidencePath": "",
                "methodsTried": [
                    {"method": "P1", "evidencePath": "existing.json"},
                ],
            },
            {
                "id": legacy_pkg,
                "lastDecisionEvidencePath": "",
                "methodsTried": [
                    {"method": "L1", "evidencePath": "missing-legacy.json"},
                ],
            },
        ]
    }

    rep = learnings_lint.lint_evidence(data)
    messages = "\n".join(v.message for v in rep.violations)

    assert "missing-from-csv.json" in messages
    assert "missing-legacy.json" in messages


def test_fact_alignment_reports_stale_projection_when_html_conflicts_with_csv(tmp_path, monkeypatch):
    _set_roots(tmp_path, monkeypatch)
    pkg = "2026-06-11-demo"
    pdir = _pkg_dir(tmp_path, pkg)
    paths = _write_result_gate_csv(tmp_path, pkg, value="99")
    results = pdir / "results.html"
    results.write_text(
        '<html><body><section data-fact-projection="results" data-source-row="result_gate:P1_gate">Recall@1=99%</section></body></html>',
        encoding="utf-8",
    )
    package_facts.record_page_projection(
        pkg,
        "results.html",
        ["tables/result_gate.csv"],
        results,
        "render_result_facts.py",
        root=tmp_path,
    )
    results.write_text(
        '<html><body><section data-fact-projection="results" data-source-row="result_gate:P1_gate">Recall@1=10%</section></body></html>',
        encoding="utf-8",
    )

    rep = learnings_lint.lint_fact_alignment(
        {"packages": [{"id": pkg, "methodsTried": []}]},
        pkg_filter=pkg,
        repo_root=tmp_path,
    )

    assert "projection-stale-html" in {v.code for v in rep.violations}
    assert paths.tables_dir.exists()
