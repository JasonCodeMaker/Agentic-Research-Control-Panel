import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "skills" / "research-dashboard" / "scripts"))

from lib.interface import build_interface  # noqa: E402
from lib.research_state import EventStore, ResearchPaths  # noqa: E402
import ensure_dashboard  # noqa: E402


def _scaffold(tmp_path: Path) -> Path:
    ensure_dashboard.ensure_dashboard(tmp_path)
    return tmp_path / ".research" / "interface"


def test_dashboard_build_installs_scope_projection_files(tmp_path):
    root = _scaffold(tmp_path)

    assert (root / "data" / "scope-projection.json").read_text() == "{}\n"
    assert (
        root / "data" / "scope-projection.js"
    ).read_text().strip() == "window.RESEARCH_SCOPE_PROJECTION = {};"
    assert (root / "data" / "scope-transitions.jsonl").read_text() == ""
    assert (root / "data" / "scope-triage.jsonl").read_text() == ""
    assert not (root / "scripts").exists()

    index = (root / "index.html").read_text(encoding="utf-8")
    assert 'data-section="scope"' not in index
    assert 'src="data/scope-projection.js"' in index
    assert 'href="scope.html"' in index


def test_dashboard_build_installs_empty_brainstorms_store(tmp_path):
    root = _scaffold(tmp_path)
    assert (root / "data" / "brainstorms.js").read_text().strip() == (
        "window.BRAINSTORMS = [];"
    )


def test_dashboard_build_has_no_python_execution_surface(tmp_path):
    root = _scaffold(tmp_path)

    assert not (root / "scripts").exists()
    assert not list(root.rglob("*.py"))
    assert (ROOT / "lib" / "interface" / "serve.py").is_file()


def test_dashboard_build_preserves_module_route_but_omits_module_library(tmp_path):
    root = _scaffold(tmp_path)

    assert not (root / "templates" / "module-library.html").exists()
    assert 'templates/module-library.html' not in (root / "index.html").read_text()
    assert 'id="package-module-root"' in (root / "module.html").read_text()
    assert "module.html?package=" in (root / "assets" / "research.js").read_text()


def test_complete_rebuild_removes_unknown_projection_files(tmp_path):
    root = _scaffold(tmp_path)
    legacy = root / "templates" / "module-library.html"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("stale projection", encoding="utf-8")

    written = ensure_dashboard.ensure_dashboard(tmp_path)

    assert not legacy.exists()
    assert root / "index.html" in written


def test_deleted_interface_is_rebuilt_from_authority(tmp_path):
    root = _scaffold(tmp_path)
    shutil.rmtree(root)

    written = ensure_dashboard.ensure_dashboard(tmp_path)

    assert root / "index.html" in written
    assert (root / "scope.html").is_file()
    assert (root / "module.html").is_file()
    assert (root / "data" / "scope-projection.json").is_file()


def test_dashboard_runtime_state_uses_xdg_not_the_projection(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    workspace = tmp_path / "workspace"
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime_root))
    paths = ResearchPaths.resolve(workspace=workspace)

    assert paths.dashboard_server_state.is_relative_to(runtime_root)
    assert not paths.dashboard_server_state.is_relative_to(paths.root)
    assert not paths.dashboard_server_state.is_relative_to(paths.interface)


def test_bundle_scripts_and_python_cache_are_never_projected(tmp_path):
    bundle = tmp_path / "bundle"
    (bundle / "scripts" / "__pycache__").mkdir(parents=True)
    (bundle / "scripts" / "tool.py").write_text("print('not public')\n")
    (bundle / "scripts" / "__pycache__" / "tool.pyc").write_bytes(b"cache")
    (bundle / "index.html").write_text("<!doctype html><title>test</title>\n")

    workspace = tmp_path / "workspace"
    paths = ResearchPaths.resolve(workspace=workspace)
    EventStore(paths).initialize()
    result = build_interface(paths, bundle=bundle)

    assert (result.root / "index.html").is_file()
    assert not (result.root / "scripts").exists()
    assert not list(result.root.rglob("*.py"))
    assert not list(result.root.rglob("*.pyc"))
