import json
from pathlib import Path

from lib.exp_live import harvest


def test_adapter_chain_parses_jsonl_tqdm_kv_phase_and_anomaly():
    custom = [harvest.compile_custom_regex(r"score=(?P<R1>\d+\.\d+)")]

    json_event = harvest.parse_line('{"step": 3, "total": 10, "loss": 0.4, "lr": 0.001}', custom)
    tqdm_event = harvest.parse_line(" 24%|##4| 1200/5000 [00:10<00:32, 118.5it/s]", custom)
    kv_event = harvest.parse_line("Epoch 3: val R@1: 31.2 loss=0.41", custom)
    phase_event = harvest.parse_line("--- P2 evaluation start ---", custom)
    anomaly_event = harvest.parse_line("CUDA out of memory while allocating tensor", custom)
    custom_event = harvest.parse_line("custom logger score=32.7", custom)

    assert json_event["kind"] == "metric"
    assert json_event["step"] == 3
    assert json_event["total"] == 10
    assert json_event["values"] == {"loss": 0.4, "lr": 0.001}

    assert tqdm_event["kind"] == "progress"
    assert tqdm_event["step"] == 1200
    assert tqdm_event["total"] == 5000
    assert tqdm_event["rate"] == 118.5

    assert kv_event["kind"] == "metric"
    assert kv_event["step"] is None
    assert kv_event["values"]["R@1"] == 31.2
    assert kv_event["values"]["loss"] == 0.41

    assert phase_event == {"kind": "phase", "label": "P2 evaluation start"}
    assert anomaly_event["kind"] == "anomaly"
    assert anomaly_event["fatal"] is True
    assert custom_event["source"] == "custom"
    assert custom_event["values"] == {"R1": 32.7}


def test_run_state_writes_status_json_from_typed_events(tmp_path):
    run_dir = tmp_path / "outputs" / "pkg" / "runs" / "P2-20260610-141500"
    state = harvest.RunState(
        run_dir=run_dir,
        meta={"run_id": "P2-20260610-141500", "pkg": "pkg", "exp_id": "P2", "started_at": 1000.0},
        heartbeat_timeout=600,
        total_steps=None,
    )

    state.observe_line("warmup\n", now=1001.0)
    state.apply_event({"kind": "progress", "step": 1200, "total": 50000, "rate": 4.2, "unit": "it/s"}, now=1010.0)
    state.apply_event({"kind": "metric", "step": 1200, "values": {"loss": 0.41, "R@1": 31.2}}, now=1011.0)
    state.write_status(now=1012.0)

    status = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))
    assert status["status"] == "RUNNING"
    assert status["health"] == {"state": "OK", "reasons": []}
    assert status["progress"]["step"] == 1200
    assert status["progress"]["total"] == 50000
    assert status["progress"]["pct"] == 2.4
    assert status["latest_metrics"] == {"loss": 0.41, "R@1": 31.2}
    assert status["throughput"]["stable_since"] == 1010.0
    assert status["eta"] == "unknown"
    assert status["first_output_at"] == 1001.0
    assert status["last_output_at"] == 1011.0
    assert status["log_lines"] == 1


def test_eta_waits_for_thirty_minutes_of_stable_throughput(tmp_path):
    run_dir = tmp_path / "outputs" / "pkg" / "runs" / "P1-20260610-141500"
    state = harvest.RunState(
        run_dir=run_dir,
        meta={"run_id": "P1-20260610-141500", "pkg": "pkg", "exp_id": "P1", "started_at": 0.0},
        heartbeat_timeout=600,
        total_steps=100,
    )

    state.apply_event({"kind": "progress", "step": 10, "rate": 2.0, "unit": "it/s"}, now=10.0)
    assert state.snapshot(now=1000.0)["eta"] == "unknown"

    status = state.snapshot(now=1811.0)
    assert status["eta"] == "45s"


def test_health_stale_and_terminal_states_are_mechanical(tmp_path):
    run_dir = tmp_path / "outputs" / "pkg" / "runs" / "P3-20260610-141500"
    state = harvest.RunState(
        run_dir=run_dir,
        meta={"run_id": "P3-20260610-141500", "pkg": "pkg", "exp_id": "P3", "started_at": 0.0},
        heartbeat_timeout=100,
        total_steps=None,
    )

    state.observe_line("first output\n", now=1.0)
    warn = state.snapshot(now=60.0)
    stale = state.snapshot(now=102.0)
    state.apply_event({"kind": "anomaly", "label": "Traceback", "tail": "Traceback...", "fatal": True}, now=103.0)
    state.finalize(exit_code=1, now=104.0)
    failed = state.snapshot(now=105.0)

    assert warn["status"] == "RUNNING"
    assert warn["health"]["state"] == "WARN"
    assert "output silent" in warn["health"]["reasons"][0]

    assert stale["status"] == "STALE"
    assert stale["health"]["state"] == "WARN"

    assert failed["status"] == "RUN_FAILED"
    assert failed["health"]["state"] == "ERROR"
    assert failed["exit_code"] == 1
    assert failed["ended_at"] == 104.0


def test_harness_paths_stay_under_outputs():
    for rel in harvest.HARNESS_WRITE_PATHS:
        assert Path(rel).parts[0] == "outputs"


def test_anomaly_word_boundaries_ignore_routine_logging():
    # F2: INFO / inference / lowercase "killed" prose must not be anomalies.
    assert harvest.parse_line("INFO: dataloader worker 3 ready") is None
    assert harvest.parse_line("running inference on shard 2") is None
    assert harvest.parse_line("collecting information about the corpus") is None
    assert harvest.parse_line("killed 3 zombie dataloader workers") is None


