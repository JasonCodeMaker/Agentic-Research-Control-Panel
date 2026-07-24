import csv
import io

import pytest

from lib.experiments.result_tables import _table_csv
from lib.result_schema import (
    parse_result_table_csv,
    planned_result_table,
    validate_result_schema,
)


def _schema():
    return {
        "version": 1,
        "tables": [
            {
                "id": "effectiveness",
                "type": "main",
                "title": "Effectiveness",
                "rowLabel": "Method",
                "rows": [
                    {
                        "id": "local",
                        "label": "Local run",
                        "selector": {"method": "local"},
                    },
                    {
                        "id": "paper",
                        "label": "Paper baseline",
                        "reference": {
                            "citation": "Paper, Table 2",
                            "url": "https://arxiv.org/abs/0000.00000",
                            "values": {"recall_at_1": 61.1},
                        },
                    },
                ],
                "columns": [
                    {
                        "id": "r1",
                        "label": "R@1",
                        "metric": "recall_at_1",
                        "unit": "percent",
                    },
                    {
                        "id": "runtime",
                        "label": "Runtime",
                        "metric": "runtime_seconds",
                        "unit": "second",
                    },
                ],
            }
        ],
    }


def test_reference_rows_render_before_and_survive_result_extraction():
    table = validate_result_schema(_schema())["tables"][0]
    planned = planned_result_table(table)
    paper = planned["rows"][1]
    assert paper["r1"] == 61.1
    assert paper["_cells"]["r1"]["status"] == "REPORTED"
    assert paper["runtime"] is None
    assert paper["_cells"]["runtime"]["status"] == "NOT_REPORTED"

    source = [
        {
            "method": "local",
            "metric": "recall_at_1",
            "value": "60.0",
            "unit": "percent",
            "status": "MEASURED",
            "reason": "",
        },
        {
            "method": "local",
            "metric": "runtime_seconds",
            "value": "120",
            "unit": "second",
            "status": "MEASURED",
            "reason": "",
        },
    ]
    content = _table_csv(table, source).decode()
    rows = list(csv.DictReader(io.StringIO(content)))
    assert rows[1]["r1"] == "61.1"
    assert rows[1]["r1__status"] == "REPORTED"
    assert rows[1]["runtime__status"] == "NOT_REPORTED"

    forged = content.replace(",60.0,MEASURED,", ",60.0,REPORTED,", 1)
    with pytest.raises(ValueError, match="wrong row type"):
        parse_result_table_csv(table, forged)
