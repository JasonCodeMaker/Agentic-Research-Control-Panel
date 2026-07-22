import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "skills" / "research-dashboard" / "scripts"))

from lib.interface.project import live_run_views  # noqa: E402
from lib.interface.serve import live_runs, safe_run_dir, should_disable_cache  # noqa: E402
from lib.research_state import EventStore, ResearchPaths  # noqa: E402
import ensure_dashboard  # noqa: E402


ACTOR = {"type": "agent", "id": "dashboard-live-test"}


def _projected_root(tmp_path: Path) -> Path:
    EventStore(ResearchPaths.resolve(workspace=tmp_path)).initialize()
    ensure_dashboard.ensure_dashboard(tmp_path)
    return tmp_path / ".research" / "interface"


def _run_state(tmp_path: Path, **overrides):
    paths = ResearchPaths.resolve(workspace=tmp_path)
    store = EventStore(paths)
    store.initialize()
    run_dir = paths.run_dir("pkg-a", "P1", "P1-r1")
    run_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "id": "P1-r1",
        "package_id": "pkg-a",
        "experiment_id": "pkg-a::P1",
        "status": "RUNNING",
        "dir": str(run_dir),
        **overrides,
    }
    store.commit(
        event_type="AggregateUpserted",
        aggregate_type="run",
        aggregate_id="P1-r1",
        payload={"record": record},
        actor=ACTOR,
        idempotency_key="dashboard-live:run",
    )
    return paths, run_dir


def test_dashboard_build_installs_global_live_page(tmp_path):
    root = _projected_root(tmp_path)

    assert (root / "live.html").exists()
    assert not (root / "scripts").exists()
    assert (ROOT / "lib" / "interface" / "serve.py").exists()
    assert 'href="live.html"' in (root / "index.html").read_text(encoding="utf-8")


def test_live_page_reads_runtime_api_and_is_read_only(tmp_path):
    root = _projected_root(tmp_path)
    html = (root / "live.html").read_text(encoding="utf-8")
    index = (root / "index.html").read_text(encoding="utf-8")

    assert 'data-page="live"' in html
    assert "/api/live/runs?include_status=1" in html
    assert "data/live-runs.jsonl" in html
    assert "/api/live/status/" in html
    assert "data/research-packages.js" in html
    assert "No live runs yet." in html
    assert "Cannot fetch" in html
    assert "python -m lib.interface.serve" in html
    assert "file fallback" in html
    assert 'data-field="run-state"' in html
    assert 'data-field="latest-metrics"' in html
    assert 'data-field="next-check-source"' in html
    assert 'href="live.html"' in index

    for verb in ("POST", "PUT", "PATCH", "DELETE"):
        assert verb not in html


def test_experiment_sources_do_not_write_interface_surfaces(tmp_path):
    lib_paths = list((ROOT / "lib" / "experiments").glob("*.py"))
    for path in lib_paths:
        text = path.read_text(encoding="utf-8")
        for needle in (
            ".research/interface/packages",
            "data/research-packages.js",
        ):
            assert needle not in text, f"{path} writes or targets {needle}"
    html = (_projected_root(tmp_path) / "live.html").read_text(encoding="utf-8")
    assert ".research/interface/packages" not in html
    for mutator in ("writeText", "localStorage", "indexedDB", "navigator.sendBeacon"):
        assert mutator not in html


def test_live_page_scopes_fetches_and_derives_stale_client_side(tmp_path):
    html = (_projected_root(tmp_path) / "live.html").read_text(encoding="utf-8")

    assert "deriveState" in html
    assert "heartbeat_timeout" in html
    assert "24 * 3600" in html
    assert "shouldFetch" in html
    assert "fetchApiRuns" in html
    assert "fetchFileRuns" in html
    assert "lastHtml" in html


def test_dashboard_server_reads_state_and_attaches_experiment_status(tmp_path):
    paths, run_dir = _run_state(tmp_path)
    (run_dir / "status.json").write_text(
        json.dumps(
            {
                "run_id": "P1-r1",
                "pkg": "pkg-a",
                "exp_id": "pkg-a::P1",
                "status": "RUNNING",
                "latest_metrics": {"loss": 0.2},
            }
        ),
        encoding="utf-8",
    )

    runs, errors = live_runs(paths, include_status=True)

    assert errors == []
    assert runs[0]["run_id"] == "P1-r1"
    assert runs[0]["status"]["latest_metrics"]["loss"] == 0.2
    assert runs[0]["exp_id"] == "pkg-a::P1"


def test_live_page_shows_run_config_and_drops_gate(tmp_path):
    html = (_projected_root(tmp_path) / "live.html").read_text(encoding="utf-8")

    assert 'data-field="config"' in html
    assert "configText" in html
    assert "run.command" in html
    assert "primaryMetricVsGate" not in html
    assert ">gate:" not in html.lower()


def test_live_page_bounds_health_and_auto_clears_fixed_failures(tmp_path):
    html = (_projected_root(tmp_path) / "live.html").read_text(encoding="utf-8")

    assert "healthLine" in html
    assert '.join("; ")' not in html
    assert "retry_of" in html
    assert "superseded" in html


