"""Management-state callbacks emitted by the experiment runtime."""

from __future__ import annotations

import copy
import hashlib
import sys
from pathlib import Path
from typing import Any

RESEARCH_OP_SCRIPTS = (
    Path(__file__).resolve().parents[2] / "skills" / "research-op" / "scripts"
)
if str(RESEARCH_OP_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(RESEARCH_OP_SCRIPTS))

import management as research_management  # noqa: E402
from lib.research_state import CommandRejected, EventStore
from lib.research_state.io import read_json

from .contracts import verify_result_evidence


DEFAULT_ACTOR = {"type": "system", "id": "experiment-runtime"}


def _event(store: EventStore, event_id: str | None) -> dict[str, Any] | None:
    if not event_id:
        return None
    return next(
        (event for event in store.events() if event["event_id"] == event_id),
        None,
    )


def _run(store: EventStore, run_id: str) -> tuple[dict[str, Any], int]:
    state = store.state()
    record = state["aggregates"]["run"].get(run_id)
    if not isinstance(record, dict):
        raise CommandRejected("run-not-authorized", f"unknown authorized run: {run_id}")
    version = int(state["aggregate_versions"].get(f"run/{run_id}", 0))
    return record, version


def validate_authorized_run(
    store: EventStore,
    run: dict[str, Any],
) -> dict[str, Any]:
    """Ensure run.json still matches the management authorization event."""
    run_id = str(run["run_id"])
    current, _ = _run(store, run_id)
    expected = current.get("launch_sha256")
    if not expected or expected != run.get("launch_sha256"):
        raise CommandRejected(
            "launch-contract-mismatch",
            f"run.json is not bound to the authorization for {run_id}",
        )
    authorization = _event(store, run.get("authorization_event_id"))
    if (
        authorization is None
        or authorization.get("event_type") != "RunLaunchAuthorized"
        or authorization.get("aggregate_id") != run_id
        or authorization.get("payload", {}).get("record", {}).get("launch_sha256")
        != expected
    ):
        raise CommandRejected(
            "authorization-event-mismatch",
            f"run.json authorization_event_id is invalid for {run_id}",
        )
    return current


def commit_run_launched(
    store: EventStore,
    run: dict[str, Any],
    *,
    started_at: float,
    pid: int | None,
    actor: dict[str, str] | None = None,
) -> dict[str, Any]:
    run_id = str(run["run_id"])
    current, version = _run(store, run_id)
    prior = _event(store, current.get("launched_event_id"))
    if prior is not None:
        return prior
    if current.get("launch_failed"):
        raise CommandRejected(
            "run-launch-already-failed",
            f"cannot launch a run already marked launch-failed: {run_id}",
        )
    patch = {
        "started_at": started_at,
        "pid": pid,
        "transport": run.get("transport"),
        "run_json": run.get("run_json"),
        "context_json": run.get("context_json"),
    }
    return research_management.record_run_launched(
        store.paths,
        run_id,
        patch,
        expected_version=version,
        causation_id=run.get("authorization_event_id"),
        actor=actor or DEFAULT_ACTOR,
    )


def commit_run_launch_failed(
    store: EventStore,
    run: dict[str, Any],
    *,
    failed_at: float,
    reason: str,
    actor: dict[str, str] | None = None,
) -> dict[str, Any]:
    run_id = str(run["run_id"])
    current, version = _run(store, run_id)
    if current.get("launch_failed"):
        event = next(
            (
                item
                for item in reversed(store.events())
                if item["aggregate_type"] == "run"
                and item["aggregate_id"] == run_id
                and item["event_type"] == "RunLaunchFailed"
            ),
            None,
        )
        if event is not None:
            return event
    if current.get("launched_event_id"):
        raise CommandRejected(
            "run-already-launched",
            f"RunLaunchFailed cannot follow RunLaunched: {run_id}",
        )
    return research_management.record_run_launch_failed(
        store.paths,
        run_id,
        {
            "failed_at": failed_at,
            "failure_reason": reason,
            "run_json": run.get("run_json"),
            "context_json": run.get("context_json"),
        },
        expected_version=version,
        causation_id=run.get("authorization_event_id"),
        actor=actor or DEFAULT_ACTOR,
    )


