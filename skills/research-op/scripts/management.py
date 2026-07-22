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
    ResearchPaths,
    approval_receipt,
    build_transaction_payload,
    commit_transaction as commit_semantic_transaction,
    review_digest,
    resolve_bound_experiment,
)
from lib.research_state.io import canonical_json
from lib.research_state import lifecycle as lifecycle_policy
from lib.research_state.package_identity import (
    PackageIdentityViolation,
    package_id as canonical_package_id,
    renamed_record,
    validate_identity_date,
    validate_title,
)
from lib.research_state.reducer import fold
from lib.research_state import policy as state_policy
from lib.research_state.schema import (
    compatibility_map,
    enum,
    require_enum,
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
PACKAGE_LOCAL_EXPERIMENT_FIELDS = {
    "after",
    "complex",
    "docsAnchor",
    "label",
    "local_id",
    "measures",
    "output",
    "requiresCode",
    "resultSchema",
    "resultSchemaRef",
    "runLink",
}
PACKAGE_RESULT_FIELDS = {
    "analysisInsights",
    "methodsTried",
    "resultBlocks",
    "resultGateRows",
}


def _commit(store: EventStore, /, **command: Any) -> dict[str, Any]:
    """Commit canonical state and leave the rebuildable interface lazy."""
    event = EventStore.commit(store, **command)
    receipt = copy.deepcopy(event)
    receipt["_interface_projection"] = {
        "written": False,
        "stale": True,
        "root": str(store.paths.interface),
        "source_seq": event["seq"],
        "source_hash": event["hash"],
    }
    return receipt


def _transaction_receipt(
    paths: ResearchPaths,
    event: dict[str, Any],
) -> dict[str, Any]:
    receipt = copy.deepcopy(event)
    receipt["_interface_projection"] = {
        "written": False,
        "stale": True,
        "root": str(paths.interface),
        "source_seq": event["seq"],
        "source_hash": event["hash"],
    }
    return receipt


def _commit_transaction(
    paths: ResearchPaths,
    *,
    payload: dict[str, Any],
    actor: dict[str, str],
    idempotency_key: str,
    entry_skill: str,
    event_id: str | None = None,
) -> dict[str, Any]:
    event = commit_semantic_transaction(
        paths,
        payload=payload,
        actor=actor,
        idempotency_key=idempotency_key,
        entry_skill=entry_skill,
        event_id=event_id,
    )
    return _transaction_receipt(paths, event)


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


_DRAFT_SOURCE_FIELDS = {"id", "draft_revision", "document_sha256"}


def _draft_source_binding(record: dict[str, Any]) -> dict[str, Any]:
    note = record.get("document_note")
    if not isinstance(note, dict):
        raise CommandRejected(
            "draft-package-document-required",
            "Draft Package requires a content-addressed proposal document",
        )
    return {
        "id": str(record.get("id") or ""),
        "draft_revision": int(record.get("draftRevision") or 0),
        "document_sha256": str(note.get("sha256") or ""),
    }


def _validate_draft_package_record(paths: ResearchPaths, record: dict[str, Any]) -> None:
    package_id = record.get("id")
    if not isinstance(package_id, str) or not package_id.strip():
        raise CommandRejected("draft-package-id-required", "Draft Package requires id")
    if (
        record.get("lifecycle") != "DRAFT"
        or record.get("phase") is not None
        or record.get("blocker") is not None
    ):
        raise CommandRejected(
            "draft-package-state-invalid",
            "Draft Package must use lifecycle=DRAFT with no execution phase or blocker",
        )
    require_enum("package_draft_status", record.get("draftStatus"))
    revision = record.get("draftRevision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise CommandRejected(
            "draft-package-revision-invalid",
            "Draft Package draftRevision must be a positive integer",
        )
    if record.get("executionAuthorized") is not False:
        raise CommandRejected(
            "draft-package-execution-forbidden",
            "Draft Package must set executionAuthorized=false",
        )
    if record.get("direction_id") is not None:
        raise CommandRejected(
            "draft-package-direction-forbidden",
            "Draft Package cannot bind a Direction before Scope ratification",
        )
    if record.get("sourceVersion") is not None or record.get("sourceChange") is not None:
        raise CommandRejected(
            "draft-package-scope-source-forbidden",
            "Draft Package cannot carry committed Scope provenance",
        )
    if record.get("sourceExperiments") != [] or record.get("scopeBinding") is not None:
        raise CommandRejected(
            "draft-package-scope-binding-forbidden",
            "Draft Package cannot bind Experiments or Scope before activation",
        )
    document_path = record.get("documentPath")
    if document_path != "docs/proposal.html":
        raise CommandRejected(
            "draft-package-document-path-invalid",
            "Draft Package proposal document must use docs/proposal.html",
        )
    _validate_note_ref(paths, record.get("document_note"))


def _validate_source_package_binding(
    state: dict[str, Any],
    binding: Any,
    *,
    require_scope_ready: bool = True,
) -> dict[str, Any]:
    if not isinstance(binding, dict) or set(binding) != _DRAFT_SOURCE_FIELDS:
        raise CommandRejected(
            "scope-source-package-invalid",
            "source_package must contain exactly id, draft_revision, and document_sha256",
        )
    package_id = binding.get("id")
    package = state["aggregates"]["package"].get(package_id)
    if not isinstance(package, dict) or package.get("lifecycle") != "DRAFT":
        raise CommandRejected(
            "scope-draft-package-required",
            f"Scope proposal requires an existing Draft Package: {package_id}",
        )
    current = _draft_source_binding(package)
    if current != binding:
        raise CommandConflict(
            "scope-draft-package-stale",
            f"Draft Package {package_id} changed after the visible Scope review",
        )
    if require_scope_ready and package.get("draftStatus") not in {
        "SCOPE_READY",
        "SCOPE_REVIEW",
    }:
        raise CommandRejected(
            "scope-draft-package-not-ready",
            f"Draft Package {package_id} must be SCOPE_READY before Scope proposal",
        )
    return package


def create_draft_package(
    paths: ResearchPaths,
    package_id: str,
    record: dict[str, Any],
    brainstorm_consumptions: list[dict[str, Any]] | None = None,
    *,
    actor: dict[str, str],
    idempotency_key: str,
) -> dict[str, Any]:
    """Create a non-executable Draft Package from one exact Brainstorm revision."""
    candidate = copy.deepcopy(record)
    consumptions = copy.deepcopy(list(brainstorm_consumptions or []))
    if candidate.get("id") != package_id:
        raise CommandRejected(
            "draft-package-id-mismatch",
            "Draft Package record id must equal aggregate id",
        )
    _validate_draft_package_record(paths, candidate)
    if len(consumptions) != 1:
        raise CommandRejected(
            "brainstorm-conversion-source-count",
            "normal Draft Package conversion materializes exactly one Brainstorm",
        )
    store = EventStore(paths)
    state = store.state()
    _validate_brainstorm_consumptions(state, candidate, consumptions)
    consumption = consumptions[0]
    brainstorm_id = str(consumption["aggregate_id"])
    brainstorm = copy.deepcopy(state["aggregates"]["brainstorm"][brainstorm_id])
    brainstorm.update(
        {
            "status": "MATERIALIZED",
            "materialized_as": package_id,
        }
    )
    brainstorm_version = _version(state, "brainstorm", brainstorm_id)
    payload = build_transaction_payload(
        command_kind="DRAFT_MATERIALIZE",
        owner_type="package",
        owner_id=package_id,
        participants=[
            {
                "aggregate_type": "package",
                "aggregate_id": package_id,
                "expected_version": _version(state, "package", package_id),
                "aggregate_version": _version(state, "package", package_id) + 1,
                "operation": "put",
                "record": candidate,
            },
            {
                "aggregate_type": "brainstorm",
                "aggregate_id": brainstorm_id,
                "expected_version": brainstorm_version,
                "aggregate_version": brainstorm_version + 1,
                "operation": "put",
                "record": brainstorm,
            },
        ],
        evidence=[
            {
                "kind": "brainstorm-document",
                "uri": consumption["document_note"].get("uri"),
                "sha256": consumption["document_note"].get("sha256"),
            }
        ],
    )
    return _commit_transaction(
        paths,
        payload=payload,
        actor=actor,
        idempotency_key=idempotency_key,
        entry_skill="research-package",
    )


def revise_draft_package(
    paths: ResearchPaths,
    package_id: str,
    patch: dict[str, Any],
    *,
    expected_version: int,
    actor: dict[str, str],
    idempotency_key: str,
) -> dict[str, Any]:
    """Revise Draft Package content without creating executable authority."""
    candidate_patch = copy.deepcopy(patch)
    forbidden = {
        "id",
        "lifecycle",
        "phase",
        "blocker",
        "direction_id",
        "sourceVersion",
        "sourceChange",
        "sourceExperiments",
        "scopeBinding",
        "executionAuthorized",
    }
    illegal = sorted(forbidden.intersection(candidate_patch))
    if illegal:
        raise CommandRejected(
            "draft-package-revision-forbidden",
            f"Draft Package revision cannot change {illegal}",
        )
    state = EventStore(paths).state()
    current = state["aggregates"]["package"].get(package_id)
    if not isinstance(current, dict) or current.get("lifecycle") != "DRAFT":
        raise CommandRejected(
            "draft-package-required",
            f"unknown Draft Package: {package_id}",
        )
    if current.get("draftStatus") == "ARCHIVED_DRAFT":
        raise CommandRejected(
            "draft-package-archived",
            f"cannot revise archived Draft Package: {package_id}",
        )
    current_version = _version(state, "package", package_id)
    if expected_version != current_version:
        raise CommandConflict(
            "draft-package-version-conflict",
            f"expected Package version {expected_version}, current version is {current_version}",
        )
    if candidate_patch.get("draftRevision") != current.get("draftRevision", 0) + 1:
        raise CommandConflict(
            "draft-package-revision-conflict",
            "every Draft Package refinement must advance draftRevision by one",
        )
    projected = copy.deepcopy(current)
    projected.update(copy.deepcopy(candidate_patch))
    _validate_draft_package_record(paths, projected)
    payload = build_transaction_payload(
        command_kind="DRAFT_REVISE",
        owner_type="package",
        owner_id=package_id,
        participants=[
            {
                "aggregate_type": "package",
                "aggregate_id": package_id,
                "expected_version": current_version,
                "aggregate_version": current_version + 1,
                "operation": "put",
                "record": projected,
            }
        ],
    )
    return _commit_transaction(
        paths,
        payload=payload,
        actor=actor,
        idempotency_key=idempotency_key,
        entry_skill="research-package",
    )


def archive_draft_package(
    paths: ResearchPaths,
    package_id: str,
    patch: dict[str, Any],
    *,
    expected_version: int,
    actor: dict[str, str],
    idempotency_key: str,
) -> dict[str, Any]:
    """Archive one abandoned Draft Package while retaining its event history."""
    candidate_patch = copy.deepcopy(patch)
    forbidden = {
        "id",
        "lifecycle",
        "phase",
        "blocker",
        "direction_id",
        "sourceVersion",
        "sourceChange",
        "sourceExperiments",
        "scopeBinding",
        "executionAuthorized",
        "documentPath",
        "document_note",
    }
    illegal = sorted(forbidden.intersection(candidate_patch))
    if illegal:
        raise CommandRejected(
            "draft-package-archive-forbidden",
            f"Draft Package archive cannot change {illegal}",
        )
    store = EventStore(paths)

    def policy(state: dict[str, Any], _command: dict[str, Any]) -> None:
        current = state["aggregates"]["package"].get(package_id)
        if not isinstance(current, dict) or current.get("lifecycle") != "DRAFT":
            raise CommandRejected(
                "draft-package-required",
                f"unknown Draft Package: {package_id}",
            )
        if candidate_patch.get("draftRevision") != current.get("draftRevision", 0) + 1:
            raise CommandConflict(
                "draft-package-revision-conflict",
                "archiving a Draft Package must advance draftRevision by one",
            )
        projected = copy.deepcopy(current)
        projected.update(candidate_patch)
        projected["draftStatus"] = "ARCHIVED_DRAFT"
        _validate_draft_package_record(paths, projected)

    return _commit(
        store,
        event_type="PackageDraftArchived",
        aggregate_type="package",
        aggregate_id=package_id,
        payload={"patch": candidate_patch},
        actor=actor,
        idempotency_key=idempotency_key,
        expected_version=expected_version,
        entry_skill="research-package",
        policy=policy,
    )


def _reopen_proposal_source(
    package: dict[str, Any],
    source_document: str | None,
) -> dict[str, Any]:
    direct_note = package.get("document_note")
    direct_path = package.get("documentPath")
    if isinstance(direct_note, dict) and isinstance(direct_path, str):
        if source_document in {None, "", direct_path, "proposal"}:
            return {
                **copy.deepcopy(package),
                "documentPath": direct_path,
                "document_note": copy.deepcopy(direct_note),
            }

    sources = package.get("sourceBrainstorms")
    notes = package.get("interface_notes")
    candidates: list[dict[str, Any]] = []
    if isinstance(sources, list) and isinstance(notes, dict):
        for raw in sources:
            if not isinstance(raw, dict):
                continue
            path = raw.get("documentPath")
            note = raw.get("document_note")
            if (
                isinstance(path, str)
                and isinstance(note, dict)
                and notes.get(path) == note
            ):
                candidates.append(copy.deepcopy(raw))
    if source_document:
        candidates = [
            row
            for row in candidates
            if source_document in {row.get("id"), row.get("documentPath")}
        ]
    if len(candidates) != 1:
        raise CommandRejected(
            "package-reopen-proposal-ambiguous",
            "Package reopen requires exactly one owned proposal document; "
            "select it explicitly when multiple source proposals exist",
        )
    return candidates[0]


def _draft_record_from_active_package(
    package: dict[str, Any],
    source: dict[str, Any],
    *,
    reason: str,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    title = str(source.get("title") or package.get("name") or package["id"])
    idea = str(
        source.get("idea")
        or package.get("problem")
        or package.get("objective")
        or title
    )
    abstract = str(
        source.get("abstract") or package.get("motivation") or idea
    )
    prior_revision = package.get("draftRevision")
    revision = (
        int(prior_revision) + 1
        if isinstance(prior_revision, int) and not isinstance(prior_revision, bool)
        else 1
    )
    draft = {
        "id": package["id"],
        "slug": package.get("slug") or package["id"],
        "name": package.get("name") or title,
        "title": title,
        "idea": idea,
        "abstract": abstract,
        "created_at": source.get("created_at") or package.get("lastUpdated") or now,
        "updated_at": now,
        "page_language": source.get("page_language") or "en",
        "tag": "brainstorm",
        "lifecycle": "DRAFT",
        "phase": None,
        "blocker": None,
        "draftStatus": "REFINING",
        "draftRevision": revision,
        "executionAuthorized": False,
        "direction_id": None,
        "sourceVersion": None,
        "sourceChange": None,
        "sourceExperiments": [],
        "scopeBinding": None,
        "documentPath": "docs/proposal.html",
        "document_note": copy.deepcopy(source["document_note"]),
        "pages": ["overview", "plan", "experiments", "results", "docs"],
        "detailPath": f"packages/{package['id']}/docs/proposal.html",
        "reopen_reason": reason,
    }
    for field in ("idea_snapshot", "lit_refs"):
        if field in source:
            draft[field] = copy.deepcopy(source[field])
    return draft


def _detached_experiment_record(experiment: dict[str, Any]) -> dict[str, Any]:
    record = copy.deepcopy(experiment)
    for field in PACKAGE_LOCAL_EXPERIMENT_FIELDS:
        record.pop(field, None)
    prior_status = record.get("status")
    if prior_status == "BLOCKED":
        prior_status = record.get("status_before_scope_stale") or "PLANNED"
    record["package_id"] = None
    record["status_before_scope_stale"] = prior_status
    record["status"] = "BLOCKED"
    record["scope_confirmation"] = "STALE"
    if isinstance(record.get("confirmed_direction_version"), int):
        record["stale_direction_version"] = record["confirmed_direction_version"]
    return record


def _validate_package_reopen_state(
    state: dict[str, Any],
    package_id: str,
) -> tuple[dict[str, Any], list[tuple[str, dict[str, Any]]]]:
    package = state["aggregates"]["package"].get(package_id)
    if not isinstance(package, dict) or package.get("lifecycle") != "ACTIVE":
        raise CommandRejected(
            "package-active-required",
            f"Package reopen requires an ACTIVE Package: {package_id}",
        )
    if package.get("phase") not in {
        "CONTEXT_LOADED",
        "IMPLEMENTING",
        "IMPLEMENTATION_REVIEW",
        "READY_TO_LAUNCH",
    }:
        raise CommandRejected(
            "package-reopen-prelaunch-only",
            "Only a pre-launch ACTIVE Package may reopen as Draft",
        )
    if package.get("blocker") is not None:
        raise CommandRejected(
            "package-reopen-blocker-present",
            "Resolve the Package blocker before reopening it as Draft",
        )
    run_records = [
        str(run_id)
        for run_id, run in state["aggregates"]["run"].items()
        if isinstance(run, dict) and run.get("package_id") == package_id
    ]
    open_runs = [
        str(run_id)
        for run_id, run in state["open_runs"].items()
        if isinstance(run, dict) and run.get("package_id") == package_id
    ]
    if run_records or open_runs:
        raise CommandRejected(
            "package-reopen-run-history-forbidden",
            "A Package with Run history cannot be rewritten as a pre-execution Draft",
        )
    populated_results = [field for field in PACKAGE_RESULT_FIELDS if package.get(field)]
    if populated_results:
        raise CommandRejected(
            "package-reopen-results-forbidden",
            "A Package with recorded results cannot reopen as a pre-execution Draft: "
            + ", ".join(sorted(populated_results)),
        )
    bound = sorted(
        (
            (str(experiment_id), experiment)
            for experiment_id, experiment in state["aggregates"]["experiment"].items()
            if isinstance(experiment, dict)
            and experiment.get("package_id") == package_id
        ),
        key=lambda row: row[0],
    )
    if not bound:
        raise CommandRejected(
            "package-reopen-experiments-required",
            "ACTIVE Package has no bound Experiments to detach",
        )
    source_ids = {
        str(row.get("id"))
        for row in package.get("sourceExperiments", [])
        if isinstance(row, dict) and row.get("id")
    }
    if source_ids != {experiment_id for experiment_id, _ in bound}:
        raise CommandConflict(
            "package-reopen-experiment-provenance-mismatch",
            "Package sourceExperiments no longer matches its bound Experiments",
        )
    for experiment_id, experiment in bound:
        if experiment.get("status") not in {"PLANNED", "READY", "BLOCKED"}:
            raise CommandRejected(
                "package-reopen-experiment-started",
                f"Experiment is no longer pre-launch: {experiment_id}",
            )
        if experiment.get("latest_result_run_id") or experiment.get(
            "latest_result_sha256"
        ):
            raise CommandRejected(
                "package-reopen-experiment-results-forbidden",
                f"Experiment has recorded result evidence: {experiment_id}",
            )
    return package, bound


def commit_package_reopen_as_draft(
    paths: ResearchPaths,
    package_id: str,
    *,
    reason: str,
    expected_version: int,
    actor: dict[str, str],
    source_document: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Atomically return one never-run ACTIVE Package to a governed Draft."""
    if actor.get("type") != "user":
        raise CommandRejected(
            "package-reopen-user-required",
            "Reopening an ACTIVE Package as Draft requires an explicit user actor",
        )
    if not isinstance(reason, str) or not reason.strip():
        raise CommandRejected(
            "package-reopen-reason-required",
            "Package reopen requires a non-empty reason",
        )
    store = EventStore(paths)
    store.initialize()
    before = store.state()
    package, bound = _validate_package_reopen_state(before, package_id)
    source = _reopen_proposal_source(package, source_document)
    draft = _draft_record_from_active_package(
        package,
        source,
        reason=reason.strip(),
    )
    _validate_draft_package_record(paths, draft)
    payload = {
        "record": draft,
        "reason": reason.strip(),
        "prior_scope": {
            "direction_id": package.get("direction_id"),
            "direction_version": package.get("sourceVersion"),
            "experiment_ids": [experiment_id for experiment_id, _ in bound],
        },
        "experiment_unbindings": [
            {
                "aggregate_id": experiment_id,
                "expected_version": _version(before, "experiment", experiment_id),
                "aggregate_version": _version(before, "experiment", experiment_id) + 1,
                "record": _detached_experiment_record(experiment),
            }
            for experiment_id, experiment in bound
        ],
    }

    def policy(state: dict[str, Any], _command: dict[str, Any]) -> None:
        current_package, current_bound = _validate_package_reopen_state(
            state,
            package_id,
        )
        current_source = _reopen_proposal_source(
            current_package,
            source_document,
        )
        if current_source.get("document_note") != draft.get("document_note"):
            raise CommandConflict(
                "package-reopen-document-changed",
                "Package proposal document changed before the reopen commit",
            )
        current_by_id = dict(current_bound)
        for unbinding in payload["experiment_unbindings"]:
            experiment_id = unbinding["aggregate_id"]
            current = current_by_id.get(experiment_id)
            if not isinstance(current, dict):
                raise CommandConflict(
                    "package-reopen-experiment-changed",
                    f"Experiment binding changed before reopen: {experiment_id}",
                )
            if _detached_experiment_record(current) != unbinding["record"]:
                raise CommandConflict(
                    "package-reopen-experiment-changed",
                    f"Experiment changed before reopen: {experiment_id}",
                )

    return _commit(
        store,
        event_type="PackageReopenedAsDraft",
        aggregate_type="package",
        aggregate_id=package_id,
        payload=payload,
        actor=copy.deepcopy(actor),
        idempotency_key=idempotency_key
        or f"package:reopen-draft:{package_id}:v{expected_version}",
        expected_version=expected_version,
        entry_skill="research-package",
        policy=policy,
    )


_REACTIVATED_PROPOSAL_FIELDS = (
    "abstract",
    "created_at",
    "documentPath",
    "document_note",
    "idea",
    "idea_snapshot",
    "lit_refs",
    "page_language",
    "title",
)


def reactivate_unchanged_reopen(
    paths: ResearchPaths,
    package_id: str,
    *,
    actor: dict[str, str],
    expected_version: int | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Cancel the latest unchanged reopen and restore its exact approved Scope.

    This is a narrow compensating transition, not a way to bypass a fresh
    Scope review. Any Draft, Direction, Experiment, Run, or result change after
    the reopen makes the command fail closed.
    """
    if actor.get("type") != "user":
        raise CommandRejected(
            "package-reactivation-user-required",
            "Reactivating a reopened Package requires an explicit user actor",
        )
    store = EventStore(paths)
    store.initialize()
    events = store.events()
    reopen_event = next(
        (
            event
            for event in reversed(events)
            if event.get("event_type") == "PackageReopenedAsDraft"
            and event.get("aggregate_type") == "package"
            and event.get("aggregate_id") == package_id
        ),
        None,
    )
    if not isinstance(reopen_event, dict):
        raise CommandRejected(
            "package-reopen-event-required",
            f"Package has no reopen event to reactivate: {package_id}",
        )
    package_key = idempotency_key or (
        f"package:reactivate-reopen:{package_id}:{reopen_event['event_id']}"
    )
    prior_commit = next(
        (
            event
            for event in events
            if event.get("idempotency_key") == package_key
        ),
        None,
    )
    if prior_commit is not None:
        reactivation = prior_commit.get("payload", {}).get("reopen_reactivation")
        if (
            prior_commit.get("event_type") != "PackageActivated"
            or prior_commit.get("aggregate_id") != package_id
            or not isinstance(reactivation, dict)
            or reactivation.get("reopen_event_id") != reopen_event["event_id"]
        ):
            raise CommandConflict(
                "idempotency-conflict",
                "idempotency key was already used for another Package transition",
            )
        return copy.deepcopy(prior_commit)

    state = store.state()
    current = state["aggregates"]["package"].get(package_id)
    current_version = _version(state, "package", package_id)
    if expected_version is not None and expected_version != current_version:
        raise CommandConflict(
            "package-version-conflict",
            f"expected Package version {expected_version}, got {current_version}",
        )
    latest_package_event = next(
        (
            event
            for event in reversed(events)
            if event.get("aggregate_type") == "package"
            and event.get("aggregate_id") == package_id
        ),
        None,
    )
    reopen_payload = reopen_event.get("payload")
    reopen_record = (
        reopen_payload.get("record") if isinstance(reopen_payload, dict) else None
    )
    if (
        not isinstance(current, dict)
        or current.get("lifecycle") != "DRAFT"
        or latest_package_event != reopen_event
        or current_version != reopen_event.get("aggregate_version")
        or current != reopen_record
    ):
        raise CommandConflict(
            "package-reopen-changed",
            "The reopened Draft changed after PackageReopenedAsDraft; a fresh Scope review is required",
        )
    if current.get("draftStatus") != "REFINING":
        raise CommandRejected(
            "package-reopen-draft-status-invalid",
            "Only an unchanged REFINING reopen may be reactivated",
        )

    prior_state = fold(events[: int(reopen_event["seq"]) - 1])
    prior_package = prior_state["aggregates"]["package"].get(package_id)
    prior_package_version = _version(prior_state, "package", package_id)
    if (
        not isinstance(prior_package, dict)
        or prior_package.get("lifecycle") != "ACTIVE"
        or prior_package_version + 1 != current_version
    ):
        raise CommandConflict(
            "package-reopen-prior-state-invalid",
            "The reopen event does not have one recoverable ACTIVE Package predecessor",
        )
    if any(
        isinstance(run, dict) and run.get("package_id") == package_id
        for run in state["aggregates"]["run"].values()
    ) or any(
        isinstance(run, dict) and run.get("package_id") == package_id
        for run in state["open_runs"].values()
    ):
        raise CommandRejected(
            "package-reactivation-run-history-forbidden",
            "A reopened Package with Run history cannot use unchanged reactivation",
        )

    unbindings = reopen_payload.get("experiment_unbindings")
    if not isinstance(unbindings, list) or not unbindings:
        raise CommandConflict(
            "package-reopen-participants-missing",
            "The reopen event has no Experiment participants to restore",
        )
    prior_scope = reopen_payload.get("prior_scope")
    if not isinstance(prior_scope, dict):
        raise CommandConflict(
            "package-reopen-scope-missing",
            "The reopen event has no prior Scope binding",
        )
    restored_records: dict[str, dict[str, Any]] = {}
    current_records: dict[str, dict[str, Any]] = {}
    for unbinding in unbindings:
        experiment_id = unbinding.get("aggregate_id")
        prior_experiment = prior_state["aggregates"]["experiment"].get(
            experiment_id
        )
        current_experiment = state["aggregates"]["experiment"].get(experiment_id)
        if (
            not isinstance(experiment_id, str)
            or not isinstance(prior_experiment, dict)
            or not isinstance(current_experiment, dict)
            or current_experiment != unbinding.get("record")
            or current_experiment != _detached_experiment_record(prior_experiment)
            or _version(state, "experiment", experiment_id)
            != unbinding.get("aggregate_version")
        ):
            raise CommandConflict(
                "package-reopen-experiment-changed",
                f"Experiment changed after Package reopen: {experiment_id}",
            )
        restored_records[experiment_id] = copy.deepcopy(prior_experiment)
        current_records[experiment_id] = copy.deepcopy(current_experiment)

    source_rows = prior_package.get("sourceExperiments")
    source_ids = [
        str(row.get("id"))
        for row in source_rows
        if isinstance(row, dict) and row.get("id")
    ] if isinstance(source_rows, list) else []
    if (
        not source_ids
        or set(source_ids) != set(restored_records)
        or prior_scope.get("experiment_ids") != source_ids
        or prior_scope.get("direction_id") != prior_package.get("direction_id")
        or prior_scope.get("direction_version") != prior_package.get("sourceVersion")
    ):
        raise CommandConflict(
            "package-reopen-scope-mismatch",
            "The prior Scope snapshot no longer matches the Package participants",
        )
    direction_id = str(prior_package.get("direction_id") or "")
    direction = state["aggregates"]["direction"].get(direction_id)
    if (
        not isinstance(direction, dict)
        or direction.get("status") != "ACTIVE"
        or direction.get("version") != prior_package.get("sourceVersion")
    ):
        raise CommandRejected(
            "package-reactivation-direction-inactive",
            "The Package's prior Direction is no longer ACTIVE at the same version",
        )
    latest_direction_event = next(
        (
            event
            for event in reversed(events)
            if event.get("aggregate_type") == "direction"
            and event.get("aggregate_id") == direction_id
        ),
        None,
    )
    if (
        not isinstance(latest_direction_event, dict)
        or prior_package.get("sourceChange") != latest_direction_event.get("event_id")
    ):
        raise CommandConflict(
            "package-reactivation-direction-changed",
            "The Package's prior Direction event is no longer current",
        )

    source_package = _draft_source_binding(current)
    now = datetime.now(timezone.utc).isoformat()
    active = copy.deepcopy(prior_package)
    for field in _REACTIVATED_PROPOSAL_FIELDS:
        if field in current:
            active[field] = copy.deepcopy(current[field])
    active.update(
        {
            "lifecycle": "ACTIVE",
            "phase": "CONTEXT_LOADED",
            "blocker": None,
            "draftStatus": "SCOPE_READY",
            "draftRevision": current["draftRevision"],
            "executionAuthorized": True,
            "scopeBinding": {
                "source_package": source_package,
                "direction_id": direction_id,
                "direction_version": prior_package["sourceVersion"],
                "experiment_ids": list(source_ids),
            },
            "lastAction": (
                "Reactivated after explicit user confirmation cancelled the "
                "unchanged Draft reopen."
            ),
            "nextAction": (
                "Resume implementation review and preflight; do not launch "
                "until readiness passes."
            ),
            "nextRoute": "FIX_IMPLEMENTATION",
            "lastUpdated": now[:10],
            "updated_at": now,
        }
    )
    active.pop("reopen_reason", None)
    active.pop("detailPath", None)
    _validate_package_record(active)
    _validate_package_activation_record(active)

    restorations = [
        {
            "aggregate_id": experiment_id,
            "expected_version": _version(state, "experiment", experiment_id),
            "aggregate_version": _version(state, "experiment", experiment_id) + 1,
            "record": copy.deepcopy(restored_records[experiment_id]),
        }
        for experiment_id in source_ids
    ]
    payload = {
        "record": active,
        "reopen_reactivation": {
            "reopen_event_id": reopen_event["event_id"],
            "source_package": source_package,
            "prior_package_version": prior_package_version,
        },
        "experiment_restorations": restorations,
    }

    def policy(locked_state: dict[str, Any], _command: dict[str, Any]) -> None:
        locked_package = locked_state["aggregates"]["package"].get(package_id)
        if (
            locked_package != current
            or _version(locked_state, "package", package_id) != current_version
            or locked_state["aggregates"]["direction"].get(direction_id) != direction
        ):
            raise CommandConflict(
                "package-reactivation-state-changed",
                "Package or Direction changed before reopen reactivation committed",
            )
        for experiment_id, expected_record in current_records.items():
            if (
                locked_state["aggregates"]["experiment"].get(experiment_id)
                != expected_record
                or _version(locked_state, "experiment", experiment_id)
                != next(
                    row["expected_version"]
                    for row in restorations
                    if row["aggregate_id"] == experiment_id
                )
            ):
                raise CommandConflict(
                    "package-reactivation-experiment-changed",
                    f"Experiment changed before reactivation: {experiment_id}",
                )

    return _commit(
        store,
        event_type="PackageActivated",
        aggregate_type="package",
        aggregate_id=package_id,
        payload=payload,
        actor=copy.deepcopy(actor),
        idempotency_key=package_key,
        expected_version=current_version,
        causation_id=reopen_event["event_id"],
        entry_skill="research-package",
        policy=policy,
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
    if (
        decision == "ACCEPTED"
        and isinstance(current, dict)
        and (
            current.get("proposal_kind") == "package_finalization"
            or (
                isinstance(current.get("accepted_proposal"), dict)
                and current["accepted_proposal"].get("proposal_kind")
                == "package_finalization"
            )
        )
    ):
        raise CommandRejected(
            "package-finalization-command-required",
            "Package finalization proposals must be approved through package-finalize so Scope and activation commit atomically",
        )
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
        if decision == "ACCEPTED" and "source_package" in live_snapshot:
            _validate_source_package_binding(
                before,
                live_snapshot["source_package"],
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
    if "source_package" in item:
        if node.get("level") != "direction" or item.get("op") != "create":
            raise CommandRejected(
                "scope-source-package-level-invalid",
                "source_package is valid only on a new Direction proposal",
            )
        if item.get("proposal_kind") == "package_finalization":
            package = _validate_source_package_binding(
                state,
                item["source_package"],
                require_scope_ready=False,
            )
            if package.get("draftStatus") != "REFINING":
                raise CommandRejected(
                    "package-finalization-draft-status-invalid",
                    "Package finalization proposals require a REFINING Draft Package",
                )
            declared_brainstorms = item.get("source_brainstorms", [])
            package_brainstorms = [
                str(row.get("id"))
                for row in package.get("sourceBrainstorms", [])
                if isinstance(row, dict) and row.get("id")
            ]
            if declared_brainstorms != package_brainstorms:
                raise CommandConflict(
                    "package-finalization-brainstorm-provenance-mismatch",
                    "finalization proposal must preserve the Draft Package Brainstorm provenance",
                )
            if node.get("version") != 1 or state["aggregates"]["direction"].get(
                node.get("id")
            ) is not None:
                raise CommandConflict(
                    "package-finalization-direction-exists",
                    "Package finalization must create a new Direction at version 1",
                )
            project = state["aggregates"]["project"].get(node["parents"][0])
            if not isinstance(project, dict) or project.get("status") != "ACTIVE":
                raise CommandRejected(
                    "scope-parent-active-required",
                    "Package finalization Direction requires an ACTIVE Project parent",
                )
            experiments = item.get("proposed_experiments")
            if not isinstance(experiments, list) or not experiments:
                raise CommandRejected(
                    "package-finalization-experiments-required",
                    "Package finalization requires at least one proposed Experiment",
                )
            seen: set[str] = set()
            for experiment in experiments:
                if not isinstance(experiment, dict):
                    raise CommandRejected(
                        "package-finalization-experiment-invalid",
                        "proposed_experiments must contain complete Scope nodes",
                    )
                _validate_scope_node(
                    experiment,
                    "create",
                    scope_ssot.REQUIRED_GATE["experiment"],
                )
                experiment_id = experiment.get("id")
                if (
                    experiment.get("level") != "experiment"
                    or experiment.get("parents") != [node["id"]]
                    or experiment.get("version") != 1
                    or not isinstance(experiment_id, str)
                    or not experiment_id
                    or experiment_id in seen
                ):
                    raise CommandRejected(
                        "package-finalization-experiment-invalid",
                        "every proposed Experiment must be unique, version 1, and parented by the new Direction",
                    )
                if state["aggregates"]["experiment"].get(experiment_id) is not None:
                    raise CommandConflict(
                        "package-finalization-experiment-exists",
                        f"Package finalization cannot recreate Experiment: {experiment_id}",
                    )
                seen.add(experiment_id)
        elif item.get("proposal_kind") is not None:
            raise CommandRejected(
                "proposal-kind-invalid",
                f"unknown proposal_kind: {item.get('proposal_kind')!r}",
            )
        else:
            _validate_source_package_binding(state, item["source_package"])


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


def _project_commit_payload(
    paths: ResearchPaths,
    node: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    scope_ssot.validate_node(node)
    if (
        node.get("level") != "project"
        or node.get("parents") != []
        or node.get("version") != 1
        or node.get("status") != "ACTIVE"
    ):
        raise CommandRejected(
            "project-commit-node-invalid",
            "onboarding requires one new ACTIVE Project at version 1",
        )
    store = EventStore(paths)
    store.initialize()
    state = store.state()
    if state["aggregates"]["project"]:
        raise CommandConflict(
            "project-already-committed",
            "workspace already has Project authority",
        )
    project_id = str(node["id"])
    payload = build_transaction_payload(
        command_kind="PROJECT_COMMIT",
        owner_type="project",
        owner_id=project_id,
        participants=[
            {
                "aggregate_type": "project",
                "aggregate_id": project_id,
                "expected_version": 0,
                "aggregate_version": 1,
                "operation": "put",
                "record": copy.deepcopy(node),
            }
        ],
        evidence=(
            [
                {
                    "kind": "prior-knowledge",
                    "uri": node["prior_knowledge"].get("uri"),
                    "sha256": node["prior_knowledge"].get("sha256"),
                }
            ]
            if isinstance(node.get("prior_knowledge"), dict)
            else []
        ),
    )
    return payload, f"evt_project_{_digest(node)[:32]}"


def prepare_project_commit(
    paths: ResearchPaths,
    node: dict[str, Any],
) -> dict[str, Any]:
    """Prepare the only human review used by research-onboard."""
    payload, event_id = _project_commit_payload(paths, copy.deepcopy(node))
    spec = node.get("spec") if isinstance(node.get("spec"), dict) else {}
    return {
        "kind": "project_review",
        "review": {
            "project_id": node["id"],
            "goal": spec.get("goal"),
            "intended_outcomes": copy.deepcopy(spec.get("contributions", [])),
            "boundaries": copy.deepcopy(spec.get("out_of_scope", [])),
        },
        "receipt": {
            "content_sha256": review_digest(payload),
            "event_id": event_id,
        },
    }


def finalize_project_commit(
    paths: ResearchPaths,
    node: dict[str, Any],
    expected_review_sha256: str,
    *,
    actor: dict[str, str],
    review_id: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Consume one onboarding approval and create Project authority."""
    if actor.get("type") != "user":
        raise CommandRejected(
            "project-commit-user-required",
            "Project commit requires explicit user approval",
        )
    if not expected_review_sha256:
        raise CommandRejected(
            "project-review-required",
            "Project commit requires its reviewed content binding",
        )
    project_id = str(node.get("id") or "")
    stable_key = idempotency_key or (
        f"project-commit:{project_id}:{expected_review_sha256}"
    )
    store = EventStore(paths)
    store.initialize()
    prior = store.database.event_by_idempotency_key(stable_key)
    if prior is not None:
        if (
            prior.get("event_type") != "TransactionCommitted"
            or prior.get("aggregate_type") != "project"
            or prior.get("aggregate_id") != project_id
            or prior.get("payload", {}).get("command_kind") != "PROJECT_COMMIT"
            or prior.get("actor") != actor
            or review_digest(prior["payload"]) != expected_review_sha256
        ):
            raise CommandConflict(
                "idempotency-conflict",
                "idempotency_key was already used by another command",
            )
        return _commit_transaction(
            paths,
            payload=copy.deepcopy(prior["payload"]),
            actor=actor,
            idempotency_key=stable_key,
            entry_skill="research-onboard",
            event_id=prior["event_id"],
        )
    payload, event_id = _project_commit_payload(paths, copy.deepcopy(node))
    actual = review_digest(payload)
    if actual != expected_review_sha256:
        raise CommandConflict(
            "project-review-changed",
            "Project charter changed after the user review",
        )
    payload["approval"] = approval_receipt(
        action="COMMIT_PROJECT",
        subject=project_id,
        content_sha256=actual,
        actor_id=actor["id"],
        review_id=review_id,
    )
    return _commit_transaction(
        paths,
        payload=payload,
        actor=actor,
        idempotency_key=stable_key,
        entry_skill="research-onboard",
        event_id=event_id,
    )


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


def _validate_package_activation_record(record: dict[str, Any]) -> None:
    """Require an exact bridge from one reviewed draft to executable Scope."""
    if record.get("executionAuthorized") is not True:
        raise CommandRejected(
            "package-activation-authorization-required",
            "activated Package must set executionAuthorized=true",
        )
    binding = record.get("scopeBinding")
    if not isinstance(binding, dict) or set(binding) != {
        "source_package",
        "direction_id",
        "direction_version",
        "experiment_ids",
    }:
        raise CommandRejected(
            "package-scope-binding-invalid",
            "activated Package requires exact source_package, direction_id, "
            "direction_version, and experiment_ids binding",
        )
    if binding.get("direction_id") != record.get("direction_id"):
        raise CommandRejected(
            "package-scope-direction-mismatch",
            "scopeBinding direction_id must match Package direction_id",
        )
    if binding.get("direction_version") != record.get("sourceVersion"):
        raise CommandRejected(
            "package-scope-direction-version-mismatch",
            "scopeBinding direction_version must match Package sourceVersion",
        )
    source_ids = [
        item.get("id")
        for item in record.get("sourceExperiments", [])
        if isinstance(item, dict)
    ]
    if binding.get("experiment_ids") != source_ids:
        raise CommandRejected(
            "package-scope-experiments-mismatch",
            "scopeBinding experiment_ids must match sourceExperiments in order",
        )


def _validate_brainstorm_consumptions(
    state: dict[str, Any],
    package: dict[str, Any],
    consumptions: list[dict[str, Any]],
) -> None:
    if not consumptions:
        return
    sources = package.get("sourceBrainstorms")
    notes = package.get("interface_notes")
    if not isinstance(sources, list) or not isinstance(notes, dict):
        raise CommandRejected(
            "package-brainstorm-documents-required",
            "Brainstorm conversion requires Package sourceBrainstorms and "
            "interface_notes",
        )
    source_by_id = {
        str(row.get("id")): row
        for row in sources
        if isinstance(row, dict) and row.get("id")
    }
    seen: set[str] = set()
    for consumption in consumptions:
        if not isinstance(consumption, dict):
            raise CommandRejected(
                "package-brainstorm-consumption-invalid",
                "Brainstorm consumption rows must be objects",
            )
        idea_id = consumption.get("aggregate_id")
        expected_version = consumption.get("expected_version")
        document_path = consumption.get("document_path")
        document_note = consumption.get("document_note")
        if not isinstance(idea_id, str) or not idea_id or idea_id in seen:
            raise CommandRejected(
                "package-brainstorm-consumption-invalid",
                "Brainstorm consumption ids must be unique non-empty strings",
            )
        seen.add(idea_id)
        current = state["aggregates"]["brainstorm"].get(idea_id)
        current_version = _version(state, "brainstorm", idea_id)
        if not isinstance(current, dict) or current.get("status") != "ACTIVE":
            raise CommandRejected(
                "package-active-brainstorm-required",
                f"Package conversion requires an ACTIVE Brainstorm: {idea_id}",
            )
        if expected_version != current_version:
            raise CommandConflict(
                "package-brainstorm-version-mismatch",
                f"Brainstorm {idea_id} changed before Package conversion",
            )
        if not isinstance(document_note, dict) or current.get(
            "document_note"
        ) != document_note:
            raise CommandConflict(
                "package-brainstorm-document-mismatch",
                f"Brainstorm {idea_id} document changed before Package conversion",
            )
        source = source_by_id.get(idea_id)
        if (
            not isinstance(document_path, str)
            or not isinstance(source, dict)
            or source.get("documentPath") != document_path
            or source.get("document_note") != document_note
            or notes.get(document_path) != document_note
        ):
            raise CommandRejected(
                "package-brainstorm-ownership-required",
                f"Package must own the source document before consuming {idea_id}",
            )


def _commit_package_create_locked(
    paths: ResearchPaths,
    record: dict[str, Any],
    experiments: list[dict[str, Any]] | None = None,
    brainstorm_consumptions: list[dict[str, Any]] | None = None,
    *,
    activate_draft: bool = False,
    actor: dict[str, str] | None = None,
    idempotency_key: str | None = None,
    entry_skill: str = "research-package",
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Create or activate Package state and bind accepted Scope Experiments.

    All rows are normalized and collision-checked before one composite event
    atomically materializes the Package and every Experiment binding.
    """
    package = copy.deepcopy(record)
    consumptions = copy.deepcopy(list(brainstorm_consumptions or []))
    _validate_package_record(package)
    if activate_draft:
        _validate_package_activation_record(package)
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
    event_type = "PackageActivated" if activate_draft else "PackageMaterialized"
    action = "activate" if activate_draft else "create"
    package_key = idempotency_key or (
        f"package:{action}:{package_id}:"
        f"{_digest({'package': package, 'experiments': normalized})}"
    )
    prior_package = next(
        (
            event
            for event in store.events()
            if event["idempotency_key"] == package_key
        ),
        None,
    )
    if prior_package is None:
        if activate_draft and (
            not isinstance(existing_package, dict)
            or existing_package.get("lifecycle") != "DRAFT"
        ):
            raise CommandConflict(
                "package-draft-required",
                f"Package activation requires an existing Draft Package: {package_id}",
            )
        if not activate_draft and existing_package is not None:
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
    if consumptions:
        candidate_payload["brainstorm_consumptions"] = consumptions
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
            "brainstorm_consumptions": (
                prior_payload.get("brainstorm_consumptions", [])
                if isinstance(prior_payload, dict)
                else []
            ),
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
            "brainstorm_consumptions": candidate_payload.get(
                "brainstorm_consumptions", []
            ),
        }
        if (
            prior_package.get("event_type") != event_type
            or prior_package.get("aggregate_type") != "package"
            or prior_package.get("aggregate_id") != package_id
            or prior_semantics != candidate_semantics
        ):
            raise CommandConflict(
                "idempotency-conflict",
                "idempotency_key was already committed with different "
                f"Package {action} content",
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
        if activate_draft:
            scope_binding = package["scopeBinding"]
            draft = _validate_source_package_binding(
                state,
                scope_binding["source_package"],
            )
            if package.get("document_note") != draft.get("document_note"):
                raise CommandConflict(
                    "package-draft-document-mismatch",
                    "activated Package must preserve the reviewed proposal document",
                )
            if package.get("documentPath") != draft.get("documentPath"):
                raise CommandConflict(
                    "package-draft-path-mismatch",
                    "activated Package must preserve the proposal document path",
                )
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
        _validate_brainstorm_consumptions(state, package, consumptions)

    if prior_package is None:
        validate_bindings(before)

    package_event = _commit(store,
        event_type=event_type,
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
            "_composite_event_type": event_type,
        }
        for binding in materialization_payload["experiment_bindings"]
    ]
    return package_event, experiment_events


def commit_package_create(
    paths: ResearchPaths,
    record: dict[str, Any],
    experiments: list[dict[str, Any]] | None = None,
    brainstorm_consumptions: list[dict[str, Any]] | None = None,
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
        brainstorm_consumptions,
        actor=actor,
        idempotency_key=idempotency_key,
        entry_skill=entry_skill,
    )


def commit_package_activate(
    paths: ResearchPaths,
    record: dict[str, Any],
    experiments: list[dict[str, Any]] | None = None,
    *,
    actor: dict[str, str] | None = None,
    idempotency_key: str | None = None,
    entry_skill: str = "research-package",
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Atomically activate the same reviewed Draft Package and bind Scope."""
    return _commit_package_create_locked(
        paths,
        record,
        experiments,
        activate_draft=True,
        actor=actor,
        idempotency_key=idempotency_key,
        entry_skill=entry_skill,
    )


def _scope_display(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("name") or json.dumps(value, sort_keys=True))
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value or "unmeasured")


def _build_scope_bundle_transaction(
    paths: ResearchPaths,
    package_id: str,
    direction: dict[str, Any],
    experiments: list[dict[str, Any]],
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    """Build the exact one-event authority boundary for a reviewed Scope."""
    store = EventStore(paths)
    store.initialize()
    state = store.state()
    draft = state["aggregates"]["package"].get(package_id)
    if (
        not isinstance(draft, dict)
        or draft.get("lifecycle") != "DRAFT"
        or draft.get("draftStatus") != "REFINING"
    ):
        raise CommandRejected(
            "package-refining-draft-required",
            f"Scope commit requires a REFINING Draft Package: {package_id}",
        )
    scope_ssot.validate_node(direction)
    if direction.get("level") != "direction" or direction.get("version") != 1:
        raise CommandRejected(
            "scope-bundle-direction-invalid",
            "Scope Bundle requires one new Direction at version 1",
        )
    if _version(state, "direction", str(direction.get("id") or "")) != 0:
        raise CommandConflict(
            "scope-bundle-direction-exists",
            f"Direction already exists: {direction.get('id')}",
        )
    if not isinstance(experiments, list) or not experiments:
        raise CommandRejected(
            "scope-bundle-experiments-required",
            "Scope Bundle requires at least one Experiment",
        )
    seen: set[str] = set()
    for node in experiments:
        scope_ssot.validate_node(node)
        experiment_id = str(node.get("id") or "")
        if (
            node.get("level") != "experiment"
            or node.get("parents") != [direction["id"]]
            or node.get("version") != 1
            or not experiment_id
            or experiment_id in seen
        ):
            raise CommandRejected(
                "scope-bundle-experiment-invalid",
                "every Scope Bundle Experiment must be unique, version 1, "
                "and parented by its Direction",
            )
        if _version(state, "experiment", experiment_id) != 0:
            raise CommandConflict(
                "scope-bundle-experiment-exists",
                f"Experiment already exists: {experiment_id}",
            )
        seen.add(experiment_id)

    source_package = _draft_source_binding(draft)
    scope_sha256 = _digest(
        {
            "source_package": source_package,
            "direction": direction,
            "experiments": experiments,
        }
    )
    event_id = f"evt_scope_{scope_sha256[:32]}"
    transition = {
        "op": "create",
        "gate": scope_ssot.REQUIRED_GATE["direction"],
        "trigger": f"scope-bundle:{package_id}",
        "cause": f"draft-package:{package_id}:v{draft['draftRevision']}",
    }
    direction_record = _scope_record(direction, transition)
    experiment_records: list[dict[str, Any]] = []
    for index, node in enumerate(experiments):
        record = _scope_record(
            node,
            {
                "op": "create",
                "gate": scope_ssot.REQUIRED_GATE["experiment"],
                "trigger": f"scope-bundle:{package_id}",
                "cause": f"draft-package:{package_id}:v{draft['draftRevision']}",
            },
            direction_version=int(direction["version"]),
        )
        _, binding = normalize_experiment_binding(
            package_id,
            {
                "scope_experiment_id": node["id"],
                "local_id": f"P{index}",
                "output": (
                    f".research/experiments/{package_id}/P{index}/"
                    "<run-id>/result.json"
                ),
                "status": "READY",
                "measures": True,
                "requiresCode": False,
                "complex": False,
            },
        )
        record.update(binding)
        experiment_records.append(record)

    finalized = copy.deepcopy(draft)
    finalized["draftStatus"] = "SCOPE_READY"
    spec = direction["spec"]
    hypothesis = str(spec.get("hypothesis") or "")
    metric = _scope_display(spec.get("metric"))
    baseline = _scope_display(spec.get("baselines"))
    gate = str(spec.get("success_gate") or "")
    active = copy.deepcopy(finalized)
    active.update(
        {
            "lifecycle": "ACTIVE",
            "phase": "CONTEXT_LOADED",
            "blocker": None,
            # Kept during the compatibility window. executionLease is the
            # vNext authority consumed by launch admission.
            "executionAuthorized": True,
            "executionLease": {
                "status": "OPEN",
                "scope_sha256": scope_sha256,
                "package_revision": draft["draftRevision"],
                "experiment_ids": [node["id"] for node in experiments],
                "grants": ["IMPLEMENT", "LAUNCH", "RECORD_RESULTS"],
            },
            "direction_id": direction["id"],
            "sourceDirection": direction["id"],
            "sourceVersion": direction["version"],
            "sourceChange": event_id,
            "sourceExperiments": [
                {
                    "id": node["id"],
                    "version": node["version"],
                    "source": node["source"],
                }
                for node in experiments
            ],
            "scopeBinding": {
                "source_package": source_package,
                "direction_id": direction["id"],
                "direction_version": direction["version"],
                "experiment_ids": [node["id"] for node in experiments],
            },
            "problem": active.get("problem") or hypothesis,
            "objective": active.get("objective") or hypothesis,
            "hypothesis": hypothesis,
            "direction": hypothesis,
            "primaryMetric": metric,
            "baseline": baseline,
            "activeGate": gate,
            "primaryMetricVsGate": f"{metric} vs {gate}",
            "artifactRoot": active.get("artifactRoot")
            or f".research/experiments/{package_id}/",
            "runtime": active.get("runtime")
            or f".research/experiments/{package_id}/",
            "openRuns": "none",
            "lastAction": "Scope Bundle committed",
            "lastUpdated": str(
                draft.get("lastUpdated") or draft.get("updated_at") or ""
            )[:10],
            "nextAction": f"Start implementation for {experiments[0]['id']}",
        }
    )
    _validate_package_record(active)
    _validate_package_activation_record(active)
    package_version = _version(state, "package", package_id)
    participants = [
        {
            "aggregate_type": "package",
            "aggregate_id": package_id,
            "expected_version": package_version,
            "aggregate_version": package_version + 1,
            "operation": "put",
            "record": active,
        },
        {
            "aggregate_type": "direction",
            "aggregate_id": direction["id"],
            "expected_version": 0,
            "aggregate_version": 1,
            "operation": "put",
            "record": direction_record,
        },
    ]
    participants.extend(
        {
            "aggregate_type": "experiment",
            "aggregate_id": node["id"],
            "expected_version": 0,
            "aggregate_version": 1,
            "operation": "put",
            "record": record,
        }
        for node, record in zip(experiments, experiment_records, strict=True)
    )
    note = draft.get("document_note") or {}
    payload = build_transaction_payload(
        command_kind="SCOPE_BUNDLE_COMMIT",
        owner_type="package",
        owner_id=package_id,
        participants=participants,
        evidence=[
            {
                "kind": "draft-package-document",
                "uri": note.get("uri"),
                "sha256": note.get("sha256"),
            }
        ],
    )
    review = {
        "package_id": package_id,
        "draft_revision": draft["draftRevision"],
        "question": draft.get("idea") or draft.get("problem"),
        "direction": copy.deepcopy(direction),
        "experiments": copy.deepcopy(experiments),
        "execution": "Implement and launch only the Experiments in this Scope Bundle",
    }
    return payload, event_id, review


def prepare_scope_bundle(
    paths: ResearchPaths,
    package_id: str,
    direction: dict[str, Any],
    experiments: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return one plain-language review plus an internal content binding."""
    payload, event_id, review = _build_scope_bundle_transaction(
        paths,
        package_id,
        copy.deepcopy(direction),
        copy.deepcopy(experiments),
    )
    return {
        "kind": "scope_bundle_review",
        "review": review,
        "receipt": {
            "content_sha256": review_digest(payload),
            "event_id": event_id,
        },
    }


def finalize_scope_bundle(
    paths: ResearchPaths,
    package_id: str,
    direction: dict[str, Any],
    experiments: list[dict[str, Any]],
    expected_review_sha256: str,
    *,
    actor: dict[str, str],
    review_id: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Commit Package, Direction, and Experiments under one user approval."""
    if actor.get("type") != "user":
        raise CommandRejected(
            "scope-bundle-user-required",
            "Scope Bundle commit requires explicit user approval",
        )
    if not expected_review_sha256:
        raise CommandRejected(
            "scope-bundle-review-required",
            "Scope Bundle commit requires its reviewed content binding",
        )
    stable_key = idempotency_key or (
        f"scope-bundle:{package_id}:{expected_review_sha256}"
    )
    store = EventStore(paths)
    store.initialize()
    prior = store.database.event_by_idempotency_key(stable_key)
    if prior is not None:
        if (
            prior.get("event_type") != "TransactionCommitted"
            or prior.get("aggregate_type") != "package"
            or prior.get("aggregate_id") != package_id
            or prior.get("payload", {}).get("command_kind")
            != "SCOPE_BUNDLE_COMMIT"
            or prior.get("actor") != actor
            or review_digest(prior["payload"]) != expected_review_sha256
        ):
            raise CommandConflict(
                "idempotency-conflict",
                "idempotency_key was already used by another command",
            )
        return _commit_transaction(
            paths,
            payload=copy.deepcopy(prior["payload"]),
            actor=actor,
            idempotency_key=stable_key,
            entry_skill="research-package",
            event_id=prior["event_id"],
        )

    payload, event_id, _ = _build_scope_bundle_transaction(
        paths,
        package_id,
        copy.deepcopy(direction),
        copy.deepcopy(experiments),
    )
    actual_review_sha256 = review_digest(payload)
    if actual_review_sha256 != expected_review_sha256:
        raise CommandConflict(
            "scope-bundle-review-changed",
            "Draft Package or Scope Bundle changed after the user review",
        )
    payload["approval"] = approval_receipt(
        action="COMMIT_SCOPE_BUNDLE",
        subject=package_id,
        content_sha256=actual_review_sha256,
        actor_id=actor["id"],
        review_id=review_id,
    )
    return _commit_transaction(
        paths,
        payload=payload,
        actor=actor,
        idempotency_key=stable_key,
        entry_skill="research-package",
        event_id=event_id,
    )


def _package_identity_date(
    package_id: str,
    package: dict[str, Any] | None = None,
    explicit: str | None = None,
) -> str:
    inferred: str | None = None
    if isinstance(package, dict):
        candidates = [
            package.get("identityDate"),
            package_id[:10] if len(package_id) > 10 and package_id[10] == "-" else None,
            str(package.get("created_at") or "")[:10],
            str(package.get("lastUpdated") or "")[:10],
        ]
    else:
        candidates = [
            package_id[:10] if len(package_id) > 10 and package_id[10] == "-" else None
        ]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            inferred = validate_identity_date(str(candidate))
            break
        except PackageIdentityViolation:
            continue
    if explicit is not None:
        try:
            supplied = validate_identity_date(explicit)
        except PackageIdentityViolation as exc:
            raise CommandRejected("package-identity-date-invalid", str(exc)) from exc
        if inferred is not None and supplied != inferred:
            raise CommandRejected(
                "package-identity-date-immutable",
                f"Package identity date must remain {inferred}",
            )
        return supplied
    if inferred is not None:
        return inferred
    raise CommandRejected(
        "package-identity-date-required",
        "Package rename requires its original YYYY-MM-DD identity date",
    )


def _rewrite_package_root(
    value: Any,
    *,
    old_id: str,
    new_id: str,
    field: str,
) -> Any:
    if not isinstance(value, str) or not value:
        return value
    old_root = f".research/experiments/{old_id}/"
    new_root = f".research/experiments/{new_id}/"
    if value.startswith(old_root):
        return new_root + value[len(old_root):]
    old_route = f"packages/{old_id}/"
    new_route = f"packages/{new_id}/"
    if old_route in value:
        return value.replace(old_route, new_route, 1)
    if old_id in value:
        raise CommandRejected(
            "package-identity-path-ambiguous",
            f"cannot safely rewrite {field}: {value}",
        )
    return value


def _build_package_identity_transaction(
    paths: ResearchPaths,
    package_id: str,
    title: str,
    rationale: str,
    *,
    identity_date: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build one pre-run Package identity transaction and semantic review."""
    try:
        canonical_title = validate_title(title)
    except PackageIdentityViolation as exc:
        raise CommandRejected("package-title-invalid", str(exc)) from exc
    if not isinstance(rationale, str) or not rationale.strip():
        raise CommandRejected(
            "package-title-rationale-required",
            "Package title requires the agent's core-purpose analysis",
        )

    store = EventStore(paths)
    store.initialize()
    state = store.state()
    package = state["aggregates"]["package"].get(package_id)
    if not isinstance(package, dict):
        raise CommandRejected(
            "package-identity-source-missing",
            f"unknown Package: {package_id}",
        )
    if package.get("lifecycle") not in {"DRAFT", "ACTIVE"}:
        raise CommandRejected(
            "package-identity-lifecycle-forbidden",
            "Package identity can change only before a terminal lifecycle",
        )
    if package.get("blocker") is not None:
        raise CommandRejected(
            "package-identity-blocked",
            "Package identity cannot change while a blocker is active",
        )
    if any(package.get(field) for field in PACKAGE_RESULT_FIELDS):
        raise CommandRejected(
            "package-identity-results-exist",
            "Package identity cannot change after result summaries exist",
        )

    resolved_date = _package_identity_date(
        package_id,
        package,
        explicit=identity_date,
    )
    new_id = canonical_package_id(canonical_title, resolved_date)
    if new_id == package_id:
        raise CommandRejected(
            "package-identity-unchanged",
            "Package already has the requested canonical id",
        )
    if (
        state["aggregates"]["package"].get(new_id) is not None
        or _version(state, "package", new_id) != 0
    ):
        raise CommandConflict(
            "package-identity-collision",
            f"Package id already exists or has history: {new_id}",
        )

    old_experiment_root = paths.experiments / package_id
    new_experiment_root = paths.experiments / new_id
    if old_experiment_root.exists() or new_experiment_root.exists():
        raise CommandRejected(
            "package-identity-evidence-exists",
            "Package identity cannot change after an evidence directory exists",
        )
    referenced_runs = [
        run_id
        for run_id, run in state["aggregates"]["run"].items()
        if isinstance(run, dict) and run.get("package_id") == package_id
    ]
    if referenced_runs or any(
        isinstance(run, dict) and run.get("package_id") == package_id
        for run in state.get("open_runs", {}).values()
    ):
        raise CommandRejected(
            "package-identity-runs-exist",
            "Package identity cannot change after a Run exists",
        )

    bound_experiments = [
        (experiment_id, copy.deepcopy(experiment))
        for experiment_id, experiment in state["aggregates"]["experiment"].items()
        if isinstance(experiment, dict)
        and experiment.get("package_id") == package_id
    ]
    unsafe_experiments = [
        experiment_id
        for experiment_id, experiment in bound_experiments
        if experiment.get("status") not in {"PLANNED", "READY"}
    ]
    if unsafe_experiments:
        raise CommandRejected(
            "package-identity-experiment-started",
            "Package identity cannot change after an Experiment starts: "
            + ", ".join(sorted(unsafe_experiments)),
        )

    migrated = renamed_record(
        package,
        title=canonical_title,
        identity_date=resolved_date,
        rationale=rationale,
    )
    for field in ("artifactRoot", "runtime", "detailPath"):
        if field in migrated:
            migrated[field] = _rewrite_package_root(
                migrated[field],
                old_id=package_id,
                new_id=new_id,
                field=field,
            )
    scope_binding = migrated.get("scopeBinding")
    if isinstance(scope_binding, dict):
        source_package = scope_binding.get("source_package")
        if isinstance(source_package, dict) and source_package.get("id") == package_id:
            source_package["id"] = new_id
    source_brainstorms = migrated.get("sourceBrainstorms")
    if isinstance(source_brainstorms, list):
        for source in source_brainstorms:
            if isinstance(source, dict) and source.get("convertedInto") == package_id:
                source["convertedInto"] = new_id
    migrated["lastAction"] = f"Package identity renamed from {package_id} to {new_id}"

    old_version = _version(state, "package", package_id)
    participants: list[dict[str, Any]] = [
        {
            "aggregate_type": "package",
            "aggregate_id": package_id,
            "expected_version": old_version,
            "aggregate_version": old_version + 1,
            "operation": "remove",
        },
        {
            "aggregate_type": "package",
            "aggregate_id": new_id,
            "expected_version": 0,
            "aggregate_version": 1,
            "operation": "put",
            "record": migrated,
        },
    ]
    for experiment_id, experiment in bound_experiments:
        experiment["package_id"] = new_id
        if "output" in experiment:
            experiment["output"] = _rewrite_package_root(
                experiment["output"],
                old_id=package_id,
                new_id=new_id,
                field=f"experiment/{experiment_id}.output",
            )
        experiment_version = _version(state, "experiment", experiment_id)
        participants.append(
            {
                "aggregate_type": "experiment",
                "aggregate_id": experiment_id,
                "expected_version": experiment_version,
                "aggregate_version": experiment_version + 1,
                "operation": "put",
                "record": experiment,
            }
        )

    source_ids = {
        str(source.get("id"))
        for source in package.get("sourceBrainstorms", [])
        if isinstance(source, dict) and source.get("id")
    }
    for brainstorm_id in sorted(source_ids):
        brainstorm = state["aggregates"]["brainstorm"].get(brainstorm_id)
        if not isinstance(brainstorm, dict):
            continue
        if brainstorm.get("materialized_as") != package_id:
            raise CommandRejected(
                "package-identity-brainstorm-mismatch",
                f"source Brainstorm does not point to Package {package_id}: {brainstorm_id}",
            )
        updated_brainstorm = copy.deepcopy(brainstorm)
        updated_brainstorm["materialized_as"] = new_id
        brainstorm_version = _version(state, "brainstorm", brainstorm_id)
        participants.append(
            {
                "aggregate_type": "brainstorm",
                "aggregate_id": brainstorm_id,
                "expected_version": brainstorm_version,
                "aggregate_version": brainstorm_version + 1,
                "operation": "put",
                "record": updated_brainstorm,
            }
        )

    payload = build_transaction_payload(
        command_kind="PACKAGE_IDENTITY_RENAME",
        owner_type="package",
        owner_id=package_id,
        participants=participants,
        evidence=[
            {
                "kind": "package-core-purpose-analysis",
                "old_id": package_id,
                "new_id": new_id,
                "title": canonical_title,
                "rationale": rationale.strip(),
            }
        ],
    )
    review = {
        "old_id": package_id,
        "new_id": new_id,
        "name": canonical_title,
        "title": canonical_title,
        "core_purpose": rationale.strip(),
        "bound_experiments": [row[0] for row in bound_experiments],
        "scope_change": False,
    }
    return payload, review


def prepare_package_identity_rename(
    paths: ResearchPaths,
    package_id: str,
    title: str,
    rationale: str,
    *,
    identity_date: str | None = None,
) -> dict[str, Any]:
    """Return the semantic review and exact binding for one Package rename."""
    payload, review = _build_package_identity_transaction(
        paths,
        package_id,
        title,
        rationale,
        identity_date=identity_date,
    )
    return {
        "kind": "package_identity_review",
        "review": review,
        "receipt": {"content_sha256": review_digest(payload)},
    }


def rename_package_identity(
    paths: ResearchPaths,
    package_id: str,
    title: str,
    rationale: str,
    expected_review_sha256: str,
    *,
    actor: dict[str, str],
    review_id: str,
    identity_date: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Atomically replace a pre-run Package id and all execution bindings."""
    if actor.get("type") != "user":
        raise CommandRejected(
            "package-identity-user-required",
            "Package identity rename requires explicit user approval",
        )
    if not expected_review_sha256:
        raise CommandRejected(
            "package-identity-review-required",
            "Package identity rename requires its reviewed content binding",
        )
    resolved_date = _package_identity_date(
        package_id,
        explicit=identity_date,
    )
    new_id = canonical_package_id(title, resolved_date)
    stable_key = idempotency_key or (
        f"package-identity:{package_id}:{new_id}:{expected_review_sha256}"
    )
    store = EventStore(paths)
    store.initialize()
    prior = store.database.event_by_idempotency_key(stable_key)
    if prior is not None:
        if (
            prior.get("event_type") != "TransactionCommitted"
            or prior.get("aggregate_type") != "package"
            or prior.get("aggregate_id") != package_id
            or prior.get("payload", {}).get("command_kind")
            != "PACKAGE_IDENTITY_RENAME"
            or prior.get("actor") != actor
            or review_digest(prior["payload"]) != expected_review_sha256
        ):
            raise CommandConflict(
                "idempotency-conflict",
                "idempotency_key was already used by another command",
            )
        return _commit_transaction(
            paths,
            payload=copy.deepcopy(prior["payload"]),
            actor=actor,
            idempotency_key=stable_key,
            entry_skill="research-package",
            event_id=prior["event_id"],
        )

    payload, _ = _build_package_identity_transaction(
        paths,
        package_id,
        title,
        rationale,
        identity_date=resolved_date,
    )
    actual_review_sha256 = review_digest(payload)
    if actual_review_sha256 != expected_review_sha256:
        raise CommandConflict(
            "package-identity-review-changed",
            "Package identity inputs or participants changed after user review",
        )
    payload["approval"] = approval_receipt(
        action="RENAME_PACKAGE",
        subject=package_id,
        content_sha256=actual_review_sha256,
        actor_id=actor["id"],
        review_id=review_id,
    )
    return _commit_transaction(
        paths,
        payload=payload,
        actor=actor,
        idempotency_key=stable_key,
        entry_skill="research-package",
    )


def _build_package_decision_transaction(
    paths: ResearchPaths,
    package_id: str,
    outcome: str,
    reason: str,
    evidence: list[dict[str, Any]],
    *,
    actor: dict[str, str],
) -> tuple[dict[str, Any], str, str]:
    if outcome not in {"SUCCESS", "FAIL"}:
        raise CommandRejected(
            "package-outcome-invalid",
            "Package outcome must be SUCCESS or FAIL",
        )
    if not isinstance(reason, str) or not reason.strip():
        raise CommandRejected(
            "package-outcome-reason-required",
            "Package outcome requires a concise reason",
        )
    if not isinstance(evidence, list) or not evidence:
        raise CommandRejected(
            "package-outcome-evidence-required",
            "Package outcome requires at least one evidence reference",
        )
    state = EventStore(paths).state()
    package = state["aggregates"]["package"].get(package_id)
    if not isinstance(package, dict) or package.get("lifecycle") != "ACTIVE":
        raise CommandRejected(
            "active-package-required",
            f"Package outcome requires an ACTIVE Package: {package_id}",
        )
    open_runs = [
        run_id
        for run_id, run in state.get("open_runs", {}).items()
        if isinstance(run, dict) and run.get("package_id") == package_id
    ]
    if open_runs:
        raise CommandRejected(
            "package-open-runs",
            "Package outcome cannot close while Runs remain open: "
            + ", ".join(sorted(open_runs)),
        )
    package_version = _version(state, "package", package_id)
    decision_seed = {
        "package_id": package_id,
        "package_version": package_version,
        "outcome": outcome,
        "reason": reason.strip(),
        "evidence": evidence,
        "actor": actor,
    }
    decision_id = f"decision/package-outcome/{_digest(decision_seed)[:24]}"
    decision = {
        "id": decision_id,
        "kind": "PACKAGE_OUTCOME",
        "package_id": package_id,
        "outcome": outcome,
        "reason": reason.strip(),
        "actor": copy.deepcopy(actor),
        "evidence": copy.deepcopy(evidence),
    }
    terminal = copy.deepcopy(package)
    terminal.update(
        {
            "lifecycle": "ADOPTED" if outcome == "SUCCESS" else "ARCHIVED",
            "phase": None,
            "blocker": None,
            "executionAuthorized": False,
            "terminationMessage": reason.strip(),
            "lastAction": f"Package closed as {outcome}",
            "nextAction": (
                "Optional evidence analysis and Rule promotion"
                if outcome == "SUCCESS"
                else "Archive retained evidence or reopen as a new Draft"
            ),
        }
    )
    lease = terminal.get("executionLease")
    if isinstance(lease, dict):
        terminal["executionLease"] = {
            **copy.deepcopy(lease),
            "status": "CLOSED",
            "closed_by": decision_id,
            "outcome": outcome,
        }
    payload = build_transaction_payload(
        command_kind="PACKAGE_DECIDE",
        owner_type="package",
        owner_id=package_id,
        participants=[
            {
                "aggregate_type": "package",
                "aggregate_id": package_id,
                "expected_version": package_version,
                "aggregate_version": package_version + 1,
                "operation": "put",
                "record": terminal,
            },
            {
                "aggregate_type": "decision",
                "aggregate_id": decision_id,
                "expected_version": 0,
                "aggregate_version": 1,
                "operation": "put",
                "record": decision,
            },
        ],
        evidence=copy.deepcopy(evidence),
    )
    return payload, f"evt_decide_{_digest(decision_seed)[:32]}", decision_id


def prepare_package_decision(
    paths: ResearchPaths,
    package_id: str,
    outcome: str,
    reason: str,
    evidence: list[dict[str, Any]],
    *,
    actor_id: str,
) -> dict[str, Any]:
    actor = {"type": "user", "id": actor_id}
    payload, event_id, decision_id = _build_package_decision_transaction(
        paths,
        package_id,
        outcome,
        reason,
        evidence,
        actor=actor,
    )
    return {
        "kind": "package_decision_review",
        "review": {
            "package_id": package_id,
            "outcome": outcome,
            "reason": reason.strip(),
            "evidence": copy.deepcopy(evidence),
        },
        "receipt": {
            "content_sha256": review_digest(payload),
            "event_id": event_id,
            "decision_id": decision_id,
        },
    }


def finalize_package_decision(
    paths: ResearchPaths,
    package_id: str,
    outcome: str,
    reason: str,
    evidence: list[dict[str, Any]],
    expected_review_sha256: str,
    *,
    actor: dict[str, str],
    review_id: str,
) -> dict[str, Any]:
    if actor.get("type") != "user":
        raise CommandRejected(
            "package-decision-user-required",
            "Package outcome requires explicit user approval",
        )
    stable_key = f"package-decide:{package_id}:{expected_review_sha256}"
    store = EventStore(paths)
    store.initialize()
    prior = store.database.event_by_idempotency_key(stable_key)
    if prior is not None:
        if (
            prior.get("event_type") != "TransactionCommitted"
            or prior.get("aggregate_type") != "package"
            or prior.get("aggregate_id") != package_id
            or prior.get("payload", {}).get("command_kind") != "PACKAGE_DECIDE"
            or prior.get("actor") != actor
            or review_digest(prior["payload"]) != expected_review_sha256
        ):
            raise CommandConflict(
                "idempotency-conflict",
                "Package decision receipt belongs to another command",
            )
        return _commit_transaction(
            paths,
            payload=copy.deepcopy(prior["payload"]),
            actor=actor,
            idempotency_key=stable_key,
            entry_skill="research-package",
            event_id=prior["event_id"],
        )
    payload, event_id, decision_id = _build_package_decision_transaction(
        paths,
        package_id,
        outcome,
        reason,
        evidence,
        actor=actor,
    )
    actual = review_digest(payload)
    if actual != expected_review_sha256:
        raise CommandConflict(
            "package-decision-review-changed",
            "Package state or outcome changed after the user review",
        )
    payload["approval"] = approval_receipt(
        action="DECIDE_PACKAGE",
        subject=package_id,
        content_sha256=actual,
        actor_id=actor["id"],
        review_id=review_id,
    )
    return _commit_transaction(
        paths,
        payload=payload,
        actor=actor,
        idempotency_key=stable_key,
        entry_skill="research-package",
        event_id=event_id,
    )


def finalize_draft_package(
    paths: ResearchPaths,
    package_id: str,
    proposal_id: str,
    expected_proposal_hash: str,
    *,
    actor: dict[str, str],
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Atomically finalize Draft, accept Scope, and activate the same Package."""
    if actor.get("type") != "user":
        raise CommandRejected(
            "package-finalization-user-required",
            "Package finalization requires explicit user approval",
        )
    if not expected_proposal_hash:
        raise CommandRejected(
            "proposal-hash-required",
            "Package finalization requires the visible proposal hash",
        )
    store = EventStore(paths)
    store.initialize()
    stable_key = idempotency_key or (
        f"package-finalize:{package_id}:{proposal_id}:{expected_proposal_hash}"
    )
    prior = next(
        (
            event
            for event in reversed(store.events())
            if event.get("idempotency_key") == stable_key
        ),
        None,
    )
    if prior is not None:
        if (
            prior.get("event_type") != "PackageActivated"
            or prior.get("aggregate_type") != "package"
            or prior.get("aggregate_id") != package_id
            or not isinstance(prior.get("payload", {}).get("scope_finalization"), dict)
        ):
            raise CommandConflict(
                "idempotency-conflict",
                "idempotency_key was already used by another command",
            )
        return _commit(
            store,
            event_type="PackageActivated",
            aggregate_type="package",
            aggregate_id=package_id,
            payload=copy.deepcopy(prior["payload"]),
            actor=actor,
            idempotency_key=stable_key,
            expected_version=prior["aggregate_version"],
            event_id=prior["event_id"],
            entry_skill="research-package",
        )

    state = store.state()
    draft = state["aggregates"]["package"].get(package_id)
    if (
        not isinstance(draft, dict)
        or draft.get("lifecycle") != "DRAFT"
        or draft.get("draftStatus") != "REFINING"
    ):
        raise CommandRejected(
            "package-refining-draft-required",
            f"Package finalization requires a REFINING Draft Package: {package_id}",
        )
    proposal = state["aggregates"]["proposal"].get(proposal_id)
    if not isinstance(proposal, dict) or proposal.get("disposition") != "PENDING":
        raise CommandRejected(
            "proposal-not-pending",
            f"Package finalization proposal is not pending: {proposal_id}",
        )
    if (
        proposal.get("proposal_kind") != "package_finalization"
        or proposal.get("proposal_hash") != expected_proposal_hash
        or proposal_content_hash(proposal) != expected_proposal_hash
    ):
        raise CommandConflict(
            "package-finalization-proposal-mismatch",
            "Package finalization does not match the visible proposal snapshot",
        )
    _validate_proposal_item(paths, proposal, state)
    source_package = _draft_source_binding(draft)
    if proposal.get("source_package") != source_package:
        raise CommandConflict(
            "scope-draft-package-stale",
            "Draft Package changed after the finalization proposal was reviewed",
        )
    direction_node = copy.deepcopy(proposal["proposed_node"])
    experiment_nodes = copy.deepcopy(proposal["proposed_experiments"])
    event_id = f"evt_pkgfinal_{_digest({'key': stable_key})[:32]}"
    direction_record = _scope_record(direction_node, proposal)
    experiment_records = [
        _scope_record(
            node,
            {
                "op": "create",
                "gate": scope_ssot.REQUIRED_GATE["experiment"],
                "trigger": f"package-finalization:{package_id}",
                "cause": proposal_id,
            },
            direction_version=int(direction_node["version"]),
        )
        for node in experiment_nodes
    ]
    bindings = []
    for index, node in enumerate(experiment_nodes):
        experiment_id = str(node["id"])
        _, patch = normalize_experiment_binding(
            package_id,
            {
                "scope_experiment_id": experiment_id,
                "local_id": f"P{index}",
                "output": (
                    f".research/experiments/{package_id}/P{index}/"
                    "<run-id>/result.json"
                ),
                "status": "READY",
                "measures": True,
                "requiresCode": False,
                "complex": False,
            },
        )
        bindings.append(
            {
                "aggregate_id": experiment_id,
                "expected_version": 0,
                "aggregate_version": 1,
                "patch": patch,
            }
        )

    finalized_draft = copy.deepcopy(draft)
    finalized_draft["draftStatus"] = "SCOPE_READY"
    spec = direction_node["spec"]
    hypothesis = str(spec.get("hypothesis") or "")
    metric = _scope_display(spec.get("metric"))
    baseline = _scope_display(spec.get("baselines"))
    gate = str(spec.get("success_gate") or "")
    active = copy.deepcopy(finalized_draft)
    active.update(
        {
            "lifecycle": "ACTIVE",
            "phase": "CONTEXT_LOADED",
            "blocker": None,
            "executionAuthorized": True,
            "direction_id": direction_node["id"],
            "sourceDirection": direction_node["id"],
            "sourceVersion": direction_node["version"],
            "sourceChange": event_id,
            "sourceExperiments": [
                {
                    "id": node["id"],
                    "version": node["version"],
                    "source": node["source"],
                }
                for node in experiment_nodes
            ],
            "scopeBinding": {
                "source_package": source_package,
                "direction_id": direction_node["id"],
                "direction_version": direction_node["version"],
                "experiment_ids": [node["id"] for node in experiment_nodes],
            },
            "problem": active.get("problem") or hypothesis,
            "objective": active.get("objective") or hypothesis,
            "hypothesis": hypothesis,
            "direction": hypothesis,
            "primaryMetric": metric,
            "baseline": baseline,
            "activeGate": gate,
            "primaryMetricVsGate": f"{metric} vs {gate}",
            "artifactRoot": active.get("artifactRoot")
            or f".research/experiments/{package_id}/",
            "runtime": active.get("runtime")
            or f".research/experiments/{package_id}/",
            "openRuns": "none",
            "lastAction": f"atomically finalized and activated from {proposal_id}",
            "lastUpdated": str(
                draft.get("lastUpdated") or draft.get("updated_at") or ""
            )[:10],
            "nextAction": f"Load Package context and run {experiment_nodes[0]['id']}",
        }
    )
    _validate_package_record(active)
    _validate_package_activation_record(active)
    accepted_snapshot = {
        key: copy.deepcopy(value)
        for key, value in proposal.items()
        if key != "disposition"
    }
    accepted_record = {
        "id": proposal_id,
        "status": "accepted",
        "decision": "ACCEPTED",
        "proposal_hash": expected_proposal_hash,
        "accepted_proposal": accepted_snapshot,
    }
    payload = {
        "record": active,
        "experiment_bindings": bindings,
        "scope_finalization": {
            "proposal": {
                "aggregate_id": proposal_id,
                "expected_version": _version(state, "proposal", proposal_id),
                "aggregate_version": _version(state, "proposal", proposal_id) + 1,
                "record": accepted_record,
            },
            "direction": {
                "aggregate_id": direction_node["id"],
                "expected_version": 0,
                "aggregate_version": 1,
                "record": direction_record,
            },
            "experiments": [
                {
                    "aggregate_id": node["id"],
                    "expected_version": 0,
                    "aggregate_version": 1,
                    "record": record,
                }
                for node, record in zip(
                    experiment_nodes,
                    experiment_records,
                    strict=True,
                )
            ],
            "source_package": source_package,
            "finalized_draft": finalized_draft,
        },
    }

    def policy(before: dict[str, Any], _command: dict[str, Any]) -> None:
        if actor.get("type") != "user":
            raise CommandRejected(
                "package-finalization-user-required",
                "Package finalization requires explicit user approval",
            )
        if before["aggregates"]["package"].get(package_id) != draft:
            raise CommandConflict(
                "scope-draft-package-stale",
                "Draft Package changed before finalization committed",
            )
        if before["aggregates"]["proposal"].get(proposal_id) != proposal:
            raise CommandConflict(
                "proposal-snapshot-mismatch",
                "Proposal changed before finalization committed",
            )
        _validate_proposal_item(paths, proposal, before)

    return _commit(
        store,
        event_type="PackageActivated",
        aggregate_type="package",
        aggregate_id=package_id,
        payload=payload,
        actor=actor,
        idempotency_key=stable_key,
        expected_version=_version(state, "package", package_id),
        event_id=event_id,
        entry_skill="research-package",
        policy=policy,
    )


def commit_package_brainstorm_transfer(
    paths: ResearchPaths,
    package_id: str,
    *,
    source_brainstorms: list[dict[str, Any]],
    docs_groups: list[dict[str, Any]],
    interface_notes: dict[str, dict[str, Any]],
    brainstorm_consumptions: list[dict[str, Any]],
    expected_version: int,
    actor: dict[str, str],
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Atomically transfer Brainstorm documents into an existing Package."""
    if actor.get("type") != "user":
        raise CommandRejected(
            "package-brainstorm-transfer-user-required",
            "repairing an existing Package conversion requires an explicit user actor",
        )
    operations = [
        {
            "operation": "set",
            "target": "sourceBrainstorms",
            "value": copy.deepcopy(source_brainstorms),
        },
        {
            "operation": "set",
            "target": "docsGroups",
            "value": copy.deepcopy(docs_groups),
        },
        {
            "operation": "set",
            "target": "interface_notes",
            "value": copy.deepcopy(interface_notes),
        },
        {
            "operation": "set",
            "target": "lastUpdated",
            "value": datetime.now(timezone.utc).date().isoformat(),
        },
    ]
    payload = {
        "operations": operations,
        "brainstorm_consumptions": copy.deepcopy(brainstorm_consumptions),
    }
    store = EventStore(paths)

    def policy(state: dict[str, Any], _command: dict[str, Any]) -> None:
        current = state["aggregates"]["package"].get(package_id)
        if not isinstance(current, dict):
            raise CommandRejected(
                "package-not-found",
                f"unknown Package: {package_id}",
            )
        final_package = copy.deepcopy(current)
        final_package["sourceBrainstorms"] = copy.deepcopy(source_brainstorms)
        final_package["docsGroups"] = copy.deepcopy(docs_groups)
        final_package["interface_notes"] = copy.deepcopy(interface_notes)
        _validate_brainstorm_consumptions(
            state,
            final_package,
            brainstorm_consumptions,
        )

    return _commit(
        store,
        event_type="PackageMutationApplied",
        aggregate_type="package",
        aggregate_id=package_id,
        payload=payload,
        actor=copy.deepcopy(actor),
        idempotency_key=idempotency_key
        or f"package:brainstorm-transfer:{package_id}:{_digest(payload)}",
        expected_version=expected_version,
        entry_skill="research-package",
        policy=policy,
    )


def _package_policy(
    *,
    package_id: str,
    operation: str,
    target: str,
):
    def policy(before: dict[str, Any], _command: dict[str, Any]) -> None:
        package = _package(before, package_id)
        legal = (
            lifecycle_policy.is_legal(package, operation, target)
            if lifecycle_policy.uses_capability_policy(package)
            else state_policy.is_legal(
                str(package.get("lifecycle")),
                package.get("phase"),
                package.get("blocker"),
                operation,
                target,
            )
        )
        if not legal:
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
    elif operation == "update" and target == "abstract":
        value = payload.get("to")
        if not isinstance(value, str) or not value.strip():
            raise CommandRejected(
                "package-abstract-required",
                "Package abstract must be a non-empty English paragraph",
            )
        abstract = " ".join(value.split())
        if not abstract.isascii() or re.search(r"[A-Za-z]", abstract) is None:
            raise CommandRejected(
                "package-abstract-english-required",
                "Package abstract must use clear natural English",
            )
        if len(abstract.split()) > 150:
            raise CommandRejected(
                "package-abstract-too-long",
                "Package abstract must contain at most 150 words",
            )
        direction = state["aggregates"]["direction"].get(
            package.get("direction_id")
        )
        direction_spec = (
            direction.get("spec")
            if isinstance(direction, dict) and isinstance(direction.get("spec"), dict)
            else {}
        )
        source_texts = [
            package.get("problem"),
            package.get("objective"),
            package.get("direction"),
            package.get("hypothesis"),
            direction_spec.get("hypothesis"),
        ]
        if abstract.casefold() in {
            " ".join(str(text).split()).casefold()
            for text in source_texts
            if str(text or "").strip()
        }:
            raise CommandRejected(
                "package-abstract-not-distinct",
                "Package abstract must summarize the whole Package instead of "
                "reusing its problem, objective, or Direction hypothesis",
            )
        operations = [
            {"operation": "set", "target": "abstract", "value": abstract}
        ]
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
