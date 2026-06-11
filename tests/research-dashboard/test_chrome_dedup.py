"""Chrome owns no protocol content: objective renders from the Scope SSOT projection,
routes from schema.js, rules from the registry (核心问题 #1)."""

import subprocess
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[2] / "skills" / "research-dashboard"
SCRIPT = SKILL / "scripts" / "ensure_dashboard.py"


def _scaffold(tmp_path):
    r = subprocess.run([sys.executable, str(SCRIPT), "--root", str(tmp_path / "research_html")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return tmp_path / "research_html"


def test_no_protocol_literals_in_scaffold(tmp_path):
    root = _scaffold(tmp_path)
    data = (root / "data" / "research-packages.js").read_text()
    assert "RESEARCH_GLOBAL_PROTOCOL" not in data
    assert "RESEARCH_GLOBAL_CONTEXT" not in data
    assert "evidenceGates" not in data and "objectiveCards" not in data


def test_schema_owns_route_meanings(tmp_path):
    root = _scaffold(tmp_path)
    schema = (root / "data" / "schema.js").read_text()
    assert "NEXT_ROUTE_MEANING" in schema and "RUN_NEXT_EXPERIMENT" in schema


def test_research_js_renders_from_owners(tmp_path):
    root = _scaffold(tmp_path)
    js = (root / "assets" / "research.js").read_text()
    assert "RESEARCH_GLOBAL_PROTOCOL" not in js
    assert "RESEARCH_SCOPE_PROJECTION" in js     # objective panel source
    assert "NEXT_ROUTE_MEANING" in js            # routes source
    assert "RESEARCH_RULES" in js                # rules section source
    r = subprocess.run(["node", "--check", str(root / "assets" / "research.js")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_index_keeps_required_anchors(tmp_path):
    root = _scaffold(tmp_path)
    html = (root / "index.html").read_text()
    for anchor in ("snapshot", "lanes", "packages", "protocol", "profile", "rules"):
        assert f'data-section="{anchor}"' in html
    assert "rules/html-rules.html" in html and "rules/trustworthy-research-rules.html" in html
    assert 'id="rules-registry-root"' in html
    assert "data/rules.js" in html  # the registry is loaded on the homepage
