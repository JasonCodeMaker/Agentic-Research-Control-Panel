"""Phase 2 — the context.html human surface (derived view over data/context-core.js)."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "research-dashboard" / "scripts"))

import ensure_dashboard  # noqa: E402


def _scaffold(tmp_path):
    root = tmp_path / "research_html"
    ensure_dashboard.ensure_dashboard(root, force=False)
    return root


def test_scaffold_installs_context_surface(tmp_path):
    root = _scaffold(tmp_path)
    assert (root / "context.html").exists()
    assert (root / "assets" / "research-context.js").exists()
    assert (root / "data" / "context-core.js").exists()


def test_context_html_wires_data_and_renderer(tmp_path):
    html = (_scaffold(tmp_path) / "context.html").read_text(encoding="utf-8")
    assert 'src="data/context-core.js"' in html
    assert 'src="assets/research-context.js"' in html
    assert 'id="context-root"' in html


def test_context_footer_names_current_upstream_stores(tmp_path):
    html = (_scaffold(tmp_path) / "context.html").read_text(encoding="utf-8")
    assert "data/rules.js" in html
    assert "outputs/_learned/rules.md" not in html
    assert "analysis.html</code> Rules" not in html


def test_default_context_core_is_empty_valid_json(tmp_path):
    txt = (_scaffold(tmp_path) / "data" / "context-core.js").read_text(encoding="utf-8")
    assert txt.startswith("window.RESEARCH_CONTEXT_CORE")
    payload = txt.split("=", 1)[1].strip().rstrip(";\n").strip()
    assert json.loads(payload)["sections"] == []


def test_renderer_reads_core_global(tmp_path):
    js = (_scaffold(tmp_path) / "assets" / "research-context.js").read_text(encoding="utf-8")
    assert "RESEARCH_CONTEXT_CORE" in js
    assert "context-root" in js


def test_index_and_learnings_link_context(tmp_path):
    root = _scaffold(tmp_path)
    assert 'href="context.html"' in (root / "index.html").read_text(encoding="utf-8")
    assert 'href="context.html"' in (root / "learnings.html").read_text(encoding="utf-8")


@pytest.mark.skipif(shutil.which("node") is None, reason="node required to execute the renderer")
def test_renderer_renders_sections(tmp_path):
    root = _scaffold(tmp_path)
    (root / "data" / "context-core.js").write_text(
        "window.RESEARCH_CONTEXT_CORE = " + json.dumps({
            "stamp": {"scope_version": 3, "generated_at": "t0", "truncated": False},
            "sections": [{"key": "rules", "title": "Learned Rules (constraints)",
                          "protected": True, "lines": ["- reproduce the baseline first"]}],
        }) + ";\n", encoding="utf-8")
    script = f'''
      global.window = {{}};
      var captured = "";
      global.document = {{
        readyState: "complete",
        getElementById: function (id) {{
          return id === "context-root" ? {{ set innerHTML(v) {{ captured = v; }} }} : null;
        }},
        addEventListener: function () {{}},
      }};
      const fs = require("fs");
      eval(fs.readFileSync({json.dumps(str(root / "data" / "context-core.js"))}, "utf8"));
      eval(fs.readFileSync({json.dumps(str(root / "assets" / "research-context.js"))}, "utf8"));
      process.stdout.write(captured);
    '''
    out = subprocess.check_output(["node", "-e", script], text=True)
    assert "Learned Rules (constraints)" in out
    assert "reproduce the baseline first" in out
