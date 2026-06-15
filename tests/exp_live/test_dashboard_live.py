import sys
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "research-dashboard" / "scripts"))

import ensure_dashboard  # noqa: E402


LIVE_HTML = ROOT / "skills" / "research-dashboard" / "assets" / "dashboard" / "live.html"
INDEX_HTML = ROOT / "skills" / "research-dashboard" / "assets" / "dashboard" / "index.html"
SERVE_DASHBOARD = ROOT / "skills" / "research-dashboard" / "assets" / "dashboard" / "scripts" / "serve_dashboard.py"


def _load_serve_dashboard():
    spec = importlib.util.spec_from_file_location("serve_dashboard_under_test", SERVE_DASHBOARD)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dashboard_scaffold_installs_global_live_page(tmp_path):
    root = tmp_path / "research_html"
    written = ensure_dashboard.ensure_dashboard(root, force=False)
    written_rel = {p.relative_to(root).as_posix() for p in written}

    assert "live.html" in written_rel
    assert "scripts/serve_dashboard.py" in written_rel
    assert (root / "live.html").exists()
    assert (root / "scripts" / "serve_dashboard.py").exists()
    assert 'href="live.html"' in (root / "index.html").read_text(encoding="utf-8")


def test_live_page_reads_runtime_files_and_is_read_only():
    html = LIVE_HTML.read_text(encoding="utf-8")
    index = INDEX_HTML.read_text(encoding="utf-8")

    assert 'data-page="live"' in html
    assert "/api/live/runs?include_status=1" in html
    assert "../outputs/_live/runs.jsonl" in html
    assert "status.json" in html
    assert "data/research-packages.js" in html
    assert "No live runs yet." in html
    assert "Cannot fetch" in html
    assert "serve_dashboard.py ensure --json" in html
    assert "file fallback" in html
    assert 'data-field="run-state"' in html
    assert 'data-field="latest-metrics"' in html
    assert 'data-field="next-check-source"' in html
    assert 'href="live.html"' in index

    for verb in ("POST", "PUT", "PATCH", "DELETE"):
        assert verb not in html


def test_exp_live_sources_do_not_write_package_surfaces():
    lib_paths = [p for p in (ROOT / "lib" / "exp_live").glob("*.py")] if (ROOT / "lib" / "exp_live").exists() else []
    for path in lib_paths:
        text = path.read_text(encoding="utf-8")
        for needle in ("research_html/packages", "data/research-packages.js"):
            assert needle not in text, f"{path} writes or targets {needle}"
    html = LIVE_HTML.read_text(encoding="utf-8")
    assert "research_html/packages" not in html
    for mutator in ("writeText", "localStorage", "indexedDB", "navigator.sendBeacon"):
        assert mutator not in html


def test_live_page_scopes_fetches_and_derives_stale_client_side():
    # F6: only open + recently-terminal runs are fetched each poll.
    # F1d: the page derives STALE from last-output age when status is frozen.
    # F7: the failed counter uses a real 24h window.
    html = LIVE_HTML.read_text(encoding="utf-8")

    assert "deriveState" in html
    assert "heartbeat_timeout" in html
    assert "24 * 3600" in html
    assert "shouldFetch" in html
    assert "fetchApiRuns" in html
    assert "fetchFileRuns" in html
    assert "lastHtml" in html  # F8: repaint only on change


def test_dashboard_server_folds_index_and_attaches_status(tmp_path):
    module = _load_serve_dashboard()
    outputs = tmp_path / "outputs"
    run_dir = outputs / "pkg-a" / "runs" / "P1-r1"
    run_dir.mkdir(parents=True)
    (outputs / "_live").mkdir(parents=True)
    (run_dir / "status.json").write_text(
        json.dumps({
            "run_id": "P1-r1",
            "pkg": "pkg-a",
            "exp_id": "P1",
            "status": "RUNNING",
            "latest_metrics": {"loss": 0.2},
        }),
        encoding="utf-8",
    )
    (outputs / "_live" / "runs.jsonl").write_text(
        json.dumps({
            "op": "launched",
            "run_id": "P1-r1",
            "pkg": "pkg-a",
            "exp_id": "P1",
            "dir": str(run_dir),
            "started_at": 1.0,
        }) + "\n",
        encoding="utf-8",
    )

    runs, errors = module.fold_index(outputs)
    assert errors == []
    assert runs[0]["run_id"] == "P1-r1"
    attached = module.attach_status(tmp_path, outputs, runs[0])
    assert attached["status"]["latest_metrics"]["loss"] == 0.2


def test_dashboard_server_rejects_status_paths_outside_outputs(tmp_path):
    module = _load_serve_dashboard()
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    run = {"run_id": "bad", "dir": str(tmp_path / "elsewhere")}
    assert module.safe_run_dir(tmp_path, outputs, run) is None


def test_ensure_dashboard_repairs_missing_live_nav_on_existing_index(tmp_path):
    # F11b: an already-attached project's index.html gains the Live Runs links.
    root = tmp_path / "research_html"
    ensure_dashboard.ensure_dashboard(root, force=False)
    index = root / "index.html"
    stripped = (
        index.read_text(encoding="utf-8")
        .replace('        <a class="pill" href="live.html">Live Runs</a>\n', "")
        .replace('      <a href="live.html">Live Runs</a>\n', "")
    )
    assert 'href="live.html"' not in stripped
    index.write_text(stripped, encoding="utf-8")

    written = ensure_dashboard.ensure_dashboard(root, force=False)
    text = index.read_text(encoding="utf-8")
    assert '<a class="pill" href="live.html">Live Runs</a>' in text
    assert '<a href="live.html">Live Runs</a>' in text
    assert index in written
