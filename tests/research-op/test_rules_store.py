"""rules.js store helpers: JSON-in-JS load/save round-trip + row validation (核心问题 #2)."""

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "research-op" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import rules_store  # noqa: E402


def _row(**kw):
    r = {"id": "PRJ-no-test-data", "level": "project", "kind": "constraint",
         "title": "No test data in training", "text": "Never train on the eval split.",
         "rationale": "leakage", "source": "user directive", "origin": "user",
         "status": "ACTIVE", "addedAt": "2026-06-11"}
    r.update(kw)
    return r


def test_load_missing_file_returns_empty(tmp_path):
    assert rules_store.load_rules(tmp_path / "research_html") == []


def test_load_invalid_json_raises_row_error(tmp_path):
    root = tmp_path / "research_html"
    (root / "data").mkdir(parents=True)
    (root / "data" / "rules.js").write_text("window.RESEARCH_RULES = [{bad}];\n")
    with pytest.raises(rules_store.RuleRowError):
        rules_store.load_rules(root)


def test_save_then_load_round_trips(tmp_path):
    root = tmp_path / "research_html"
    rules_store.save_rules(root, [_row()])
    rules = rules_store.load_rules(root)
    assert rules == [_row()]
    text = (root / "data" / "rules.js").read_text()
    assert text.startswith("window.RESEARCH_RULES = ") and text.rstrip().endswith(";")


def test_validate_rejects_missing_required_field():
    with pytest.raises(rules_store.RuleRowError):
        rules_store.validate_row(_row(title=""))


def test_validate_requires_text_and_rationale_for_mutable_rows():
    with pytest.raises(rules_store.RuleRowError):
        rules_store.validate_row(_row(text=""))
    with pytest.raises(rules_store.RuleRowError):
        rules_store.validate_row(
            _row(id="2026-06-11-foo#no-mock", level="package", pkg="2026-06-11-foo",
                 kind="binding", rationale="")
        )
    rules_store.validate_row(_row(id="R1", level="universal", kind="form",
                                  text="", rationale=""))


def test_validate_rejects_bad_level_and_kind():
    with pytest.raises(rules_store.RuleRowError):
        rules_store.validate_row(_row(level="galaxy"))
    with pytest.raises(rules_store.RuleRowError):
        rules_store.validate_row(_row(kind="vibe"))


def test_validate_rejects_level_kind_mismatches():
    with pytest.raises(rules_store.RuleRowError):
        rules_store.validate_row(_row(level="project", kind="lesson"))
    with pytest.raises(rules_store.RuleRowError):
        rules_store.validate_row(
            _row(id="2026-06-11-foo#bad", level="package", pkg="2026-06-11-foo", kind="constraint")
        )
    with pytest.raises(rules_store.RuleRowError):
        rules_store.validate_row(_row(id="R99", level="universal", kind="constraint"))


def test_validate_package_row_needs_pkg_and_id_prefix():
    ok = _row(id="2026-06-11-foo#no-mock", level="package", pkg="2026-06-11-foo", kind="binding")
    rules_store.validate_row(ok)
    with pytest.raises(rules_store.RuleRowError):
        rules_store.validate_row(_row(level="package", kind="binding"))  # no pkg


def test_validate_lifecycle_fields():
    with pytest.raises(rules_store.RuleRowError):
        rules_store.validate_row(_row(status="RETIRED"))  # no retireReason
    with pytest.raises(rules_store.RuleRowError):
        rules_store.validate_row(_row(status="PROMOTED"))  # no promotedTo
    rules_store.validate_row(_row(status="RETIRED", retireReason="superseded"))


def test_duplicate_id_rejected_on_save(tmp_path):
    with pytest.raises(rules_store.RuleRowError):
        rules_store.save_rules(tmp_path / "research_html", [_row(), _row()])
