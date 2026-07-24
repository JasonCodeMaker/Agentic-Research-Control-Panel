#!/usr/bin/env python3
"""Authorize and launch a command under ``.research/experiments``."""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import os
import secrets
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

RESEARCH_OP_SCRIPTS = (
    Path(__file__).resolve().parents[2] / "skills" / "research-op" / "scripts"
)
if str(RESEARCH_OP_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(RESEARCH_OP_SCRIPTS))

import management as research_management  # noqa: E402
from lib.experiments import harvest  # noqa: E402
from lib.experiments.callbacks import commit_run_launch_failed  # noqa: E402
from lib.experiments.contracts import (  # noqa: E402
    DEFAULT_AUTHORIZATION_LEASE_SECONDS,
    context_sha256,
    environment_envelope,
    launch_sha256,
)
from lib.research_state import (  # noqa: E402
    CommandRejected,
    EventStore,
    ResearchPaths,
    StateQuery,
    resolve_bound_experiment,
)
from lib.research_state.io import read_json, write_json_atomic  # noqa: E402
from lib.research_state.paths import add_research_root_argument  # noqa: E402
from lib.result_schema import (  # noqa: E402
    result_schema_sha256,
    validate_result_schema,
)


DEFAULT_ACTOR = {"type": "agent", "id": "research-exp-live"}


@dataclass(frozen=True)
class PreparedRun:
    run_id: str
    run_dir: Path
    run_path: Path
    context_path: Path
    run: dict[str, Any]
    context: dict[str, Any]
    authorization_event: dict[str, Any]


@dataclass(frozen=True)
class LaunchResult:
    run_id: str
    run_dir: Path
    run_path: Path
    context_path: Path
    authorization_event_id: str
    launched_event_id: str | None
    terminal_event_id: str | None
    status: str
    exit_code: int | None
    tmux_session: str | None
    callback_errors: tuple[str, ...] = ()


def _iso(timestamp: float) -> str:
    return dt.datetime.fromtimestamp(timestamp, dt.UTC).isoformat(
        timespec="milliseconds"
    )


def _utc_stamp(timestamp: float) -> str:
    return dt.datetime.fromtimestamp(timestamp, dt.UTC).strftime("%Y%m%d-%H%M%S")


def _new_run_id(experiment_id: str, timestamp: float) -> str:
    return f"{experiment_id}-{_utc_stamp(timestamp)}-{secrets.token_hex(4)}"


def _gpu_ids(environment: dict[str, str]) -> list[str]:
    return [
        value.strip()
        for value in environment.get("CUDA_VISIBLE_DEVICES", "").split(",")
        if value.strip()
    ]


def _git_commit(cwd: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def freeze_context(
    context: dict[str, Any],
    *,
    experiment_id: str,
    experiment_local_id: str | None = None,
    result_schema: dict[str, Any] | None = None,
    captured_at: float,
) -> dict[str, Any]:
    """Create a readable snapshot whose hash excludes wall-clock metadata."""
    if not isinstance(context, dict):
        raise TypeError("context must be an object")
    if {"source_seq", "source_hash", "data"} <= set(context):
        frozen = {
            "source_seq": context["source_seq"],
            "source_hash": context["source_hash"],
            "data": copy.deepcopy(context["data"]),
            "selected_experiment_id": experiment_id,
            "selected_experiment_local_id": experiment_local_id or experiment_id,
        }
    else:
        frozen = {
            "source_seq": None,
            "source_hash": None,
            "data": copy.deepcopy(context),
            "selected_experiment_id": experiment_id,
            "selected_experiment_local_id": experiment_local_id or experiment_id,
        }
    snapshot = {
        "schema_version": 1,
        "captured_at": _iso(captured_at),
        **frozen,
        "result_schema": copy.deepcopy(result_schema),
        "result_schema_sha256": (
            result_schema_sha256(result_schema)
            if result_schema is not None
            else None
        ),
    }
    snapshot["context_sha256"] = context_sha256(snapshot)
    return snapshot


def _write_immutable_json(path: Path, value: dict[str, Any]) -> None:
    """Create JSON once; an existing launch envelope is never overwritten."""
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o644)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        parent_fd = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        path.unlink(missing_ok=True)
        raise


def _relative(paths: ResearchPaths, path: Path) -> str:
    return path.resolve().relative_to(paths.root.resolve()).as_posix()


