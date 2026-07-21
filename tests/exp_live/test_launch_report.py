import inspect
import json

import pytest

from lib.exp_live import launch, report
from lib.experiments import launch as canonical_launch
from lib.experiments import report as canonical_report


def test_deprecated_module_name_is_a_thin_canonical_alias():
    assert launch.launch_run is canonical_launch.launch_run
    assert launch.prepare_run is canonical_launch.prepare_run
    assert report.open_runs is canonical_report.open_runs
    assert report.run_summary is canonical_report.run_summary


def test_legacy_outputs_root_option_is_not_a_writer_surface():
    with pytest.raises(SystemExit) as exc:
        launch.main(
            [
                "--package",
                "pkg",
                "--experiment",
                "P1",
                "--outputs-root",
                "outputs",
                "--",
                "true",
            ]
        )
    assert exc.value.code != 0


def test_report_run_bounds_log_tail_and_reads_canonical_envelope(tmp_path):
    run_dir = tmp_path / ".research" / "experiments" / "pkg-a" / "P1" / "run-one"
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(
        json.dumps({"run_id": "run-one", "package_id": "pkg-a"}),
        encoding="utf-8",
    )
    (run_dir / "context.json").write_text(
        json.dumps({"source_seq": 1, "source_hash": "abc"}),
        encoding="utf-8",
    )
    (run_dir / "status.json").write_text(
        json.dumps({"status": "FAILED", "exit_code": 1}),
        encoding="utf-8",
    )
    (run_dir / "result.json").write_text(
        json.dumps({"verdict": "INCONCLUSIVE"}),
        encoding="utf-8",
    )
    (run_dir / "events.jsonl").write_text(
        json.dumps({"kind": "anomaly", "label": "Traceback"}) + "\n",
        encoding="utf-8",
    )
    (run_dir / "log.txt").write_text(
        "\n".join(f"line {index}" for index in range(100)) + "\n",
        encoding="utf-8",
    )

    summary = report.run_summary(run_dir, tail=5)
    assert summary["run"]["run_id"] == "run-one"
    assert summary["context"]["source_seq"] == 1
    assert summary["status"]["status"] == "FAILED"
    assert summary["result"]["verdict"] == "INCONCLUSIVE"
    assert summary["tail"] == [f"line {index}" for index in range(95, 100)]
    assert summary["anomalies"][0]["label"] == "Traceback"


def test_compatibility_modules_contain_no_legacy_storage_implementation():
    for module in (launch, report):
        source = inspect.getsource(module)
        assert "runs.jsonl" not in source
        assert "meta.json" not in source
