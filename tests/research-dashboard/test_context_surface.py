"""The global context.html surface has been removed.

The Context Pack remains an agent-facing artifact under outputs/<pkg>/; the
dashboard should no longer scaffold a separate human-facing Agent Context page.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "research-dashboard" / "scripts"))

import ensure_dashboard  # noqa: E402


def _scaffold(tmp_path):
    root = tmp_path / "research_html"
    ensure_dashboard.ensure_dashboard(root, force=False)
    return root


def test_scaffold_omits_global_context_surface(tmp_path):
    root = _scaffold(tmp_path)
    assert not (root / "context.html").exists()
    assert not (root / "assets" / "research-context.js").exists()
    assert not (root / "data" / "context-core.js").exists()


def test_scaffold_removes_legacy_global_context_surface(tmp_path):
    root = tmp_path / "research_html"
    (root / "assets").mkdir(parents=True)
    (root / "data").mkdir(parents=True)
    (root / "context.html").write_text("legacy", encoding="utf-8")
    (root / "assets" / "research-context.js").write_text("legacy", encoding="utf-8")
    (root / "data" / "context-core.js").write_text("legacy", encoding="utf-8")

    written = ensure_dashboard.ensure_dashboard(root, force=False)

    removed = {p.relative_to(root).as_posix() for p in written}
    assert {"context.html", "assets/research-context.js", "data/context-core.js"} <= removed
    assert not (root / "context.html").exists()
    assert not (root / "assets" / "research-context.js").exists()
    assert not (root / "data" / "context-core.js").exists()


def test_dashboard_surfaces_do_not_link_global_agent_context(tmp_path):
    root = _scaffold(tmp_path)
    for rel in ("index.html", "learnings.html", "live.html"):
        html = (root / rel).read_text(encoding="utf-8")
        assert 'href="context.html"' not in html
        assert "Agent Context" not in html
