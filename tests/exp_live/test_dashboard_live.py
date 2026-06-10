import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "research-dashboard" / "scripts"))

import ensure_dashboard  # noqa: E402


LIVE_HTML = ROOT / "skills" / "research-dashboard" / "assets" / "dashboard" / "live.html"
INDEX_HTML = ROOT / "skills" / "research-dashboard" / "assets" / "dashboard" / "index.html"


def test_dashboard_scaffold_installs_global_live_page(tmp_path):
    root = tmp_path / "research_html"
    written = ensure_dashboard.ensure_dashboard(root, force=False)
    written_rel = {p.relative_to(root).as_posix() for p in written}

    assert "live.html" in written_rel
    assert (root / "live.html").exists()
    assert 'href="live.html"' in (root / "index.html").read_text(encoding="utf-8")


def test_live_page_reads_runtime_files_and_is_read_only():
    html = LIVE_HTML.read_text(encoding="utf-8")
    index = INDEX_HTML.read_text(encoding="utf-8")

    assert 'data-page="live"' in html
    assert "../outputs/_live/runs.jsonl" in html
    assert "status.json" in html
    assert "data/research-packages.js" in html
    assert "No live runs yet." in html
    assert "Cannot fetch" in html
    assert "python -m http.server" in html
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
    assert "lastHtml" in html  # F8: repaint only on change


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
