"""Event-backed management commands owned by research-op.

This module is deliberately independent from the legacy package mutation
router. Scope, Proposal, and Knowledge commands validate structured records
and commit them through ``lib.research_state.EventStore`` only.
"""

from __future__ import annotations

import copy
import functools
import hashlib
import inspect
import json
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "lib") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "lib"))

from lib.research_state import (
    CommandConflict,
    CommandRejected,
    EventStore,
    ProjectionFailed,
    ResearchPaths,
    resolve_bound_experiment,
)
from lib.research_state.io import canonical_json
from lib.research_state import policy as state_policy
from lib.research_state.schema import (
    compatibility_map,
    enum,
    rule_kind_for_level,
    status_group,
    transition_map,
)
from lib.self_evolve import state as self_evolve_state
from lib import verifier

import scope_ssot


SCOPE_AGGREGATES = {
    "project": "project",
    "direction": "direction",
    "experiment": "experiment",
}
KNOWLEDGE_AGGREGATES = {
    "paper": "paper",
    "edge": "knowledge_edge",
    "gap": "knowledge_gap",
}
KNOWLEDGE_EDGE_TYPES = set(enum("knowledge_edge_type"))
COMMITTED_SCOPE_STATUSES = set(enum("scope_status"))
EXPERIMENT_STATUS_COMPAT = compatibility_map("experiment_status")
EXPERIMENT_STATUSES = set(enum("experiment_status"))
PACKAGE_PHASES = set(enum("package_phase"))
TERMINAL_RUN_STATUSES = set(status_group("run", "terminal"))
TERMINAL_PACKAGE_STATUSES = {
    "STOPPED",
    *state_policy.SUCCESS_STATUS.values(),
    *state_policy.FAIL_STATUS.values(),
}