def test_anomaly_detects_real_failure_and_numeric_instability_markers():
    nan = harvest.parse_line("Loss is nan at step 10")
    assert nan["kind"] == "anomaly" and nan["fatal"] is False

    inf = harvest.parse_line("gradient norm is inf, skipping update")
    assert inf["kind"] == "anomaly" and inf["fatal"] is False

    oom = harvest.parse_line("RuntimeError: CUDA out of memory. Tried to allocate 2.00 GiB")
    assert oom["kind"] == "anomaly" and oom["fatal"] is True

    killed = harvest.parse_line("Killed")
    assert killed["kind"] == "anomaly" and killed["fatal"] is True


def test_phase_parser_requires_marker_shape_not_bare_prose():
    assert harvest.parse_line("loading phase information from disk") is None
    fenced = harvest.parse_line("### P1 train start")
    assert fenced == {"kind": "phase", "label": "P1 train start"}
    numbered = harvest.parse_line("Phase 2 begins")
    assert numbered["kind"] == "phase"


def test_zero_output_run_goes_stale_from_started_at(tmp_path):
    # F1b: a run that never prints must still go STALE (age from started_at).
    state = harvest.RunState(
        run_dir=tmp_path / "r",
        meta={"run_id": "P7", "pkg": "pkg", "exp_id": "P7", "started_at": 0.0},
        heartbeat_timeout=100,
    )
    snap = state.snapshot(now=150.0)
    assert snap["status"] == "STALE"
    assert snap["health"]["state"] == "WARN"


def test_snapshot_includes_heartbeat_timeout_and_pids(tmp_path):
    # F4: liveness checks need pids; readers need the timeout to derive STALE.
    import os

    state = harvest.RunState(
        run_dir=tmp_path / "r",
        meta={"run_id": "P8", "pkg": "pkg", "exp_id": "P8", "started_at": 0.0},
        heartbeat_timeout=300,
    )
    state.child_pid = 4242
    snap = state.snapshot(now=1.0)
    assert snap["heartbeat_timeout"] == 300
    assert snap["pid"] == 4242
    assert snap["harvester_pid"] == os.getpid()


def test_run_command_watchdog_flips_stale_during_silence(tmp_path):
    # F1: the harvester must re-write status on its own clock while the child is silent.
    import json as _json
    import sys
    import threading
    import time as _time

    run_dir = tmp_path / "outputs" / "pkg" / "runs" / "P9"
    meta = {"run_id": "P9", "pkg": "pkg", "exp_id": "P9", "started_at": _time.time()}
    code = "import time; print('hello', flush=True); time.sleep(2.5)"
    worker = threading.Thread(
        target=harvest.run_command,
        kwargs=dict(
            run_dir=run_dir,
            meta=meta,
            command=[sys.executable, "-c", code],
            heartbeat_timeout=1,
            watchdog_interval=0.2,
        ),
    )
    worker.start()
    saw_stale = False
    deadline = _time.time() + 4
    status_path = run_dir / "status.json"
    while _time.time() < deadline:
        if status_path.exists():
            snap = _json.loads(status_path.read_text(encoding="utf-8"))
            if snap["status"] == "STALE":
                saw_stale = True
                break
        _time.sleep(0.1)
    worker.join()
    assert saw_stale, "status.json never showed STALE during silence"
    final = _json.loads(status_path.read_text(encoding="utf-8"))
    assert final["status"] == "COMPLETED"


def test_run_command_throttles_status_writes(tmp_path, monkeypatch):
    # F5: 300 fast output lines must not mean 300 status.json rewrites.
    import sys

    writes = []
    real_atomic = harvest.atomic_json

    def counting(path, data):
        if path.name == "status.json":
            writes.append(path)
        real_atomic(path, data)

    monkeypatch.setattr(harvest, "atomic_json", counting)
    run_dir = tmp_path / "outputs" / "pkg" / "runs" / "P10"
    meta = {"run_id": "P10", "pkg": "pkg", "exp_id": "P10", "started_at": 0.0}
    code = "for i in range(300): print(f'line {i}', flush=True)"
    harvest.run_command(
        run_dir=run_dir,
        meta=meta,
        command=[sys.executable, "-c", code],
        heartbeat_timeout=600,
        watchdog_interval=30.0,
    )
    log_lines = (run_dir / "log.txt").read_text(encoding="utf-8").splitlines()
    assert len(log_lines) == 300
    assert len(writes) < 30, f"expected throttled status writes, saw {len(writes)}"


def test_gpu_sampler_parses_nvidia_smi_and_flows_into_snapshot(tmp_path):
    def fake_runner(cmd, capture_output, text, timeout):
        class Result:
            stdout = "87, 39322\n"
            returncode = 0

        assert "nvidia-smi" in cmd[0]
        return Result()

    sampler = harvest.gpu_sampler(["0"], runner=fake_runner)
    sample = sampler()
    assert sample == {"gpu_util": 87.0, "gpu_mem_gb": 38.4}

    state = harvest.RunState(
        run_dir=tmp_path / "r",
        meta={"run_id": "P11", "pkg": "pkg", "exp_id": "P11", "started_at": 0.0},
        heartbeat_timeout=600,
    )
    state.resource = sample
    assert state.snapshot(now=1.0)["resource"] == {"gpu_util": 87.0, "gpu_mem_gb": 38.4}
