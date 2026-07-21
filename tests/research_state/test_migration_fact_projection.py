from lib.research_state.migration_facts import legacy_package_fact_projection


def test_legacy_fact_projection_is_bounded_and_marks_rows_unbound():
    package = {
        "id": "pkg",
        "legacy_fact_store": {
            "files": {
                "tables/methods_tried.csv": {
                    "format": "csv",
                    "sha256": "a" * 64,
                    "data": [
                        {
                            "row_id": "method-1",
                            "exp_id": "P0",
                            "method": "legacy baseline",
                            "verdict": "FAIL",
                        }
                    ],
                },
                "tables/result_gate.csv": {
                    "format": "csv",
                    "sha256": "b" * 64,
                    "data": [
                        {
                            "row_id": "gate-1",
                            "exp_id": "P0",
                            "metric": "accuracy",
                            "value": "0.9",
                            "verdict": "PASS",
                            "validity": "VALID",
                        }
                    ],
                },
            }
        },
    }

    projection = legacy_package_fact_projection(package)

    method = projection["methodsTried"][0]
    gate = projection["resultGateRows"][0]
    assert method["legacy_unbound"] is True
    assert gate["legacy_unbound"] is True
    assert method["source_fact"]["sha256"] == "a" * 64
    assert gate["source_fact"]["sha256"] == "b" * 64
    assert gate["observed_metric"] == "0.9"
    assert gate["plan_gate"] == "accuracy"
    assert projection["resultBlocks"] == []
