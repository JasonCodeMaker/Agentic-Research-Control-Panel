"""Artifact contract for the Scope Inspector page (scope.html + wiring).

Locks the acceptance criteria from plan/2026-06-09-scope-inspector-live-view.md:
dashboard entry point, direct read of the canonical Scope logs, no dependency on
the dashboard scope-projection, explicit failure states, read-only, and the
no-hardcoded-SSOT-rules requirement (the tree/fields are data-driven).
"""

import re
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DASH = ROOT / "skills" / "research-dashboard" / "assets" / "dashboard"
SCOPE_HTML = DASH / "scope.html"
INDEX_HTML = DASH / "index.html"
INSPECTOR_JS = DASH / "assets" / "scope-inspector.js"
RESEARCH_JS = DASH / "assets" / "research.js"
SCOPE_SCHEMA_JS = DASH / "data" / "scope-schema.js"
SCOPE_SCHEMA_RENDERER = DASH / "scripts" / "render_scope_schema.py"

# Spec field names are SSOT schema rules; the live view must not hardcode them.
# `gate` is also transition metadata, so a plain text check would be a false positive.
SPEC_FIELDS = [
    "goal", "contributions", "out_of_scope",
    "hypothesis", "success_gate", "baselines",
    "experiment", "config", "control_mode",
]
LEVEL_LITERALS = ['"project"', '"direction"', '"task"', "'project'", "'direction'", "'task'"]


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
    assert "sourceTasks" in js
    assert "scope.html" in js


def test_scope_reads_canonical_logs_directly():
    html = _read(SCOPE_HTML)
    assert "outputs/_scope/transitions.jsonl" in html
    assert "outputs/_scope/triage.jsonl" in html


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
    assert "python -m http.server" in _read(SCOPE_HTML)   # static, always-visible hint


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


def test_scope_schema_js_is_generated_from_scope_ssot():
    spec = importlib.util.spec_from_file_location("render_scope_schema", SCOPE_SCHEMA_RENDERER)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    assert module.render_js() == _read(SCOPE_SCHEMA_JS)


def test_inspector_logic_has_no_hardcoded_level_names():
    js = _read(INSPECTOR_JS)
    for literal in LEVEL_LITERALS:
        assert literal not in js, f"hardcoded level literal {literal} in scope-inspector.js"
