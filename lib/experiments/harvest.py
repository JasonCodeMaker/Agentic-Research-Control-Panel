#!/usr/bin/env python3
"""Run a command and harvest only its package/experiment/run directory."""

from __future__ import annotations

import argparse
import math
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lib.experiments.callbacks import (  # noqa: E402
    commit_run_launch_failed,
    commit_run_launched,
    commit_run_terminal,
    validate_authorized_run,
)
from lib.experiments.contracts import (  # noqa: E402
    ENV_DIGEST_KEYS,
    file_evidence_ref,
    verify_environment_envelope,
    verify_result_evidence,
    verify_run_files,
)
from lib.experiments.parsing import (  # noqa: E402
    compile_custom_regex,
    gpu_sampler,
    parse_line,
)
from lib.experiments.status import exit_status  # noqa: E402
from lib.research_state import EventStore, ResearchPaths  # noqa: E402
from lib.research_state.io import (  # noqa: E402
    append_jsonl_fsync,
    read_json,
    write_json_atomic,
)
from lib.research_state.paths import add_research_root_argument  # noqa: E402


@dataclass(frozen=True)
class HarvestResult:
    exit_code: int
    status: str
    launched_event_id: str | None
    terminal_event_id: str | None
    callback_errors: tuple[str, ...] = ()


@dataclass
class RunState:
    run_dir: Path
    run: dict[str, Any]
    heartbeat_timeout: int = 600
    total_steps: int | None = None
    status: str = "QUEUED"
    started_at: float | None = None
    first_output_at: float | None = None
    last_output_at: float | None = None
    log_lines: int = 0
    progress: dict[str, Any] = field(default_factory=dict)
    latest_metrics: dict[str, int | float] = field(default_factory=dict)
    source_map: dict[str, str] = field(default_factory=dict)
    throughput: dict[str, Any] | None = None
    anomalies: int = 0
    resource: dict[str, Any] | None = None
    pid: int | None = None
    exit_code: int | None = None
    ended_at: float | None = None
    launch_failed: bool = False
    callback_errors: list[str] = field(default_factory=list)
    fatal_reasons: list[str] = field(default_factory=list)
    warning_reasons: list[str] = field(default_factory=list)

    def observe_line(self, line: str, at: float) -> None:
        self.log_lines += 1
        self.first_output_at = self.first_output_at or at
        self.last_output_at = at

    def apply_event(self, event: dict[str, Any], at: float) -> None:
        self.first_output_at = self.first_output_at or at
        self.last_output_at = at
        kind = event.get("kind")
        if kind == "progress":
            step = event.get("step")
            total = event.get("total") or self.total_steps
            rate = event.get("rate")
            if step is not None:
                self.progress["step"] = int(step)
            if total is not None:
                self.progress["total"] = int(total)
            if "epoch" in event:
                self.progress["epoch"] = event["epoch"]
            if step is not None and total:
                self.progress["pct"] = round(float(step) / float(total) * 100, 2)
            if rate is not None:
                stable_since = (
                    self.throughput.get("stable_since", at)
                    if self.throughput
                    else at
                )
                self.throughput = {
                    "rate": float(rate),
                    "unit": str(event.get("unit") or "it/s"),
                    "stable_since": stable_since,
                }
        elif kind == "metric":
            step = event.get("step")
            total = event.get("total") or self.total_steps
            if step is not None:
                self.progress["step"] = int(step)
            if total is not None:
                self.progress["total"] = int(total)
                if self.progress.get("step") is not None:
                    self.progress["pct"] = round(
                        float(self.progress["step"]) / float(total) * 100,
                        2,
                    )
            source = str(event.get("source") or "unknown")
            for key, value in (event.get("values") or {}).items():
                self.latest_metrics[str(key)] = value
                self.source_map[str(key)] = source
                if isinstance(value, float) and not math.isfinite(value):
                    self.warning_reasons.append(f"non-finite metric: {key}")
        elif kind == "phase":
            self.progress["phase"] = event.get("label")
        elif kind == "anomaly":
            self.anomalies += 1
            reason = str(event.get("label") or "anomaly")
            target = self.fatal_reasons if event.get("fatal") else self.warning_reasons
            if reason not in target:
                target.append(reason)

    def finalize(
        self,
        exit_code: int | None,
        at: float,
        *,
        launch_failed: bool = False,
    ) -> None:
        self.exit_code = exit_code
        self.ended_at = at
        self.launch_failed = launch_failed
        self.status = exit_status(exit_code)
        if self.status != "COMPLETED":
            reason = "process did not start" if launch_failed else f"exit_code={exit_code}"
            if reason not in self.fatal_reasons:
                self.fatal_reasons.append(reason)

    def snapshot(self, at: float | None = None) -> dict[str, Any]:
        timestamp = time.time() if at is None else at
        status = self.status
        reasons = list(dict.fromkeys(self.fatal_reasons + self.warning_reasons))
        health = "ERROR" if self.fatal_reasons else ("WARN" if reasons else "OK")
        reference = self.last_output_at or self.started_at
        if status in {"QUEUED", "RUNNING"} and reference is not None:
            silence = timestamp - reference
            if silence > self.heartbeat_timeout:
                status = "STALE"
            if silence > self.heartbeat_timeout / 2 and health == "OK":
                health = "WARN"
                reasons.append(f"output silent for {int(silence)}s")
        return {
            "schema_version": 1,
            "run_id": self.run["run_id"],
            "package_id": self.run["package_id"],
            "experiment_id": self.run["experiment_id"],
            "experiment_local_id": self.run["experiment_local_id"],
            "status": status,
            "health": {"state": health, "reasons": reasons},
            "progress": dict(self.progress),
            "latest_metrics": dict(self.latest_metrics),
            "source_map": dict(self.source_map),
            "throughput": self.throughput,
            "first_output_at": self.first_output_at,
            "last_output_at": self.last_output_at,
            "started_at": self.started_at,
            "heartbeat_timeout": self.heartbeat_timeout,
            "anomalies": self.anomalies,
            "log_lines": self.log_lines,
            "resource": self.resource,
            "pid": self.pid,
            "harvester_pid": os.getpid(),
            "exit_code": self.exit_code,
            "ended_at": self.ended_at,
            "launch_failed": self.launch_failed,
            "callback_errors": list(self.callback_errors),
        }

    def write_status(self, at: float | None = None) -> dict[str, Any]:
        snapshot = self.snapshot(at)
        write_json_atomic(self.run_dir / "status.json", snapshot)
        return snapshot


