import json

from lib.experiments import harvest


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


def test_debug_totals_cannot_overwrite_progress_boundary(tmp_path):
    event = harvest.parse_line(
        "[search][dbg] payload shape=(64, 3, 160, 224) "
        "fps=1.0 total=64 idx_len=64 idx_last=63"
    )
    assert event["kind"] == "metric"
    assert event["values"]["total"] == 64
    assert "total" not in event

    state = harvest.RunState(
        run_dir=tmp_path / "run",
        run=_run(),
        status="RUNNING",
    )
    state.apply_event(
        {
            "kind": "progress",
            "source": "tqdm",
            "step": 125,
            "total": 40492,
            "rate": 6.14,
            "unit": "s/it",
        },
        at=1.0,
    )
    state.apply_event(
        {
            "kind": "metric",
            "source": "kv-metrics",
            "step": 125,
            "total": 64,
            "values": {"fps": 1.0},
        },
        at=2.0,
    )

    assert state.progress == {"step": 125, "total": 40492, "pct": 0.31}


def test_authorized_total_steps_owns_progress_boundary(tmp_path):
    state = harvest.RunState(
        run_dir=tmp_path / "run",
        run=_run(),
        status="RUNNING",
        total_steps=40492,
    )
    state.apply_event(
        {
            "kind": "progress",
            "source": "tqdm",
            "step": 125,
            "total": 64,
            "rate": 6.14,
            "unit": "s/it",
        },
        at=1.0,
    )

    assert state.progress == {"step": 125, "total": 40492, "pct": 0.31}


def test_all_metric_sources_are_progress_attribution_only(tmp_path):
    state = harvest.RunState(
        run_dir=tmp_path / "run",
        run=_run(),
        status="RUNNING",
    )
    state.apply_event(
        {
            "kind": "progress",
            "source": "tqdm",
            "step": 125,
            "total": 40492,
        },
        at=1.0,
    )
    for source in ("jsonl", "custom", "kv-metrics"):
        state.apply_event(
            {
                "kind": "metric",
                "source": source,
                "step": 999,
                "total": 64,
                "values": {"loss": 0.4},
            },
            at=2.0,
        )

    assert state.progress == {"step": 125, "total": 40492, "pct": 0.31}


def test_progress_boundary_and_step_are_monotonic(tmp_path):
    state = harvest.RunState(
        run_dir=tmp_path / "run",
        run=_run(),
        status="RUNNING",
    )
    state.apply_event(
        {"kind": "progress", "step": 125, "total": 40492},
        at=1.0,
    )
    state.apply_event(
        {"kind": "progress", "step": 126, "total": 64},
        at=2.0,
    )
    state.apply_event(
        {"kind": "progress", "step": 124, "total": 40492},
        at=3.0,
    )

    assert state.progress == {"step": 125, "total": 40492, "pct": 0.31}
    assert state.warning_reasons == [
        "conflicting progress boundary ignored",
        "invalid progress ignored",
    ]


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


def test_anomaly_word_boundaries_ignore_routine_logging():
    assert harvest.parse_line("INFO: dataloader worker 3 ready") is None
    assert harvest.parse_line("running inference on shard 2") is None
    assert harvest.parse_line("collecting information about the corpus") is None
    assert harvest.parse_line("killed 3 zombie dataloader workers") is None
    assert harvest.parse_line('    "steps_per_print": inf,') is None
    assert harvest.parse_line("loss=inf")["kind"] == "anomaly"
