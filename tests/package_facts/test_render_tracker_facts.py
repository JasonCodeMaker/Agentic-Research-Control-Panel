import re
import subprocess
import sys
from pathlib import Path

from lib import package_facts


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills" / "research-package" / "scripts" / "render_tracker_facts.py"


def _write_tracker_shell(root: Path, pkg: str) -> Path:
    path = root / "research_html" / "packages" / pkg / "tracker.html"
    path.parent.mkdir(parents=True)
    path.write_text(
        """<!doctype html>
<html><body>
<article id="todo"><ul data-field="todo-list"><li><label><input type="checkbox"> keep todo</label></li></ul></article>
<article id="live-check" data-card="live-check-user">
  <table class="data-table" data-table="live-check">
    <tbody data-table-body="live-check"></tbody>
  </table>
  <table class="data-table" data-table="live-check-history">
    <tbody data-table-body="live-check-history"></tbody>
  </table>
</article>
<article id="resume-block"><div data-field="last-action">keep resume</div></article>
<section id="chosen-route"><div data-field="chosen-route">keep route</div></section>
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


def _tbody(text: str, name: str) -> str:
    match = re.search(rf'<tbody[^>]*data-table-body="{name}"[^>]*>(.*?)</tbody>', text, re.DOTALL)
    assert match, f"missing tbody {name}"
    return match.group(1)


def test_renders_tracker_tables_from_csv_facts(tmp_path):
    pkg = "2026-06-11-demo"
    tracker_path = _write_tracker_shell(tmp_path, pkg)
    paths = package_facts.fact_paths(pkg, root=tmp_path)
    live_rows = []
    for idx in range(6):
        live_rows.append({
            "row_id": f"P1:r{idx}",
            "time": f"2026-06-11T10:0{idx}:00+10:00",
            "exp_id": "P1",
            "run_id": f"r{idx}",
            "agent": "codex",
            "run_state": "RUNNING",
            "last_log": f"log-{idx}",
            "progress": f"{idx}/6",
            "metrics": f"Recall@1={idx}",
            "resource": "gpu0",
            "artifacts": f"artifact-{idx}",
            "eta": "unknown",
            "action": "CONTINUE_RUN",
            "next_check": "later",
        })
    package_facts.upsert_csv_rows(paths.tables_dir / "live_checks.csv", package_facts.LIVE_CHECK_COLUMNS, live_rows)
    package_facts.upsert_csv_rows(paths.tables_dir / "resource_allocation.csv", package_facts.RESOURCE_ALLOCATION_COLUMNS, [
        {"row_id": "P1:r5", "exp_id": "P1", "purpose": "run latest", "status": "RUNNING", "runtime_root": "outputs/latest"},
        {"row_id": "P2:r1", "exp_id": "P2", "purpose": "run second", "status": "QUEUED", "runtime_root": "outputs/second"},
    ])

    result = subprocess.run([
        sys.executable, str(SCRIPT),
        "--repo-root", str(tmp_path),
        "--pkg", pkg,
    ], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr + result.stdout
    text = tracker_path.read_text(encoding="utf-8")
    live_body = _tbody(text, "live-check")
    history_body = _tbody(text, "live-check-history")
    resource_body = _tbody(text, "resource-allocation")
    assert "log-5" in live_body
    assert "log-1" in live_body
    assert "log-0" not in live_body
    assert "log-0" in history_body
    assert "run latest" in resource_body
    assert "run second" in resource_body
    assert 'data-source="tables/live_checks.csv"' in text
    assert 'data-fact-revision="sha256:' in text
    assert 'data-source-row="live_checks:P1:r5"' in live_body
    assert 'id="resume-block"' in text
    assert 'id="chosen-route"' in text
    assert "keep todo" in text