def _validate_run_dir(paths: ResearchPaths, run_dir: Path, run: dict[str, Any]) -> Path:
    expected = paths.run_dir(
        str(run["package_id"]),
        str(run.get("experiment_local_id") or run["experiment_id"]),
        str(run["run_id"]),
    ).resolve()
    actual = run_dir.resolve()
    if actual != expected:
        raise ValueError(f"run directory does not match run.json: {actual} != {expected}")
    return actual


def _runtime_result(
    paths: ResearchPaths,
    run: dict[str, Any],
    status: dict[str, Any],
    run_dir: Path,
) -> dict[str, Any]:
    evidence = [
        file_evidence_ref(paths, run, path)
        for path in (
            run_dir / "log.txt",
            run_dir / "events.jsonl",
            run_dir / "metrics.jsonl",
        )
        if path.is_file()
    ]
    return {
        "schema_version": 1,
        "kind": "runtime-terminal",
        "run_id": run["run_id"],
        "package_id": run["package_id"],
        "experiment_id": run["experiment_id"],
        "status": status["status"],
        "exit_code": status.get("exit_code"),
        "ended_at": status.get("ended_at"),
        "protocol": {},
        "measurements": {},
        "verdict": "INCONCLUSIVE",
        "validity": "UNMEASURED",
        "supported_claims": [],
        "unsupported_claims": [],
        "decision_candidate": None,
        "evidence": evidence,
    }


def _callback_error(
    *,
    state: RunState,
    run_dir: Path,
    stage: str,
    error: Exception,
    at: float,
) -> None:
    message = f"{stage}: {type(error).__name__}: {error}"
    state.callback_errors.append(message)
    append_jsonl_fsync(
        run_dir / "events.jsonl",
        {
            "t": at,
            "kind": "management_callback_error",
            "stage": stage,
            "error": message,
        },
    )