def _commit(store: EventStore, /, **command: Any) -> dict[str, Any]:
    """Commit canonical state, then rebuild and audit the human interface.

    Projection work runs after the state lock is released.  A failed rebuild
    therefore cannot undo, truncate, or block a committed domain event.  The
    returned projection receipt is deliberately transient and is never stored
    in the event log or current-state fold.
    """
    projection: dict[str, Any] = {
        "written": False,
        "root": str(store.paths.interface),
    }

    def rebuild() -> list[Path]:
        # Lazy import keeps the state core independent of the read-only view
        # and avoids an import cycle through lib.interface.build.
        from lib.interface import build_interface

        result = build_interface(store.paths)
        projection.update(
            {
                "written": True,
                "files_written": len(result.files),
                "source_seq": result.source_seq,
                "source_hash": result.source_hash,
            }
        )
        return list(result.files)

    try:
        event = EventStore.commit(store, render=rebuild, **command)
    except ProjectionFailed as exc:
        if exc.committed_event is None:
            raise
        event = exc.committed_event
        projection["error"] = str(exc)
    receipt = copy.deepcopy(event)
    receipt["_interface_projection"] = projection
    return receipt


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def proposal_content_hash(item: dict[str, Any]) -> str:
    """Preserve the user-visible Triage hash contract."""
    content = {
        key: value
        for key, value in item.items()
        if key
        not in {
            "status",
            "disposition",
            "proposal_hash",
            "accepted_proposal",
            "disposed_at",
            "decision",
        }
    }
    encoded = json.dumps(content, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _version(state: dict[str, Any], aggregate_type: str, aggregate_id: str) -> int:
    return int(state["aggregate_versions"].get(f"{aggregate_type}/{aggregate_id}", 0))


def _latest_aggregate_event(
    events: list[dict[str, Any]],
    aggregate_type: str,
    aggregate_id: str,
    aggregate_version: int,
) -> dict[str, Any]:
    event = next(
        (
            item
            for item in reversed(events)
            if item.get("aggregate_type") == aggregate_type
            and item.get("aggregate_id") == aggregate_id
            and item.get("aggregate_version") == aggregate_version
        ),
        None,
    )
    if event is None:
        raise CommandConflict(
            "causation-event-missing",
            f"{aggregate_type}/{aggregate_id}@{aggregate_version} has no event",
        )
    return event


def _actor(actor: dict[str, str] | None, *, default_type: str = "agent") -> dict[str, str]:
    return actor or {"type": default_type, "id": "main" if default_type == "agent" else "pm"}


_AUDIT_SENSITIVE_FIELD_PARTS = {
    "argv",
    "authorization",
    "cmd",
    "command",
    "content",
    "cookie",
    "env",
    "environment",
    "note",
    "password",
    "secret",
    "text",
    "token",
}


def _audit_json_value(value: Any) -> Any:
    """Convert an arbitrary value to a bounded JSON-safe representation."""
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return {
            "kind": "bytes",
            "size_bytes": len(value),
            "sha256": hashlib.sha256(value).hexdigest(),
        }
    if isinstance(value, dict):
        return {str(key): _audit_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_audit_json_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        items = [_audit_json_value(item) for item in value]
        return sorted(items, key=lambda item: canonical_json(item))
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return {"type": type(value).__name__, "repr": repr(value)[:500]}


def _audit_field_is_sensitive(field_name: str) -> bool:
    snake = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", field_name)
    parts = set(re.findall(r"[a-z0-9]+", snake.lower()))
    return bool(parts.intersection(_AUDIT_SENSITIVE_FIELD_PARTS))


def _audit_summary(value: Any) -> dict[str, Any]:
    if isinstance(value, bytes):
        encoded = value
    elif isinstance(value, str):
        encoded = value.encode("utf-8")
    else:
        encoded = canonical_json(_audit_json_value(value)).encode("utf-8")
    return {
        "kind": "redacted-argument",
        "size_bytes": len(encoded),
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }


def _audit_value(value: Any, *, field_name: str = "") -> Any:
    """Convert facade arguments without persisting sensitive free-form values."""
    if field_name and _audit_field_is_sensitive(field_name):
        return _audit_summary(value)
    if isinstance(value, dict):
        return {
            str(key): _audit_value(item, field_name=str(key))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_audit_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        items = [_audit_value(item) for item in value]
        return sorted(items, key=lambda item: canonical_json(item))
    return _audit_json_value(value)


def record_rejected_attempt(
    paths: ResearchPaths,
    *,
    command_name: str,
    actor: dict[str, str],
    payload: dict[str, Any],
    rule: str,
    detail: Any,
    entry_skill: str = "research-op",
    idempotency_key: str | None = None,
    command_id: str | None = None,
) -> str:
    """Record one pre-commit rejection through the research-op gateway."""
    return EventStore(paths).record_rejected_attempt(
        command_name=command_name,
        actor=copy.deepcopy(actor),
        payload=copy.deepcopy(payload),
        rule=rule,
        detail=copy.deepcopy(detail),
        entry_skill=entry_skill,
        idempotency_key=idempotency_key,
        command_id=command_id,
    )


def _audit_precommit_rejections(function: Callable[..., Any]) -> Callable[..., Any]:
    """Ensure facade validation failures receive a complete audit pair."""
    signature = inspect.signature(function)

    @functools.wraps(function)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        try:
            return function(*args, **kwargs)
        except CommandRejected as exc:
            if exc.audited:
                raise
            bound = signature.bind_partial(*args, **kwargs)
            paths = bound.arguments.get("paths")
            if not isinstance(paths, ResearchPaths):
                raise
            audit_payload = {
                "parameters": {
                    name: _audit_value(value, field_name=name)
                    for name, value in bound.arguments.items()
                    if name != "paths"
                },
            }
            record_rejected_attempt(
                paths,
                command_name=function.__name__,
                actor=_actor(bound.arguments.get("actor")),
                payload=audit_payload,
                rule=exc.rule,
                detail=exc.detail,
                entry_skill="research-op",
                idempotency_key=(
                    str(bound.arguments["idempotency_key"])
                    if bound.arguments.get("idempotency_key")
                    else None
                ),
            )
            exc.audited = True
            raise

    return wrapped


def write_note(
    paths: ResearchPaths,
    content: str | bytes,
    *,
    mime: str = "text/markdown",
    title: str = "",
) -> dict[str, Any]:
    """Store a content-addressed NoteRef through the research-op gateway."""
    return EventStore(paths).write_note(content, mime=mime, title=title)


def initialize(paths: ResearchPaths) -> dict[str, Any]:
    """Initialize a greenfield store while preserving ResearchPaths upgrade gates."""
    return EventStore(paths).initialize()


def authorize_run(
    paths: ResearchPaths,
    run_id: str,
    record: dict[str, Any],
    *,
    actor: dict[str, str],
    policy: Callable[[dict[str, Any], dict[str, Any]], None],
) -> dict[str, Any]:
    """Research-op gateway for the immutable run-launch authorization."""
    return _commit(EventStore(paths),
        event_type="RunLaunchAuthorized",
        aggregate_type="run",
        aggregate_id=run_id,
        payload={"record": copy.deepcopy(record)},
        actor=actor,
        idempotency_key=f"run:{run_id}:authorize",
        expected_version=0,
        entry_skill="research-op/runtime",
        policy=policy,
    )


def link_run_allocation(
    paths: ResearchPaths,
    allocation_id: str,
    run_id: str,
    *,
    expected_version: int,
    causation_id: str,
    actor: dict[str, str],
    policy: Callable[[dict[str, Any], dict[str, Any]], None],
) -> dict[str, Any]:
    """Research-op gateway for binding one authorized Run to an allocation."""
    return _commit(EventStore(paths),
        event_type="ResourceAllocationLinked",
        aggregate_type="resource_allocation",
        aggregate_id=allocation_id,
        payload={"patch": {"run_id": run_id}},
        actor=actor,
        idempotency_key=f"allocation:{allocation_id}:run:{run_id}",
        expected_version=expected_version,
        causation_id=causation_id,
        entry_skill="research-op/runtime",
        policy=policy,
    )


def record_run_launched(
    paths: ResearchPaths,
    run_id: str,
    patch: dict[str, Any],
    *,
    expected_version: int,
    causation_id: str | None,
    actor: dict[str, str],
) -> dict[str, Any]:
    """Research-op gateway for a launcher/harvester start callback."""
    return _commit(EventStore(paths),
        event_type="RunLaunched",
        aggregate_type="run",
        aggregate_id=run_id,
        payload={"patch": copy.deepcopy(patch)},
        actor=actor,
        idempotency_key=f"run:{run_id}:launched",
        expected_version=expected_version,
        causation_id=causation_id,
        entry_skill="research-op/runtime",
    )


def record_run_launch_failed(
    paths: ResearchPaths,
    run_id: str,
    patch: dict[str, Any],
    *,
    expected_version: int,
    causation_id: str | None,
    actor: dict[str, str],
) -> dict[str, Any]:
    """Research-op gateway for a failure before the experiment starts."""
    return _commit(EventStore(paths),
        event_type="RunLaunchFailed",
        aggregate_type="run",
        aggregate_id=run_id,
        payload={"patch": copy.deepcopy(patch)},
        actor=actor,
        idempotency_key=f"run:{run_id}:launch-failed",
        expected_version=expected_version,
        causation_id=causation_id,
        entry_skill="research-op/runtime",
    )


def record_run_terminal(
    paths: ResearchPaths,
    run_id: str,
    *,
    status: str,
    patch: dict[str, Any],
    expected_version: int,
    causation_id: str | None,
    actor: dict[str, str],
) -> dict[str, Any]:
    """Research-op gateway for a verified terminal Result callback."""
    return _commit(EventStore(paths),
        event_type="RunTerminal",
        aggregate_type="run",
        aggregate_id=run_id,
        payload={"status": status, "patch": copy.deepcopy(patch)},
        actor=actor,
        idempotency_key=f"run:{run_id}:terminal",
        expected_version=expected_version,
        causation_id=causation_id,
        entry_skill="research-op/runtime",
    )


def record_run_result_finalized(
    paths: ResearchPaths,
    run_id: str,
    result: dict[str, Any],
    *,
    expected_version: int,
    causation_id: str,
    actor: dict[str, str],
) -> dict[str, Any]:
    """Commit one hash-bound scientific Result summary without changing status."""
    summary = copy.deepcopy(result)
    digest = str(summary.get("result_sha256") or "").lower()

    def result_policy(
        before: dict[str, Any],
        _command: dict[str, Any],
    ) -> None:
        current = before["aggregates"]["run"].get(run_id)
        if not isinstance(current, dict):
            raise CommandRejected(
                "result-run-missing",
                f"unknown run: {run_id}",
            )
        if (
            not current.get("terminal_event_id")
            or current.get("status") not in TERMINAL_RUN_STATUSES
        ):
            raise CommandRejected(
                "result-run-not-terminal",
                f"scientific result requires a terminal run: {run_id}",
            )
        expected_cause = (
            current.get("result_finalized_event_id")
            or current.get("terminal_event_id")
        )
        if causation_id != expected_cause:
            raise CommandRejected(
                "result-causation-stale",
                f"scientific result causation is stale for run {run_id}",
            )
        result_json = summary.get("result_json")
        if (
            not isinstance(result_json, str)
            or not result_json
            or result_json != current.get("result_json")
        ):
            raise CommandRejected(
                "result-path-mismatch",
                f"scientific result path does not match run {run_id}",
            )
        relative = Path(result_json)
        if relative.is_absolute() or ".." in relative.parts:
            raise CommandRejected(
                "result-path-invalid",
                f"scientific result path is unsafe for run {run_id}",
            )
        result_path = (paths.root / relative).resolve()
        expected_run_dir = paths.run_dir(
            str(current.get("package_id") or ""),
            str(
                current.get("experiment_local_id")
                or current.get("experiment_id")
                or ""
            ),
            run_id,
        ).resolve()
        try:
            result_path.relative_to(expected_run_dir)
        except ValueError as exc:
            raise CommandRejected(
                "result-path-invalid",
                f"scientific result is outside its producer run: {run_id}",
            ) from exc
        if not result_path.is_file():
            raise CommandRejected(
                "result-file-missing",
                f"scientific result file is missing for run {run_id}",
            )
        actual = hashlib.sha256(result_path.read_bytes()).hexdigest()
        if actual != digest:
            raise CommandRejected(
                "result-hash-mismatch",
                f"scientific result changed before commit: {run_id}",
            )
        experiment = before["aggregates"]["experiment"].get(
            current.get("experiment_id")
        )
        spec = (
            experiment.get("spec")
            if isinstance(experiment, dict)
            and isinstance(experiment.get("spec"), dict)
            else {}
        )
        verdict_conflict = verifier.assess_measurements_verdict(
            summary.get("measurements"),
            spec.get("gate"),
            summary.get("verdict"),
        )
        if verdict_conflict:
            raise CommandRejected(
                "result-verdict-gate-conflict",
                verdict_conflict,
            )

    return _commit(EventStore(paths),
        event_type="RunResultFinalized",
        aggregate_type="run",
        aggregate_id=run_id,
        payload={"result": summary},
        actor=actor,
        idempotency_key=f"run:{run_id}:result:{digest}",
        expected_version=expected_version,
        causation_id=causation_id,
        entry_skill="research-op/runtime",
        policy=result_policy,
    )


def create_brainstorm(
    paths: ResearchPaths,
    idea_id: str,
    record: dict[str, Any],
    *,
    actor: dict[str, str],
    idempotency_key: str,
) -> dict[str, Any]:
    """Research-op gateway for a new pre-package idea."""
    return _commit(EventStore(paths),
        event_type="BrainstormCreated",
        aggregate_type="brainstorm",
        aggregate_id=idea_id,
        payload={"record": copy.deepcopy(record)},
        actor=actor,
        idempotency_key=idempotency_key,
        expected_version=0,
        entry_skill="research-op/brainstorm",
    )


def revise_brainstorm(
    paths: ResearchPaths,
    idea_id: str,
    patch: dict[str, Any],
    *,
    expected_version: int,
    actor: dict[str, str],
    idempotency_key: str,
) -> dict[str, Any]:
    """Research-op gateway for a bounded idea revision."""
    return _commit(EventStore(paths),
        event_type="BrainstormRevised",
        aggregate_type="brainstorm",
        aggregate_id=idea_id,
        payload={"patch": copy.deepcopy(patch)},
        actor=actor,
        idempotency_key=idempotency_key,
        expected_version=expected_version,
        entry_skill="research-op/brainstorm",
    )


def archive_brainstorm(
    paths: ResearchPaths,
    idea_id: str,
    patch: dict[str, Any],
    *,
    expected_version: int,
    actor: dict[str, str],
    idempotency_key: str,
) -> dict[str, Any]:
    """Research-op gateway for removing an idea from the active lane."""
    return _commit(EventStore(paths),
        event_type="BrainstormArchived",
        aggregate_type="brainstorm",
        aggregate_id=idea_id,
        payload={"patch": copy.deepcopy(patch)},
        actor=actor,
        idempotency_key=idempotency_key,
        expected_version=expected_version,
        entry_skill="research-op/brainstorm",
    )


def discard_brainstorm(
    paths: ResearchPaths,
    idea_id: str,
    *,
    reason: str,
    expected_version: int,
    actor: dict[str, str],
    idempotency_key: str,
) -> dict[str, Any]:
    """Remove an archived duplicate from current state while retaining history."""
    store = EventStore(paths)
    state = store.state()
    current = state["aggregates"]["brainstorm"].get(idea_id)
    if not isinstance(current, dict):
        raise CommandRejected(
            "brainstorm-not-found",
            f"unknown Brainstorm: {idea_id}",
        )
    if current.get("status") != "ARCHIVED":
        raise CommandRejected(
            "brainstorm-archive-required",
            "only an archived Brainstorm may be removed from the current catalogue",
        )
    if actor.get("type") != "user":
        raise CommandRejected(
            "brainstorm-discard-user-required",
            "discarding an archived Brainstorm requires an explicit user actor",
        )
    return _commit(
        store,
        event_type="AggregateRemoved",
        aggregate_type="brainstorm",
        aggregate_id=idea_id,
        payload={
            "reason": reason,
            "event_history_retained": True,
        },
        actor=copy.deepcopy(actor),
        idempotency_key=idempotency_key,
        expected_version=expected_version,
        entry_skill="research-op/brainstorm",
    )


def update_campaign(
    paths: ResearchPaths,
    campaign_id: str,
    patch: dict[str, Any],
    *,
    expected_version: int,
    actor: dict[str, str],
    idempotency_key: str,
) -> dict[str, Any]:
    """Research-op gateway for campaign cycle and PACK projections."""
    return _commit(EventStore(paths),
        event_type="CampaignUpdated",
        aggregate_type="campaign",
        aggregate_id=campaign_id,
        payload={"patch": copy.deepcopy(patch)},
        actor=actor,
        idempotency_key=idempotency_key,
        expected_version=expected_version,
        entry_skill="research-op/campaign",
    )


def register_resource(
    paths: ResearchPaths,
    resource_id: str,
    record: dict[str, Any],
    *,
    expected_version: int,
    actor: dict[str, str],
    idempotency_key: str,
) -> dict[str, Any]:
    """Research-op gateway for one typed compute resource."""
    return _commit(EventStore(paths),
        event_type="ResourceRegistered",
        aggregate_type="resource",
        aggregate_id=resource_id,
        payload={"record": copy.deepcopy(record)},
        actor=actor,
        idempotency_key=idempotency_key,
        expected_version=expected_version,
        entry_skill="research-op/resource",
    )


def update_resource_allocation(
    paths: ResearchPaths,
    allocation_id: str,
    *,
    event_type: str,
    payload: dict[str, Any],
    expected_version: int,
    actor: dict[str, str],
    idempotency_key: str,
    policy: Callable[[dict[str, Any], dict[str, Any]], None] | None = None,
    causation_id: str | None = None,
) -> dict[str, Any]:
    """Research-op gateway for allocate, link, or release."""
    if event_type not in {
        "ResourceAllocationCreated",
        "ResourceAllocationLinked",
        "ResourceAllocationReleased",
    }:
        raise CommandRejected(
            "resource-allocation-event-invalid",
            f"unsupported allocation event: {event_type}",
        )
    return _commit(EventStore(paths),
        event_type=event_type,
        aggregate_type="resource_allocation",
        aggregate_id=allocation_id,
        payload=copy.deepcopy(payload),
        actor=actor,
        idempotency_key=idempotency_key,
        expected_version=expected_version,
        causation_id=causation_id,
        entry_skill="research-op/resource",
        policy=policy,
    )


def submit_proposal(
    paths: ResearchPaths,
    item: dict[str, Any],
    *,
    actor: dict[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate and commit one pending, executable Scope proposal."""
    candidate = copy.deepcopy(item) if isinstance(item, dict) else {}
    store = EventStore(paths)
    before = store.state() if paths.version_file.exists() else None
    proposed_node = candidate.get("proposed_node")
    if (
        isinstance(proposed_node, dict)
        and proposed_node.get("level") == "experiment"
        and isinstance(proposed_node.get("parents"), list)
        and len(proposed_node["parents"]) == 1
        and before is not None
    ):
        parent = before["aggregates"]["direction"].get(proposed_node["parents"][0])
        if (
            isinstance(parent, dict)
            and isinstance(parent.get("version"), int)
            and not isinstance(parent.get("version"), bool)
        ):
            candidate.setdefault("parent_scope_version", parent["version"])
    raw_id = candidate.get("id")
    item_id = (
        str(raw_id).strip()
        if isinstance(raw_id, str) and raw_id.strip()
        else f"invalid-{_digest({'proposal': repr(item)})[:16]}"
    )
    proposal_hash = proposal_content_hash(candidate)
    record = copy.deepcopy(candidate)
    record.update(
        {
            "id": item_id,
            "status": "pending",
            "proposal_hash": proposal_hash,
        }
    )
    expected_version = (
        _version(before, "proposal", item_id) if before is not None else 0
    )
    event = _commit(store,
        event_type="ProposalSubmitted",
        aggregate_type="proposal",
        aggregate_id=item_id,
        payload={"record": record},
        actor=_actor(actor),
        idempotency_key=f"proposal-submit:{item_id}:{proposal_hash}",
        expected_version=expected_version,
        entry_skill="research-scope",
        policy=lambda live, _command: _validate_proposal_item(
            paths,
            candidate,
            live,
        ),
    )
    return record, event


def proposal_records(paths: ResearchPaths) -> list[dict[str, Any]]:
    """Return proposal snapshots in event order for compatibility callers."""
    if not paths.version_file.exists():
        return []
    return [
        copy.deepcopy(event["payload"]["record"])
        for event in EventStore(paths).events()
        if event["aggregate_type"] == "proposal"
        and isinstance(event.get("payload", {}).get("record"), dict)
    ]


def pending_proposals(paths: ResearchPaths) -> list[dict[str, Any]]:
    """Return the latest pending proposal snapshot per id."""
    if not paths.version_file.exists():
        return []
    proposals = EventStore(paths).state()["aggregates"]["proposal"]
    return [
        copy.deepcopy(record)
        for record in proposals.values()
        if record.get("disposition") == "PENDING"
    ]


def dispose_proposal(
    paths: ResearchPaths,
    item_id: str,
    decision: str,
    expected_proposal_hash: str,
    *,
    actor: dict[str, str] | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Commit a hash-bound ProposalAccepted or ProposalRejected event."""
    if decision not in {"ACCEPTED", "REJECTED"}:
        raise CommandRejected(
            "proposal-decision-invalid",
            f"decision must be ACCEPTED|REJECTED, got {decision!r}",
        )
    if not expected_proposal_hash:
        raise CommandRejected(
            "proposal-hash-required",
            "proposal disposition requires the visible proposal hash",
        )
    store = EventStore(paths)
    state = store.state()
    # A missing caller identity is an agent, never an implicit PM.  The
    # disposition policy below is the authority boundary.
    principal = _actor(actor)
    current = state["aggregates"]["proposal"].get(item_id)
    disposition = current.get("disposition") if isinstance(current, dict) else None
    event_type = "ProposalAccepted" if decision == "ACCEPTED" else "ProposalRejected"
    disposition_key = (
        f"proposal-dispose:{item_id}:{expected_proposal_hash}:{decision}"
    )
    if (
        disposition == decision
        and current.get("proposal_hash") == expected_proposal_hash
    ):
        prior = next(
            (
                event
                for event in reversed(store.events())
                if event["idempotency_key"] == disposition_key
            ),
            None,
        )
        if prior is None:
            raise CommandConflict(
                "proposal-disposition-event-missing",
                f"proposal {item_id} is disposed but has no matching event",
            )
        replay = _commit(store,
            event_type=event_type,
            aggregate_type="proposal",
            aggregate_id=item_id,
            payload=copy.deepcopy(prior["payload"]),
            actor=principal,
            idempotency_key=disposition_key,
            expected_version=_version(state, "proposal", item_id),
            entry_skill="research-scope",
        )
        return ("accepted" if decision == "ACCEPTED" else "archived"), replay

    snapshot = {
        key: copy.deepcopy(value)
        for key, value in (current or {}).items()
        if key != "disposition"
    }
    status = "accepted" if decision == "ACCEPTED" else "archived"
    record: dict[str, Any] = {
        "id": item_id,
        "status": status,
        "decision": decision,
        "proposal_hash": expected_proposal_hash,
        "disposed_at": datetime.now(timezone.utc).astimezone().isoformat(
            timespec="milliseconds"
        ),
    }
    if decision == "ACCEPTED":
        record["accepted_proposal"] = snapshot

    aggregate_version = _version(state, "proposal", item_id)

    def policy(before: dict[str, Any], _command: dict[str, Any]) -> None:
        if principal.get("type") != "user":
            raise CommandRejected(
                "proposal-disposition-user-required",
                "only an explicit user actor may dispose a Scope proposal",
            )
        live = before["aggregates"]["proposal"].get(item_id)
        if not isinstance(live, dict):
            raise CommandRejected(
                "proposal-not-found",
                f"proposal does not exist: {item_id}",
            )
        if live.get("proposal_hash") != expected_proposal_hash:
            raise CommandConflict(
                "proposal-hash-mismatch",
                f"proposal hash mismatch for {item_id}: expected "
                f"{live.get('proposal_hash')}, got {expected_proposal_hash}",
            )
        if live.get("disposition") != "PENDING":
            raise CommandConflict(
                "proposal-not-pending",
                f"proposal {item_id} is not pending",
            )
        live_snapshot = {
            key: copy.deepcopy(value)
            for key, value in live.items()
            if key != "disposition"
        }
        if proposal_content_hash(live_snapshot) != expected_proposal_hash:
            raise CommandConflict(
                "proposal-snapshot-mismatch",
                f"stored proposal content no longer matches its hash: {item_id}",
            )

    event = _commit(store,
        event_type=event_type,
        aggregate_type="proposal",
        aggregate_id=item_id,
        payload={"record": record},
        actor=principal,
        idempotency_key=disposition_key,
        expected_version=aggregate_version,
        entry_skill="research-scope",
        policy=policy,
    )
    return status, event


def accepted_scope_payload(
    paths: ResearchPaths,
    item_id: str,
) -> tuple[dict[str, Any], str]:
    """Load and independently verify one accepted Triage proposal."""
    store = EventStore(paths)
    state = store.state()
    accepted = state["aggregates"]["proposal"].get(item_id)
    if not isinstance(accepted, dict) or accepted.get("disposition") != "ACCEPTED":
        raise CommandRejected(
            "accepted-proposal-required",
            f"accepted proposal not found: {item_id}",
        )
    proposal = accepted.get("accepted_proposal")
    if not isinstance(proposal, dict):
        raise CommandRejected(
            "accepted-proposal-snapshot-required",
            f"accepted proposal has no bound snapshot: {item_id}",
        )
    expected_hash = str(accepted.get("proposal_hash", ""))
    if proposal_content_hash(proposal) != expected_hash:
        raise CommandConflict(
            "accepted-proposal-hash-mismatch",
            f"accepted proposal hash mismatch: {item_id}",
        )
    node = proposal.get("proposed_node")
    if not isinstance(node, dict):
        raise CommandRejected(
            "accepted-proposal-node-required",
            f"accepted proposal has no proposed_node: {item_id}",
        )
    payload = {
        key: copy.deepcopy(node[key])
        for key in (
            "id",
            "level",
            "parents",
            "version",
            "status",
            "spec",
            "source",
            "package_id",
            "prior_knowledge",
        )
        if key in node
    }
    for key in (
        "op",
        "gate",
        "invalidates",
        "reopens",
        "dial_revert",
        "parent_scope_version",
    ):
        if key in proposal:
            payload[key] = copy.deepcopy(proposal[key])
    payload["trigger"] = f"triage:{item_id}"
    payload["cause"] = (
        proposal.get("change")
        or proposal.get("rationale")
        or accepted.get("decision")
    )
    payload["_triage_id"] = item_id
    payload["_proposal_hash"] = expected_hash
    accepted_event = next(
        (
            event
            for event in reversed(store.events())
            if event["aggregate_type"] == "proposal"
            and event["aggregate_id"] == item_id
            and event["event_type"] == "ProposalAccepted"
        ),
        None,
    )
    if accepted_event is None:
        raise CommandRejected(
            "accepted-proposal-event-required",
            f"accepted proposal has no ProposalAccepted event: {item_id}",
        )
    return payload, str(accepted_event["event_id"])


def _validate_scope_node(node: dict[str, Any], op: Any, gate: Any) -> None:
    required = {"id", "level", "parents", "version", "status", "spec", "source"}
    missing = sorted(required - set(node))
    if missing:
        raise CommandRejected(
            "scope-node-required-fields",
            f"Scope node missing required fields: {missing}",
        )
    try:
        scope_ssot.validate_node(node)
    except scope_ssot.RuleViolation as exc:
        raise CommandRejected("scope-node-invalid", str(exc)) from exc
    node_id = node["id"]
    if not isinstance(node_id, str) or not node_id.strip():
        raise CommandRejected("scope-node-id-invalid", "Scope node id must be non-empty")
    parents = node["parents"]
    if not isinstance(parents, list) or not all(
        isinstance(parent, str) and parent.strip() for parent in parents
    ):
        raise CommandRejected(
            "scope-node-parents-invalid",
            "Scope node parents must be a list of non-empty ids",
        )
    if node["level"] == "project" and parents:
        raise CommandRejected(
            "scope-project-parent-invalid",
            "Project Scope nodes cannot have parents",
        )
    if node["level"] != "project" and not parents:
        raise CommandRejected(
            "scope-parent-required",
            f"{node['level']} Scope nodes require at least one parent",
        )
    if node["level"] != "project" and len(parents) != 1:
        raise CommandRejected(
            "scope-parent-cardinality",
            f"{node['level']} Scope nodes require exactly one parent",
        )
    version = node["version"]
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise CommandRejected(
            "scope-version-invalid",
            "Scope node version must be a positive integer",
        )
    if node["status"] not in COMMITTED_SCOPE_STATUSES:
        raise CommandRejected(
            "scope-status-invalid",
            f"committed Scope status must be one of {sorted(COMMITTED_SCOPE_STATUSES)}",
        )
    if not isinstance(node["source"], str) or not node["source"].strip():
        raise CommandRejected(
            "scope-source-required",
            "Scope node source must be a non-empty string",
        )
    if op not in scope_ssot.OPS:
        raise CommandRejected("scope-op-invalid", f"illegal Scope op: {op!r}")
    required_gate = scope_ssot.REQUIRED_GATE[node["level"]]
    if gate != required_gate:
        raise CommandRejected(
            "scope-gate",
            f"{node['level']} transition requires gate {required_gate!r}, got {gate!r}",
        )


def _validate_scope_effect_ids(item: dict[str, Any], field: str) -> None:
    value = item.get(field, [])
    if (
        not isinstance(value, list)
        or not all(isinstance(entry, str) and entry.strip() for entry in value)
        or len(value) != len(set(value))
    ):
        raise CommandRejected(
            "scope-effect-ids-invalid",
            f"{field} must be a unique list of non-empty Experiment ids",
        )


def _validate_proposal_item(
    paths: ResearchPaths,
    item: Any,
    state: dict[str, Any],
) -> None:
    """Reject malformed Triage input before it can become governance state."""
    if not isinstance(item, dict):
        raise CommandRejected(
            "proposal-object-required",
            "proposal must be a JSON object",
        )
    required = {
        "id",
        "level",
        "node_id",
        "op",
        "gate",
        "proposed_spec",
        "proposed_node",
    }
    missing = sorted(required - set(item))
    if missing:
        raise CommandRejected(
            "proposal-required-fields",
            f"proposal is missing required fields: {missing}",
        )
    if not isinstance(item["id"], str) or not item["id"].strip():
        raise CommandRejected("proposal-id-required", "proposal needs a non-empty id")
    node = item["proposed_node"]
    if not isinstance(node, dict):
        raise CommandRejected(
            "proposal-node-required",
            "proposed_node must be a complete Scope node",
        )
    _validate_scope_node(node, item.get("op"), item.get("gate"))
    if item.get("level") != node.get("level"):
        raise CommandRejected(
            "proposal-level-mismatch",
            "proposal level must match proposed_node.level",
        )
    if item.get("node_id") != node.get("id"):
        raise CommandRejected(
            "proposal-node-id-mismatch",
            "proposal node_id must match proposed_node.id",
        )
    if item.get("proposed_spec") != node.get("spec"):
        raise CommandRejected(
            "proposal-spec-mismatch",
            "proposed_spec must equal proposed_node.spec",
        )
    for field in ("invalidates", "reopens", "dial_revert"):
        _validate_scope_effect_ids(item, field)
    if node.get("level") == "experiment":
        parent_version = item.get("parent_scope_version")
        if (
            isinstance(parent_version, bool)
            or not isinstance(parent_version, int)
            or parent_version < 1
        ):
            raise CommandRejected(
                "proposal-parent-version-required",
                "Experiment proposal must bind the current Direction version",
            )
        parent_id = node["parents"][0]
        parent = state["aggregates"]["direction"].get(parent_id)
        if not isinstance(parent, dict) or parent.get("version") != parent_version:
            raise CommandConflict(
                "proposal-parent-version-conflict",
                "Experiment proposal does not match the current Direction version",
            )
    if node.get("level") == "project" and "prior_knowledge" in node:
        _validate_note_ref(paths, node["prior_knowledge"])


def _validate_note_ref(paths: ResearchPaths, note_ref: Any) -> None:
    if not isinstance(note_ref, dict):
        raise CommandRejected(
            "note-ref-invalid",
            "prior_knowledge must be a content-addressed NoteRef",
        )
    required = {"uri", "sha256", "mime", "title"}
    missing = sorted(required - set(note_ref))
    if missing:
        raise CommandRejected(
            "note-ref-invalid",
            f"NoteRef is missing required fields: {missing}",
        )
    digest = str(note_ref.get("sha256") or "").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise CommandRejected("note-ref-invalid", "NoteRef sha256 must be 64 hex digits")
    expected_uri = f"state/notes/{digest}.md"
    if note_ref.get("uri") != expected_uri:
        raise CommandRejected(
            "note-ref-invalid",
            f"NoteRef uri must be {expected_uri!r}",
        )
    path = paths.root / expected_uri
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise CommandRejected(
            "note-ref-unresolved",
            f"NoteRef content is missing or does not match its hash: {expected_uri}",
        )


def _scope_record(
    node: dict[str, Any],
    payload: dict[str, Any],
    *,
    current: dict[str, Any] | None = None,
    direction_version: int | None = None,
) -> dict[str, Any]:
    transition = {
        "scope_version": node["version"],
        "op": payload.get("op"),
        "gate": payload.get("gate"),
        "trigger": payload.get("trigger"),
        "cause": payload.get("cause"),
        "invalidates": list(payload.get("invalidates") or []),
        "reopens": list(payload.get("reopens") or []),
        "dial_revert": list(payload.get("dial_revert") or []),
    }
    if node["level"] != "experiment":
        record = copy.deepcopy(node)
        record["_scope_transition"] = transition
        return record
    spec = node["spec"]
    if isinstance(current, dict):
        status = str(
            current.get("status_before_scope_stale")
            if current.get("scope_confirmation") == "STALE"
            else current.get("status")
        )
        if status not in EXPERIMENT_STATUSES:
            status = "PLANNED"
    else:
        status = "PLANNED" if node["status"] == "ACTIVE" else "SKIPPED"
    return {
        "id": node["id"],
        "direction_id": node["parents"][0],
        "package_id": node.get("package_id"),
        "spec": copy.deepcopy(spec),
        "status": status,
        "scope_version": node["version"],
        "scope_status": node["status"],
        "scope_confirmation": "CONFIRMED",
        "confirmed_direction_version": direction_version,
        "scope_source": node["source"],
        "_scope_transition": transition,
    }


def _direction_scope_effects(
    state: dict[str, Any],
    direction_id: str,
    payload: dict[str, Any],
) -> dict[str, list[str]]:
    children = {
        aggregate_id
        for aggregate_id, experiment in state["aggregates"]["experiment"].items()
        if isinstance(experiment, dict)
        and experiment.get("direction_id") == direction_id
    }
    explicit: dict[str, set[str]] = {}
    for field in ("invalidates", "reopens", "dial_revert"):
        values = set(payload.get(field) or [])
        unknown = values - children
        if unknown:
            raise CommandRejected(
                "scope-effect-target-invalid",
                f"{field} names Experiments outside {direction_id}: "
                + ", ".join(sorted(unknown)),
            )
        explicit[field] = values
    invalidates = explicit["invalidates"]
    if payload.get("op") in {"revise", "supersede", "archive"}:
        # A Direction spec/status change changes the interpretation boundary for
        # every child Experiment. Omitting a list must never preserve a silently
        # stale executable spec.
        invalidates |= children
    return {
        "invalidates": sorted(invalidates),
        "reopens": sorted(explicit["reopens"]),
        "dial_revert": sorted(explicit["dial_revert"]),
    }


def _apply_direction_scope_effects(
    store: EventStore,
    direction_event: dict[str, Any],
    payload: dict[str, Any],
    effects: dict[str, list[str]],
    *,
    actor: dict[str, str],
) -> list[dict[str, Any]]:
    affected = set().union(*(set(values) for values in effects.values()))
    committed: list[dict[str, Any]] = []
    for experiment_id in sorted(affected):
        state = store.state()
        current = state["aggregates"]["experiment"].get(experiment_id)
        if not isinstance(current, dict):
            raise CommandConflict(
                "scope-effect-target-disappeared",
                f"Experiment disappeared while applying Direction effects: {experiment_id}",
            )
        prior_status = current.get("status_before_scope_stale")
        if prior_status not in EXPERIMENT_STATUSES:
            prior_status = current.get("status")
        if prior_status not in EXPERIMENT_STATUSES or prior_status == "BLOCKED":
            prior_status = "PLANNED"
        patch: dict[str, Any] = {
            "scope_confirmation": "STALE",
            "confirmed_direction_version": int(payload["version"]) - 1,
            "stale_direction_version": payload["version"],
            "status_before_scope_stale": prior_status,
            "status": "BLOCKED",
        }
        if experiment_id in effects["reopens"]:
            patch["scope_status"] = "ACTIVE"
        elif payload.get("op") in {"supersede", "archive"}:
            patch["scope_status"] = (
                "SUPERSEDED" if payload.get("op") == "supersede" else "ARCHIVED"
            )
        if experiment_id in effects["dial_revert"]:
            spec = copy.deepcopy(current.get("spec") or {})
            spec["control_mode"] = "SUPERVISED"
            patch["spec"] = spec
        committed.append(
            _commit(
                store,
                event_type="ExperimentStatusChanged",
                aggregate_type="experiment",
                aggregate_id=experiment_id,
                payload={"patch": patch},
                actor=actor,
                idempotency_key=(
                    f"scope-effect:{direction_event['event_id']}:{experiment_id}"
                ),
                expected_version=_version(state, "experiment", experiment_id),
                causation_id=direction_event["event_id"],
                entry_skill="research-op",
            )
        )
    return committed


def commit_scope_transition(
    paths: ResearchPaths,
    payload: dict[str, Any],
    *,
    actor: dict[str, str] | None = None,
    idempotency_key: str | None = None,
    expected_version: int | None = None,
    causation_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any], bool]:
    """Validate and commit one Project/Direction/Experiment spec snapshot."""
    if not isinstance(payload, dict):
        raise CommandRejected(
            "scope-payload-object-required",
            "scope-transition payload must be a JSON object",
        )
    node = {
        key: copy.deepcopy(payload[key])
        for key in (
            "id",
            "level",
            "parents",
            "version",
            "status",
            "spec",
            "source",
            "package_id",
            "prior_knowledge",
        )
        if key in payload
    }
    level = node.get("level")
    aggregate_type = SCOPE_AGGREGATES.get(level, "project")
    aggregate_id = str(node.get("id") or f"invalid-{_digest(payload)[:16]}")
    required_node_fields = {
        "id",
        "level",
        "parents",
        "version",
        "status",
        "spec",
        "source",
    }
    store = EventStore(paths)
    existing_state = store.state() if paths.version_file.exists() else None
    current = (
        existing_state["aggregates"][aggregate_type].get(aggregate_id)
        if existing_state is not None
        else None
    )
    direction_version: int | None = None
    if level == "experiment" and node.get("parents") and existing_state is not None:
        direction = existing_state["aggregates"]["direction"].get(node["parents"][0])
        if isinstance(direction, dict) and isinstance(direction.get("version"), int):
            direction_version = direction["version"]
    effective_payload = copy.deepcopy(payload)
    direction_effects = {
        "invalidates": [],
        "reopens": [],
        "dial_revert": [],
    }
    direction_effect_error: CommandRejected | None = None
    if level == "direction" and existing_state is not None:
        try:
            direction_effects = _direction_scope_effects(
                existing_state,
                aggregate_id,
                payload,
            )
        except CommandRejected as exc:
            direction_effect_error = exc
        effective_payload.update(direction_effects)
    record = (
        _scope_record(
            node,
            effective_payload,
            current=current if isinstance(current, dict) else None,
            direction_version=direction_version,
        )
        if level in SCOPE_AGGREGATES and required_node_fields <= set(node)
        else {"id": aggregate_id}
    )
    stable_key = idempotency_key or (
        f"scope:{aggregate_type}:{aggregate_id}:v{node.get('version')}:"
        f"{_digest(effective_payload)}"
    )
    if level == "experiment":
        event_type = "ExperimentSpecRevised"
    else:
        event_type = "ScopeCommitted"
    if event_type == "ScopeCommitted" or (
        event_type == "ExperimentSpecRevised"
        and payload.get("op") == "create"
    ):
        event_payload = {"record": record}
    else:
        patch = copy.deepcopy(record)
        if level == "experiment":
            if patch.get("package_id") is None:
                patch.pop("package_id", None)
        event_payload = {"patch": patch}
    event_payload["proposal_binding"] = {
        "proposal_id": effective_payload.get("_triage_id"),
        "proposal_hash": effective_payload.get("_proposal_hash"),
        "proposed_node": copy.deepcopy(node),
        "op": effective_payload.get("op"),
        "gate": effective_payload.get("gate"),
        "invalidates": list(payload.get("invalidates") or []),
        "reopens": list(payload.get("reopens") or []),
        "dial_revert": list(payload.get("dial_revert") or []),
    }
    command_id = f"cmd_{uuid.uuid4().hex}"
    prior = (
        next(
            (
                event
                for event in store.events()
                if event["idempotency_key"] == stable_key
            ),
            None,
        )
        if existing_state is not None
        else None
    )
    resolved_expected = (
        expected_version
        if expected_version is not None
        else (
            _version(existing_state, aggregate_type, aggregate_id)
            if existing_state is not None
            else 0
        )
    )

    def policy(before: dict[str, Any], _command: dict[str, Any]) -> None:
        if direction_effect_error is not None:
            raise direction_effect_error
        _validate_scope_node(node, effective_payload.get("op"), effective_payload.get("gate"))
        triage_id = effective_payload.get("_triage_id")
        proposal_hash = effective_payload.get("_proposal_hash")
        accepted = before["aggregates"]["proposal"].get(triage_id)
        if (
            not isinstance(triage_id, str)
            or not triage_id
            or not isinstance(proposal_hash, str)
            or not proposal_hash
            or not isinstance(accepted, dict)
            or accepted.get("disposition") != "ACCEPTED"
        ):
            raise CommandRejected(
                "accepted-proposal-required",
                "Scope commits require a hash-bound ProposalAccepted event",
            )
        accepted_snapshot = accepted.get("accepted_proposal")
        if (
            not isinstance(accepted_snapshot, dict)
            or accepted.get("proposal_hash") != proposal_hash
            or proposal_content_hash(accepted_snapshot) != proposal_hash
            or accepted_snapshot.get("proposed_node") != node
            or accepted_snapshot.get("op") != effective_payload.get("op")
            or accepted_snapshot.get("gate") != effective_payload.get("gate")
        ):
            raise CommandConflict(
                "accepted-proposal-binding-mismatch",
                "Scope command no longer matches the accepted proposal snapshot",
            )
        for field in ("invalidates", "reopens", "dial_revert"):
            accepted_values = sorted(accepted_snapshot.get(field) or [])
            requested_values = sorted(payload.get(field) or [])
            if accepted_values != requested_values:
                raise CommandConflict(
                    "accepted-proposal-effect-mismatch",
                    f"{field} differs from the accepted proposal",
                )
        accepted_event = next(
            (
                row
                for row in reversed(store.events())
                if row["event_type"] == "ProposalAccepted"
                and row["aggregate_id"] == triage_id
            ),
            None,
        )
        if accepted_event is None or causation_id != accepted_event["event_id"]:
            raise CommandRejected(
                "proposal-causation-required",
                "Scope commit causation_id must name its ProposalAccepted event",
            )
        if node["level"] == "project" and "prior_knowledge" in node:
            _validate_note_ref(paths, node["prior_knowledge"])
        current = before["aggregates"][aggregate_type].get(aggregate_id)
        op = payload.get("op")
        if op == "create" and current is not None:
            raise CommandConflict(
                "scope-create-exists",
                f"cannot create existing {aggregate_type}: {aggregate_id}",
            )
        if op != "create" and current is None:
            raise CommandConflict(
                "scope-revise-missing",
                f"cannot {op} missing {aggregate_type}: {aggregate_id}",
            )
        if node["level"] == "experiment" and isinstance(current, dict):
            current_scope_version = current.get("scope_version", 0)
        elif isinstance(current, dict):
            current_scope_version = current.get("version", 0)
        else:
            current_scope_version = 0
        if node["version"] != current_scope_version + 1:
            raise CommandConflict(
                "scope-version-conflict",
                f"Scope node version must be {current_scope_version + 1}, "
                f"got {node['version']}",
            )
        if node["level"] in {"direction", "experiment"}:
            parent_type = "project" if node["level"] == "direction" else "direction"
            parent = before["aggregates"][parent_type].get(node["parents"][0])
            if not isinstance(parent, dict) or parent.get("status") != "ACTIVE":
                raise CommandRejected(
                    "scope-parent-active-required",
                    f"{node['level']} requires an ACTIVE {parent_type} parent",
                )
            if node["level"] == "experiment":
                if accepted_snapshot.get("parent_scope_version") != parent.get("version"):
                    raise CommandConflict(
                        "accepted-proposal-parent-stale",
                        "Direction changed after the Experiment proposal was submitted",
                    )
                if direction_version != parent.get("version"):
                    raise CommandConflict(
                        "scope-parent-version-changed",
                        "Direction changed while the Experiment proposal was committing",
                    )
            else:
                live_effects = _direction_scope_effects(
                    before,
                    aggregate_id,
                    payload,
                )
                if live_effects != direction_effects:
                    raise CommandConflict(
                        "scope-effect-set-changed",
                        "Direction children changed while applying Scope propagation",
                    )

    event = _commit(store,
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        payload=event_payload,
        actor=_actor(actor),
        idempotency_key=stable_key,
        expected_version=resolved_expected,
        causation_id=causation_id,
        command_id=command_id,
        entry_skill="research-op",
        policy=policy,
    )
    scope_effect_events: list[dict[str, Any]] = []
    if level == "direction" and any(direction_effects.values()):
        scope_effect_events = _apply_direction_scope_effects(
            store,
            event,
            effective_payload,
            direction_effects,
            actor=_actor(actor),
        )
    event["_scope_effects"] = [
        {
            "event_id": row["event_id"],
            "experiment_id": row["aggregate_id"],
        }
        for row in scope_effect_events
    ]
    return event, record, prior is not None


def _registry_candidate(
    target: str,
    payload: dict[str, Any],
    package_id: str,
) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    normalized_input = copy.deepcopy(payload)
    if target == "paper" and not normalized_input.get("pkg"):
        normalized_input["pkg"] = package_id
    if target == "paper":
        key = (
            normalized_input.get("id")
            or normalized_input.get("arxiv")
            or normalized_input.get("source_id")
            or f"invalid-{_digest(payload)[:16]}"
        )
        record = {
            "id": key,
            "title": normalized_input.get("title"),
            "url": normalized_input.get("url", ""),
            "arxiv": normalized_input.get("arxiv", ""),
            "source_id": normalized_input.get("source_id", ""),
            "pkg": normalized_input.get("pkg", ""),
        }
    elif target == "gap":
        key = normalized_input.get("id") or f"invalid-{_digest(payload)[:16]}"
        record = {
            "id": key,
            "summary": normalized_input.get("summary"),
            "status": normalized_input.get("status", "open"),
        }
    else:
        record = {
            "from": normalized_input.get("from"),
            "to": normalized_input.get("to"),
            "type": normalized_input.get("type"),
            "evidence": normalized_input.get("evidence", ""),
        }
        key = f"edge-{_digest(record)[:24]}"
    aggregate_type = KNOWLEDGE_AGGREGATES.get(target, "paper")
    return aggregate_type, str(key), record, normalized_input


def _validate_registry_record(target: str, record: dict[str, Any]) -> None:
    """Reject invalid knowledge identities without consulting a file store."""
    if target == "paper":
        if not record.get("id"):
            raise CommandRejected(
                "paper-id-required",
                "paper needs id (or arxiv/source_id)",
            )
        if not record.get("title"):
            raise CommandRejected("paper-title-required", "paper needs a title")
        return
    if target == "edge":
        if not record.get("from") or not record.get("to"):
            raise CommandRejected(
                "edge-endpoints-required",
                "edge needs both from and to",
            )
        if record.get("type") not in KNOWLEDGE_EDGE_TYPES:
            raise CommandRejected(
                "edge-type-unknown",
                f"edge type must be one of {sorted(KNOWLEDGE_EDGE_TYPES)}",
            )
        return
    if target == "gap":
        if not record.get("id"):
            raise CommandRejected("gap-id-required", "gap needs an id")
        if not record.get("summary"):
            raise CommandRejected("gap-summary-required", "gap needs a summary")
        return
    raise CommandRejected(
        "unknown-target",
        f"unknown registry target {target!r}",
    )


def _knowledge_ref_exists(state: dict[str, Any], reference: str) -> bool:
    prefix_map = {
        "paper": "paper",
        "gap": "knowledge_gap",
        "package": "package",
        "direction": "direction",
        "experiment": "experiment",
        "learning": "learning",
        "rule": "rule",
    }
    if ":" not in reference:
        return any(
            reference in state["aggregates"][aggregate_type]
            for aggregate_type in prefix_map.values()
        )
    prefix, aggregate_id = reference.split(":", 1)
    aggregate_type = prefix_map.get(prefix)
    return bool(
        aggregate_type
        and aggregate_id
        and aggregate_id in state["aggregates"][aggregate_type]
    )


def commit_registry_add(
    paths: ResearchPaths,
    target: str,
    payload: dict[str, Any],
    *,
    package_id: str,
    actor: dict[str, str] | None = None,
    idempotency_key: str | None = None,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """Validate and commit one Paper, KnowledgeEdge, or KnowledgeGap event."""
    if not isinstance(payload, dict):
        raise CommandRejected(
            "registry-payload-object-required",
            "registry-add payload must be a JSON object",
        )
    aggregate_type, aggregate_id, record, normalized_input = _registry_candidate(
        target,
        payload,
        package_id,
    )
    stable_key = idempotency_key or f"registry-add:{target}:{aggregate_id}"
    store = EventStore(paths)
    command_id = f"cmd_{uuid.uuid4().hex}"
    prior = next(
        (event for event in store.events() if event["idempotency_key"] == stable_key),
        None,
    ) if paths.version_file.exists() else None

    def policy(before: dict[str, Any], _command: dict[str, Any]) -> None:
        if package_id not in before["aggregates"]["package"]:
            raise CommandRejected(
                "registry-package-required",
                f"adding package is not present in research state: {package_id}",
            )
        _validate_registry_record(target, record)
        if target == "edge":
            invalid = [
                reference
                for reference in (str(record["from"]), str(record["to"]))
                if not _knowledge_ref_exists(before, reference)
            ]
            if invalid:
                raise CommandRejected(
                    "knowledge-reference-missing",
                    "knowledge edge references unknown identities: "
                    + ", ".join(invalid),
                )
        current = before["aggregates"][aggregate_type].get(aggregate_id)
        if current is not None:
            rule = (
                "registry-duplicate"
                if current == record
                else "registry-identity-conflict"
            )
            raise CommandConflict(
                rule,
                f"{aggregate_type} identity already exists: {aggregate_id}",
            )

    event = _commit(store,
        event_type="AggregateUpserted",
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        payload={
            "record": record,
            "command_context": {"package_id": package_id},
        },
        actor=_actor(actor),
        idempotency_key=stable_key,
        expected_version=0,
        command_id=command_id,
        entry_skill="research-op",
        policy=policy,
    )
    return ("duplicate" if prior is not None else "added"), record, event


# ---------------------------------------------------------------------------
# Package / Experiment / Decision facade
# ---------------------------------------------------------------------------


def propagate_run_result(
    paths: ResearchPaths,
    package_id: str,
    run_id: str,
    *,
    actor: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Finalize one hash-verified Run result as the sole scientific authority.

    Package result tables and Experiment summaries are renderer/query
    projections of this Run event.  They are deliberately not written back to
    Package or Experiment aggregates.
    """
    from lib import package_facts

    store = EventStore(paths)
    state = store.state()
    package = state["aggregates"]["package"][package_id]
    if not state_policy.is_legal(
        str(package.get("lifecycle")),
        package.get("phase"),
        package.get("blocker"),
        "insert",
        "results-gate-row",
    ):
        raise CommandRejected(
            "result-propagation-phase",
            "package phase does not admit a finalized result",
        )
    run = state["aggregates"]["run"][run_id]
    normalized = package_facts.load_run_result(
        paths,
        package_id,
        run_id,
        state=state,
    )
    prior_summary = run.get("latest_scientific_result")
    if (
        isinstance(prior_summary, dict)
        and prior_summary.get("result_sha256") == normalized["result_sha256"]
        and run.get("result_finalized_event_id")
    ):
        prior = next(
            (
                event
                for event in reversed(store.events())
                if event.get("event_id") == run["result_finalized_event_id"]
            ),
            None,
        )
        if prior is None:
            raise CommandConflict(
                "result-finalization-event-missing",
                f"run {run_id} names a missing RunResultFinalized event",
            )
        return [copy.deepcopy(prior)]

    raw_result = normalized["result"]
    measurements = raw_result.get("measurements")
    if not isinstance(measurements, dict):
        raw_metrics = raw_result.get("metrics")
        measurements = (
            copy.deepcopy(raw_metrics)
            if isinstance(raw_metrics, dict)
            else {normalized["metric"]: copy.deepcopy(normalized["measured"])}
        )
    summary = {
        "run_id": run_id,
        "package_id": package_id,
        "experiment_id": normalized["experiment_id"],
        "kind": "experiment-result",
        "result_json": normalized["source_artifact"],
        "result_sha256": normalized["result_sha256"],
        "protocol": copy.deepcopy(raw_result.get("protocol") or {}),
        "measurements": measurements,
        "verdict": normalized["verdict"],
        "validity": normalized["validity"],
        "supported_claims": copy.deepcopy(
            raw_result.get("supported_claims") or []
        ),
        "unsupported_claims": copy.deepcopy(
            raw_result.get("unsupported_claims") or []
        ),
        "decision_candidate": copy.deepcopy(
            raw_result.get("decision_candidate")
        ),
        "evidence": copy.deepcopy(normalized["evidence"]),
        "evidence_count": len(normalized["evidence"]),
        # Presentation-neutral descriptors let projections preserve the
        # existing result-table wording without owning a second fact copy.
        "experiment_local_id": normalized["exp_id"],
        "method": normalized["method"],
        "hypothesis": normalized["hypothesis"],
        "gate": normalized["gate"],
        "metric": normalized["metric"],
        "measured": copy.deepcopy(normalized["measured"]),
    }
    causation_id = str(
        run.get("result_finalized_event_id") or run.get("terminal_event_id") or ""
    )
    if not causation_id:
        raise CommandRejected(
            "result-terminal-causation-required",
            f"run {run_id} has no terminal event",
        )
    principal = actor or {"type": "system", "id": "result-propagator"}
    event = record_run_result_finalized(
        paths,
        run_id,
        summary,
        expected_version=_version(state, "run", run_id),
        causation_id=causation_id,
        actor=principal,
    )
    return [event]


def _package(
    state: dict[str, Any],
    package_id: str,
) -> dict[str, Any]:
    record = state["aggregates"]["package"].get(package_id)
    if not isinstance(record, dict):
        raise CommandRejected(
            "package-not-found",
            f"package is not present in research state: {package_id}",
        )
    return record


def _canonical_experiment_status(value: Any) -> str:
    raw = str(value or "PLANNED")
    canonical = EXPERIMENT_STATUS_COMPAT.get(raw, raw)
    if canonical not in EXPERIMENT_STATUSES:
        raise CommandRejected(
            "experiment-status-invalid",
            f"unknown experiment status: {value!r}",
        )
    return canonical


def resolve_package_experiment(
    state: dict[str, Any],
    package_id: str,
    requested_id: Any,
) -> tuple[str, dict[str, Any]]:
    """Resolve a bound Experiment without inventing a package-scoped id.

    New records use their accepted Scope id as the aggregate id.  Legacy
    package-scoped ids and aliases remain readable during migration.
    """
    try:
        return resolve_bound_experiment(
            state["aggregates"]["experiment"],
            package_id,
            requested_id,
        )
    except ValueError as exc:
        detail = str(exc)
        if "identifier is required" in detail:
            raise CommandRejected("experiment-id-required", detail) from exc
        if "found 0" in detail:
            raise CommandRejected("experiment-not-found", detail) from exc
        raise CommandConflict("experiment-id-ambiguous", detail) from exc


def normalize_experiment_binding(
    package_id: str,
    row: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Normalize metadata that binds one accepted Experiment to a Package."""
    if not isinstance(row, dict):
        raise CommandRejected(
            "experiment-object-required",
            "Experiment binding must be a JSON object",
        )
    forbidden_fields = sorted(
        {
            "id",
            "spec",
            "purpose",
            "config_ref",
            "gate",
            "control_mode",
            "localId",
            "controlMode",
            "config",
            "sourceTask",
            "source_task_id",
            "source_task",
        }.intersection(row)
    )
    if forbidden_fields:
        raise CommandRejected(
            "experiment-spec-owner",
            "Package materialization binds an accepted Experiment and cannot "
            "define or copy Experiment.spec fields: "
            + ", ".join(forbidden_fields),
        )
    aggregate_id = row.get("scope_experiment_id")
    if not isinstance(aggregate_id, str) or not aggregate_id.strip():
        raise CommandRejected(
            "scope-experiment-id-required",
            "Experiment binding requires scope_experiment_id",
        )
    local_id = row.get("local_id")
    if not isinstance(local_id, str) or not local_id.strip():
        raise CommandRejected(
            "experiment-local-id-required",
            "Experiment binding requires a non-empty local_id",
        )
    patch: dict[str, Any] = {
        "local_id": local_id.strip(),
        "package_id": package_id,
        "status": _canonical_experiment_status(row.get("status", "READY")),
    }
    for field in (
        "label",
        "output",
        "measures",
        "requiresCode",
        "complex",
        "resultSchemaRef",
        "resultSchema",
        "runLink",
        "docsAnchor",
    ):
        if field in row:
            patch[field] = copy.deepcopy(row[field])
    # Dependency edges are retained only when the caller supplied them.
    if "after" in row:
        after = row["after"]
        if not isinstance(after, list) or not all(
            isinstance(item, str) and item for item in after
        ):
            raise CommandRejected(
                "experiment-after-invalid",
                f"experiment {local_id} after must be a list of local ids",
            )
        patch["after"] = copy.deepcopy(after)
    return aggregate_id.strip(), patch


def _validate_package_record(record: dict[str, Any]) -> None:
    package_id = record.get("id")
    if not isinstance(package_id, str) or not package_id.strip():
        raise CommandRejected("package-id-required", "package requires id")
    lifecycle = record.get("lifecycle")
    phase = record.get("phase")
    blocker = record.get("blocker")
    try:
        state_policy.legacy_cell(str(lifecycle), phase, blocker)
    except ValueError as exc:
        raise CommandRejected("package-state-invalid", str(exc)) from exc
    if (
        lifecycle != "ACTIVE"
        or phase != "CONTEXT_LOADED"
        or blocker is not None
    ):
        raise CommandRejected(
            "package-initial-state-invalid",
            "new Packages must start at ACTIVE/CONTEXT_LOADED without a "
            "blocker; historical state belongs in explicit migration",
        )
    pages = record.get("pages")
    if pages is not None and (
        not isinstance(pages, list)
        or not all(isinstance(page, str) and page for page in pages)
    ):
        raise CommandRejected("package-pages-invalid", "package pages must be a string list")
    direction_id = record.get("direction_id")
    if not isinstance(direction_id, str) or not direction_id.strip():
        raise CommandRejected(
            "package-direction-required",
            "Package creation requires a committed direction_id",
        )
    source_version = record.get("sourceVersion")
    if (
        isinstance(source_version, bool)
        or not isinstance(source_version, int)
        or source_version < 1
    ):
        raise CommandRejected(
            "package-direction-version-required",
            "Package creation requires a positive integer sourceVersion",
        )
    if not isinstance(record.get("sourceChange"), str) or not record[
        "sourceChange"
    ].strip():
        raise CommandRejected(
            "package-direction-event-required",
            "Package creation requires a non-empty sourceChange event id",
        )
    provenance = record.get("sourceExperiments")
    if not isinstance(provenance, list) or not provenance:
        raise CommandRejected(
            "package-source-experiments-required",
            "Package creation requires at least one accepted source Experiment",
        )
    if not all(
        isinstance(item, dict)
        and set(item) == {"id", "version", "source"}
        and isinstance(item["id"], str)
        and item["id"]
        and isinstance(item["version"], int)
        and not isinstance(item["version"], bool)
        and item["version"] > 0
        and isinstance(item["source"], str)
        and item["source"]
        for item in provenance
    ):
        raise CommandRejected(
            "package-source-experiments-invalid",
            "sourceExperiments entries must be exact {id, version, source} records",
        )


def _commit_package_create_locked(
    paths: ResearchPaths,
    record: dict[str, Any],
    experiments: list[dict[str, Any]] | None = None,
    *,
    actor: dict[str, str] | None = None,
    idempotency_key: str | None = None,
    entry_skill: str = "research-package",
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Create package management state and bind accepted Scope Experiments.

    All rows are normalized and collision-checked before one composite event
    atomically materializes the Package and every Experiment binding.
    """
    package = copy.deepcopy(record)
    _validate_package_record(package)
    package_id = str(package["id"])
    normalized = [
        normalize_experiment_binding(package_id, row)
        for row in list(experiments or [])
    ]
    if not normalized:
        raise CommandRejected(
            "package-experiment-bindings-required",
            "Package creation requires accepted Experiment bindings",
        )
    aggregate_ids = [aggregate_id for aggregate_id, _ in normalized]
    if len(aggregate_ids) != len(set(aggregate_ids)):
        raise CommandRejected(
            "experiment-id-duplicate",
            f"package {package_id} has duplicate experiment ids",
        )
    local_ids = [patch["local_id"] for _, patch in normalized]
    if len(local_ids) != len(set(local_ids)):
        raise CommandRejected(
            "experiment-local-id-duplicate",
            f"package {package_id} has duplicate local Experiment ids",
        )
    store = EventStore(paths)
    store.initialize()
    before = store.state()
    existing_package = before["aggregates"]["package"].get(package_id)
    package_key = idempotency_key or (
        f"package:create:{package_id}:{_digest({'package': package, 'experiments': normalized})}"
    )
    prior_package = next(
        (
            event
            for event in store.events()
            if event["idempotency_key"] == package_key
        ),
        None,
    )
    if existing_package is not None and prior_package is None:
        raise CommandConflict(
            "package-create-exists",
            f"package already exists: {package_id}",
        )
    provenance = {
        item["id"]: item
        for item in package["sourceExperiments"]
    }
    if set(provenance) != set(aggregate_ids):
        raise CommandRejected(
            "package-provenance-binding-mismatch",
            "sourceExperiments must name exactly the Experiments being bound",
        )
    candidate_payload = {
        "record": package,
        "experiment_bindings": [
            {
                "aggregate_id": aggregate_id,
                "expected_version": _version(
                    before, "experiment", aggregate_id
                ),
                "aggregate_version": _version(
                    before, "experiment", aggregate_id
                )
                + 1,
                "patch": patch,
            }
            for aggregate_id, patch in normalized
        ],
    }
    if prior_package is not None:
        prior_payload = prior_package.get("payload")
        prior_semantics = {
            "record": (
                prior_payload.get("record")
                if isinstance(prior_payload, dict)
                else None
            ),
            "experiment_bindings": [
                {
                    "aggregate_id": binding.get("aggregate_id"),
                    "patch": binding.get("patch"),
                }
                for binding in (
                    prior_payload.get("experiment_bindings", [])
                    if isinstance(prior_payload, dict)
                    else []
                )
                if isinstance(binding, dict)
            ],
        }
        candidate_semantics = {
            "record": candidate_payload["record"],
            "experiment_bindings": [
                {
                    "aggregate_id": binding["aggregate_id"],
                    "patch": binding["patch"],
                }
                for binding in candidate_payload["experiment_bindings"]
            ],
        }
        if (
            prior_package.get("event_type") != "PackageMaterialized"
            or prior_package.get("aggregate_type") != "package"
            or prior_package.get("aggregate_id") != package_id
            or prior_semantics != candidate_semantics
        ):
            raise CommandConflict(
                "idempotency-conflict",
                "idempotency_key was already committed with different "
                "Package materialization content",
            )
        materialization_payload = copy.deepcopy(prior_payload)
    else:
        materialization_payload = candidate_payload
    binding_versions = {
        binding["aggregate_id"]: binding["expected_version"]
        for binding in materialization_payload.get("experiment_bindings", [])
        if isinstance(binding, dict)
        and isinstance(binding.get("aggregate_id"), str)
    }

    def validate_bindings(state: dict[str, Any]) -> None:
        direction_id = str(package["direction_id"])
        direction = state["aggregates"]["direction"].get(direction_id)
        if (
            not isinstance(direction, dict)
            or direction.get("level") != "direction"
            or direction.get("status") != "ACTIVE"
        ):
            raise CommandRejected(
                "package-active-direction-required",
                f"Package requires an ACTIVE Direction: {direction_id}",
            )
        if package.get("sourceVersion") != direction.get("version"):
            raise CommandConflict(
                "package-direction-version-mismatch",
                "Package sourceVersion must equal the current Direction version",
            )
        latest_direction_event = next(
            (
                row
                for row in reversed(store.events())
                if row["aggregate_type"] == "direction"
                and row["aggregate_id"] == direction_id
            ),
            None,
        )
        if (
            latest_direction_event is None
            or package.get("sourceChange") != latest_direction_event["event_id"]
        ):
            raise CommandConflict(
                "package-direction-event-mismatch",
                "Package sourceChange must name the current Direction event",
            )
        used_local_ids = {
            experiment.get("local_id")
            for experiment in state["aggregates"]["experiment"].values()
            if isinstance(experiment, dict)
            and experiment.get("package_id") == package_id
        }
        for aggregate_id, patch in normalized:
            experiment = state["aggregates"]["experiment"].get(aggregate_id)
            if not isinstance(experiment, dict):
                raise CommandRejected(
                    "accepted-experiment-required",
                    f"accepted Experiment not found: {aggregate_id}",
                )
            if experiment.get("direction_id") != direction_id:
                raise CommandRejected(
                    "experiment-direction-mismatch",
                    f"Experiment {aggregate_id} belongs to another Direction",
                )
            if experiment.get("package_id") not in {None, "", package_id}:
                raise CommandConflict(
                    "experiment-already-bound",
                    f"Experiment {aggregate_id} is already bound to "
                    f"{experiment.get('package_id')}",
                )
            if _version(state, "experiment", aggregate_id) != binding_versions.get(
                aggregate_id
            ):
                raise CommandConflict(
                    "experiment-version-conflict",
                    f"Experiment {aggregate_id} changed before Package "
                    "materialization",
                )
            if (
                experiment.get("scope_status") != "ACTIVE"
                or experiment.get("scope_confirmation") != "CONFIRMED"
                or experiment.get("confirmed_direction_version") != direction.get("version")
            ):
                raise CommandRejected(
                    "experiment-scope-not-executable",
                    f"Experiment {aggregate_id} is inactive or requires reconfirmation",
                )
            spec = experiment.get("spec")
            if not isinstance(spec, dict) or set(spec) != {
                "purpose",
                "config_ref",
                "gate",
                "control_mode",
            }:
                raise CommandRejected(
                    "experiment-spec-invalid",
                    f"Experiment {aggregate_id} lacks the canonical four-field spec",
                )
            source = provenance[aggregate_id]
            if (
                source["version"] != experiment.get("scope_version")
                or source["source"] != experiment.get("scope_source")
            ):
                raise CommandConflict(
                    "experiment-provenance-mismatch",
                    f"Package provenance is stale for Experiment {aggregate_id}",
                )
            if (
                patch["local_id"] in used_local_ids
                and experiment.get("local_id") != patch["local_id"]
            ):
                raise CommandConflict(
                    "experiment-local-id-conflict",
                    f"local Experiment id is already used: {patch['local_id']}",
                )
            used_local_ids.add(patch["local_id"])

    if prior_package is None:
        validate_bindings(before)

    package_event = _commit(store,
        event_type="PackageMaterialized",
        aggregate_type="package",
        aggregate_id=package_id,
        payload=materialization_payload,
        actor=_actor(actor),
        idempotency_key=package_key,
        expected_version=0 if existing_package is None else _version(
            before, "package", package_id
        ),
        entry_skill=entry_skill,
        policy=lambda state, _command: validate_bindings(state),
    )
    # Preserve the established facade return shape without fabricating more
    # domain events.  Every receipt points at the one atomic event and exposes
    # the participant identity/version for callers that list bound Experiments.
    experiment_events = [
        {
            **copy.deepcopy(package_event),
            "aggregate_type": "experiment",
            "aggregate_id": binding["aggregate_id"],
            "aggregate_version": binding["aggregate_version"],
            "_composite_event_type": "PackageMaterialized",
        }
        for binding in materialization_payload["experiment_bindings"]
    ]
    return package_event, experiment_events


def commit_package_create(
    paths: ResearchPaths,
    record: dict[str, Any],
    experiments: list[dict[str, Any]] | None = None,
    *,
    actor: dict[str, str] | None = None,
    idempotency_key: str | None = None,
    entry_skill: str = "research-package",
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Atomically materialize one Package and its accepted Experiments."""
    return _commit_package_create_locked(
        paths,
        record,
        experiments,
        actor=actor,
        idempotency_key=idempotency_key,
        entry_skill=entry_skill,
    )


def _package_policy(
    *,
    package_id: str,
    operation: str,
    target: str,
):
    def policy(before: dict[str, Any], _command: dict[str, Any]) -> None:
        package = _package(before, package_id)
        if not state_policy.is_legal(
            str(package.get("lifecycle")),
            package.get("phase"),
            package.get("blocker"),
            operation,
            target,
        ):
            category, status = state_policy.legacy_cell(
                str(package.get("lifecycle")),
                package.get("phase"),
                package.get("blocker"),
            )
            raise CommandRejected(
                "illegal-transition",
                f"({category}, {status}) does not allow {operation} {target}",
            )

    return policy


def commit_package_mutation(
    paths: ResearchPaths,
    package_id: str,
    *,
    operation: str,
    target: str,
    operations: list[dict[str, Any]],
    actor: dict[str, str] | None = None,
    idempotency_key: str | None = None,
    expected_version: int | None = None,
    causation_id: str | None = None,
    entry_skill: str = "research-op",
    semantic_policy: Callable[[dict[str, Any], dict[str, Any]], None] | None = None,
    command_input_digest: str | None = None,
) -> dict[str, Any]:
    """Commit one atomic top-level package mutation event."""
    if not operations:
        raise CommandRejected(
            "package-mutation-empty",
            "package mutation requires at least one operation",
        )
    store = EventStore(paths)
    state = store.state()
    _package(state, package_id)
    version = _version(state, "package", package_id)
    payload = {
        "operation": operation,
        "target": target,
        "operations": copy.deepcopy(operations),
    }
    if command_input_digest is not None:
        payload["command_input_digest"] = command_input_digest
    legality_policy = _package_policy(
        package_id=package_id,
        operation=operation,
        target=target,
    )

    def mutation_policy(
        before: dict[str, Any],
        command: dict[str, Any],
    ) -> None:
        legality_policy(before, command)
        if semantic_policy is not None:
            semantic_policy(before, command)

    return _commit(store,
        event_type="PackageMutationApplied",
        aggregate_type="package",
        aggregate_id=package_id,
        payload=payload,
        actor=_actor(actor),
        idempotency_key=idempotency_key
        or f"package:{package_id}:{operation}:{target}:v{version + 1}:{_digest(operations)}",
        expected_version=version if expected_version is None else expected_version,
        causation_id=causation_id,
        entry_skill=entry_skill,
        policy=mutation_policy,
    )


def commit_package_pages(
    paths: ResearchPaths,
    package_id: str,
    pages: list[str],
    *,
    actor: dict[str, str] | None = None,
    idempotency_key: str | None = None,
    entry_skill: str = "research-analysis",
) -> dict[str, Any]:
    """Update renderer page selection as package configuration."""
    if not isinstance(pages, list) or not all(
        isinstance(page, str) and page for page in pages
    ):
        raise CommandRejected(
            "package-pages-invalid",
            "package pages must be a list of non-empty strings",
        )
    normalized = list(dict.fromkeys(pages))
    store = EventStore(paths)
    state = store.state()
    package = _package(state, package_id)
    if package.get("lifecycle") != "ACTIVE":
        raise CommandRejected(
            "package-terminal-frozen",
            "page configuration cannot change on a terminal package",
        )
    version = _version(state, "package", package_id)
    return _commit(store,
        event_type="PackageMutationApplied",
        aggregate_type="package",
        aggregate_id=package_id,
        payload={
            "operation": "update",
            "target": "pages",
            "operations": [
                {"operation": "set", "target": "pages", "value": normalized}
            ],
        },
        actor=_actor(actor),
        idempotency_key=idempotency_key
        or f"package:{package_id}:pages:v{version + 1}:{_digest(normalized)}",
        expected_version=version,
        entry_skill=entry_skill,
    )


def _status_operations(
    package: dict[str, Any],
    value: str,
) -> list[dict[str, Any]]:
    if value in PACKAGE_PHASES:
        canonical = {"lifecycle": "ACTIVE", "phase": value, "blocker": None}
    elif value == "BLOCKED":
        canonical = {
            "lifecycle": "ACTIVE",
            "phase": package.get("phase"),
            "blocker": package.get("blocker")
            or {
                "code": "PACKAGE_BLOCKED",
                "summary": str(
                    package.get("currentBlocker") or "Package is blocked"
                ),
            },
        }
    elif value == "STOPPED":
        canonical = {"lifecycle": "STOPPED", "phase": None, "blocker": None}
    elif value in state_policy.SUCCESS_STATUS.values():
        canonical = state_policy.from_legacy("success", value, package)
    elif value in state_policy.FAIL_STATUS.values():
        canonical = state_policy.from_legacy("fail", value, package)
    else:
        raise CommandRejected(
            "package-status-invalid",
            f"unknown package status: {value!r}",
        )
    return [
        {"operation": "set", "target": key, "value": val}
        for key, val in canonical.items()
    ]


def _reference_id(
    state: dict[str, Any],
    aggregate_type: str,
    package_id: str,
    raw_id: Any,
) -> str:
    requested = str(raw_id or "").strip()
    if not requested:
        return ""
    if requested in state["aggregates"][aggregate_type]:
        return requested
    prefixes = {
        "change": f"{package_id}::change::",
    }
    prefix = prefixes.get(aggregate_type)
    candidate = f"{prefix}{requested}" if prefix else requested
    return (
        candidate
        if candidate in state["aggregates"][aggregate_type]
        else requested
    )


def _launch_review_authority(
    state: dict[str, Any],
    package_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    change_id = _reference_id(
        state,
        "change",
        package_id,
        payload.get("review_change_id"),
    )
    change = state["aggregates"]["change"].get(change_id)
    if not isinstance(change, dict) or change.get("package_id") != package_id:
        raise CommandRejected(
            "launch-review-required",
            "entering READY_TO_LAUNCH requires review_change_id for a "
            "committed package Change",
        )
    review = change.get("review")
    if not isinstance(review, dict):
        raise CommandRejected(
            "launch-review-invalid",
            f"Change {change_id} has no structured review",
        )
    verdict = (
        review.get("verdict")
        if isinstance(review.get("verdict"), dict)
        else review
    )
    producer = verdict.get("producer")
    judge = verdict.get("judge")
    if not producer or not judge or producer == judge:
        raise CommandRejected(
            "launch-review-independent-required",
            "implementation review requires distinct producer and judge",
        )
    if verdict.get("result") not in verifier.ACQUIT_STATES:
        raise CommandRejected(
            "launch-review-does-not-acquit",
            f"implementation review result must be one of "
            f"{sorted(verifier.ACQUIT_STATES)}",
        )
    return {
        "aggregate_type": "change",
        "aggregate_id": change_id,
        "aggregate_version": _version(state, "change", change_id),
    }


def _terminal_ack_authority(
    state: dict[str, Any],
    package_id: str,
    desired_status: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    decision_id = str(payload.get("terminal_decision_id") or "").strip()
    decision = state["aggregates"]["decision"].get(decision_id)
    if not isinstance(decision, dict):
        raise CommandRejected(
            "terminal-decision-required",
            "terminal Package transitions require terminal_decision_id",
        )
    if (
        decision.get("kind") != "TERMINAL_ACK"
        or decision.get("package_id") != package_id
        or decision.get("target_status") != desired_status
        or decision.get("status") != "ACKNOWLEDGED"
        or not isinstance(decision.get("actor"), dict)
        or decision["actor"].get("type") != "user"
    ):
        raise CommandRejected(
            "terminal-decision-invalid",
            "terminal_decision_id must name a user TERMINAL_ACK for the "
            f"same package and target status {desired_status}",
        )
    return {
        "aggregate_type": "decision",
        "aggregate_id": decision_id,
        "aggregate_version": _version(state, "decision", decision_id),
    }


def _transition_ack_authority(
    state: dict[str, Any],
    package_id: str,
    desired_status: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    decision_id = str(payload.get("transition_decision_id") or "").strip()
    decision = state["aggregates"]["decision"].get(decision_id)
    if (
        not isinstance(decision, dict)
        or decision.get("kind") != "PACKAGE_TRANSITION_ACK"
        or decision.get("package_id") != package_id
        or decision.get("target_status") != desired_status
        or decision.get("status") != "ACKNOWLEDGED"
        or not isinstance(decision.get("actor"), dict)
        or decision["actor"].get("type") != "user"
    ):
        raise CommandRejected(
            "transition-decision-required",
            "lane-crossing status changes require transition_decision_id for "
            "a user PACKAGE_TRANSITION_ACK",
        )
    return {
        "aggregate_type": "decision",
        "aggregate_id": decision_id,
        "aggregate_version": _version(state, "decision", decision_id),
    }


def _verifier_decision_authority(
    state: dict[str, Any],
    package_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    decision_id = str(payload.get("verifier_decision_id") or "").strip()
    decision = state["aggregates"]["decision"].get(decision_id)
    if not isinstance(decision, dict):
        raise CommandRejected(
            "verifier-decision-required",
            "success transitions require verifier_decision_id",
        )
    run_id = str(decision.get("run_id") or "")
    run = state["aggregates"]["run"].get(run_id)
    result = (
        run.get("latest_scientific_result")
        if isinstance(run, dict)
        else None
    )
    experiment = (
        state["aggregates"]["experiment"].get(run.get("experiment_id"))
        if isinstance(run, dict)
        else None
    )
    spec = (
        experiment.get("spec")
        if isinstance(experiment, dict)
        and isinstance(experiment.get("spec"), dict)
        else {}
    )
    verdict = decision.get("verdict")
    control_mode = str(spec.get("control_mode") or "")
    if (
        decision.get("kind") != "VERIFIER_VERDICT"
        or decision.get("package_id") != package_id
        or decision.get("status") != "ACCEPTED"
        or not isinstance(result, dict)
        or run.get("package_id") != package_id
        or decision.get("result_event_id") != run.get("result_finalized_event_id")
        or decision.get("result_sha256") != result.get("result_sha256")
        or decision.get("gate") != spec.get("gate")
        or decision.get("experiment_scope_version")
        != experiment.get("scope_version")
        or decision.get("control_mode") != control_mode
        or not isinstance(verdict, dict)
    ):
        raise CommandRejected(
            "verifier-decision-invalid",
            "verifier_decision_id must remain bound to the current finalized "
            "Run result and exact Experiment gate",
        )
    reason = verifier.assess_acquit(verdict, control_mode)
    if reason:
        raise CommandRejected("verifier-decision-does-not-acquit", reason)
    return {
        "aggregate_type": "decision",
        "aggregate_id": decision_id,
        "aggregate_version": _version(state, "decision", decision_id),
    }


def _status_command(
    state: dict[str, Any],
    package_id: str,
    payload: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    package = _package(state, package_id)
    desired_status = str(payload.get("to") or "")
    current_category, current_status = state_policy.legacy_cell(
        str(package.get("lifecycle")),
        package.get("phase"),
        package.get("blocker"),
    )
    operations = _status_operations(package, desired_status)
    projected = {
        item["target"]: item["value"]
        for item in operations
    }
    next_category, _ = state_policy.legacy_cell(
        str(projected["lifecycle"]),
        projected.get("phase"),
        projected.get("blocker"),
    )
    authority: dict[str, Any] | None = None
    if (
        desired_status == "READY_TO_LAUNCH"
        and current_status != desired_status
    ):
        authority = _launch_review_authority(state, package_id, payload)
        operations.append(
            {
                "operation": "set",
                "target": "reviewChangeId",
                "value": authority["aggregate_id"],
            }
        )
    if (
        desired_status in TERMINAL_PACKAGE_STATUSES
        and current_status != desired_status
    ):
        required = {"terminationMessage"}
        if next_category == "success":
            required.add("adoptionPath")
        missing = sorted(
            field
            for field in required
            if not str(payload.get(field) or "").strip()
        )
        if missing:
            raise CommandRejected(
                "terminal-fields-required",
                f"terminal status {desired_status} requires fields {missing}",
            )
        terminal_authority = _terminal_ack_authority(
            state,
            package_id,
            desired_status,
            payload,
        )
        authority = terminal_authority
        for field in sorted(required):
            operations.append(
                {
                    "operation": "set",
                    "target": field,
                    "value": payload[field],
                }
            )
        operations.append(
            {
                "operation": "set",
                "target": "terminalDecisionId",
                "value": terminal_authority["aggregate_id"],
            }
        )
        if next_category == "success":
            verifier_authority = _verifier_decision_authority(
                state,
                package_id,
                payload,
            )
            operations.append(
                {
                    "operation": "set",
                    "target": "verifierDecisionId",
                    "value": verifier_authority["aggregate_id"],
                }
            )
    if current_category != next_category and authority is None:
        authority = _transition_ack_authority(
            state,
            package_id,
            desired_status,
            payload,
        )
        operations.append(
            {
                "operation": "set",
                "target": "transitionDecisionId",
                "value": authority["aggregate_id"],
            }
        )
    return operations, authority


def package_operations_for_target(
    state: dict[str, Any],
    package_id: str,
    operation: str,
    target: str,
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    """Translate the public target vocabulary into canonical package operations."""
    package = _package(state, package_id)
    timestamp = datetime.now(timezone.utc).date().isoformat()
    operations: list[dict[str, Any]]
    if operation == "update" and target == "status":
        operations, _ = _status_command(state, package_id, payload)
        projected = {
            item["target"]: item["value"]
            for item in operations
            if item["target"] in {"lifecycle", "phase", "blocker"}
        }
        current_phase = package.get("phase")
        next_phase = projected.get("phase")
        if (
            package.get("lifecycle") == "ACTIVE"
            and projected.get("lifecycle") == "ACTIVE"
            and package.get("blocker") is None
            and projected.get("blocker") is None
            and current_phase != next_phase
            and next_phase not in transition_map("package_phase").get(
                str(current_phase), ()
            )
        ):
            raise CommandRejected(
                "package-phase-transition-invalid",
                f"cannot move package phase {current_phase!r} -> {next_phase!r}",
            )
    elif operation == "update" and target == "objectiveContract":
        current = (
            copy.deepcopy(package.get("objectiveContract"))
            if isinstance(package.get("objectiveContract"), dict)
            else {}
        )
        if "field" in payload:
            current[str(payload["field"])] = copy.deepcopy(payload.get("to"))
        else:
            current = copy.deepcopy(payload.get("to"))
        if not isinstance(current, dict):
            raise CommandRejected(
                "objective-contract-invalid",
                "objectiveContract must be an object",
            )
        operations = [
            {"operation": "set", "target": "objectiveContract", "value": current}
        ]
    elif operation == "update" and target in {
        "activeGate",
        "primaryMetricVsGate",
        "lastAction",
        "lastUpdated",
        "openRuns",
        "terminationMessage",
        "adoptionPath",
        "supersededBy",
        "reopenTrigger",
    }:
        operations = [
            {"operation": "set", "target": target, "value": copy.deepcopy(payload.get("to"))}
        ]
    elif operation == "update" and target == "currentBlocker":
        value = payload.get("to")
        blocker = (
            None
            if value in (None, "", "none")
            else (
                copy.deepcopy(value)
                if isinstance(value, dict)
                else {"code": "PACKAGE_BLOCKED", "summary": str(value)}
            )
        )
        operations = [
            {"operation": "set", "target": "currentBlocker", "value": value},
            {"operation": "set", "target": "blocker", "value": blocker},
        ]
    elif target in {"doc-card", "doc-file"}:
        slug = str(payload.get("slug") or payload.get("id") or "")
        if not slug:
            raise CommandRejected(
                "doc-slug-required",
                f"{target} requires slug",
            )
        group_id = str(payload.get("group") or "general")
        groups = (
            copy.deepcopy(package.get("docsGroups"))
            if isinstance(package.get("docsGroups"), list)
            else []
        )
        group = next(
            (
                row
                for row in groups
                if isinstance(row, dict) and row.get("id") == group_id
            ),
            None,
        )
        if group is None:
            group = {
                "id": group_id,
                "kind": group_id,
                "title": payload.get("group_title") or group_id.replace("-", " ").title(),
                "rationale": payload.get("group_rationale") or "Package documentation",
                "docs": [],
            }
        else:
            group = copy.deepcopy(group)
        docs = (
            copy.deepcopy(group.get("docs"))
            if isinstance(group.get("docs"), list)
            else []
        )
        docs = [
            row
            for row in docs
            if not isinstance(row, dict) or row.get("id") != slug
        ]
        if operation != "delete":
            docs.append(
                {
                    "id": slug,
                    "title": payload.get("title") or slug.replace("-", " ").title(),
                    "tldr": payload.get("tldr") or payload.get("purpose") or "unmeasured",
                    "topics": copy.deepcopy(payload.get("topics") or []),
                    "relatedPages": copy.deepcopy(payload.get("relatedPages") or []),
                    "citedByExperiments": copy.deepcopy(
                        payload.get("citedByExperiments")
                        or payload.get("citedByTasks")
                        or []
                    ),
                    "preview": payload.get("preview") or "",
                    "href": payload.get("path") or f"{slug}.html",
                    "lastUpdated": timestamp,
                }
            )
        group["docs"] = docs
        operations = [
            {"operation": "upsert_by_id", "target": "docsGroups", "value": group}
        ]
        if target == "doc-file":
            notes = (
                copy.deepcopy(package.get("interface_notes"))
                if isinstance(package.get("interface_notes"), dict)
                else {}
            )
            relative = str(payload.get("path") or f"docs/{slug}.html")
            if operation == "delete":
                notes.pop(relative, None)
            else:
                note_ref = payload.get("_note_ref")
                if not isinstance(note_ref, dict):
                    raise CommandRejected(
                        "doc-note-ref-required",
                        "doc-file must be stored as a content-addressed NoteRef",
                    )
                notes[relative] = copy.deepcopy(note_ref)
            operations.append(
                {"operation": "set", "target": "interface_notes", "value": notes}
            )
    elif target == "last-updated-time":
        operations = [
            {"operation": "set", "target": "lastUpdated", "value": timestamp}
        ]
    else:
        raise CommandRejected(
            "package-target-not-facaded",
            f"target {target!r} has no state-backed package facade",
        )
    if target not in {"lastUpdated", "last-updated-time"}:
        operations.append(
            {"operation": "set", "target": "lastUpdated", "value": timestamp}
        )
    return operations


CANONICAL_AGGREGATE_TARGETS = {
    "analysis-insight": "Learning",
    "approval-ack-slot": "Decision",
    "methodsTried": "RunResultFinalized",
    "results-block": "RunResultFinalized",
    "results-gate-row": "RunResultFinalized",
    "tracker-chosen-route": "Decision",
    "tracker-impl-review-row": "Change",
    "tracker-live-check-row": "Run",
    "tracker-resource-allocation-row": "ResourceAllocation",
}


def apply_package_operation(
    paths: ResearchPaths,
    package_id: str,
    *,
    operation: str,
    target: str,
    payload: dict[str, Any],
    actor: dict[str, str] | None = None,
    idempotency_key: str | None = None,
    expected_version: int | None = None,
) -> list[dict[str, Any]]:
    """Apply one package command and refresh the read-only interface."""
    store = EventStore(paths)
    state = store.state()
    canonical_owner = CANONICAL_AGGREGATE_TARGETS.get(target)
    if canonical_owner is not None:
        raise CommandRejected(
            "canonical-aggregate-required",
            f"{target} is a read projection owned by {canonical_owner}; "
            "commit the canonical aggregate instead of mutating Package state",
        )
    if target == "experiments-row":
        _package_policy(
            package_id=package_id,
            operation=operation,
            target=target,
        )(state, {})
        if operation != "insert":
            raise CommandRejected(
                "experiment-scope-proposal-required",
                "Experiment rows are accepted Scope records. Revise, archive, "
                "or supersede Experiment.spec through a Triage proposal; "
                "package operations may only bind an accepted Experiment.",
            )
        aggregate_id, patch = normalize_experiment_binding(package_id, payload)
        experiment_expected_version = _version(
            state, "experiment", aggregate_id
        )

        def validate_binding(
            before: dict[str, Any],
            _command: dict[str, Any],
        ) -> dict[str, Any]:
            package = _package(before, package_id)
            direction_id = package.get("direction_id")
            direction = before["aggregates"]["direction"].get(direction_id)
            if (
                not isinstance(direction, dict)
                or direction.get("status") != "ACTIVE"
                or package.get("sourceVersion") != direction.get("version")
            ):
                raise CommandRejected(
                    "package-direction-stale",
                    "Package must still point to the current ACTIVE Direction "
                    "before another Experiment can be bound.",
                )
            experiment = before["aggregates"]["experiment"].get(aggregate_id)
            if not isinstance(experiment, dict):
                raise CommandRejected(
                    "accepted-experiment-required",
                    f"accepted Experiment not found: {aggregate_id}",
                )
            if experiment.get("direction_id") != direction_id:
                raise CommandRejected(
                    "experiment-direction-mismatch",
                    f"Experiment {aggregate_id} belongs to another Direction",
                )
            if experiment.get("package_id") not in {None, "", package_id}:
                raise CommandConflict(
                    "experiment-already-bound",
                    f"Experiment {aggregate_id} is already bound to "
                    f"{experiment.get('package_id')}",
                )
            if (
                experiment.get("scope_status") != "ACTIVE"
                or experiment.get("scope_confirmation") != "CONFIRMED"
                or experiment.get("confirmed_direction_version")
                != direction.get("version")
            ):
                raise CommandRejected(
                    "experiment-scope-not-executable",
                    f"Experiment {aggregate_id} is inactive or requires "
                    "reconfirmation",
                )
            spec = experiment.get("spec")
            if not isinstance(spec, dict) or set(spec) != {
                "purpose",
                "config_ref",
                "gate",
                "control_mode",
            }:
                raise CommandRejected(
                    "experiment-spec-invalid",
                    f"Experiment {aggregate_id} lacks the canonical "
                    "four-field spec",
                )
            if (
                isinstance(experiment.get("scope_version"), bool)
                or not isinstance(experiment.get("scope_version"), int)
                or experiment["scope_version"] < 1
                or not isinstance(experiment.get("scope_source"), str)
                or not experiment["scope_source"].strip()
            ):
                raise CommandRejected(
                    "experiment-scope-provenance-invalid",
                    f"Experiment {aggregate_id} lacks versioned Scope provenance",
                )
            collisions = [
                other_id
                for other_id, other in before["aggregates"]["experiment"].items()
                if isinstance(other, dict)
                and other_id != aggregate_id
                and other.get("package_id") == package_id
                and other.get("local_id") == patch["local_id"]
            ]
            if collisions:
                raise CommandConflict(
                    "experiment-local-id-conflict",
                    f"local Experiment id is already used: {patch['local_id']}",
                )
            return {
                "id": aggregate_id,
                "version": experiment["scope_version"],
                "source": experiment["scope_source"],
            }

        provenance = validate_binding(state, {})
        package_version = _version(state, "package", package_id)
        selected_key = idempotency_key or (
            f"package:{package_id}:bind:{aggregate_id}:"
            f"{_digest({'patch': patch, 'source': provenance})}"
        )
        prior_binding = next(
            (
                event
                for event in store.events()
                if event["idempotency_key"] == selected_key
            ),
            None,
        )
        candidate_binding_payload = {
            "operation": operation,
            "target": target,
            "operations": [
                {
                    "operation": "upsert_by_id",
                    "target": "sourceExperiments",
                    "value": provenance,
                }
            ],
            "experiment_bindings": [
                {
                    "aggregate_id": aggregate_id,
                    "expected_version": experiment_expected_version,
                    "aggregate_version": experiment_expected_version + 1,
                    "patch": patch,
                }
            ],
        }
        if prior_binding is not None:
            prior_payload = prior_binding.get("payload")
            prior_semantics = {
                "operation": (
                    prior_payload.get("operation")
                    if isinstance(prior_payload, dict)
                    else None
                ),
                "target": (
                    prior_payload.get("target")
                    if isinstance(prior_payload, dict)
                    else None
                ),
                "operations": (
                    prior_payload.get("operations")
                    if isinstance(prior_payload, dict)
                    else None
                ),
                "experiment_bindings": [
                    {
                        "aggregate_id": binding.get("aggregate_id"),
                        "patch": binding.get("patch"),
                    }
                    for binding in (
                        prior_payload.get("experiment_bindings", [])
                        if isinstance(prior_payload, dict)
                        else []
                    )
                    if isinstance(binding, dict)
                ],
            }
            candidate_semantics = {
                "operation": candidate_binding_payload["operation"],
                "target": candidate_binding_payload["target"],
                "operations": candidate_binding_payload["operations"],
                "experiment_bindings": [
                    {
                        "aggregate_id": binding["aggregate_id"],
                        "patch": binding["patch"],
                    }
                    for binding in candidate_binding_payload[
                        "experiment_bindings"
                    ]
                ],
            }
            if (
                prior_binding.get("event_type") != "PackageExperimentBound"
                or prior_binding.get("aggregate_type") != "package"
                or prior_binding.get("aggregate_id") != package_id
                or prior_semantics != candidate_semantics
            ):
                raise CommandConflict(
                    "idempotency-conflict",
                    "idempotency_key was already committed with different "
                    "Package/Experiment binding content",
                )
            binding_payload = copy.deepcopy(prior_payload)
        else:
            binding_payload = candidate_binding_payload

        def atomic_binding_policy(
            before: dict[str, Any],
            command: dict[str, Any],
        ) -> None:
            _package_policy(
                package_id=package_id,
                operation=operation,
                target=target,
            )(before, command)
            validate_binding(before, command)
            if (
                _version(before, "experiment", aggregate_id)
                != experiment_expected_version
            ):
                raise CommandConflict(
                    "experiment-version-conflict",
                    f"Experiment {aggregate_id} changed before Package binding",
                )

        package_event = _commit(
            store,
            event_type="PackageExperimentBound",
            aggregate_type="package",
            aggregate_id=package_id,
            payload=binding_payload,
            actor=_actor(actor),
            idempotency_key=selected_key,
            expected_version=(
                package_version if expected_version is None else expected_version
            ),
            entry_skill="research-op",
            policy=atomic_binding_policy,
        )
        return [package_event]

    if target == "experiments-status":
        _package_policy(
            package_id=package_id,
            operation=operation,
            target=target,
        )(state, {})
        aggregate_id, _ = resolve_package_experiment(
            state,
            package_id,
            payload.get("id"),
        )
        version = _version(state, "experiment", aggregate_id)
        status = _canonical_experiment_status(payload.get("to"))
        event = _commit(store,
            event_type="ExperimentStatusChanged",
            aggregate_type="experiment",
            aggregate_id=aggregate_id,
            payload={"patch": {"status": status}},
            actor=_actor(actor),
            idempotency_key=idempotency_key
            or f"experiment:status:{aggregate_id}:v{version + 1}:{status}",
            expected_version=version,
            entry_skill="research-op",
        )
        return [event]

    prior_mutation = (
        next(
            (
                event
                for event in store.events()
                if event.get("idempotency_key") == idempotency_key
            ),
            None,
        )
        if idempotency_key
        else None
    )
    if prior_mutation is not None:
        prior_payload = prior_mutation.get("payload")
        if (
            prior_mutation.get("event_type") != "PackageMutationApplied"
            or prior_mutation.get("aggregate_type") != "package"
            or prior_mutation.get("aggregate_id") != package_id
            or not isinstance(prior_payload, dict)
            or prior_payload.get("operation") != operation
            or prior_payload.get("target") != target
            or not isinstance(prior_payload.get("operations"), list)
            or prior_payload.get("command_input_digest") != _digest(payload)
        ):
            raise CommandConflict(
                "idempotency-conflict",
                "idempotency_key was already committed for another command",
            )
        return [
            commit_package_mutation(
                paths,
                package_id,
                operation=operation,
                target=target,
                operations=copy.deepcopy(prior_payload["operations"]),
                actor=actor,
                idempotency_key=idempotency_key,
                expected_version=expected_version,
                causation_id=prior_mutation.get("causation_id"),
                command_input_digest=_digest(payload),
            )
        ]

    operations = package_operations_for_target(
        state,
        package_id,
        operation,
        target,
        payload,
    )
    causation_id: str | None = None
    semantic_policy = None
    if operation == "update" and target == "status":
        _, status_authority = _status_command(state, package_id, payload)
        if status_authority is not None:
            causation_event = _latest_aggregate_event(
                store.events(),
                status_authority["aggregate_type"],
                status_authority["aggregate_id"],
                status_authority["aggregate_version"],
            )
            causation_id = str(causation_event["event_id"])

        def validate_status_authority(
            before: dict[str, Any],
            _command: dict[str, Any],
        ) -> None:
            fresh_operations = package_operations_for_target(
                before,
                package_id,
                operation,
                target,
                payload,
            )
            _, fresh_authority = _status_command(
                before,
                package_id,
                payload,
            )
            if fresh_operations != operations:
                raise CommandConflict(
                    "status-command-stale",
                    "Package status inputs changed before commit",
                )
            if fresh_authority != status_authority:
                raise CommandConflict(
                    "status-authority-stale",
                    "referenced status authority changed before commit",
                )

        semantic_policy = validate_status_authority
    return [
        commit_package_mutation(
            paths,
            package_id,
            operation=operation,
            target=target,
            operations=operations,
            actor=actor,
            idempotency_key=idempotency_key,
            expected_version=expected_version,
            causation_id=causation_id,
            semantic_policy=semantic_policy,
            command_input_digest=_digest(payload),
        )
    ]


def commit_evolution_learning(
    paths: ResearchPaths,
    record: dict[str, Any],
    *,
    idempotency_key: str,
    actor: dict[str, str] | None = None,
    expected_version: int | None = None,
) -> dict[str, Any]:
    """Typed gateway for one immutable self-evolve Learning."""
    learning = self_evolve_state.prepare_learning(record)
    learning_id = str(learning["id"])
    store = EventStore(paths)
    state = store.state() if paths.version_file.exists() else None
    version = (
        _version(state, "learning", learning_id)
        if state is not None
        else 0
    )

    def policy(before: dict[str, Any], _command: dict[str, Any]) -> None:
        self_evolve_state.validate_learning_insert(before, learning_id)

    return _commit(store,
        event_type="LearningRecorded",
        aggregate_type="learning",
        aggregate_id=learning_id,
        payload={"record": learning},
        actor=self_evolve_state.actor_record(actor),
        idempotency_key=idempotency_key,
        expected_version=version if expected_version is None else expected_version,
        entry_skill="research-op/self-evolve",
        policy=policy,
    )


def commit_evolution_decision(
    paths: ResearchPaths,
    record: dict[str, Any],
    *,
    idempotency_key: str,
    actor: dict[str, str] | None = None,
    expected_version: int | None = None,
) -> dict[str, Any]:
    """Typed gateway for an oracle, admission, or Rule lifecycle Decision."""
    decision = self_evolve_state.prepare_decision(record, actor=actor)
    decision_id = str(decision["id"])
    store = EventStore(paths)
    state = store.state() if paths.version_file.exists() else None
    version = (
        _version(state, "decision", decision_id)
        if state is not None
        else 0
    )

    def policy(before: dict[str, Any], _command: dict[str, Any]) -> None:
        self_evolve_state.validate_decision_insert(before, decision)

    return _commit(store,
        event_type="DecisionRecorded",
        aggregate_type="decision",
        aggregate_id=decision_id,
        payload={"record": decision},
        actor=self_evolve_state.actor_record(actor),
        idempotency_key=idempotency_key,
        expected_version=version if expected_version is None else expected_version,
        entry_skill="research-op/self-evolve",
        policy=policy,
    )


def commit_evolution_rule_promotion(
    paths: ResearchPaths,
    *,
    learning_id: str,
    decision_id: str,
    rule: dict[str, Any],
    idempotency_key: str,
    actor: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Typed gateway for evidence-backed Learning to Rule promotion."""
    candidate = copy.deepcopy(rule)
    store = EventStore(paths)
    state = store.state()
    aggregate_id, promoted = self_evolve_state.shape_rule_promotion(
        state,
        learning_id=learning_id,
        decision_id=decision_id,
        rule=candidate,
    )
    version = _version(state, "rule", aggregate_id)

    def policy(before: dict[str, Any], _command: dict[str, Any]) -> None:
        self_evolve_state.validate_rule_promotion(
            before,
            learning_id=learning_id,
            decision_id=decision_id,
            rule=candidate,
        )

    return _commit(store,
        event_type="RulePromoted",
        aggregate_type="rule",
        aggregate_id=aggregate_id,
        payload={"record": promoted},
        actor=self_evolve_state.actor_record(actor),
        idempotency_key=idempotency_key,
        expected_version=version,
        causation_id=decision_id,
        entry_skill="research-op/self-evolve",
        policy=policy,
    )


def commit_evolution_rule_retirement(
    paths: ResearchPaths,
    *,
    rule_id: str,
    version: str,
    decision_id: str,
    lifecycle_state: str,
    idempotency_key: str,
    actor: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Typed gateway for retiring one active selfevolve-origin Rule."""
    store = EventStore(paths)
    state = store.state()
    aggregate_id, retired = self_evolve_state.shape_rule_retirement(
        state,
        rule_id=rule_id,
        version=version,
        decision_id=decision_id,
        lifecycle_state=lifecycle_state,
    )
    aggregate_version = _version(state, "rule", aggregate_id)

    def policy(before: dict[str, Any], _command: dict[str, Any]) -> None:
        self_evolve_state.validate_rule_retirement(
            before,
            rule_id=rule_id,
            version=version,
            decision_id=decision_id,
        )

    return _commit(store,
        event_type="RuleRetired",
        aggregate_type="rule",
        aggregate_id=aggregate_id,
        payload={"record": retired},
        actor=self_evolve_state.actor_record(actor),
        idempotency_key=idempotency_key,
        expected_version=aggregate_version,
        causation_id=decision_id,
        entry_skill="research-op/self-evolve",
        policy=policy,
    )


def _decision_evidence(value: Any) -> list[Any]:
    if isinstance(value, list):
        evidence = copy.deepcopy(value)
    elif value not in (None, ""):
        evidence = [{"kind": "REFERENCE", "uri": str(value)}]
    else:
        evidence = []
    return evidence


def _verified_learning_evidence(
    state: dict[str, Any],
    package_id: str,
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    raw_items = payload.get("evidence")
    if raw_items is None:
        raw_items = payload.get("evidence_refs")
    if raw_items is None and payload.get("provenance"):
        raw_items = [payload["provenance"]]
    if not isinstance(raw_items, list) or not raw_items:
        raise CommandRejected(
            "learning-evidence-required",
            "Learning requires a reference to a finalized Run result",
        )
    finalized_runs = {
        str(run_id): run
        for run_id, run in state["aggregates"]["run"].items()
        if isinstance(run, dict)
        and run.get("package_id") == package_id
        and isinstance(run.get("latest_scientific_result"), dict)
        and run.get("result_finalized_event_id")
    }
    verified: list[dict[str, Any]] = []
    for item in raw_items:
        candidate = item if isinstance(item, dict) else {"uri": str(item)}
        requested_run = str(candidate.get("run_id") or "")
        requested_uri = str(candidate.get("uri") or candidate.get("provenance") or "")
        requested_digest = str(candidate.get("result_sha256") or candidate.get("sha256") or "")
        matches: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
        for run_id, run in finalized_runs.items():
            result = run["latest_scientific_result"]
            uris = {
                str(result.get("result_json") or ""),
                *{
                    str(ref.get("uri") or "")
                    for ref in result.get("evidence", [])
                    if isinstance(ref, dict)
                },
            }
            if requested_run and requested_run != run_id:
                continue
            if requested_uri and requested_uri not in uris:
                continue
            if requested_digest and requested_digest not in {
                str(result.get("result_sha256") or ""),
                *{
                    str(ref.get("sha256") or "")
                    for ref in result.get("evidence", [])
                    if isinstance(ref, dict)
                },
            }:
                continue
            matches.append((run_id, run, result))
        if len(matches) != 1:
            raise CommandRejected(
                "learning-evidence-unverified",
                "Learning evidence must resolve to exactly one finalized "
                f"package Run result; got {len(matches)} matches",
            )
        run_id, run, result = matches[0]
        verified.append(
            {
                "kind": "RUN_RESULT",
                "run_id": run_id,
                "experiment_id": run.get("experiment_id"),
                "result_event_id": run.get("result_finalized_event_id"),
                "result_sha256": result.get("result_sha256"),
                "uri": result.get("result_json"),
            }
        )
    return verified


def _verifier_decision_record(
    state: dict[str, Any],
    package_id: str,
    payload: dict[str, Any],
    actor: dict[str, str],
) -> tuple[str, dict[str, Any], str]:
    run_id = str(payload.get("run_id") or "").strip()
    run = state["aggregates"]["run"].get(run_id)
    result = (
        run.get("latest_scientific_result")
        if isinstance(run, dict)
        else None
    )
    if (
        not isinstance(run, dict)
        or run.get("package_id") != package_id
        or not isinstance(result, dict)
        or not run.get("result_finalized_event_id")
    ):
        raise CommandRejected(
            "verifier-result-required",
            "verifier verdict requires a finalized Run result from the package",
        )
    experiment_id = str(run.get("experiment_id") or "")
    experiment = state["aggregates"]["experiment"].get(experiment_id)
    spec = (
        experiment.get("spec")
        if isinstance(experiment, dict)
        and isinstance(experiment.get("spec"), dict)
        else {}
    )
    control_mode = str(spec.get("control_mode") or "")
    verdict = payload.get("verdict")
    if (
        not isinstance(verdict, dict)
        or not all(
            str(verdict.get(field) or "").strip()
            for field in ("producer", "judge", "result")
        )
        or verdict.get("result") not in verifier.VERDICT_STATES
    ):
        raise CommandRejected(
            "verifier-verdict-invalid",
            "verifier verdict requires producer, judge, and a canonical result",
        )
    reason = verifier.assess_acquit(verdict, control_mode)
    if reason:
        raise CommandRejected("verifier-verdict-does-not-acquit", reason)
    decision_id = str(
        payload.get("id")
        or (
            f"{package_id}::verifier::{run_id}::"
            f"{_digest({'event': run['result_finalized_event_id'], 'verdict': verdict})[:12]}"
        )
    )
    evidence = [
        {
            "kind": "RUN_RESULT",
            "run_id": run_id,
            "experiment_id": experiment_id,
            "result_event_id": run["result_finalized_event_id"],
            "result_sha256": result.get("result_sha256"),
            "uri": result.get("result_json"),
        }
    ]
    record = {
        "id": decision_id,
        "package_id": package_id,
        "kind": "VERIFIER_VERDICT",
        "status": "ACCEPTED",
        "run_id": run_id,
        "experiment_id": experiment_id,
        "experiment_scope_version": experiment.get("scope_version"),
        "result_event_id": run["result_finalized_event_id"],
        "result_sha256": result.get("result_sha256"),
        "scientific_verdict": result.get("verdict"),
        "gate": spec.get("gate"),
        "measurements": copy.deepcopy(result.get("measurements")),
        "measured": copy.deepcopy(result.get("measured")),
        "control_mode": control_mode,
        "verdict": copy.deepcopy(verdict),
        "actor": copy.deepcopy(actor),
        "evidence": evidence,
        **(
            {"recorded_at": copy.deepcopy(payload["recorded_at"])}
            if payload.get("recorded_at")
            else {}
        ),
    }
    return decision_id, record, str(run["result_finalized_event_id"])


def commit_verifier_decision(
    paths: ResearchPaths,
    package_id: str,
    payload: dict[str, Any],
    *,
    actor: dict[str, str] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Persist the independent verdict over one exact finalized Run result."""
    store = EventStore(paths)
    state = store.state()
    _package(state, package_id)
    _package_policy(
        package_id=package_id,
        operation="update",
        target="results-verdict",
    )(state, {})
    decision_actor = _actor(actor)
    decision_id, record, causation_id = _verifier_decision_record(
        state,
        package_id,
        payload,
        decision_actor,
    )

    def policy(
        before: dict[str, Any],
        command: dict[str, Any],
    ) -> None:
        _package_policy(
            package_id=package_id,
            operation="update",
            target="results-verdict",
        )(before, command)
        fresh_id, fresh_record, fresh_cause = _verifier_decision_record(
            before,
            package_id,
            payload,
            decision_actor,
        )
        if (
            fresh_id != decision_id
            or fresh_record != record
            or fresh_cause != causation_id
        ):
            raise CommandConflict(
                "verifier-result-stale",
                "Run result or Experiment gate changed before verdict commit",
            )

    return _commit(
        store,
        event_type="DecisionRecorded",
        aggregate_type="decision",
        aggregate_id=decision_id,
        payload={"record": record},
        actor=decision_actor,
        idempotency_key=idempotency_key
        or f"verifier:{decision_id}:{_digest(record)}",
        expected_version=0,
        causation_id=causation_id,
        entry_skill="research-op",
        policy=policy,
    )


def commit_decision(
    paths: ResearchPaths,
    package_id: str,
    payload: dict[str, Any],
    *,
    actor: dict[str, str] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Record a chosen route as a Decision aggregate."""
    store = EventStore(paths)
    state = store.state()
    _package(state, package_id)
    _package_policy(
        package_id=package_id,
        operation="insert",
        target="tracker-chosen-route",
    )(state, {})
    route = str(payload.get("route") or payload.get("nextRoute") or "")
    if not route:
        raise CommandRejected(
            "decision-route-required",
            "chosen route requires route",
        )
    decision_id = str(
        payload.get("id")
        or f"{package_id}::decision::{_digest(payload)[:16]}"
    )
    record = {
        **copy.deepcopy(payload),
        "id": decision_id,
        "package_id": package_id,
        "route": route,
        "actor": copy.deepcopy(_actor(actor)),
        "evidence": _decision_evidence(payload.get("evidence")),
        **(
            {"recorded_at": copy.deepcopy(payload["recorded_at"])}
            if payload.get("recorded_at")
            else {}
        ),
    }
    if not record["evidence"]:
        raise CommandRejected(
            "decision-evidence-required",
            "chosen route requires evidence",
        )
    return _commit(store,
        event_type="DecisionRecorded",
        aggregate_type="decision",
        aggregate_id=decision_id,
        payload={"record": record},
        actor=record["actor"],
        idempotency_key=idempotency_key
        or f"decision:{decision_id}:{_digest(payload)}",
        expected_version=0,
        entry_skill="research-op",
    )


def commit_acknowledgement(
    paths: ResearchPaths,
    package_id: str,
    payload: dict[str, Any],
    *,
    actor: dict[str, str] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Record one explicit acknowledgement as a Decision aggregate."""
    ack_type = str(payload.get("ack_type") or "").strip()
    launch_ack_types = {"LAUNCH_ACK", "READY_TO_LAUNCH_ACK"}
    user_ack_types = {
        *launch_ack_types,
        "TERMINAL_ACK",
        "PACKAGE_TRANSITION_ACK",
    }
    canonical_ack_type = ack_type.upper()
    is_launch_ack = canonical_ack_type in launch_ack_types
    is_user_ack = canonical_ack_type in user_ack_types
    if is_user_ack:
        ack_type = canonical_ack_type
    value = payload.get("to", payload.get("value"))
    if not ack_type or value in (None, ""):
        raise CommandRejected(
            "ack-fields-required",
            "acknowledgement requires ack_type and value/to",
        )
    store = EventStore(paths)
    state = store.state()
    _package(state, package_id)
    _package_policy(
        package_id=package_id,
        operation="update",
        target="approval-ack-slot",
    )(state, {})
    experiment_id: str | None = None
    experiment_ref = payload.get("experiment_id", payload.get("exp_id"))
    if is_launch_ack and experiment_ref not in (None, ""):
        experiment_id, _ = resolve_package_experiment(
            state,
            package_id,
            experiment_ref,
        )
    # Missing identity is never promoted to a user. Protected lifecycle
    # acknowledgements therefore require an explicit caller actor.
    decision_actor = _actor(actor)
    if is_user_ack and decision_actor.get("type") != "user":
        raise CommandRejected(
            (
                "launch-ack-user-required"
                if is_launch_ack
                else "protected-ack-user-required"
            ),
            f"{ack_type} must be recorded by a user actor",
        )
    if is_user_ack and str(value).upper() not in {
        "ACKNOWLEDGED",
        "ACCEPTED",
    }:
        raise CommandRejected(
            (
                "launch-ack-value-invalid"
                if is_launch_ack
                else "protected-ack-value-invalid"
            ),
            f"{ack_type} value/to must be ACKNOWLEDGED or ACCEPTED",
        )
    target_status = str(payload.get("target_status") or "").strip()
    if ack_type == "TERMINAL_ACK" and target_status not in TERMINAL_PACKAGE_STATUSES:
        raise CommandRejected(
            "terminal-ack-target-invalid",
            "TERMINAL_ACK requires a canonical terminal target_status",
        )
    all_package_statuses = {
        status
        for statuses in state_policy.STATES.values()
        for status in statuses
    }
    if (
        ack_type == "PACKAGE_TRANSITION_ACK"
        and target_status not in all_package_statuses
    ):
        raise CommandRejected(
            "transition-ack-target-invalid",
            "PACKAGE_TRANSITION_ACK requires a canonical target_status",
        )
    decision_value = (
        {"value": value, "experiment_id": experiment_id}
        if is_launch_ack
        else {"value": value, "target_status": target_status}
        if is_user_ack
        else value
    )
    decision_id = str(
        payload.get("id")
        or f"{package_id}::ack::{ack_type}::{_digest(decision_value)[:12]}"
    )
    evidence = _decision_evidence(payload.get("evidence"))
    if not evidence:
        evidence = [
            {
                "kind": "ACTOR_ATTESTATION",
                "actor": copy.deepcopy(decision_actor),
                "ack_type": ack_type,
                "value": copy.deepcopy(value),
            }
        ]
    record = {
        "id": decision_id,
        "package_id": package_id,
        "kind": ack_type if is_user_ack else "ACKNOWLEDGEMENT",
        "ack_type": ack_type,
        "value": copy.deepcopy(value),
        "page": payload.get("page"),
        "evidence": evidence,
        "actor": copy.deepcopy(decision_actor),
        "status": "ACKNOWLEDGED",
        **(
            {"recorded_at": copy.deepcopy(payload["recorded_at"])}
            if payload.get("recorded_at")
            else {}
        ),
    }
    if experiment_id is not None:
        record["experiment_id"] = experiment_id
    if target_status:
        record["target_status"] = target_status
    return _commit(store,
        event_type="DecisionRecorded",
        aggregate_type="decision",
        aggregate_id=decision_id,
        payload={"record": record},
        actor=decision_actor,
        idempotency_key=idempotency_key
        or f"ack:{decision_id}:{_digest(decision_value)}",
        expected_version=0,
        entry_skill="research-op",
    )


def commit_learning_operation(
    paths: ResearchPaths,
    package_id: str,
    operation: str,
    payload: dict[str, Any],
    *,
    actor: dict[str, str] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Record the management identity behind a rendered analysis insight."""
    insight_id = str(payload.get("id") or payload.get("slug") or "")
    if not insight_id:
        raise CommandRejected(
            "learning-id-required",
            "analysis insight requires id or slug",
        )
    aggregate_id = f"{package_id}::learning::{insight_id}"
    store = EventStore(paths)
    state = store.state()
    _package(state, package_id)
    _package_policy(
        package_id=package_id,
        operation=operation,
        target="analysis-insight",
    )(state, {})
    current = state["aggregates"]["learning"].get(aggregate_id)
    if operation == "delete":
        if not isinstance(current, dict):
            raise CommandRejected(
                "learning-not-found",
                f"unknown learning: {aggregate_id}",
            )
        return _commit(store,
            event_type="AggregateRemoved",
            aggregate_type="learning",
            aggregate_id=aggregate_id,
            payload={"reason": payload.get("reason", "analysis correction")},
            actor=_actor(actor),
            idempotency_key=idempotency_key
            or f"learning:remove:{aggregate_id}",
            expected_version=_version(state, "learning", aggregate_id),
            entry_skill="research-analysis",
        )
    record = {
        **copy.deepcopy(current or {}),
        **copy.deepcopy(payload),
        "id": aggregate_id,
        "local_id": insight_id,
        "package_id": package_id,
        "kind": "insight",
        "status": "ACTIVE",
        "evidence": _verified_learning_evidence(state, package_id, payload),
        **(
            {"recorded_at": copy.deepcopy(payload["recorded_at"])}
            if payload.get("recorded_at")
            else {}
        ),
    }
    if not payload.get("recorded_at"):
        record.pop("recorded_at", None)
    if not str(record.get("title") or "").strip():
        raise CommandRejected(
            "learning-title-required",
            "analysis insight requires title",
        )
    record["provenance"] = record["evidence"][0]["uri"]
    version = _version(state, "learning", aggregate_id)
    return _commit(store,
        event_type="LearningRecorded",
        aggregate_type="learning",
        aggregate_id=aggregate_id,
        payload={"record": record},
        actor=_actor(actor),
        idempotency_key=idempotency_key
        or f"learning:{operation}:{aggregate_id}:v{version + 1}:{_digest(record)}",
        expected_version=version,
        entry_skill="research-analysis",
    )


def commit_change_operation(
    paths: ResearchPaths,
    package_id: str,
    operation: str,
    payload: dict[str, Any],
    *,
    actor: dict[str, str] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Record an implementation/review change independently of its UI row."""
    local_id = str(payload.get("id") or payload.get("change_id") or "")
    if not local_id:
        raise CommandRejected(
            "change-id-required",
            "implementation review requires change_id",
        )
    change_aggregate_id = f"{package_id}::change::{local_id}"
    store = EventStore(paths)
    state = store.state()
    _package(state, package_id)
    _package_policy(
        package_id=package_id,
        operation=operation,
        target="tracker-impl-review-row",
    )(state, {})
    current = state["aggregates"]["change"].get(change_aggregate_id)
    if operation == "delete":
        if not isinstance(current, dict):
            raise CommandRejected(
                "change-not-found",
                f"unknown change: {change_aggregate_id}",
            )
        return _commit(store,
            event_type="AggregateRemoved",
            aggregate_type="change",
            aggregate_id=change_aggregate_id,
            payload={"reason": payload.get("reason", "pre-review correction")},
            actor=_actor(actor),
            idempotency_key=idempotency_key
            or f"change:remove:{change_aggregate_id}",
            expected_version=_version(state, "change", change_aggregate_id),
            entry_skill="research-op",
        )
    record = {
        **copy.deepcopy(current or {}),
        **copy.deepcopy(payload),
        "id": change_aggregate_id,
        "local_id": local_id,
        "package_id": package_id,
        "status": payload.get("status") or "RECORDED",
        **(
            {"recorded_at": copy.deepcopy(payload["recorded_at"])}
            if payload.get("recorded_at")
            else {}
        ),
    }
    if not payload.get("recorded_at"):
        record.pop("recorded_at", None)
    owned_files = record.get("owned_files", record.get("ownedFiles"))
    if not isinstance(owned_files, list) or not owned_files or not all(
        isinstance(path, str) and path.strip() for path in owned_files
    ):
        raise CommandRejected(
            "change-owned-files-required",
            "Change requires a non-empty owned_files list",
        )
    record["owned_files"] = list(dict.fromkeys(owned_files))
    review = record.get("review")
    if not isinstance(review, dict):
        summary = str(record.get("summary") or "").strip()
        status = str(record.get("status") or "").strip()
        review = {"status": status, "summary": summary}
    if not any(str(value or "").strip() for value in review.values()):
        raise CommandRejected(
            "change-review-required",
            "Change requires a non-empty review record",
        )
    record["review"] = copy.deepcopy(review)
    validating = record.get(
        "validating_experiments",
        record.get("validatingExperiments"),
    )
    if not isinstance(validating, list) or not validating:
        raise CommandRejected(
            "change-validating-experiments-required",
            "Change requires one or more validating_experiments",
        )
    canonical_validating = []
    for reference in validating:
        experiment_id, _ = resolve_package_experiment(
            state,
            package_id,
            reference,
        )
        canonical_validating.append(experiment_id)
    record["validating_experiments"] = list(
        dict.fromkeys(canonical_validating)
    )
    version = _version(state, "change", change_aggregate_id)
    return _commit(store,
        event_type="AggregateUpserted",
        aggregate_type="change",
        aggregate_id=change_aggregate_id,
        payload={"record": record},
        actor=_actor(actor),
        idempotency_key=idempotency_key
        or (
            f"change:{operation}:{change_aggregate_id}:v{version + 1}:"
            f"{_digest(record)}"
        ),
        expected_version=version,
        entry_skill="research-op",
    )


def commit_rule_operation(
    paths: ResearchPaths,
    package_id: str,
    operation: str,
    payload: dict[str, Any],
    *,
    actor: dict[str, str] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Manage package/project rules as state aggregates, never rules.js."""
    store = EventStore(paths)
    state = store.state()
    level = str(payload.get("level") or ("project" if package_id == "_project" else "package"))
    if level == "universal":
        raise CommandRejected(
            "rule-universal-writelock",
            "universal rules are bundled and write-locked",
        )
    if level not in {"package", "project"}:
        raise CommandRejected("rule-level-invalid", f"unknown rule level: {level}")
    expected_kind = rule_kind_for_level(level)
    assert expected_kind is not None
    requested_kind = str(payload.get("kind") or expected_kind)
    if requested_kind != expected_kind:
        raise CommandRejected(
            "rule-kind-scope-mismatch",
            f"{level} rules require kind={expected_kind}",
        )
    if payload.get("origin") == "selfevolve":
        raise CommandRejected(
            "rule-origin-reserved",
            "selfevolve-origin Rules are managed only by the evidence-backed "
            "Learning promotion/retirement use case",
        )
    if level == "project" and not str(payload.get("ack") or "").strip():
        raise CommandRejected(
            "rule-project-needs-ack",
            "project rule mutations require payload.ack",
        )
    if level == "package":
        _package(state, package_id)
        _package_policy(
            package_id=package_id,
            operation=operation,
            target="rule",
        )(state, {})
    slug = str(payload.get("slug") or "")
    rule_id = str(
        payload.get("id")
        or (
            f"{package_id}#{slug}"
            if level == "package"
            else f"PRJ-{slug}"
        )
    )
    current = state["aggregates"]["rule"].get(rule_id)
    if operation == "insert":
        for field in ("slug", "title", "text", "rationale", "addedAt"):
            if not str(payload.get(field) or "").strip():
                raise CommandRejected(
                    "rule-required-fields",
                    f"rule is missing {field}",
                )
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
            raise CommandRejected(
                "rule-slug-invalid",
                "rule slug must be kebab-case",
            )
        if current is not None:
            raise CommandConflict("rule-create-exists", f"rule already exists: {rule_id}")
        record = {
            **copy.deepcopy(payload),
            "id": rule_id,
            "level": level,
            "kind": expected_kind,
            "package_id": package_id if level == "package" else None,
            "pkg": package_id if level == "package" else None,
            "status": "ACTIVE",
        }
        event_type = "AggregateUpserted"
        event_payload = {"record": record}
        expected = 0
    else:
        if not isinstance(current, dict):
            raise CommandRejected("rule-not-found", f"unknown rule: {rule_id}")
        if current.get("origin") == "selfevolve":
            raise CommandRejected(
                "rule-origin-retire-only",
                "selfevolve-origin Rules can only be retired by an evidence-backed "
                "self-evolve Decision",
            )
        if operation == "delete":
            if level != "package":
                raise CommandRejected(
                    "rule-no-hard-delete",
                    "project rules retire; they are not hard-deleted",
                )
            return _commit(store,
                event_type="AggregateRemoved",
                aggregate_type="rule",
                aggregate_id=rule_id,
                payload={"reason": payload.get("reason", "pre-launch correction")},
                actor=_actor(actor),
                idempotency_key=idempotency_key or f"rule:remove:{rule_id}",
                expected_version=_version(state, "rule", rule_id),
                entry_skill="research-op",
            )
        record = {**copy.deepcopy(current), **copy.deepcopy(payload), "id": rule_id}
        desired = str(record.get("status") or current.get("status") or "ACTIVE")
        if desired == "RETIRED":
            if not str(record.get("retireReason") or "").strip():
                raise CommandRejected(
                    "rule-retire-reason-required",
                    "retiring a rule requires retireReason",
                )
            event_type = "RuleRetired"
        elif desired == "PROMOTED":
            raise CommandRejected(
                "rule-promotion-learning-required",
                "Rule promotion requires the evidence-backed Learning promotion use case",
            )
        else:
            event_type = "AggregateUpserted"
        event_payload = {"record": record}
        expected = _version(state, "rule", rule_id)
    return _commit(store,
        event_type=event_type,
        aggregate_type="rule",
        aggregate_id=rule_id,
        payload=event_payload,
        actor=_actor(actor),
        idempotency_key=idempotency_key
        or f"rule:{operation}:{rule_id}:v{expected + 1}:{_digest(record)}",
        expected_version=expected,
        entry_skill="research-op",
    )


# Public management commands may reject while normalizing or validating their
# input, before they reach EventStore.commit.  Wrap only write façades; read
# models and internal helpers remain side-effect free.
for _audited_command_name in (
    "write_note",
    "authorize_run",
    "link_run_allocation",
    "record_run_launched",
    "record_run_launch_failed",
    "record_run_terminal",
    "record_run_result_finalized",
    "create_brainstorm",
    "revise_brainstorm",
    "archive_brainstorm",
    "discard_brainstorm",
    "update_campaign",
    "register_resource",
    "update_resource_allocation",
    "submit_proposal",
    "dispose_proposal",
    "commit_scope_transition",
    "commit_registry_add",
    "propagate_run_result",
    "commit_package_create",
    "commit_package_mutation",
    "commit_package_pages",
    "apply_package_operation",
    "commit_evolution_learning",
    "commit_evolution_decision",
    "commit_evolution_rule_promotion",
    "commit_evolution_rule_retirement",
    "commit_verifier_decision",
    "commit_decision",
    "commit_acknowledgement",
    "commit_learning_operation",
    "commit_change_operation",
    "commit_rule_operation",
):
    globals()[_audited_command_name] = _audit_precommit_rejections(
        globals()[_audited_command_name]
    )
