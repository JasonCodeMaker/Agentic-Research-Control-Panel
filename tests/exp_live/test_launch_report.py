import json
import sys

from lib.exp_live import launch, report


def _lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_launch_run_foreground_creates_run_artifacts_and_global_index(tmp_path):
    outputs_root = tmp_path / "outputs"
    result = launch.launch_run(
        pkg="pkg-a",
        exp_id="P2",
        command=[
            sys.executable,
            "-c",
            (
                "import json; "
                "print(json.dumps({'step': 2, 'total': 4, 'loss': 0.25}), flush=True)"
            ),
        ],
        outputs_root=outputs_root,
        tmux_session="test-p2",
        use_tmux=False,
        now=lambda: 1765430000.0,
    )

    run_dir = result.run_dir
    assert result.run_id == "P2-20251211-051320"
    assert (run_dir / "meta.json").exists()
    assert (run_dir / "events.jsonl").exists()
    assert (run_dir / "status.json").exists()
    assert (run_dir / "log.txt").exists()

    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["pkg"] == "pkg-a"
    assert meta["exp_id"] == "P2"
    assert meta["tmux_session"] == "test-p2"
    assert meta["transport"] == "local-tmux"
    assert meta["command"][:2] == [sys.executable, "-c"]

    status = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))
    assert status["status"] == "COMPLETED"
    assert status["latest_metrics"]["loss"] == 0.25
    assert status["progress"]["step"] == 2
    assert status["exit_code"] == 0

    index_lines = _lines(outputs_root / "_live" / "runs.jsonl")
    assert [line["op"] for line in index_lines] == ["launched", "terminal"]
    assert index_lines[0]["dir"] == str(run_dir)
    assert index_lines[1]["final_status"] == "COMPLETED"


def test_launch_run_rejects_commands_without_separator(tmp_path):
    try:
        launch.main(["--pkg", "pkg", "--exp", "P1", "--outputs-root", str(tmp_path / "outputs")])
    except SystemExit as exc:
        assert exc.code != 0
    else:
        raise AssertionError("launch.main should reject missing command")


def test_report_open_lists_only_non_terminal_runs(tmp_path):
    outputs = tmp_path / "outputs"
    open_dir = outputs / "pkg-a" / "runs" / "P1-20260610-100000"
    done_dir = outputs / "pkg-b" / "runs" / "P2-20260610-100000"
    open_dir.mkdir(parents=True)
    done_dir.mkdir(parents=True)
    (outputs / "_live").mkdir(parents=True)

    (open_dir / "status.json").write_text(
        json.dumps({
            "run_id": "P1-20260610-100000",
            "pkg": "pkg-a",
            "exp_id": "P1",
            "status": "STALE",
            "last_output_at": 100.0,
        }),
        encoding="utf-8",
    )
    (done_dir / "status.json").write_text(
        json.dumps({
            "run_id": "P2-20260610-100000",
            "pkg": "pkg-b",
            "exp_id": "P2",
            "status": "COMPLETED",
            "last_output_at": 110.0,
            "ended_at": 120.0,
        }),
        encoding="utf-8",
    )
    index = outputs / "_live" / "runs.jsonl"
    index.write_text(
        "\n".join([
            json.dumps({"op": "launched", "run_id": "P1-20260610-100000", "pkg": "pkg-a", "exp_id": "P1", "dir": str(open_dir), "started_at": 0}),
            json.dumps({"op": "launched", "run_id": "P2-20260610-100000", "pkg": "pkg-b", "exp_id": "P2", "dir": str(done_dir), "started_at": 0}),
            json.dumps({"op": "terminal", "run_id": "P2-20260610-100000", "final_status": "COMPLETED", "exit_code": 0, "ended_at": 120.0}),
        ])
        + "\n",
        encoding="utf-8",
    )

    open_runs = report.open_runs(outputs_root=outputs, now=lambda: 700.0)
    assert open_runs == [
        {
            "run_id": "P1-20260610-100000",
            "pkg": "pkg-a",
            "exp_id": "P1",
            "status": "STALE",
            "last_output_age_s": 600,
            "dir": str(open_dir),
        }
    ]