def release_launch_failed_allocation(
    store: EventStore,
    run_id: str,
    *,
    actor: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """Release the OPEN allocation owned by a failed launch, if one exists."""
    current, _ = _run(store, run_id)
    if not current.get("launch_failed"):
        raise CommandRejected(
            "run-launch-failure-required",
            f"allocation recovery requires a failed launch: {run_id}",
        )
    resource = current.get("resource")
    allocation_id = (
        resource.get("alloc_id")
        if isinstance(resource, dict)
        else None
    )
    if not isinstance(allocation_id, str) or not allocation_id:
        return None
    state = store.state()
    allocation = state["aggregates"]["resource_allocation"].get(allocation_id)
    if not isinstance(allocation, dict):
        raise CommandRejected(
            "resource-allocation-missing",
            f"failed run references unknown allocation: {allocation_id}",
        )
    if allocation.get("status") == "RELEASED":
        return None
    if allocation.get("status") != "OPEN":
        raise CommandRejected(
            "resource-allocation-open",
            f"allocation is not releasable: {allocation_id}",
        )
    linked_run = allocation.get("run_id")
    if linked_run not in {None, "", run_id}:
        raise CommandRejected(
            "resource-allocation-bound",
            f"allocation {allocation_id} belongs to another run: {linked_run}",
        )
    failed_event = _event(store, current.get("launch_failed_event_id"))
    if failed_event is None or failed_event.get("event_type") != "RunLaunchFailed":
        raise CommandRejected(
            "run-launch-failure-event-required",
            f"failed run has no RunLaunchFailed event: {run_id}",
        )
    version = int(
        state["aggregate_versions"].get(
            f"resource_allocation/{allocation_id}",
            0,
        )
    )
    patch = {
        "run_id": run_id,
        "outcome": "RUN_LAUNCH_FAILED",
        "released_at": current.get("failed_at"),
        "release_reason": current.get("failure_reason") or "run launch failed",
        "run_launch_failed_event_id": failed_event["event_id"],
    }

    def policy(before: dict[str, Any], _command: dict[str, Any]) -> None:
        live_run = before["aggregates"]["run"].get(run_id)
        live_allocation = before["aggregates"]["resource_allocation"].get(
            allocation_id
        )
        if (
            not isinstance(live_run, dict)
            or not live_run.get("launch_failed")
            or not isinstance(live_run.get("resource"), dict)
            or live_run["resource"].get("alloc_id") != allocation_id
        ):
            raise CommandRejected(
                "run-allocation-release-owner",
                f"run no longer owns allocation {allocation_id}",
            )
        if (
            not isinstance(live_allocation, dict)
            or live_allocation.get("status") != "OPEN"
            or live_allocation.get("run_id") not in {None, "", run_id}
        ):
            raise CommandRejected(
                "resource-allocation-open",
                f"allocation is missing, closed, or rebound: {allocation_id}",
            )

    return research_management.update_resource_allocation(
        store.paths,
        allocation_id,
        event_type="ResourceAllocationReleased",
        payload={"patch": patch},
        expected_version=version,
        actor=actor or DEFAULT_ACTOR,
        idempotency_key=(
            f"allocation:{allocation_id}:run:{run_id}:launch-failed-release"
        ),
        policy=policy,
        causation_id=failed_event["event_id"],
    )


def commit_run_terminal(
    store: EventStore,
    run: dict[str, Any],
    *,
    status: str,
    ended_at: float,
    exit_code: int | None,
    actor: dict[str, str] | None = None,
) -> dict[str, Any]:
    from .status import canonical_status, is_terminal

    run_id = str(run["run_id"])
    final_status = canonical_status(status)
    if not is_terminal(final_status):
        raise ValueError(f"RunTerminal requires a terminal status, got {status!r}")
    current, version = _run(store, run_id)
    prior = _event(store, current.get("terminal_event_id"))
    if prior is not None:
        if current.get("status") != final_status:
            raise CommandRejected(
                "terminal-status-conflict",
                f"run {run_id} is already terminal with {current.get('status')}",
            )
        return prior
    raw_result_path = run.get("result_json")
    if not isinstance(raw_result_path, str) or not raw_result_path:
        raise CommandRejected(
            "run-result-required",
            f"run.json has no result_json path for {run_id}",
        )
    result_path = (store.paths.root / raw_result_path).resolve()
    expected_run_dir = store.paths.run_dir(
        str(run["package_id"]),
        str(run.get("experiment_local_id") or run["experiment_id"]),
        run_id,
    ).resolve()
    try:
        result_path.relative_to(expected_run_dir)
    except ValueError as exc:
        raise CommandRejected(
            "run-result-path-invalid",
            f"result.json is outside the producer run for {run_id}",
        ) from exc
    result = read_json(result_path, {})
    if not isinstance(result, dict) or not result:
        raise CommandRejected(
            "run-result-required",
            f"RunTerminal requires a durable result.json for {run_id}",
        )
    if result.get("status") != final_status:
        raise CommandRejected(
            "run-result-status-mismatch",
            f"result status {result.get('status')!r} does not match {final_status!r}",
        )
    try:
        verify_result_evidence(store.paths, run, result)
    except ValueError as exc:
        raise CommandRejected("run-evidence-invalid", str(exc)) from exc
    return research_management.record_run_terminal(
        store.paths,
        run_id,
        status=final_status,
        patch={
            "ended_at": ended_at,
            "exit_code": exit_code,
            "result_json": run.get("result_json"),
        },
        expected_version=version,
        causation_id=current.get("launched_event_id"),
        actor=actor or DEFAULT_ACTOR,
    )


def commit_run_result_finalized(
    store: EventStore,
    run: dict[str, Any],
    *,
    result: dict[str, Any] | None = None,
    actor: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Record the latest verified scientific Result without owning terminal state."""
    validate_authorized_run(store, run)
    run_id = str(run["run_id"])
    current, version = _run(store, run_id)
    if (
        not current.get("terminal_event_id")
        or current.get("status") not in {"COMPLETED", "FAILED", "HALTED", "SKIPPED"}
    ):
        raise CommandRejected(
            "result-run-not-terminal",
            f"scientific result requires an earlier RunTerminal: {run_id}",
        )
    raw_result_path = run.get("result_json")
    if not isinstance(raw_result_path, str) or not raw_result_path:
        raise CommandRejected(
            "run-result-required",
            f"run.json has no result_json path for {run_id}",
        )
    result_path = (store.paths.root / raw_result_path).resolve()
    expected_run_dir = store.paths.run_dir(
        str(run["package_id"]),
        str(run.get("experiment_local_id") or run["experiment_id"]),
        run_id,
    ).resolve()
    try:
        result_path.relative_to(expected_run_dir)
    except ValueError as exc:
        raise CommandRejected(
            "run-result-path-invalid",
            f"result.json is outside the producer run for {run_id}",
        ) from exc
    persisted = read_json(result_path, {})
    if not isinstance(persisted, dict) or not persisted:
        raise CommandRejected(
            "run-result-required",
            f"scientific result.json is missing for {run_id}",
        )
    if result is not None and persisted != result:
        raise CommandRejected(
            "run-result-write-mismatch",
            f"persisted scientific result differs from the verified value: {run_id}",
        )
    if persisted.get("kind") != "experiment-result":
        raise CommandRejected(
            "run-result-not-scientific",
            f"RunResultFinalized requires kind='experiment-result': {run_id}",
        )
    if persisted.get("status") != current.get("status"):
        raise CommandRejected(
            "run-result-status-mismatch",
            f"result status {persisted.get('status')!r} does not match "
            f"{current.get('status')!r}",
        )
    try:
        verify_result_evidence(store.paths, run, persisted)
    except ValueError as exc:
        raise CommandRejected("run-evidence-invalid", str(exc)) from exc
    result_sha256 = hashlib.sha256(result_path.read_bytes()).hexdigest()
    prior = _event(store, current.get("result_finalized_event_id"))
    latest = current.get("latest_scientific_result")
    if (
        prior is not None
        and isinstance(latest, dict)
        and latest.get("result_sha256") == result_sha256
    ):
        return prior
    evidence = copy.deepcopy(persisted.get("evidence") or [])
    summary = {
        "run_id": run_id,
        "package_id": str(run["package_id"]),
        "experiment_id": str(run["experiment_id"]),
        "kind": "experiment-result",
        "result_json": raw_result_path,
        "result_sha256": result_sha256,
        "protocol": copy.deepcopy(persisted["protocol"]),
        "measurements": copy.deepcopy(persisted["measurements"]),
        "verdict": persisted["verdict"],
        "validity": persisted["validity"],
        "supported_claims": copy.deepcopy(persisted["supported_claims"]),
        "unsupported_claims": copy.deepcopy(persisted["unsupported_claims"]),
        "decision_candidate": copy.deepcopy(
            persisted.get("decision_candidate")
        ),
        "evidence": evidence,
        "evidence_count": len(evidence),
    }
    for field in (
        "result_schema_sha256",
        "result_table_manifest_uri",
        "result_tables",
    ):
        if field in persisted:
            summary[field] = copy.deepcopy(persisted[field])
    causation_id = str(
        current.get("result_finalized_event_id")
        or current["terminal_event_id"]
    )
    return research_management.record_run_result_finalized(
        store.paths,
        run_id,
        summary,
        expected_version=version,
        causation_id=causation_id,
        actor=actor or DEFAULT_ACTOR,
    )
