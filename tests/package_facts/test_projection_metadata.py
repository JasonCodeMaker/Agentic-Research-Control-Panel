import re

import pytest

from lib import package_facts


def test_load_facts_js_returns_empty_when_absent(tmp_path):
    assert package_facts.load_facts_js("2026-06-11-demo", root=tmp_path) == {}


def test_record_page_projection_writes_metadata_and_preserves_existing_facts(tmp_path):
    pkg = "2026-06-11-demo"
    paths = package_facts.fact_paths(pkg, root=tmp_path)
    source = paths.tables_dir / "result_table_P1.csv"
    source.parent.mkdir(parents=True)
    source.write_text("row_id,value\nbest,42.0\n", encoding="utf-8")
    html_path = tmp_path / "research_html" / "packages" / pkg / "results.html"
    html_path.parent.mkdir(parents=True)
    html_path.write_text("<html>42.0</html>", encoding="utf-8")
    package_facts.write_facts_js(pkg, {"schemaVersion": 1, "packageId": pkg}, root=tmp_path)

    package_facts.record_page_projection(
        pkg,
        "results.html",
        ["tables/result_table_P1.csv"],
        html_path,
        "render_result_facts.py",
        root=tmp_path,
    )

    facts = package_facts.load_facts_js(pkg, root=tmp_path)
    assert facts["schemaVersion"] == 1
    projection = facts["projections"]["pages"]["results.html"]
    assert projection["renderer"] == "render_result_facts.py"
    assert projection["sources"]["tables/result_table_P1.csv"] == package_facts.file_revision(source)
    assert projection["htmlRevision"] == package_facts.file_revision(html_path)
    assert re.match(r"\d{4}-\d{2}-\d{2}T", projection["renderedAt"])


def test_assert_page_projection_fresh_detects_source_drift(tmp_path):
    pkg = "2026-06-11-demo"
    paths = package_facts.fact_paths(pkg, root=tmp_path)
    source = paths.tables_dir / "result_table_P1.csv"
    source.parent.mkdir(parents=True)
    source.write_text("row_id,value\nbest,42.0\n", encoding="utf-8")
    html_path = tmp_path / "research_html" / "packages" / pkg / "results.html"
    html_path.parent.mkdir(parents=True)
    html_path.write_text("<html>42.0</html>", encoding="utf-8")
    package_facts.record_page_projection(
        pkg,
        "results.html",
        ["tables/result_table_P1.csv"],
        html_path,
        "render_result_facts.py",
        root=tmp_path,
    )

    package_facts.assert_page_projection_fresh(pkg, "results.html", root=tmp_path)
    source.write_text("row_id,value\nbest,43.0\n", encoding="utf-8")
    with pytest.raises(package_facts.FactError, match="stale source"):
        package_facts.assert_page_projection_fresh(pkg, "results.html", root=tmp_path)


def test_assert_page_projection_fresh_detects_html_drift(tmp_path):
    pkg = "2026-06-11-demo"
    paths = package_facts.fact_paths(pkg, root=tmp_path)
    source = paths.tables_dir / "result_table_P1.csv"
    source.parent.mkdir(parents=True)
    source.write_text("row_id,value\nbest,42.0\n", encoding="utf-8")
    html_path = tmp_path / "research_html" / "packages" / pkg / "results.html"
    html_path.parent.mkdir(parents=True)
    html_path.write_text("<html>42.0</html>", encoding="utf-8")
    package_facts.record_page_projection(
        pkg,
        "results.html",
        ["tables/result_table_P1.csv"],
        html_path,
        "render_result_facts.py",
        root=tmp_path,
    )

    html_path.write_text("<html>hand edit</html>", encoding="utf-8")
    with pytest.raises(package_facts.FactError, match="stale html"):
        package_facts.assert_page_projection_fresh(pkg, "results.html", root=tmp_path)
