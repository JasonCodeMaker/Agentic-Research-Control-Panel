#!/usr/bin/env python3
"""Repair missing run-management callbacks from immutable run-local facts."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from lib.experiments.callbacks import (
    commit_run_launch_failed,
    commit_run_launched,
    commit_run_terminal,
    release_launch_failed_allocation,
    validate_authorized_run,
)
from lib.experiments.contracts import (
    DEFAULT_AUTHORIZATION_LEASE_SECONDS,
    verify_run_files,
)
from lib.experiments.status import RUNNING_STATUSES, canonical_status, is_terminal
from lib.research_state import EventStore, ResearchPaths
from lib.research_state.io import read_json
from lib.research_state.paths import add_research_root_argument


RECONCILER_ACTOR = {"type": "system", "id": "run-reconciler"}


@dataclass(frozen=True)
class ReconcileAction:
    run_id: str
    event_type: str
    event_id: str


@dataclass(frozen=True)
class ReconcileResult:
    scanned: int
    actions: tuple[ReconcileAction, ...]
    errors: tuple[str, ...]


def _run_files(paths: ResearchPaths) -> list[Path]:
    if not paths.experiments.exists():
        return []
    return sorted(paths.experiments.glob("*/*/*/run.json"))


def _validated_run(paths: ResearchPaths, run_file: Path) -> tuple[dict[str, Any], Path]:
    run = read_json(run_file)
    if not isinstance(run, dict):
        raise ValueError(f"{run_file} must contain an object")
    required = ("run_id", "package_id", "experiment_id")
    missing = [field for field in required if not run.get(field)]
    if missing:
        raise ValueError(f"{run_file} is missing {', '.join(missing)}")
    expected = paths.run_dir(
        str(run["package_id"]),
        str(run.get("experiment_local_id") or run["experiment_id"]),
        str(run["run_id"]),
    ).resolve()
    if run_file.parent.resolve() != expected:
        raise ValueError(
            f"run.json hierarchy does not match its identifiers: {run_file}"
        )
    return run, expected


def _status(run_dir: Path) -> dict[str, Any]:
    status = read_json(run_dir / "status.json", {})
    result = read_json(run_dir / "result.json", {})
    if not isinstance(status, dict) or not isinstance(result, dict):
        raise ValueError(f"status/result must be JSON objects below {run_dir}")
    if not status.get("status") and result.get("status"):
        status["status"] = result["status"]
        status.setdefault("ended_at", result.get("ended_at"))
        status.setdefault("exit_code", result.get("exit_code"))
    return status


def _started(status: dict[str, Any]) -> bool:
    raw = status.get("status")
    if raw:
        try:
            if canonical_status(raw) in RUNNING_STATUSES | {
                "COMPLETED",
                "FAILED",
                "HALTED",
                "SKIPPED",
            }:
                return canonical_status(raw) != "QUEUED"
        except ValueError:
            return False
    return status.get("pid") is not None or status.get("started_at") is not None


def _event_time(event: dict[str, Any]) -> float:
    raw = str(event.get("occurred_at") or "")
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except ValueError as exc:
        raise ValueError(
            f"RunLaunchAuthorized has invalid occurred_at: {raw!r}"
        ) from exc


def _authorization_deadline(
    record: dict[str, Any],
    event: dict[str, Any],
) -> float:
    raw_lease = record.get(
        "authorization_lease_seconds",
        DEFAULT_AUTHORIZATION_LEASE_SECONDS,
    )
    if (
        isinstance(raw_lease, bool)
        or not isinstance(raw_lease, int)
        or raw_lease <= 0
    ):
        raise ValueError(
            "authorization_lease_seconds must be a positive integer"
        )
    return _event_time(event) + raw_lease


def _expected_run_dir(
    paths: ResearchPaths,
    run_id: str,
    record: dict[str, Any],
) -> Path:
    required = ("package_id", "experiment_id")
    missing = [field for field in required if not record.get(field)]
    if missing:
        raise ValueError(
            f"authorized run {run_id} is missing {', '.join(missing)}"
        )
    return paths.run_dir(
        str(record["package_id"]),
        str(record.get("experiment_local_id") or record["experiment_id"]),
        run_id,
    ).resolve()


def _complete_run_envelope(
    paths: ResearchPaths,
    store: EventStore,
    run_file: Path,
    run_id: str,
) -> tuple[dict[str, Any], Path]:
    run, run_dir = _validated_run(paths, run_file)
    if str(run["run_id"]) != run_id:
        raise ValueError(
            f"run.json identity {run.get('run_id')!r} does not match {run_id!r}"
        )
    context = read_json(run_dir / "context.json")
    if not isinstance(context, dict):
        raise ValueError(f"{run_dir / 'context.json'} must contain an object")
    verify_run_files(run, context)
    validate_authorized_run(store, run)
    return run, run_dir


def _process_evidence(
    run_dir: Path,
    record: dict[str, Any],
    state: dict[str, Any],
) -> tuple[str, ...]:
    evidence: list[str] = []
    try:
        status = read_json(run_dir / "status.json", {})
    except (OSError, ValueError, json.JSONDecodeError):
        status = {}
    if isinstance(status, dict) and _started(status):
        evidence.append("status.json records a started or terminal process")
    try:
        result = read_json(run_dir / "result.json", {})
    except (OSError, ValueError, json.JSONDecodeError):
        result = {}
    if (
        isinstance(result, dict)
        and result.get("status")
        and is_terminal(str(result["status"]))
    ):
        evidence.append("result.json records a terminal process")
    for name in ("log.txt", "events.jsonl", "metrics.jsonl"):
        path = run_dir / name
        try:
            if path.is_file() and path.stat().st_size > 0:
                evidence.append(f"{name} contains runtime output")
        except OSError:
            continue
    resource = record.get("resource")
    allocation_id = (
        resource.get("alloc_id")
        if isinstance(resource, dict)
        else None
    )
    allocation = (
        state["aggregates"]["resource_allocation"].get(allocation_id)
        if isinstance(allocation_id, str) and allocation_id
        else None
    )
    if isinstance(allocation, dict) and allocation.get("job_id"):
        evidence.append("ResourceAllocation records a scheduler job_id")
    return tuple(evidence)


def _release_failed_allocation(
    store: EventStore,
    run_id: str,
    actions: list[ReconcileAction],
) -> None:
    event = release_launch_failed_allocation(
        store,
        run_id,
        actor=RECONCILER_ACTOR,
    )
    if event is not None:
        actions.append(
            ReconcileAction(
                run_id,
                "ResourceAllocationReleased",
                event["event_id"],
            )
        )


def _fail_expired_authorization(
    store: EventStore,
    run_id: str,
    record: dict[str, Any],
    authorization: dict[str, Any],
    *,
    failed_at: float,
    reason: str,
    actions: list[ReconcileAction],
) -> None:
    event = commit_run_launch_failed(
        store,
        {
            **record,
            "run_id": run_id,
            "authorization_event_id": authorization["event_id"],
        },
        failed_at=failed_at,
        reason=reason,
        actor=RECONCILER_ACTOR,
    )
    actions.append(
        ReconcileAction(run_id, "RunLaunchFailed", event["event_id"])
    )
    _release_failed_allocation(store, run_id, actions)


def _reconcile_complete_run(
    store: EventStore,
    run: dict[str, Any],
    run_dir: Path,
    actions: list[ReconcileAction],
) -> None:
    run_id = str(run["run_id"])
    status = _status(run_dir)
    current = store.state()["aggregates"]["run"].get(run_id)
    if not isinstance(current, dict):
        raise ValueError(
            f"{run_id}: run directory has no RunLaunchAuthorized event"
        )
    if current.get("launch_failed"):
        _release_failed_allocation(store, run_id, actions)
        return
    if current.get("terminal_event_id"):
        return
    if status.get("launch_failed"):
        if current.get("launched_event_id"):
            raise ValueError(
                f"{run_id}: launch_failed snapshot conflicts with RunLaunched"
            )
        reasons = status.get("health", {}).get("reasons", [])
        reason = "; ".join(str(value) for value in reasons) or "launch failed"
        event = commit_run_launch_failed(
            store,
            run,
            failed_at=float(
                status.get("ended_at")
                or run.get("created_at_unix")
                or 0
            ),
            reason=reason,
            actor=RECONCILER_ACTOR,
        )
        actions.append(
            ReconcileAction(run_id, "RunLaunchFailed", event["event_id"])
        )
        _release_failed_allocation(store, run_id, actions)
        return
    if not current.get("launched_event_id") and _started(status):
        event = commit_run_launched(
            store,
            run,
            started_at=float(
                status.get("started_at")
                or run.get("created_at_unix")
                or status.get("ended_at")
                or 0
            ),
            pid=status.get("pid"),
            actor=RECONCILER_ACTOR,
        )
        actions.append(
            ReconcileAction(run_id, "RunLaunched", event["event_id"])
        )
        current = store.state()["aggregates"]["run"][run_id]
    raw_status = status.get("status")
    if (
        raw_status
        and is_terminal(raw_status)
        and not current.get("terminal_event_id")
    ):
        final_status = canonical_status(raw_status)
        event = commit_run_terminal(
            store,
            run,
            status=final_status,
            ended_at=float(
                status.get("ended_at")
                or run.get("created_at_unix")
                or 0
            ),
            exit_code=status.get("exit_code"),
            actor=RECONCILER_ACTOR,
        )
        actions.append(
            ReconcileAction(run_id, "RunTerminal", event["event_id"])
        )


def reconcile_runs(
    paths: ResearchPaths,
    *,
    now: float | None = None,
) -> ReconcileResult:
    """Repair callbacks and expire abandoned launch authorizations."""
    store = EventStore(paths)
    store.initialize()
    actions: list[ReconcileAction] = []
    errors: list[str] = []
    state, events, _ = store.snapshot()
    current_time = (
        datetime.now().astimezone().timestamp()
        if now is None
        else float(now)
    )
    authorizations = {
        event["aggregate_id"]: event
        for event in events
        if event["event_type"] == "RunLaunchAuthorized"
        and event["aggregate_type"] == "run"
    }
    managed_files: set[Path] = set()
    scanned = 0
    for run_id, initial in sorted(state["aggregates"]["run"].items()):
        if not isinstance(initial, dict) or not initial.get("launch_authorized"):
            continue
        scanned += 1
        try:
            authorization = authorizations.get(run_id)
            if not isinstance(authorization, dict):
                raise ValueError(
                    f"{run_id}: launch_authorized state has no authorization event"
                )
            run_dir = _expected_run_dir(paths, run_id, initial)
            run_file = run_dir / "run.json"
            managed_files.add(run_file.resolve())
            current = store.state()["aggregates"]["run"].get(run_id)
            if not isinstance(current, dict):
                raise ValueError(f"{run_id}: authorized Run aggregate disappeared")
            if current.get("launch_failed"):
                _release_failed_allocation(store, run_id, actions)
                continue
            if run_file.is_file():
                try:
                    run, validated_dir = _complete_run_envelope(
                        paths,
                        store,
                        run_file,
                        run_id,
                    )
                except Exception as envelope_error:
                    deadline = _authorization_deadline(initial, authorization)
                    evidence = _process_evidence(run_dir, initial, store.state())
                    if (
                        current.get("status") == "QUEUED"
                        and current_time >= deadline
                        and not evidence
                    ):
                        _fail_expired_authorization(
                            store,
                            run_id,
                            initial,
                            authorization,
                            failed_at=deadline,
                            reason=(
                                "authorization lease expired with an incomplete "
                                "immutable run envelope"
                            ),
                            actions=actions,
                        )
                    else:
                        suffix = (
                            f"; process evidence: {', '.join(evidence)}"
                            if evidence
                            else ""
                        )
                        raise ValueError(f"{envelope_error}{suffix}") from envelope_error
                else:
                    _reconcile_complete_run(
                        store,
                        run,
                        validated_dir,
                        actions,
                    )
                continue
            if current.get("status") != "QUEUED":
                continue
            deadline = _authorization_deadline(initial, authorization)
            if current_time < deadline:
                continue
            evidence = _process_evidence(run_dir, initial, store.state())
            if evidence:
                raise ValueError(
                    "authorization lease expired without a valid run.json; "
                    f"process evidence requires manual recovery: {', '.join(evidence)}"
                )
            _fail_expired_authorization(
                store,
                run_id,
                initial,
                authorization,
                failed_at=deadline,
                reason=(
                    "authorization lease expired before immutable run.json "
                    "was published"
                ),
                actions=actions,
            )
        except Exception as error:
            errors.append(f"{run_id}: {type(error).__name__}: {error}")
    for run_file in _run_files(paths):
        if run_file.resolve() in managed_files:
            continue
        scanned += 1
        errors.append(
            f"{run_file}: ValueError: run.json has no matching "
            "RunLaunchAuthorized aggregate"
        )
    return ReconcileResult(
        scanned=scanned,
        actions=tuple(actions),
        errors=tuple(errors),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default=".")
    add_research_root_argument(parser)
    args = parser.parse_args(argv)
    paths = ResearchPaths.resolve(
        workspace=args.workspace,
        research_root=args.research_root,
    )
    result = reconcile_runs(paths)
    print(
        json.dumps(
            {
                "scanned": result.scanned,
                "actions": [
                    {
                        "run_id": action.run_id,
                        "event_type": action.event_type,
                        "event_id": action.event_id,
                    }
                    for action in result.actions
                ],
                "errors": list(result.errors),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 1 if result.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