def _resolve_experiment(
    store: EventStore,
    *,
    package_id: str,
    requested_id: str,
    retry_of: str | None,
) -> tuple[str, str]:
    state = store.state()
    package = state["aggregates"]["package"].get(package_id)
    if not isinstance(package, dict):
        raise ValueError(f"unknown package: {package_id}")
    experiment_id, experiment = resolve_bound_experiment(
        state["aggregates"]["experiment"],
        package_id,
        requested_id,
    )
    local_id = experiment.get("local_id")
    if not isinstance(local_id, str) or not local_id:
        prefix = f"{package_id}::"
        local_id = (
            experiment_id.removeprefix(prefix)
            if experiment_id.startswith(prefix)
            else requested_id.rsplit("::", 1)[-1]
        )
    if retry_of is not None:
        prior = state["aggregates"]["run"].get(retry_of)
        if not isinstance(prior, dict):
            raise ValueError(f"unknown retry source run: {retry_of}")
        if prior.get("experiment_id") != experiment_id:
            raise ValueError(
                f"retry source {retry_of} belongs to another experiment"
            )
    return experiment_id, local_id


def _launch_ack(
    state: dict[str, Any],
    *,
    package_id: str,
    experiment_id: str,
) -> tuple[str, dict[str, Any]]:
    matches = [
        (decision_id, decision)
        for decision_id, decision in state["aggregates"]["decision"].items()
        if decision.get("kind") in {"LAUNCH_ACK", "READY_TO_LAUNCH_ACK"}
        and decision.get("package_id") == package_id
        and decision.get("experiment_id") in {None, "", experiment_id}
        and decision.get("status") in {"ACCEPTED", "ACKNOWLEDGED"}
        and isinstance(decision.get("actor"), dict)
        and decision["actor"].get("type") == "user"
    ]
    if not matches:
        raise CommandRejected(
            "launch-ack-required",
            f"run launch requires a user LAUNCH_ACK decision for {package_id}/{experiment_id}",
        )
    return matches[-1]


def _launch_authority(
    state: dict[str, Any],
    *,
    package_id: str,
    experiment_id: str,
) -> str:
    """Use the Scope execution lease, with Decision ack as legacy fallback."""
    package = state["aggregates"]["package"].get(package_id)
    lease = package.get("executionLease") if isinstance(package, dict) else None
    if isinstance(lease, dict):
        digest = str(lease.get("scope_sha256") or "")
        grants = lease.get("grants")
        experiment_ids = lease.get("experiment_ids")
        if (
            lease.get("status") == "OPEN"
            and len(digest) == 64
            and all(character in "0123456789abcdef" for character in digest)
            and isinstance(grants, list)
            and "LAUNCH" in grants
            and isinstance(experiment_ids, list)
            and experiment_id in experiment_ids
        ):
            return f"lease:{digest}"
        raise CommandRejected(
            "execution-lease-invalid",
            f"Package execution lease does not authorize {experiment_id}",
        )
    decision_id, _ = _launch_ack(
        state,
        package_id=package_id,
        experiment_id=experiment_id,
    )
    return decision_id


