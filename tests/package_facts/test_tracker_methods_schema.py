import csv

from lib import package_facts


def test_live_check_columns_include_view_columns_and_provenance():
    assert package_facts.LIVE_CHECK_COLUMNS == [
        "row_id", "time", "exp_id", "run_id", "agent", "run_state",
        "last_log", "progress", "metrics", "resource", "artifacts",
        "eta", "action", "next_check", "source_artifact", "source_mtime",
        "extractor", "extracted_at",
    ]


def test_resource_allocation_columns_include_tracker_columns_and_provenance():
    assert package_facts.RESOURCE_ALLOCATION_COLUMNS == [
        "row_id", "exp_id", "purpose", "dependency", "target", "capacity",
        "assigned", "reason", "agent", "command_cwd_env", "session_job",
        "runtime_root", "log_path", "expected_duration", "status",
        "source_artifact", "source_mtime", "extractor", "extracted_at",
    ]


def test_methods_tried_columns_keep_registry_shape_and_source_ref():
    assert package_facts.METHODS_TRIED_COLUMNS == [
        "row_id", "exp_id", "method", "hypothesis", "gate", "measured",
        "verdict", "evidencePath", "source_table", "source_row",
        "source_artifact", "extracted_at",
    ]


def test_new_fact_table_headers_are_stable(tmp_path):
    cases = [
        ("live_checks.csv", package_facts.LIVE_CHECK_COLUMNS, {"row_id": "P1:r1"}),
        ("resource_allocation.csv", package_facts.RESOURCE_ALLOCATION_COLUMNS, {"row_id": "P1:r1"}),
        ("methods_tried.csv", package_facts.METHODS_TRIED_COLUMNS, {"row_id": "P1:method"}),
    ]
    for filename, columns, row in cases:
        path = tmp_path / filename
        package_facts.upsert_csv_rows(path, columns, [row])
        with path.open(newline="", encoding="utf-8") as f:
            assert next(csv.reader(f)) == columns