def test_report_run_bounds_raw_log_tail_and_surfaces_anomalies(tmp_path):
    run_dir = tmp_path / "outputs" / "pkg-a" / "runs" / "P1-20260610-100000"
    run_dir.mkdir(parents=True)
    (run_dir / "status.json").write_text(
        json.dumps({"status": "RUN_FAILED", "exit_code": 1, "ended_at": 10.0}),
        encoding="utf-8",
    )
    (run_dir / "events.jsonl").write_text(
        json.dumps({"kind": "anomaly", "label": "Traceback", "tail": "Traceback: bad"}) + "\n",
        encoding="utf-8",
    )
    (run_dir / "log.txt").write_text("\n".join(f"line {i}" for i in range(100)) + "\n", encoding="utf-8")

    summary = report.run_summary(run_dir, tail=5)
    assert summary["status"]["status"] == "RUN_FAILED"
    assert summary["tail"] == [f"line {i}" for i in range(95, 100)]
    assert summary["anomalies"][0]["label"] == "Traceback"


def test_launch_precheck_rejects_duplicate_session_before_any_write(tmp_path, monkeypatch):
    # F3a: a doomed launch must not leave any artifact behind.
    monkeypatch.setattr(launch, "_tmux_session_exists", lambda session: True)
    try:
        launch.launch_run(
            pkg="pkg-a",
            exp_id="P1",
            command=["echo", "x"],
            outputs_root=tmp_path / "outputs",
            tmux_session="dup",
            use_tmux=True,
        )
    except RuntimeError as exc:
        assert "dup" in str(exc)
    else:
        raise AssertionError("expected RuntimeError on duplicate tmux session")
    assert not (tmp_path / "outputs").exists()


def test_launch_tmux_failure_writes_paired_terminal_line(tmp_path, monkeypatch):
    # F3b: if tmux fails after the launched line, a terminal line must pair it.
    import subprocess

    monkeypatch.setattr(launch, "_tmux_session_exists", lambda session: False)

    def failing_run(cmd, check):
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(launch.subprocess, "run", failing_run)
    try:
        launch.launch_run(
            pkg="pkg-a",
            exp_id="P1",
            command=["echo", "x"],
            outputs_root=tmp_path / "outputs",
            use_tmux=True,
        )
    except subprocess.CalledProcessError:
        pass
    else:
        raise AssertionError("expected CalledProcessError to propagate")

    lines = _lines(tmp_path / "outputs" / "_live" / "runs.jsonl")
    assert [line["op"] for line in lines] == ["launched", "terminal"]
    assert lines[1]["final_status"] == "RUN_FAILED"

    from pathlib import Path

    status = json.loads((Path(lines[0]["dir"]) / "status.json").read_text(encoding="utf-8"))
    assert status["status"] == "RUN_FAILED"
    assert status["health"]["state"] == "ERROR"
    assert any("launch" in reason.lower() for reason in status["health"]["reasons"])


def test_meta_records_expected_duration_and_log_adapter_and_status_pids(tmp_path):
    result = launch.launch_run(
        pkg="pkg-a",
        exp_id="P6",
        command=[sys.executable, "-c", "print('ok', flush=True)"],
        outputs_root=tmp_path / "outputs",
        use_tmux=False,
        expected_duration="hours",
        log_adapter="auto",
    )
    meta = json.loads((result.run_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["expected_duration_class"] == "hours"
    assert meta["log_adapter"] == "auto"

    status = json.loads((result.run_dir / "status.json").read_text(encoding="utf-8"))
    assert isinstance(status["pid"], int)
    assert isinstance(status["harvester_pid"], int)
    assert status["heartbeat_timeout"] == 600


def test_report_open_derives_stale_from_frozen_running_status(tmp_path):
    # F1c: a dead harvester leaves status.json frozen at RUNNING; --open must
    # derive STALE from last-output age vs the recorded heartbeat timeout.
    outputs = tmp_path / "outputs"
    run_dir = outputs / "pkg-a" / "runs" / "P1-20260610-100000"
    run_dir.mkdir(parents=True)
    (outputs / "_live").mkdir(parents=True)
    (run_dir / "status.json").write_text(
        json.dumps({
            "run_id": "P1-20260610-100000",
            "pkg": "pkg-a",
            "exp_id": "P1",
            "status": "RUNNING",
            "last_output_at": 100.0,
            "heartbeat_timeout": 60,
        }),
        encoding="utf-8",
    )
    (outputs / "_live" / "runs.jsonl").write_text(
        json.dumps({
            "op": "launched",
            "run_id": "P1-20260610-100000",
            "pkg": "pkg-a",
            "exp_id": "P1",
            "dir": str(run_dir),
            "started_at": 90.0,
        }) + "\n",
        encoding="utf-8",
    )

    rows = report.open_runs(outputs_root=outputs, now=lambda: 700.0)
    assert rows[0]["status"] == "STALE"
    assert rows[0]["last_output_age_s"] == 600