def _validate_launch_policy(
    state: dict[str, Any],
    *,
    package_id: str,
    experiment_id: str,
    run_id: str,
    allocation_id: str | None,
    gpu_ids: list[str],
) -> None:
    package = state["aggregates"]["package"].get(package_id)
    if not isinstance(package, dict):
        raise CommandRejected("package-not-found", f"unknown package: {package_id}")
    if package.get("lifecycle") != "ACTIVE":
        raise CommandRejected(
            "package-not-active",
            f"package lifecycle must be ACTIVE, got {package.get('lifecycle')!r}",
        )
    if package.get("phase") != "READY_TO_LAUNCH":
        raise CommandRejected(
            "package-phase",
            f"package phase must be READY_TO_LAUNCH, got {package.get('phase')!r}",
        )
    if package.get("blocker") is not None:
        raise CommandRejected("package-blocked", "blocked package cannot authorize a run")

    experiment = state["aggregates"]["experiment"].get(experiment_id)
    if not isinstance(experiment, dict) or experiment.get("package_id") != package_id:
        raise CommandRejected(
            "experiment-not-found",
            f"experiment {experiment_id!r} is not owned by package {package_id!r}",
        )
    if experiment.get("scope_confirmation") != "CONFIRMED":
        raise CommandRejected(
            "experiment-scope-stale",
            "Experiment.spec must be reconfirmed after its Direction changed",
        )
    if experiment.get("scope_status") != "ACTIVE":
        raise CommandRejected(
            "experiment-scope-inactive",
            f"Experiment Scope is {experiment.get('scope_status')}",
        )
    direction_id = experiment.get("direction_id") or package.get("direction_id")
    direction = state["aggregates"]["direction"].get(direction_id)
    confirmed_version = experiment.get("confirmed_direction_version")
    if (
        not isinstance(direction, dict)
        or direction.get("status") != "ACTIVE"
        or not isinstance(direction.get("version"), int)
        or confirmed_version != direction["version"]
    ):
        raise CommandRejected(
            "experiment-direction-version-stale",
            "Experiment.spec was not confirmed against the current Direction version",
        )
    if experiment.get("status") != "READY":
        raise CommandRejected(
            "experiment-not-ready",
            f"experiment status must be READY, got {experiment.get('status')!r}",
        )
    spec = experiment.get("spec")
    required_spec = {"purpose", "config_ref", "gate", "control_mode"}
    if not isinstance(spec, dict) or any(
        key not in spec or spec[key] is None or spec[key] == ""
        for key in required_spec
    ):
        raise CommandRejected(
            "experiment-spec-incomplete",
            f"Experiment.spec requires {sorted(required_spec)}",
        )
    _launch_authority(
        state,
        package_id=package_id,
        experiment_id=experiment_id,
    )

    if len(gpu_ids) != len(set(gpu_ids)):
        raise CommandRejected(
            "resource-gpu-id-duplicate",
            "CUDA_VISIBLE_DEVICES must contain unique GPU ids",
        )
    if gpu_ids and not allocation_id:
        raise CommandRejected(
            "resource-allocation-required",
            "CUDA_VISIBLE_DEVICES is set but no alloc_id was supplied",
        )
    if allocation_id:
        allocation = state["aggregates"]["resource_allocation"].get(allocation_id)
        if not isinstance(allocation, dict) or allocation.get("status") != "OPEN":
            raise CommandRejected(
                "resource-allocation-open",
                f"allocation is missing or closed: {allocation_id}",
            )
        if allocation.get("package_id", allocation.get("pkg")) != package_id:
            raise CommandRejected(
                "resource-package-mismatch",
                f"allocation {allocation_id} belongs to another package",
            )
        allocated_experiment = allocation.get(
            "experiment_id",
            (
                f"{package_id}::{allocation.get('exp_id')}"
                if allocation.get("exp_id")
                else None
            ),
        )
        if allocated_experiment != experiment_id:
            raise CommandRejected(
                "resource-experiment-mismatch",
                f"allocation {allocation_id} belongs to {allocated_experiment!r}",
            )
        allocated_count = allocation.get("gpu_count")
        if (
            isinstance(allocated_count, bool)
            or not isinstance(allocated_count, int)
            or allocated_count < 0
        ):
            raise CommandRejected(
                "resource-allocation-invalid",
                f"allocation {allocation_id} has an invalid gpu_count",
            )
        if len(gpu_ids) != allocated_count:
            raise CommandRejected(
                "resource-gpu-count-mismatch",
                f"allocation {allocation_id} authorizes {allocated_count} GPU(s), "
                f"but CUDA_VISIBLE_DEVICES selects {len(gpu_ids)}",
            )
        allocated_gpu_ids = allocation.get("gpu_ids")
        if allocated_gpu_ids is not None:
            if (
                not isinstance(allocated_gpu_ids, list)
                or any(
                    not isinstance(gpu_id, str)
                    or not gpu_id
                    or gpu_id != gpu_id.strip()
                    for gpu_id in allocated_gpu_ids
                )
                or len(allocated_gpu_ids) != len(set(allocated_gpu_ids))
                or len(allocated_gpu_ids) != allocated_count
            ):
                raise CommandRejected(
                    "resource-allocation-invalid",
                    f"allocation {allocation_id} has invalid gpu_ids",
                )
            if gpu_ids != allocated_gpu_ids:
                raise CommandRejected(
                    "resource-gpu-id-mismatch",
                    f"allocation {allocation_id} authorizes GPU ids "
                    f"{allocated_gpu_ids}, but CUDA_VISIBLE_DEVICES selects {gpu_ids}",
                )
        linked_run = allocation.get("run_id")
        if linked_run not in {None, "", run_id}:
            raise CommandRejected(
                "resource-allocation-bound",
                f"allocation {allocation_id} is already linked to {linked_run}",
            )
        conflicting = [
            existing_id
            for existing_id, existing in state["aggregates"]["run"].items()
            if existing_id != run_id
            and existing.get("resource", {}).get("alloc_id") == allocation_id
            and existing.get("status") in {"QUEUED", "RUNNING", "STALE"}
        ]
        if conflicting:
            raise CommandRejected(
                "resource-allocation-bound",
                f"allocation {allocation_id} is already bound to {conflicting[0]}",
            )


