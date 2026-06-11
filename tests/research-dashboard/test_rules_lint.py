"""lint-rules: registry schema, mirror sync, and slice consistency in one read-only check."""

import json
import sys
from pathlib import Path

SCRIPTS = (Path(__file__).resolve().parents[2]
           / "skills" / "research-dashboard" / "assets" / "dashboard" / "scripts")
sys.path.insert(0, str(SCRIPTS))
import learnings_lint as L  # noqa: E402


def _write_registry(root, rows):
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "data" / "rules.js").write_text(
        "window.RESEARCH_RULES = " + json.dumps(rows) + ";\n")


def _rule_file(root, name, ids):
    (root / "rules").mkdir(parents=True, exist_ok=True)
    cards = "".join(
        f'<article class="rule-card" data-rule="{i}" data-kind="x"><h3 class="title">{i} title</h3></article>'
        for i in ids)
    (root / "rules" / name).write_text(f"<html><body>{cards}</body></html>")


def _mirror(rid, name, kind):
    return {"id": rid, "level": "universal", "kind": kind, "title": f"{rid} title",
            "source": f"rules/{name}#{rid}", "origin": "mirror",
            "status": "ACTIVE", "addedAt": "bundled"}


def _setup(root):
    _rule_file(root, "html-rules.html", ["R1"])
    _rule_file(root, "trustworthy-research-rules.html", ["T1"])
    return [_mirror("R1", "html-rules.html", "form"),
            _mirror("T1", "trustworthy-research-rules.html", "trust")]


def _codes(rep):
    return {v.code for v in rep.errors()}


def test_clean_registry_passes(tmp_path):
    root = tmp_path / "research_html"
    _write_registry(root, _setup(root))
    rep = L.lint_rules(root)
    assert not rep.errors()


def test_schema_violation_is_error(tmp_path):
    root = tmp_path / "research_html"
    rows = _setup(root) + [{"id": "PRJ-bad", "level": "project", "kind": "constraint"}]
    _write_registry(root, rows)
    assert "rule-row-schema" in _codes(L.lint_rules(root))


def test_malformed_json_is_lint_error(tmp_path):
    root = tmp_path / "research_html"
    (root / "data").mkdir(parents=True)
    (root / "data" / "rules.js").write_text("window.RESEARCH_RULES = [{bad}];\n")
    assert "rule-store-malformed" in _codes(L.lint_rules(root))


def test_mutable_rule_missing_text_or_rationale_is_schema_error(tmp_path):
    root = tmp_path / "research_html"
    rows = _setup(root) + [
        {"id": "PRJ-missing-text", "level": "project", "kind": "constraint",
         "title": "bad", "source": "user", "origin": "user", "status": "ACTIVE",
         "addedAt": "2026-06-11"},
    ]
    _write_registry(root, rows)
    assert "rule-row-schema" in _codes(L.lint_rules(root))


def test_level_kind_mismatch_is_error(tmp_path):
    root = tmp_path / "research_html"
    rows = _setup(root) + [
        {"id": "PRJ-bad", "level": "project", "kind": "lesson", "title": "bad",
         "text": "bad", "rationale": "bad", "source": "user", "origin": "user",
         "status": "ACTIVE", "addedAt": "2026-06-11"},
    ]
    _write_registry(root, rows)
    assert "rule-kind-mismatch" in _codes(L.lint_rules(root))


def test_mirror_drift_is_error(tmp_path):
    root = tmp_path / "research_html"
    rows = _setup(root)
    _rule_file(root, "html-rules.html", ["R1", "R2"])  # shipped file gained R2; mirror stale
    _write_registry(root, rows)
    assert "rule-mirror-drift" in _codes(L.lint_rules(root))


def test_duplicate_id_is_error(tmp_path):
    root = tmp_path / "research_html"
    rows = _setup(root)
    dup = dict(rows[0])
    _write_registry(root, rows + [dup])
    assert "rule-id-duplicate" in _codes(L.lint_rules(root))


def test_active_lesson_row_not_painted_is_error(tmp_path):
    root = tmp_path / "research_html"
    pkg = root / "packages" / "pkg-a"
    pkg.mkdir(parents=True)
    (pkg / "analysis.html").write_text(
        '<html><body><ol class="rules-list" data-list="rules">'
        '<li><em>No rules recorded yet.</em></li>'
        '</ol></body></html>'
    )
    rows = _setup(root) + [
        {"id": "pkg-a#no-mock", "level": "package", "pkg": "pkg-a",
         "kind": "lesson", "title": "No mocked metrics",
         "text": "Never paste metrics without artifacts.", "rationale": "insight-no-mock",
         "source": "analysis", "origin": "user", "status": "ACTIVE",
         "addedAt": "2026-06-11"},
    ]
    _write_registry(root, rows)
    assert "rule-paint-drift" in _codes(L.lint_rules(root))


def test_painted_rule_without_active_lesson_row_is_error(tmp_path):
    root = tmp_path / "research_html"
    pkg = root / "packages" / "pkg-a"
    pkg.mkdir(parents=True)
    (pkg / "analysis.html").write_text(
        '<html><body><ol class="rules-list" data-list="rules">'
        '<li class="card-text" id="rule-stale">Stale rule.</li>'
        '</ol></body></html>'
    )
    _write_registry(root, _setup(root))
    assert "rule-paint-drift" in _codes(L.lint_rules(root))
