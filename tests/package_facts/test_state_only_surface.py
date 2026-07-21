"""The package-facts module exposes no projection-store compatibility API."""

from pathlib import Path

from lib import package_facts


def test_only_pure_run_result_api_remains():
    assert callable(package_facts.load_run_result)
    for retired in (
        "propagate_run_result",
        "fact_paths",
        "table_csv_path",
        "read_csv_rows",
        "upsert_csv_rows",
        "load_facts_js",
        "write_facts_js",
        "record_page_projection",
        "assert_page_projection_fresh",
    ):
        assert not hasattr(package_facts, retired)


def test_module_has_no_legacy_authority_path_literals():
    source = Path(package_facts.__file__).read_text(encoding="utf-8")
    assert "research_html" not in source
    assert "outputs/" not in source
    assert ".csv" not in source