def _link_allocation(
    store: EventStore,
    *,
    allocation_id: str,
    run_id: str,
    package_id: str,
    experiment_id: str,
    authorization_event_id: str,
    actor: dict[str, str],
) -> dict[str, Any]:
    """Bind an authorized run to its allocation as a management event."""
    state = store.state()
    version = int(
        state["aggregate_versions"].get(
            f"resource_allocation/{allocation_id}",
            0,
        )
    )

    def policy(before: dict[str, Any], _command: dict[str, Any]) -> None:
        allocation = before["aggregates"]["resource_allocation"].get(allocation_id)
        if not isinstance(allocation, dict) or allocation.get("status") != "OPEN":
            raise CommandRejected(
                "resource-allocation-open",
                f"allocation is missing or closed: {allocation_id}",
            )
        if allocation.get("package_id", allocation.get("pkg")) != package_id:
            raise CommandRejected(
                "resource-package-mismatch",
                f"allocation {allocation_id} belongs to another package",
            )
        allocated_experiment = allocation.get("experiment_id")
        if not allocated_experiment and allocation.get("exp_id"):
            allocated_experiment = f"{package_id}::{allocation['exp_id']}"
        if allocated_experiment != experiment_id:
            raise CommandRejected(
                "resource-experiment-mismatch",
                f"allocation {allocation_id} belongs to {allocated_experiment!r}",
            )
        linked_run = allocation.get("run_id")
        if linked_run not in {None, "", run_id}:
            raise CommandRejected(
                "resource-allocation-bound",
                f"allocation {allocation_id} is already linked to {linked_run}",
            )
        run = before["aggregates"]["run"].get(run_id)
        if (
            not isinstance(run, dict)
            or run.get("status") != "QUEUED"
            or run.get("resource", {}).get("alloc_id") != allocation_id
        ):
            raise CommandRejected(
                "authorized-run-required",
                f"allocation link requires the matching authorized run: {run_id}",
            )

    return research_management.link_run_allocation(
        store.paths,
        allocation_id,
        run_id,
        expected_version=version,
        causation_id=authorization_event_id,
        actor=actor,
        policy=policy,
    )


def _queued_status(run: dict[str, Any], timestamp: float) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "run_id": run["run_id"],
        "package_id": run["package_id"],
        "experiment_id": run["experiment_id"],
        "experiment_local_id": run["experiment_local_id"],
        "status": "QUEUED",
        "health": {"state": "OK", "reasons": []},
        "progress": {},
        "latest_metrics": {},
        "source_map": {},
        "throughput": None,
        "first_output_at": None,
        "last_output_at": None,
        "started_at": None,
        "queued_at": timestamp,
        "heartbeat_timeout": run["heartbeat_timeout"],
        "anomalies": 0,
        "log_lines": 0,
        "resource": None,
        "pid": None,
        "harvester_pid": None,
        "exit_code": None,
        "ended_at": None,
        "launch_failed": False,
        "callback_errors": [],
    }


def _launch_failure_artifacts(
    prepared: PreparedRun,
    *,
    failed_at: float,
    error: Exception,
) -> None:
    status = _queued_status(prepared.run, failed_at)
    status.update(
        {
            "status": "FAILED",
            "ended_at": failed_at,
            "launch_failed": True,
            "health": {
                "state": "ERROR",
                "reasons": [f"launch failed: {type(error).__name__}: {error}"],
            },
        }
    )
    write_json_atomic(prepared.run_dir / "status.json", status)
    write_json_atomic(
        prepared.run_dir / "result.json",
        {
            "schema_version": 1,
            "kind": "runtime-terminal",
            "run_id": prepared.run_id,
            "package_id": prepared.run["package_id"],
            "experiment_id": prepared.run["experiment_id"],
            "status": "FAILED",
            "exit_code": None,
            "ended_at": failed_at,
            "protocol": {},
            "measurements": {},
            "verdict": "INCONCLUSIVE",
            "validity": "UNMEASURED",
            "supported_claims": [],
            "unsupported_claims": [],
            "decision_candidate": None,
            "evidence": [],
        },
    )


