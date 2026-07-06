"""Chrome owns no protocol content: objective renders from the Scope SSOT projection,
routes from schema.js, rules from the registry (核心问题 #1)."""

import re
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


def _block(html, selector):
    pattern = rf'<[^>]+{selector}[^>]*>[\s\S]*?</(?:div|nav)>'
    match = re.search(pattern, html)
    assert match, f"missing block matching {selector}"
    return match.group(0)


def test_homepage_separates_global_toolbar_from_page_nav(tmp_path):
    root = _scaffold(tmp_path)
    html = (root / "index.html").read_text()
    toolbar = _block(html, r'data-card="dashboard-toolbar"')
    nav = _block(html, r'class="dashboard-nav"')

    for href in ("scope.html", "live.html", "learnings.html"):
        assert f'href="{href}"' in toolbar
        assert f'href="{href}"' not in nav
    assert 'href="context.html"' not in toolbar
    assert 'href="context.html"' not in nav
    assert 'templates/module-library.html' not in toolbar
    assert 'Module Library' not in toolbar
    assert 'href="README.md"' not in toolbar
    assert 'README' not in toolbar
    assert 'href="rules/html-rules.html"' not in toolbar
    assert 'href="rules/trustworthy-research-rules.html"' not in toolbar
    assert 'HTML Rules' not in toolbar
    assert 'Trust Rules' not in toolbar

    assert 'data-card="rule-link-html"' in html
    assert 'data-card="rule-link-trust"' in html
    assert 'href="rules/html-rules.html"' in html
    assert 'href="rules/trustworthy-research-rules.html"' in html

    for href in ("#snapshot", "#lanes", "#packages", "#protocol", "#profile", "#rules"):
        assert f'href="{href}"' in nav


def test_dashboard_contract_does_not_require_readme_toolbar_link():
    contract = (SKILL / "references" / "dashboard-contract.md").read_text(encoding="utf-8")
    assert "README links" not in contract


def test_dashboard_contract_does_not_require_rule_toolbar_links():
    contract = (SKILL / "references" / "dashboard-contract.md").read_text(encoding="utf-8")
    assert "toolbar with global dashboard + rule links" not in contract


def test_package_filters_do_not_include_quality_toggle(tmp_path):
    root = _scaffold(tmp_path)
    js = (root / "assets" / "research.js").read_text(encoding="utf-8")

    assert "<legend>Quality</legend>" not in js
    assert "show-only-missing" not in js
    assert "filter-meta" not in js
    assert "missingRequiredFields(p).length > 0" not in js
