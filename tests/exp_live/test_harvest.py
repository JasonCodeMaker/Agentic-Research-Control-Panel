import inspect
import json

from lib.exp_live import harvest
from lib.experiments import harvest as canonical_harvest


def _run():
    return {
        "run_id": "run-one",
        "package_id": "pkg",
        "experiment_id": "pkg::P1",
        "experiment_local_id": "P1",
    }


def test_adapter_chain_parses_training_output():
    custom = [harvest.compile_custom_regex(r"score=(?P<R1>\d+\.\d+)")]

    metric = harvest.parse_line(
        '{"step": 3, "total": 10, "loss": 0.4, "lr": 0.001}', custom
    )
    progress = harvest.parse_line(
        " 24%|##4| 1200/5000 [00:10<00:32, 118.5it/s]", custom
    )
    phase = harvest.parse_line("--- P2 evaluation start ---", custom)
    anomaly = harvest.parse_line("CUDA out of memory while allocating tensor", custom)
    custom_event = harvest.parse_line("custom logger score=32.7", custom)

    assert metric["values"] == {"loss": 0.4, "lr": 0.001}
    assert progress["step"] == 1200
    assert progress["total"] == 5000
    assert progress["rate"] == 118.5
    assert phase == {"kind": "phase", "label": "P2 evaluation start"}
    assert anomaly["kind"] == "anomaly" and anomaly["fatal"] is True
    assert custom_event["values"] == {"R1": 32.7}


def test_run_state_writes_canonical_status_inside_its_run_dir(tmp_path):
    run_dir = tmp_path / ".research" / "experiments" / "pkg" / "P1" / "run-one"
    state = harvest.RunState(
        run_dir=run_dir,
        run=_run(),
        heartbeat_timeout=600,
    )
    state.status = "RUNNING"
    state.started_at = 1000.0
    state.observe_line("warmup\n", at=1001.0)
    state.apply_event(
        {
            "kind": "progress",
            "step": 1200,
            "total": 50000,
            "rate": 4.2,
            "unit": "it/s",
        },
        at=1010.0,
    )
    state.apply_event(
        {
            "kind": "metric",
            "step": 1200,
            "values": {"loss": 0.41, "R@1": 31.2},
        },
        at=1011.0,
    )
    state.write_status(at=1012.0)

    status = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))
    assert status["status"] == "RUNNING"
    assert status["package_id"] == "pkg"
    assert status["experiment_id"] == "pkg::P1"
    assert status["latest_metrics"] == {"loss": 0.41, "R@1": 31.2}
    assert status["progress"]["pct"] == 2.4


def test_stale_and_terminal_states_are_mechanical(tmp_path):
    state = harvest.RunState(
        run_dir=tmp_path / ".research" / "experiments" / "pkg" / "P1" / "run",
        run={**_run(), "run_id": "run"},
        heartbeat_timeout=100,
        status="RUNNING",
        started_at=0.0,
    )
    state.observe_line("first output\n", at=1.0)
    assert state.snapshot(at=102.0)["status"] == "STALE"
    state.apply_event(
        {"kind": "anomaly", "label": "Traceback", "fatal": True},
        at=103.0,
    )
    state.finalize(exit_code=1, at=104.0)
    terminal = state.snapshot(at=105.0)
    assert terminal["status"] == "FAILED"
    assert terminal["health"]["state"] == "ERROR"


def test_deprecated_harvest_module_is_only_a_canonical_alias():
    assert harvest.RunState is canonical_harvest.RunState
    assert harvest.run_command is canonical_harvest.run_command
    source = inspect.getsource(harvest)
    assert "runs.jsonl" not in source
    assert "meta.json" not in source


def test_anomaly_word_boundaries_ignore_routine_logging():
    assert harvest.parse_line("INFO: dataloader worker 3 ready") is None
    assert harvest.parse_line("running inference on shard 2") is None
    assert harvest.parse_line("collecting information about the corpus") is None
    assert harvest.parse_line("killed 3 zombie dataloader workers") is None