def prepare_run(
    *,
    paths: ResearchPaths,
    package_id: str,
    experiment_id: str,
    command: list[str],
    context: dict[str, Any] | None = None,
    run_id: str | None = None,
    cwd: Path | None = None,
    retry_of: str | None = None,
    resource: dict[str, Any] | None = None,
    telemetry: dict[str, Any] | None = None,
    heartbeat_timeout: int = 600,
    authorization_lease_seconds: int = DEFAULT_AUTHORIZATION_LEASE_SECONDS,
    total_steps: int | None = None,
    metrics_regexes: list[str] | None = None,
    gpu_sample: bool = False,
    expected_duration: str | None = None,
    log_adapter: str = "auto",
    transport: str = "local-foreground",
    tmux_session: str | None = None,
    actor: dict[str, str] | None = None,
    environment: dict[str, str] | None = None,
    now: Callable[[], float] = time.time,
) -> PreparedRun:
    """Authorize and durably create immutable run/context launch envelopes."""
    if not command:
        raise ValueError("command is required")
    if heartbeat_timeout <= 0:
        raise ValueError("heartbeat_timeout must be positive")
    if (
        isinstance(authorization_lease_seconds, bool)
        or not isinstance(authorization_lease_seconds, int)
        or authorization_lease_seconds <= 0
    ):
        raise ValueError("authorization_lease_seconds must be a positive integer")
    source_directory = Path(cwd or paths.workspace).expanduser().resolve()
    if not source_directory.is_dir():
        raise ValueError(f"source cwd is not a directory: {source_directory}")
    store = EventStore(paths)
    store.initialize()
    experiment_key, experiment_local_id = _resolve_experiment(
        store,
        package_id=package_id,
        requested_id=experiment_id,
        retry_of=retry_of,
    )
    timestamp = now()
    selected_run_id = run_id or _new_run_id(experiment_id, timestamp)
    run_dir = paths.run_dir(package_id, experiment_local_id, selected_run_id)
    if run_dir.exists():
        raise FileExistsError(f"run directory already exists: {run_dir}")
    # An arbitrary experiment command cannot be proven write-safe without an
    # OS sandbox. The harness therefore gives it a run-owned working directory
    # and records the source checkout separately for provenance. Commands that
    # need project files must use absolute paths or RESEARCH_SOURCE_ROOT.
    working_directory = run_dir / "files"
    version = int(
        store.state()["aggregate_versions"].get(f"run/{selected_run_id}", 0)
    )
    if version:
        raise ValueError(f"run id already exists in management state: {selected_run_id}")
    authoritative_context = StateQuery(paths).context(package_id)
    supplied_context_matches = (
        context is None or context == authoritative_context
    )
    selected_experiment = store.state()["aggregates"]["experiment"][
        experiment_key
    ]
    raw_result_schema = selected_experiment.get("resultSchema")
    result_schema = (
        validate_result_schema(raw_result_schema)
        if raw_result_schema is not None
        else None
    )
    frozen_context = freeze_context(
        authoritative_context,
        experiment_id=experiment_key,
        experiment_local_id=experiment_local_id,
        result_schema=result_schema,
        captured_at=timestamp,
    )
    environment = dict(os.environ if environment is None else environment)
    # Absence would let CUDA inherit every device from the host.  Treat an
    # unallocated launch as explicitly CPU-only; GPU visibility is granted
    # only through a matching ResourceAllocation.
    environment.setdefault("CUDA_VISIBLE_DEVICES", "")
    selected_environment = environment_envelope(environment)
    selected_gpu_ids = _gpu_ids(selected_environment["keys"])
    resource_record = copy.deepcopy(resource or {})
    allocation_id = resource_record.get("alloc_id")
    launch_ack_decision_id: str | None = None
    try:
        launch_ack_decision_id = _launch_authority(
            store.state(),
            package_id=package_id,
            experiment_id=experiment_key,
        )
    except CommandRejected:
        # The authoritative check runs under the EventStore lock below so a
        # missing ack becomes an audited command rejection.
        pass
    run_path = run_dir / "run.json"
    context_path = run_dir / "context.json"
    launch_spec = {
        "run_id": selected_run_id,
        "package_id": package_id,
        "experiment_id": experiment_key,
        "experiment_local_id": experiment_local_id,
        "command": list(command),
        "cwd": str(working_directory),
        "source_cwd": str(source_directory),
        "created_at": _iso(timestamp),
        "created_at_unix": timestamp,
        "context_source_seq": frozen_context["source_seq"],
        "context_source_hash": frozen_context["source_hash"],
        "context_sha256": frozen_context["context_sha256"],
        "run_json": _relative(paths, run_path),
        "context_json": _relative(paths, context_path),
        "result_json": _relative(paths, run_dir / "result.json"),
        "log_path": _relative(paths, run_dir / "log.txt"),
        "events_path": _relative(paths, run_dir / "events.jsonl"),
        "metrics_path": _relative(paths, run_dir / "metrics.jsonl"),
        "environment": selected_environment,
        "gpu_ids": selected_gpu_ids,
        "git_commit": _git_commit(source_directory),
        "transport": transport,
        "tmux_session": tmux_session,
        "heartbeat_timeout": heartbeat_timeout,
        "total_steps": total_steps,
        "metrics_regexes": list(metrics_regexes or []),
        "gpu_sample": gpu_sample,
        "retry_of": retry_of,
        "resource": resource_record,
        "launch_ack_decision_id": launch_ack_decision_id,
        "telemetry": copy.deepcopy(telemetry or {}),
        "expected_duration_class": expected_duration,
        "log_adapter": log_adapter,
    }
    launch_digest = launch_sha256(launch_spec)
    run_record = {
        "id": selected_run_id,
        "run_id": selected_run_id,
        "package_id": package_id,
        "experiment_id": experiment_key,
        "experiment_local_id": experiment_local_id,
        "status": "QUEUED",
        "dir": _relative(paths, run_dir),
        "run_json": launch_spec["run_json"],
        "context_json": launch_spec["context_json"],
        "context_source_seq": frozen_context["source_seq"],
        "context_source_hash": frozen_context["source_hash"],
        "context_sha256": frozen_context["context_sha256"],
        "launch_sha256": launch_digest,
        "requested_at": timestamp,
        "authorization_lease_seconds": authorization_lease_seconds,
        "retry_of": retry_of,
        "resource": resource_record,
        "launch_ack_decision_id": launch_ack_decision_id,
        "transport": transport,
    }

    def authorization_policy(
        state: dict[str, Any],
        _command: dict[str, Any],
    ) -> None:
        if not supplied_context_matches:
            raise CommandRejected(
                "launch-context-not-authoritative",
                "caller context does not equal the current research-op context query",
            )
        if (
            state.get("source_seq") != frozen_context["source_seq"]
            or state.get("source_hash") != frozen_context["source_hash"]
        ):
            raise CommandRejected(
                "launch-context-stale",
                "management state changed after the launch context was captured",
            )
        _validate_launch_policy(
            state,
            package_id=package_id,
            experiment_id=experiment_key,
            run_id=selected_run_id,
            allocation_id=str(allocation_id) if allocation_id else None,
            gpu_ids=selected_gpu_ids,
        )
        live_ack_id = _launch_authority(
            state,
            package_id=package_id,
            experiment_id=experiment_key,
        )
        if launch_ack_decision_id != live_ack_id:
            raise CommandRejected(
                "launch-ack-changed",
                "launch ack changed while preparing the immutable launch envelope",
            )

    authorization = research_management.authorize_run(
        paths,
        selected_run_id,
        run_record,
        actor=actor or DEFAULT_ACTOR,
        policy=authorization_policy,
    )
    run = {
        "schema_version": 1,
        "authorization_event_id": authorization["event_id"],
        "launch_sha256": launch_digest,
        **launch_spec,
    }
    prepared = PreparedRun(
        run_id=selected_run_id,
        run_dir=run_dir,
        run_path=run_path,
        context_path=context_path,
        run=run,
        context=frozen_context,
        authorization_event=authorization,
    )
    try:
        if allocation_id:
            _link_allocation(
                store,
                allocation_id=str(allocation_id),
                run_id=selected_run_id,
                package_id=package_id,
                experiment_id=experiment_key,
                authorization_event_id=authorization["event_id"],
                actor=actor or DEFAULT_ACTOR,
            )
        run_dir.mkdir(parents=True, exist_ok=False)
        working_directory.mkdir()
        _write_immutable_json(run_path, run)
        _write_immutable_json(context_path, frozen_context)
        write_json_atomic(run_dir / "status.json", _queued_status(run, timestamp))
    except Exception as error:
        try:
            commit_run_launch_failed(
                store,
                run,
                failed_at=now(),
                reason=f"launch envelope creation failed: {error}",
                actor=actor,
            )
        finally:
            raise
    return prepared


