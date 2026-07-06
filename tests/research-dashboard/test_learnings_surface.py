from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DASHBOARD = ROOT / "skills" / "research-dashboard" / "assets" / "dashboard"


def test_learnings_surface_exposes_decision_scope_and_rules_contracts():
    html = (DASHBOARD / "learnings.html").read_text(encoding="utf-8")
    js = (DASHBOARD / "assets" / "research.js").read_text(encoding="utf-8")
    css = (DASHBOARD / "assets" / "research.css").read_text(encoding="utf-8")

    assert 'src="data/rules.js"' in html
    assert 'src="data/scope-projection.js"' in html
    assert "next-action.html" not in html
    assert 'href="#abandoned"' not in html

    for label in ("Reuse", "Do not repeat", "Reopen only if", "Scope impact", "Promoted rule"):
        assert label in js
    assert "function packageRulesFor" in js
    assert "function packageScopeImpactHtml" in js
    assert "learnings-decision-grid" in js
    assert 'id="\' + htmlEscape(opts.id)' in js

    assert 'tr[data-verdict="FAIL"]' in css
    assert 'tr[data-verdict="PASS"]' in css

