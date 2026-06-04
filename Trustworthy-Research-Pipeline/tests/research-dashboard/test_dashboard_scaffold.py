import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "research-dashboard" / "scripts"))

import ensure_dashboard  # noqa: E402


def test_dashboard_scaffold_installs_scope_projection_surface(tmp_path):
    root = tmp_path / "research_html"
    written = ensure_dashboard.ensure_dashboard(root, force=False)

    written_rel = {p.relative_to(root).as_posix() for p in written}
    assert "data/scope-projection.json" in written_rel
    assert "data/scope-projection.js" in written_rel
    assert "scripts/render_scope_projection.py" in written_rel

    index = (root / "index.html").read_text(encoding="utf-8")
    assert 'data-section="scope"' in index
    assert 'src="data/scope-projection.js"' in index
    assert (root / "data" / "scope-projection.js").read_text(encoding="utf-8").strip() == (
        "window.RESEARCH_SCOPE_PROJECTION = {};"
    )
