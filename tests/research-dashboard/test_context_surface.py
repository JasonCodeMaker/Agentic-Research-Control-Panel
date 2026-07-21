"""The projection has no global agent-context surface or interface authority."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "research-dashboard" / "scripts"))

import ensure_dashboard  # noqa: E402
from lib.research_state import EventStore, ResearchPaths  # noqa: E402


def _scaffold(tmp_path):
    EventStore(ResearchPaths.resolve(workspace=tmp_path)).initialize()
    ensure_dashboard.ensure_dashboard(tmp_path)
    return tmp_path / ".research" / "interface"


def test_scaffold_omits_global_context_surface(tmp_path):
    root = _scaffold(tmp_path)
    assert not (root / "context.html").exists()
    assert not (root / "assets" / "research-context.js").exists()
    assert not (root / "data" / "context-core.js").exists()


def test_rebuild_removes_stale_global_context_surface_from_projection(tmp_path):
    root = _scaffold(tmp_path)
    (root / "assets").mkdir(parents=True, exist_ok=True)
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "context.html").write_text("legacy", encoding="utf-8")
    (root / "assets" / "research-context.js").write_text("legacy", encoding="utf-8")
    (root / "data" / "context-core.js").write_text("legacy", encoding="utf-8")

    written = ensure_dashboard.ensure_dashboard(tmp_path)

    written_rel = {p.relative_to(root).as_posix() for p in written}
    assert "index.html" in written_rel
    assert not (root / "context.html").exists()
    assert not (root / "assets" / "research-context.js").exists()
    assert not (root / "data" / "context-core.js").exists()


def test_dashboard_surfaces_do_not_link_global_agent_context(tmp_path):
    root = _scaffold(tmp_path)
    for rel in ("index.html", "learnings.html", "live.html"):
        html = (root / rel).read_text(encoding="utf-8")
        assert 'href="context.html"' not in html
        assert "Agent Context" not in html