def test_live_page_supports_acknowledged_runs(tmp_path):
    html = (_projected_root(tmp_path) / "live.html").read_text(encoding="utf-8")

    assert "data/live-acknowledged.json" in html
    assert "fetchAcks" in html
    assert "acknowledged" in html


def test_dashboard_server_passes_command_and_retry_through_state(tmp_path):
    paths, _ = _run_state(
        tmp_path,
        command=["bash", "run.sh", "--lr", "3e-4"],
        retry_of="P1-r0",
    )

    runs, errors = live_runs(paths, include_status=False)

    assert errors == []
    assert runs[0]["command"] == ["bash", "run.sh", "--lr", "3e-4"]
    assert runs[0]["retry_of"] == "P1-r0"


def test_terminal_run_leaves_open_index_but_remains_explicit_history(tmp_path):
    paths, _ = _run_state(tmp_path)
    store = EventStore(paths)
    store.commit(
        event_type="AggregateUpserted",
        aggregate_type="run",
        aggregate_id="P1-r1",
        payload={
            "record": {
                "id": "P1-r1",
                "package_id": "pkg-a",
                "experiment_id": "pkg-a::P1",
                "status": "COMPLETED",
            }
        },
        actor=ACTOR,
        idempotency_key="dashboard-live:terminal",
    )

    assert store.state()["open_runs"] == {}
    api_rows, _ = live_runs(paths, include_status=True)
    static_rows = live_run_views(store.state())
    assert [row["run_id"] for row in api_rows] == ["P1-r1"]
    assert [row["run_id"] for row in static_rows] == ["P1-r1"]
    assert api_rows[0]["terminal"] is True
    assert static_rows[0]["terminal"] is True


def test_dashboard_server_rejects_status_paths_outside_experiments(tmp_path):
    paths = ResearchPaths.resolve(workspace=tmp_path)
    EventStore(paths).initialize()
    run = {
        "run_id": "bad",
        "package_id": "pkg-a",
        "experiment_id": "pkg-a::P1",
        "dir": str(tmp_path / "elsewhere"),
    }
    assert safe_run_dir(paths, "bad", run) is None


def test_dashboard_server_rejects_cross_run_directory_alias(tmp_path):
    paths = ResearchPaths.resolve(workspace=tmp_path)
    EventStore(paths).initialize()
    wrong = paths.run_dir("pkg-a", "P1", "other-run")
    wrong.mkdir(parents=True)
    run = {
        "run_id": "expected-run",
        "package_id": "pkg-a",
        "experiment_id": "pkg-a::P1",
        "dir": str(wrong),
    }

    assert safe_run_dir(paths, "expected-run", run) is None


def test_missing_or_invalid_status_is_explicitly_unknown(tmp_path):
    paths, run_dir = _run_state(tmp_path)

    runs, errors = live_runs(paths, include_status=True)
    assert runs[0]["status"]["status"] == "UNKNOWN"
    assert runs[0]["status"]["management_status"] == "RUNNING"
    assert "missing" in runs[0]["status_error"]
    assert len(errors) == 1

    (run_dir / "status.json").write_text("{broken", encoding="utf-8")
    runs, errors = live_runs(paths, include_status=True)
    assert runs[0]["status"]["status"] == "UNKNOWN"
    assert "unreadable" in runs[0]["status_error"]
    assert len(errors) == 1


def test_dashboard_server_disables_cache_for_live_data_files():
    assert should_disable_cache("/api/live/runs")
    assert should_disable_cache("/data/scope-projection.js")
    assert should_disable_cache("/data/scope-projection.json")
    assert should_disable_cache("/assets/live-data.js")
    assert not should_disable_cache("/assets/research.css")


def test_complete_rebuild_repairs_live_nav_and_removes_stale_links(tmp_path):
    root = _projected_root(tmp_path)
    index = root / "index.html"
    stripped = (
        index.read_text(encoding="utf-8")
        .replace('        <a class="pill" href="live.html">Live Runs</a>\n', "")
    )
    stripped = stripped.replace(
        '      <a href="#packages">Packages</a>\n',
        '      <a href="#packages">Packages</a>\n'
        '      <a href="scope.html">Live Scope</a>\n'
        '      <a href="live.html">Live Runs</a>\n'
        '      <a href="learnings.html">Learnings</a>\n'
        '      <a href="context.html">Agent Context</a>\n',
        1,
    )
    index.write_text(stripped, encoding="utf-8")

    written = ensure_dashboard.ensure_dashboard(tmp_path)
    text = index.read_text(encoding="utf-8")
    nav_start = text.index('<nav class="dashboard-nav"')
    nav = text[nav_start : text.index("</nav>", nav_start)]
    assert '<a class="pill" href="live.html">Live Runs</a>' in text
    for href in ("scope.html", "live.html", "learnings.html", "context.html"):
        assert f'href="{href}"' not in nav
    assert index in written
