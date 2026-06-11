import json
import subprocess
import sys
from pathlib import Path

from lib import package_facts


ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "skills" / "research-dashboard" / "assets" / "dashboard" / "scripts" / "audit_fact_migration.py"


def _write_dashboard(root: Path, packages: list[str]) -> None:
    data = root / "research_html" / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "schema.js").write_text("window.RESEARCH_STATUS_SCHEMA = {};\n", encoding="utf-8")
    rows = ",\n".join(f'  {{ id: "{pkg}", category: "in-progress", status: "RESULT_ANALYSIS" }}' for pkg in packages)
    (data / "research-packages.js").write_text(f"window.RESEARCH_PACKAGES = [\n{rows}\n];\n", encoding="utf-8")


def _write_page(root: Path, pkg: str, page: str, body: str) -> Path:
    path = root / "research_html" / "packages" / pkg / page
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def _write_result_fact(root: Path, pkg: str) -> Path:
    paths = package_facts.fact_paths(pkg, root=root)
    package_facts.upsert_csv_rows(paths.tables_dir / "result_gate.csv", package_facts.RESULT_COLUMNS, [
        {"row_id": "P1_gate", "exp_id": "P1", "metric": "Recall@1", "value": "42.1"}
    ])
    return paths.tables_dir / "result_gate.csv"


def _write_tracker_fact(root: Path, pkg: str) -> Path:
    paths = package_facts.fact_paths(pkg, root=root)
    package_facts.upsert_csv_rows(paths.tables_dir / "live_checks.csv", package_facts.LIVE_CHECK_COLUMNS, [
        {"row_id": "P1:r1", "exp_id": "P1", "run_id": "r1", "run_state": "RUNNING"}
    ])
    return paths.tables_dir / "live_checks.csv"


def _write_methods_fact(root: Path, pkg: str) -> Path:
    paths = package_facts.fact_paths(pkg, root=root)
    package_facts.upsert_csv_rows(paths.tables_dir / "methods_tried.csv", package_facts.METHODS_TRIED_COLUMNS, [
        {
            "row_id": "P1:method",
            "exp_id": "P1",
            "method": "P1",
            "hypothesis": "h",
            "gate": "g",
            "measured": "m",
            "verdict": "PASS",
            "evidencePath": "outputs/e.json",
        }
    ])
    return paths.tables_dir / "methods_tried.csv"


def _record_results_projection(root: Path, pkg: str, sources=None) -> None:
    results = _write_page(
        root,
        pkg,
        "results.html",
        '<html><body><section data-fact-projection="results" data-source-row="result_gate:P1_gate">42.1</section></body></html>',
    )
    package_facts.record_page_projection(
        pkg,
        "results.html",
        sources or ["tables/result_gate.csv"],
        results,
        "render_result_facts.py",
        root=root,
    )


def _record_tracker_projection(root: Path, pkg: str, sources=None) -> None:
    tracker = _write_page(
        root,
        pkg,
        "tracker.html",
        '<html><body><article data-fact-projection="tracker" data-source-row="live_checks:P1:r1">RUNNING</article></body></html>',
    )
    package_facts.record_page_projection(
        pkg,
        "tracker.html",
        sources or ["tables/live_checks.csv"],
        tracker,
        "render_tracker_facts.py",
        root=root,
    )


def _run_json(root: Path, *args: str) -> dict:
    result = subprocess.run(
        [sys.executable, str(AUDIT), "--repo-root", str(root), "--json", *args],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    return json.loads(result.stdout)


def test_audit_fact_migration_reports_legacy_partial_fact_backed_and_stale(tmp_path):
    legacy = "2026-06-11-legacy"
    partial = "2026-06-11-partial"
    full = "2026-06-11-full"
    stale = "2026-06-11-stale"
    _write_dashboard(tmp_path, [legacy, partial, full, stale])

    _write_result_fact(tmp_path, partial)
    _record_results_projection(tmp_path, partial)

    _write_result_fact(tmp_path, full)
    _write_tracker_fact(tmp_path, full)
    _write_methods_fact(tmp_path, full)
    _record_results_projection(tmp_path, full)
    _record_tracker_projection(tmp_path, full)

    stale_csv = _write_result_fact(tmp_path, stale)
    _record_results_projection(tmp_path, stale)
    package_facts.upsert_csv_rows(stale_csv, package_facts.RESULT_COLUMNS, [
        {"row_id": "P1_gate", "exp_id": "P1", "metric": "Recall@1", "value": "43.0"}
    ])

    report = _run_json(tmp_path)
    states = {item["id"]: item["state"] for item in report["packages"]}

    assert states[legacy] == "legacy"
    assert states[partial] == "partial"
    assert states[full] == "fact-backed"
    assert states[stale] == "stale"
    assert report["counts"] == {
        "legacy": 1,
        "partial": 1,
        "fact-backed": 1,
        "stale": 1,
    }


def test_audit_fact_migration_can_filter_one_package_as_json(tmp_path):
    pkg = "2026-06-11-full"
    _write_dashboard(tmp_path, [pkg])
    _write_result_fact(tmp_path, pkg)
    _write_tracker_fact(tmp_path, pkg)
    _write_methods_fact(tmp_path, pkg)
    _record_results_projection(tmp_path, pkg)
    _record_tracker_projection(tmp_path, pkg)

    report = _run_json(tmp_path, "--pkg", pkg)

    assert report["packages"] == [
        {
            "id": pkg,
            "state": "fact-backed",
            "tables": {
                "result": True,
                "tracker": True,
                "methods": True,
            },
            "requiredPages": ["results.html", "tracker.html"],
            "stale": [],
        }
    ]
