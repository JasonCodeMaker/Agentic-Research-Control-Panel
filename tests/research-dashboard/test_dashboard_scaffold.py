import sys
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
    assert 'src="data/scope-projection.js"' not in index  # its orphaned data include removed
    assert 'href="scope.html"' in index                 # dashboard links to the live Scope Tree


def test_dashboard_scaffold_installs_empty_brainstorms_store(tmp_path):
    root = tmp_path / "research_html"
    written = ensure_dashboard.ensure_dashboard(root, force=False)

    written_rel = {p.relative_to(root).as_posix() for p in written}
    assert "data/brainstorms.js" in written_rel
    assert (root / "data" / "brainstorms.js").read_text(encoding="utf-8").strip() == (
        "window.BRAINSTORMS = [];"
    )