def run_command(
    *,
    paths: ResearchPaths,
    run_dir: Path,
    run: dict[str, Any],
    command: list[str] | None = None,
    heartbeat_timeout: int | None = None,
    total_steps: int | None = None,
    metrics_regexes: Iterable[str] | None = None,
    now: Callable[[], float] = time.time,
    status_interval: float = 1.0,
    watchdog_interval: float | None = None,
    gpu_sample: bool | None = None,
    sampler: Callable[[], dict[str, Any] | None] | None = None,
    popen: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
) -> HarvestResult:
    """Execute one authorized run and persist recoverable callbacks."""
    run_dir = _validate_run_dir(paths, Path(run_dir), run)
    recorded_command = list(run.get("command") or [])
    selected_command = list(command) if command is not None else recorded_command
    if not selected_command:
        raise ValueError("command is required")
    store = EventStore(paths)
    store.initialize()
    recorded_heartbeat = int(run.get("heartbeat_timeout") or 600)
    heartbeat = int(
        recorded_heartbeat if heartbeat_timeout is None else heartbeat_timeout
    )
    recorded_total = run.get("total_steps")
    selected_total = recorded_total if total_steps is None else total_steps
    recorded_regexes = list(run.get("metrics_regexes") or [])
    selected_regexes = (
        recorded_regexes if metrics_regexes is None else list(metrics_regexes)
    )
    recorded_gpu_sample = bool(run.get("gpu_sample", False))
    selected_gpu_sample = (
        recorded_gpu_sample if gpu_sample is None else bool(gpu_sample)
    )
    state = RunState(
        run_dir=run_dir,
        run=run,
        heartbeat_timeout=heartbeat,
        total_steps=selected_total,
    )
    lock = threading.Lock()
    state.write_status(at=now())

    try:
        context = read_json(run_dir / "context.json")
        if not isinstance(context, dict):
            raise ValueError("context.json must contain an object")
        verify_run_files(run, context)
        validate_authorized_run(store, run)
        if selected_command != recorded_command:
            raise ValueError("command override does not match authorized run.json")
        if heartbeat != recorded_heartbeat:
            raise ValueError(
                "heartbeat_timeout override does not match authorized run.json"
            )
        if selected_total != recorded_total:
            raise ValueError("total_steps override does not match authorized run.json")
        if selected_regexes != recorded_regexes:
            raise ValueError(
                "metrics_regex override does not match authorized run.json"
            )
        if selected_gpu_sample != recorded_gpu_sample:
            raise ValueError("gpu_sample override does not match authorized run.json")
        regexes = [
            compile_custom_regex(pattern) for pattern in recorded_regexes
        ]
        if recorded_gpu_sample and sampler is None:
            sampler = gpu_sampler(
                [str(value) for value in run.get("gpu_ids", [])]
            )
        authorized_environment = verify_environment_envelope(
            run.get("environment")
        )
        process_env = os.environ.copy()
        for key in ENV_DIGEST_KEYS:
            if key in authorized_environment:
                process_env[key] = authorized_environment[key]
            else:
                process_env.pop(key, None)
        process_env.update(
            {
                "RESEARCH_RUN_DIR": str(run_dir),
                "RESEARCH_SOURCE_ROOT": str(
                    run.get("source_cwd") or paths.workspace
                ),
            }
        )
        proc = popen(
            recorded_command,
            cwd=run.get("cwd") or None,
            env=process_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            bufsize=1,
        )
    except Exception as error:
        ended_at = now()
        state.fatal_reasons.append(f"launch failed: {error}")
        state.finalize(None, ended_at, launch_failed=True)
        final = state.write_status(at=ended_at)
        write_json_atomic(
            run_dir / "result.json",
            _runtime_result(paths, run, final, run_dir),
        )
        try:
            commit_run_launch_failed(
                store,
                run,
                failed_at=ended_at,
                reason=str(error),
            )
        except Exception as callback_error:
            _callback_error(
                state=state,
                run_dir=run_dir,
                stage="RunLaunchFailed",
                error=callback_error,
                at=ended_at,
            )
            state.write_status(at=ended_at)
        raise

    started_at = now()
    state.status = "RUNNING"
    state.started_at = started_at
    state.pid = proc.pid
    launched_event_id = None
    terminal_event_id = None
    try:
        launched = commit_run_launched(
            store,
            run,
            started_at=started_at,
            pid=proc.pid,
        )
        launched_event_id = launched["event_id"]
    except Exception as error:
        _callback_error(
            state=state,
            run_dir=run_dir,
            stage="RunLaunched",
            error=error,
            at=started_at,
        )
    state.write_status(at=started_at)

    if watchdog_interval is None:
        watchdog_interval = min(15.0, max(0.5, heartbeat / 4))
    stop = threading.Event()

    def watchdog() -> None:
        while not stop.wait(watchdog_interval):
            if sampler is not None:
                try:
                    resource = sampler()
                except Exception:
                    resource = None
                with lock:
                    state.resource = resource
            with lock:
                state.write_status(at=now())

    thread = threading.Thread(target=watchdog, daemon=True)
    thread.start()
    last_write = started_at
    log_path = run_dir / "log.txt"
    events_path = run_dir / "events.jsonl"
    metrics_path = run_dir / "metrics.jsonl"
    runtime_error: BaseException | None = None
    exit_code: int
    try:
        with log_path.open("a", encoding="utf-8") as log:
            assert proc.stdout is not None
            for line in proc.stdout:
                timestamp = now()
                log.write(line)
                log.flush()
                with lock:
                    state.observe_line(line, timestamp)
                    force = state.log_lines == 1
                event = parse_line(line, regexes)
                if event is not None:
                    event = {"t": timestamp, **event}
                    append_jsonl_fsync(events_path, event)
                    if event.get("kind") == "metric":
                        append_jsonl_fsync(metrics_path, event)
                    with lock:
                        state.apply_event(event, timestamp)
                    force = force or event.get("kind") == "anomaly"
                if force or timestamp - last_write >= status_interval:
                    with lock:
                        state.write_status(at=timestamp)
                    last_write = timestamp
        exit_code = proc.wait()
    except BaseException as error:
        runtime_error = error
        state.fatal_reasons.append(
            f"harvester failed: {type(error).__name__}: {error}"
        )
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        exit_code = proc.returncode if proc.returncode is not None else 1
    finally:
        stop.set()
        thread.join(timeout=watchdog_interval + 1)

    ended_at = now()
    with lock:
        state.finalize(exit_code, ended_at)
        final = state.write_status(at=ended_at)
    result = _runtime_result(paths, run, final, run_dir)
    write_json_atomic(run_dir / "result.json", result)
    verify_result_evidence(paths, run, result)
    try:
        terminal = commit_run_terminal(
            store,
            run,
            status=final["status"],
            ended_at=ended_at,
            exit_code=exit_code,
        )
        terminal_event_id = terminal["event_id"]
    except Exception as error:
        _callback_error(
            state=state,
            run_dir=run_dir,
            stage="RunTerminal",
            error=error,
            at=ended_at,
        )
        state.write_status(at=ended_at)
    result = HarvestResult(
        exit_code=exit_code,
        status=final["status"],
        launched_event_id=launched_event_id,
        terminal_event_id=terminal_event_id,
        callback_errors=tuple(state.callback_errors),
    )
    if runtime_error is not None:
        raise runtime_error
    return result


def _command_after_separator(command: list[str]) -> list[str]:
    return command[1:] if command and command[0] == "--" else command


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default=".")
    add_research_root_argument(parser)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--run-file")
    parser.add_argument("--heartbeat-timeout", type=int)
    parser.add_argument("--total-steps", type=int)
    parser.add_argument("--metrics-regex", action="append", default=[])
    parser.add_argument("--gpu-sample", action="store_true", default=None)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)

    paths = ResearchPaths.resolve(
        workspace=args.workspace,
        research_root=args.research_root,
    )
    run_dir = Path(args.run_dir)
    run = read_json(Path(args.run_file) if args.run_file else run_dir / "run.json")
    if not isinstance(run, dict):
        parser.error("run.json must contain an object")
    command = _command_after_separator(args.command) or run.get("command")
    result = run_command(
        paths=paths,
        run_dir=run_dir,
        run=run,
        command=command,
        heartbeat_timeout=args.heartbeat_timeout,
        total_steps=args.total_steps,
        metrics_regexes=args.metrics_regex,
        gpu_sample=args.gpu_sample,
    )
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
