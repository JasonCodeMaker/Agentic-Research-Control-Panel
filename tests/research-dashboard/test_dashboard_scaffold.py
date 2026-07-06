import sys
import py_compile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "research-dashboard" / "scripts"))

import ensure_dashboard  # noqa: E402


def test_dashboard_scaffold_installs_scope_projection_files(tmp_path):
    root = tmp_path / "research_html"
    written = ensure_dashboard.ensure_dashboard(root, force=False)

    # The derived Scope projection files + renderer are still scaffolded as a
    # standalone SSOT view; the dashboard index no longer embeds an inline
    # projection section (the live Scope Tree page replaces it).
    written_rel = {p.relative_to(root).as_posix() for p in written}
    assert "data/scope-projection.json" in written_rel
    assert "data/scope-projection.js" in written_rel
    assert "scripts/render_scope_projection.py" in written_rel
    assert (root / "data" / "scope-projection.js").read_text(encoding="utf-8").strip() == (
        "window.RESEARCH_SCOPE_PROJECTION = {};"
    )

    index = (root / "index.html").read_text(encoding="utf-8")
    assert 'data-section="scope"' not in index          # inline projection section removed
    # The include is consumed again: the #protocol objective panel projects the
    # SSOT Project node (chrome de-dup — the dashboard owns no objective prose).
    assert 'src="data/scope-projection.js"' in index
    assert 'href="scope.html"' in index                 # dashboard links to the live Scope Tree


def test_dashboard_scaffold_installs_empty_brainstorms_store(tmp_path):
    root = tmp_path / "research_html"
    written = ensure_dashboard.ensure_dashboard(root, force=False)

    written_rel = {p.relative_to(root).as_posix() for p in written}
    assert "data/brainstorms.js" in written_rel
    assert (root / "data" / "brainstorms.js").read_text(encoding="utf-8").strip() == (
        "window.BRAINSTORMS = [];"
    )


def test_dashboard_scaffold_installs_live_api_server_script(tmp_path):
    root = tmp_path / "research_html"
    written = ensure_dashboard.ensure_dashboard(root, force=False)

    written_rel = {p.relative_to(root).as_posix() for p in written}
    server = root / "scripts" / "serve_dashboard.py"
    assert "scripts/serve_dashboard.py" in written_rel
    assert server.exists()
    py_compile.compile(str(server), doraise=True)


def test_dashboard_scaffold_omits_module_library_interface(tmp_path):
    root = tmp_path / "research_html"
    ensure_dashboard.ensure_dashboard(root, force=False)

    assert not (root / "templates" / "module-library.html").exists()
    assert 'templates/module-library.html' not in (root / "index.html").read_text(encoding="utf-8")
    contract = (ROOT / "skills" / "research-dashboard" / "references" / "dashboard-contract.md").read_text(encoding="utf-8")
    assert "templates/module-library.html" not in contract


def test_dashboard_scaffold_removes_legacy_module_library_interface(tmp_path):
    root = tmp_path / "research_html"
    legacy = root / "templates" / "module-library.html"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("legacy", encoding="utf-8")

    written = ensure_dashboard.ensure_dashboard(root, force=False)

    assert legacy in written
    assert not legacy.exists()


def test_chrome_copy_skips_python_cache_files(tmp_path, monkeypatch):
    bundle = tmp_path / "bundle"
    (bundle / "scripts" / "__pycache__").mkdir(parents=True)
    (bundle / "scripts" / "tool.py").write_text("print('ok')\n")
    (bundle / "scripts" / "__pycache__" / "tool.cpython-313.pyc").write_bytes(b"cache")
    monkeypatch.setattr(ensure_dashboard, "DASHBOARD_BUNDLE", bundle)

    root = tmp_path / "research_html"
    written = ensure_dashboard.copy_bundled_chrome(root, force=False)

    written_rel = {p.relative_to(root).as_posix() for p in written}
    assert "scripts/tool.py" in written_rel
    assert not (root / "scripts" / "__pycache__").exists()