def _tmux_session_exists(session: str) -> bool:
    try:
        result = subprocess.run(
            ["tmux", "has-session", "-t", f"={session}"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return False
    return result.returncode == 0


def _tmux_command(
    *,
    paths: ResearchPaths,
    prepared: PreparedRun,
    metrics_regexes: list[str],
    total_steps: int | None,
    gpu_sample: bool,
) -> str:
    script = Path(harvest.__file__).resolve()
    parts = [
        shlex.quote(sys.executable),
        shlex.quote(str(script)),
        "--workspace",
        shlex.quote(str(paths.workspace)),
        "--research-root",
        shlex.quote(str(paths.root)),
        "--run-dir",
        shlex.quote(str(prepared.run_dir)),
        "--run-file",
        shlex.quote(str(prepared.run_path)),
    ]
    if total_steps is not None:
        parts.extend(["--total-steps", str(total_steps)])
    for pattern in metrics_regexes:
        parts.extend(["--metrics-regex", shlex.quote(pattern)])
    if gpu_sample:
        parts.append("--gpu-sample")
    parts.append("--")
    parts.extend(shlex.quote(value) for value in prepared.run["command"])
    return " ".join(parts)


def launch_run(
    *,
    paths: ResearchPaths,
    package_id: str,
    experiment_id: str,
    command: list[str],
    context: dict[str, Any] | None = None,
    run_id: str | None = None,
    cwd: Path | None = None,
    tmux_session: str | None = None,
    heartbeat_timeout: int = 600,
    authorization_lease_seconds: int = DEFAULT_AUTHORIZATION_LEASE_SECONDS,
    total_steps: int | None = None,
    metrics_regexes: list[str] | None = None,
    retry_of: str | None = None,
    resource: dict[str, Any] | None = None,
    telemetry: dict[str, Any] | None = None,
    expected_duration: str | None = None,
    log_adapter: str = "auto",
    gpu_sample: bool = False,
    use_tmux: bool = True,
    actor: dict[str, str] | None = None,
    environment: dict[str, str] | None = None,
    now: Callable[[], float] = time.time,
) -> LaunchResult:
    """Authorize, materialize, and start one run."""
    timestamp = now()
    selected_run_id = run_id or _new_run_id(experiment_id, timestamp)
    session = (
        tmux_session
        or f"{package_id}-{selected_run_id}".replace("/", "-")[:80]
        if use_tmux
        else None
    )
    if session and _tmux_session_exists(session):
        raise RuntimeError(f"tmux session already exists: {session!r}")
    prepared = prepare_run(
        paths=paths,
        package_id=package_id,
        experiment_id=experiment_id,
        command=command,
        context=context,
        run_id=selected_run_id,
        cwd=cwd,
        retry_of=retry_of,
        resource=resource,
        telemetry=telemetry,
        heartbeat_timeout=heartbeat_timeout,
        authorization_lease_seconds=authorization_lease_seconds,
        total_steps=total_steps,
        metrics_regexes=metrics_regexes,
        gpu_sample=gpu_sample,
        expected_duration=expected_duration,
        log_adapter=log_adapter,
        transport="local-tmux" if use_tmux else "local-foreground",
        tmux_session=session,
        actor=actor,
        environment=environment,
        now=lambda: timestamp,
    )
    metrics_regexes = list(metrics_regexes or [])
    if use_tmux:
        try:
            command_text = _tmux_command(
                paths=paths,
                prepared=prepared,
                metrics_regexes=metrics_regexes,
                total_steps=total_steps,
                gpu_sample=gpu_sample,
            )
            subprocess.run(
                [
                    "tmux",
                    "new-session",
                    "-d",
                    "-s",
                    str(session),
                    "-c",
                    prepared.run["cwd"],
                    command_text,
                ],
                check=True,
            )
        except Exception as error:
            failed_at = now()
            _launch_failure_artifacts(prepared, failed_at=failed_at, error=error)
            commit_run_launch_failed(
                EventStore(paths),
                prepared.run,
                failed_at=failed_at,
                reason=str(error),
                actor=actor,
            )
            raise
        return LaunchResult(
            run_id=prepared.run_id,
            run_dir=prepared.run_dir,
            run_path=prepared.run_path,
            context_path=prepared.context_path,
            authorization_event_id=prepared.authorization_event["event_id"],
            launched_event_id=None,
            terminal_event_id=None,
            status="QUEUED",
            exit_code=None,
            tmux_session=session,
        )
    harvested = harvest.run_command(
        paths=paths,
        run_dir=prepared.run_dir,
        run=prepared.run,
        heartbeat_timeout=heartbeat_timeout,
        total_steps=total_steps,
        metrics_regexes=metrics_regexes,
        now=now,
        gpu_sample=gpu_sample,
    )
    return LaunchResult(
        run_id=prepared.run_id,
        run_dir=prepared.run_dir,
        run_path=prepared.run_path,
        context_path=prepared.context_path,
        authorization_event_id=prepared.authorization_event["event_id"],
        launched_event_id=harvested.launched_event_id,
        terminal_event_id=harvested.terminal_event_id,
        status=harvested.status,
        exit_code=harvested.exit_code,
        tmux_session=None,
        callback_errors=harvested.callback_errors,
    )


def _command_after_separator(command: list[str]) -> list[str]:
    return command[1:] if command and command[0] == "--" else command


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default=".")
    add_research_root_argument(parser)
    parser.add_argument("--package", "--pkg", required=True, dest="package_id")
    parser.add_argument("--experiment", "--exp", required=True, dest="experiment_id")
    parser.add_argument("--run-id")
    parser.add_argument("--context-file")
    parser.add_argument("--cwd")
    parser.add_argument("--tmux-session")
    parser.add_argument("--metrics-regex", action="append", default=[])
    parser.add_argument("--total-steps", type=int)
    parser.add_argument("--heartbeat-timeout", type=int, default=600)
    parser.add_argument(
        "--authorization-lease-seconds",
        type=int,
        default=DEFAULT_AUTHORIZATION_LEASE_SECONDS,
    )
    parser.add_argument("--retry-of")
    parser.add_argument("--log-adapter", default="auto")
    parser.add_argument("--wandb-run-id")
    parser.add_argument("--tensorboard-logdir")
    parser.add_argument("--server", default="local")
    parser.add_argument("--alloc")
    parser.add_argument("--expected-duration", choices=["minutes", "hours", "days"])
    parser.add_argument("--gpu-sample", action="store_true")
    parser.add_argument("--foreground", action="store_true")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)

    command = _command_after_separator(args.command)
    if not command:
        parser.error("command is required after --")
    context = read_json(Path(args.context_file)) if args.context_file else None
    if context is not None and not isinstance(context, dict):
        parser.error("--context-file must contain a JSON object")
    paths = ResearchPaths.resolve(
        workspace=args.workspace,
        research_root=args.research_root,
    )
    telemetry = {}
    if args.wandb_run_id:
        telemetry["wandb_run_id"] = args.wandb_run_id
    if args.tensorboard_logdir:
        telemetry["tensorboard_logdir"] = args.tensorboard_logdir
    result = launch_run(
        paths=paths,
        package_id=args.package_id,
        experiment_id=args.experiment_id,
        command=command,
        context=context,
        run_id=args.run_id,
        cwd=Path(args.cwd) if args.cwd else None,
        tmux_session=args.tmux_session,
        heartbeat_timeout=args.heartbeat_timeout,
        authorization_lease_seconds=args.authorization_lease_seconds,
        total_steps=args.total_steps,
        metrics_regexes=args.metrics_regex,
        retry_of=args.retry_of,
        resource={"server": args.server, "alloc_id": args.alloc},
        telemetry=telemetry,
        expected_duration=args.expected_duration,
        log_adapter=args.log_adapter,
        gpu_sample=args.gpu_sample,
        use_tmux=not args.foreground,
    )
    print(
        json.dumps(
            {
                "run_id": result.run_id,
                "run_dir": str(result.run_dir),
                "status": result.status,
                "tmux_session": result.tmux_session,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return result.exit_code or 0


if __name__ == "__main__":
    raise SystemExit(main())
