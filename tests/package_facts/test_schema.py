import csv
import re

import pytest

from lib import package_facts


def test_fact_paths_are_package_scoped(tmp_path):
    paths = package_facts.fact_paths("2026-06-11-demo", root=tmp_path)
    assert paths.facts_js == tmp_path / "research_html" / "data" / "packages" / "2026-06-11-demo.facts.js"
    assert paths.tables_dir == tmp_path / "research_html" / "data" / "packages" / "2026-06-11-demo" / "tables"
    assert paths.extractors_dir == tmp_path / "research_html" / "data" / "packages" / "2026-06-11-demo" / "extractors"


def test_write_and_load_facts_js_round_trip(tmp_path):
    facts = {
        "schemaVersion": 1,
        "packageId": "2026-06-11-demo",
        "updatedAt": "2026-06-11",
        "pages": {"results": {"headlineFact": "result_table_P1:best"}},
    }
    path = package_facts.write_facts_js("2026-06-11-demo", facts, root=tmp_path)
    text = path.read_text(encoding="utf-8")
    assert 'window.PACKAGE_FACTS["2026-06-11-demo"]' in text
    assert package_facts.load_facts_js("2026-06-11-demo", root=tmp_path) == facts


def test_csv_upsert_preserves_existing_rows_and_updates_by_row_id(tmp_path):
    path = tmp_path / "table.csv"
    columns = package_facts.RESULT_COLUMNS
    package_facts.upsert_csv_rows(path, columns, [
        {"row_id": "a", "exp_id": "P1", "metric": "Recall@1", "value": "41.0"},
        {"row_id": "b", "exp_id": "P1", "metric": "Recall@5", "value": "71.0"},
    ])
    package_facts.upsert_csv_rows(path, columns, [
        {"row_id": "a", "exp_id": "P1", "metric": "Recall@1", "value": "42.0"},
    ])
    rows = package_facts.read_csv_rows(path)
    assert [r["row_id"] for r in rows] == ["a", "b"]
    assert rows[0]["value"] == "42.0"
    assert rows[1]["value"] == "71.0"
    with path.open(newline="", encoding="utf-8") as f:
        assert next(csv.reader(f)) == columns


def test_upsert_requires_row_id(tmp_path):
    with pytest.raises(package_facts.FactError, match="row_id"):
        package_facts.upsert_csv_rows(tmp_path / "table.csv", package_facts.RESULT_COLUMNS, [
            {"exp_id": "P1", "metric": "Recall@1", "value": "42.0"},
        ])


def test_upsert_rejects_lowercase_result_validity(tmp_path):
    with pytest.raises(package_facts.FactError, match="validity"):
        package_facts.upsert_csv_rows(tmp_path / "table.csv", package_facts.RESULT_COLUMNS, [
            {"row_id": "best", "exp_id": "P1", "metric": "Recall@1", "value": "42.0", "validity": "valid"},
        ])


def test_upsert_rejects_unknown_experiment_verdict(tmp_path):
    with pytest.raises(package_facts.FactError, match="verdict"):
        package_facts.upsert_csv_rows(tmp_path / "table.csv", package_facts.RESULT_COLUMNS, [
            {"row_id": "best", "exp_id": "P1", "metric": "Recall@1", "value": "42.0", "verdict": "MAYBE"},
        ])


def test_source_ref_and_revision(tmp_path):
    path = tmp_path / "table.csv"
    path.write_text("row_id,value\nbest,42.0\n", encoding="utf-8")
    assert package_facts.source_ref("result_table_P1", "best") == "result_table_P1:best"
    digest = package_facts.file_revision(path)
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", digest)


def test_find_csv_row_by_source_ref(tmp_path):
    table = tmp_path / "result_table_P1.csv"
    table.write_text("row_id,value\nbest,42.0\n", encoding="utf-8")
    row = package_facts.find_row_by_ref(tmp_path, "result_table_P1:best")
    assert row["value"] == "42.0"
