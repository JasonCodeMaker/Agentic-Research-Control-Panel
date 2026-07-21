"""Projection contract for the Scope Inspector page (scope.html + wiring).

Locks the acceptance criteria from plan/2026-06-09-scope-inspector-live-view.md:
dashboard entry point, read of state-backed Scope projections, explicit failure
states, read-only behavior, and the no-hardcoded-SSOT-rules requirement. The
tree and fields remain data-driven.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from lib.interface.project import render_scope_schema_js
from lib.research_state.schema import enum, scope_contract

DASH = ROOT / "skills" / "research-dashboard" / "assets" / "dashboard"
SCOPE_HTML = DASH / "scope.html"
INDEX_HTML = DASH / "index.html"
INSPECTOR_JS = DASH / "assets" / "scope-inspector.js"
RESEARCH_JS = DASH / "assets" / "research.js"
SCOPE_SCHEMA_JS = DASH / "data" / "scope-schema.js"

# Spec field names are SSOT schema rules; the live view must not hardcode them.
# `gate` is also transition metadata, so a plain text check would be a false positive.
SPEC_FIELDS = [
    "goal", "contributions", "out_of_scope",
    "hypothesis", "success_gate", "baselines",
    "purpose", "config_ref", "control_mode",
]
LEVEL_LITERALS = [
    '"project"', '"direction"', '"experiment"',
    "'project'", "'direction'", "'experiment'",
]


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_scope_html_and_inspector_exist():
    assert SCOPE_HTML.exists(), f"missing {SCOPE_HTML}"
    assert INSPECTOR_JS.exists(), f"missing {INSPECTOR_JS}"


def test_index_links_to_scope_page():
    assert 'href="scope.html"' in _read(INDEX_HTML)


def test_index_labels_scope_as_live_decision_surface():
    assert "Live Scope" in _read(INDEX_HTML)


def test_package_overview_links_back_to_live_scope_provenance():
    js = _read(RESEARCH_JS)
    assert 'data-card="scope-provenance"' in js
    assert "sourceDirection" in js
    assert "pkg.sourceExperiments" in js
    assert "pkg.sourceTasks" not in js
    assert "scope.html" in js


def test_scope_reads_state_backed_event_projections():
    html = _read(SCOPE_HTML)
    assert "data/scope-transitions.jsonl" in html
    assert "data/scope-triage.jsonl" in html
    assert ".research/state/events.jsonl" in html


def test_scope_does_not_depend_on_dashboard_projection():
    html = _read(SCOPE_HTML)
    assert "scope-projection.json" not in html
    assert "scope-projection.js" not in html


def test_scope_loads_inspector_module_and_shared_css():
    html = _read(SCOPE_HTML)
    assert "assets/scope-inspector.js" in html
    assert "data/scope-schema.js" in html
    assert "assets/research.css" in html
    assert 'data-page="scope"' in html


def test_scope_declares_understanding_and_schema_health_surfaces():
    html = _read(SCOPE_HTML)
    assert 'data-section="understanding"' in html
    assert 'data-section="schema-health"' in html


def test_scope_declares_package_readiness_surface():
    html = _read(SCOPE_HTML)
    assert 'data-section="package-readiness"' in html
    assert "Package readiness" in html


def test_scope_inspector_renders_decision_and_audit_labels():
    js = _read(INSPECTOR_JS)
    for label in (
        "Current vs proposed",
        "Affected packages",
        "Accepted - needs scope-transition",
        "Recent changes",
        "Transition parse errors",
        "Triage parse errors",
    ):
        assert label in js


def test_scope_declares_the_four_views():
    html = _read(SCOPE_HTML).lower()
    for view in ("active scope", "pending triage", "history", "raw log"):
        assert view in html, f"missing view: {view}"


def test_scope_has_explicit_failure_states():
    # Runtime failure states are produced by the module the page ships; the
    # serve-from-root hint is also statically visible in the page footer.
    page = _read(SCOPE_HTML) + _read(INSPECTOR_JS)
    assert "No committed Scope SSOT found yet." in page   # transitions file missing
    assert "has no committed nodes" in page               # transitions file empty
    assert "Cannot read" in page                          # fetch failed / wrong mount
    assert "python -m lib.interface.serve" in _read(SCOPE_HTML)


def test_scope_view_is_read_only():
    for text in (_read(SCOPE_HTML), _read(INSPECTOR_JS)):
        for verb in ("POST", "PUT", "PATCH", "DELETE"):
            assert verb not in text, f"write verb {verb!r} present; view must be read-only"


def test_no_hardcoded_spec_fields_in_view():
    # The whole point of the live view: render whatever the node carries.
    for path in (SCOPE_HTML, INSPECTOR_JS):
        text = _read(path)
        for field in SPEC_FIELDS:
            pattern = r"(?<![A-Za-z0-9_])" + re.escape(field) + r"(?![A-Za-z0-9_])"
            assert not re.search(pattern, text), f"hardcoded SSOT field {field!r} in {path.name}"


def test_scope_schema_js_exists_as_the_field_contract_source():
    assert SCOPE_SCHEMA_JS.exists(), f"missing {SCOPE_SCHEMA_JS}"
    text = _read(SCOPE_SCHEMA_JS)
    for field in SPEC_FIELDS:
        assert field in text
    assert "SCOPE_SCHEMA" in text


def test_scope_schema_js_matches_formal_scope_levels_and_fields():
    text = _read(SCOPE_SCHEMA_JS)
    match = re.search(r"root\.SCOPE_SCHEMA = (\{.*\});", text, re.DOTALL)
    assert match
    browser_schema = json.loads(match.group(1))
    central_scope = scope_contract()
    kind_map = {
        "scalar_text": "text",
        "list_text": "list",
        "reference": "ref",
        "metric": "metric",
        "enum": "enum",
    }

    assert set(browser_schema["levels"]) == set(central_scope["specs"])
    assert browser_schema["readingFields"] == sorted(central_scope["reading_fields"])
    for level, level_contract in central_scope["specs"].items():
        source_fields = level_contract["fields"]
        browser_level = browser_schema["levels"][level]
        assert browser_level["order"] == list(source_fields)
        assert set(browser_level["fields"]) == set(source_fields)
        for field, source in source_fields.items():
            projected = browser_level["fields"][field]
            assert projected["kind"] == kind_map[source["kind"]]
            if source["kind"] in {"scalar_text", "list_text", "metric"}:
                assert projected["minWords"] == source["min_words"]
                assert projected["maxWords"] == source["max_words"]
            if source["kind"] == "enum":
                assert projected["values"] == sorted(enum(source["enum"]))


def test_checked_in_scope_schema_is_exact_generated_snapshot():
    assert _read(SCOPE_SCHEMA_JS) == render_scope_schema_js()


def test_interface_contains_scope_schema_but_no_installed_python_renderer(tmp_path):
    sys.path.insert(0, str(ROOT / "skills" / "research-dashboard" / "scripts"))
    import ensure_dashboard  # noqa: WPS433

    ensure_dashboard.ensure_dashboard(tmp_path)
    dashboard_root = tmp_path / ".research" / "interface"
    assert not (dashboard_root / "scripts").exists()
    text = (dashboard_root / "data" / "scope-schema.js").read_text(encoding="utf-8")
    assert text == render_scope_schema_js()
    assert '"minWords": 3' in text


def test_inspector_logic_has_no_hardcoded_level_names():
    js = _read(INSPECTOR_JS)
    for literal in LEVEL_LITERALS:
        assert literal not in js, f"hardcoded level literal {literal} in scope-inspector.js"
