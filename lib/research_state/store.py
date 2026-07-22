"""Locked event append, command audit, recovery, and content-addressed notes."""

from __future__ import annotations

import copy
import fcntl
import hashlib
import re
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from .database import (
    DatabaseBusy,
    StateDatabase,
    bootstrap_database,
)
from .io import (
    append_jsonl_fsync,
    canonical_json,
    read_json,
    read_jsonl,
    write_bytes_atomic,
    write_json_atomic,
)
from .paths import ResearchPaths, UpgradeRequired
from .reducer import EventIntegrityError, apply_event, event_hash, fold
from .schema import SchemaViolation, load_schema, validate_event_shape


class LockBusy(RuntimeError):
    """The management writer lock could not be obtained before timeout."""


class CommandRejected(ValueError):
    """A command failed schema or policy validation before state append."""

    def __init__(self, rule: str, detail: str):
        self.rule = rule
        self.detail = detail
        self.audited = False
        super().__init__(detail)


class CommandConflict(CommandRejected):
    """The caller supplied a stale expected aggregate version."""


class ProjectionFailed(RuntimeError):
    """State committed, but its rebuildable interface projection failed."""

    def __init__(
        self,
        detail: str,
        *,
        committed_event: dict[str, Any] | None = None,
    ):
        self.committed_event = copy.deepcopy(committed_event)
        super().__init__(detail)


Policy = Callable[[dict[str, Any], dict[str, Any]], None]
Renderer = Callable[[], list[str] | None]

SENSITIVE_KEYS = {
    "access_token",
    "api_key",
    "argv",
    "authorization",
    "cmd",
    "command",
    "cookie",
    "env",
    "environment",
    "password",
    "private_key",
    "secret",
    "token",
}
SCOPE_AGGREGATES = {"project", "direction", "experiment"}
GENERIC_AGGREGATE_EVENTS = {
    "AggregateUpserted",
    "AggregatePatched",
    "AggregateRemoved",
}
SCOPE_COMMIT_EVENTS = {"ScopeCommitted", "ExperimentSpecRevised"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _parse_time(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def _redact(value: Any, key: str = "") -> Any:
    snake = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key).lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", snake).strip("_")
    compact = normalized.replace("_", "")
    sensitive_compact = {name.replace("_", "") for name in SENSITIVE_KEYS}
    parts = set(normalized.split("_"))
    if (
        normalized in SENSITIVE_KEYS
        or compact in sensitive_compact
        or parts.intersection(
            {
                "argv",
                "authorization",
                "cmd",
                "command",
                "cookie",
                "env",
                "environment",
                "password",
                "secret",
                "token",
            }
        )
    ):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): _redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _payload_digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _validate_scope_proposal_binding(
    *,
    events: list[dict[str, Any]],
    state: dict[str, Any],
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    payload: dict[str, Any],
    causation_id: str | None,
) -> CommandRejected | None:
    """Validate the accepted snapshot at the lowest management write boundary."""
    accepted_event = next(
        (
            event
            for event in events
            if event.get("event_id") == causation_id
            and event.get("event_type") == "ProposalAccepted"
        ),
        None,
    )
    if accepted_event is None:
        return CommandRejected(
            "proposal-causation-required",
            "semantic Scope events require a ProposalAccepted causation_id",
        )
    binding = payload.get("proposal_binding")
    accepted_record = accepted_event.get("payload", {}).get("record")
    if not isinstance(binding, dict) or not isinstance(accepted_record, dict):
        return CommandRejected(
            "proposal-binding-required",
            "semantic Scope events require an embedded accepted-proposal binding",
        )
    proposal_id = accepted_event.get("aggregate_id")
    proposal_hash = accepted_record.get("proposal_hash")
    accepted_snapshot = accepted_record.get("accepted_proposal")
    current_proposal = state["aggregates"]["proposal"].get(proposal_id)
    if (
        binding.get("proposal_id") != proposal_id
        or binding.get("proposal_hash") != proposal_hash
        or not isinstance(accepted_snapshot, dict)
        or not isinstance(current_proposal, dict)
        or current_proposal.get("disposition") != "ACCEPTED"
        or current_proposal.get("proposal_hash") != proposal_hash
        or current_proposal.get("accepted_proposal") != accepted_snapshot
    ):
        return CommandConflict(
            "proposal-binding-mismatch",
            "semantic Scope event does not match the current accepted proposal",
        )
    node = accepted_snapshot.get("proposed_node")
    if (
        not isinstance(node, dict)
        or binding.get("proposed_node") != node
        or binding.get("op") != accepted_snapshot.get("op")
        or binding.get("gate") != accepted_snapshot.get("gate")
        or any(
            sorted(binding.get(field) or [])
            != sorted(accepted_snapshot.get(field) or [])
            for field in ("invalidates", "reopens", "dial_revert")
        )
    ):
        return CommandConflict(
            "proposal-binding-snapshot-mismatch",
            "semantic Scope event differs from the accepted proposal snapshot",
        )
    level = node.get("level")
    expected_owner = "experiment" if level == "experiment" else level
    if (
        expected_owner != aggregate_type
        or node.get("id") != aggregate_id
        or (
            event_type == "ScopeCommitted"
            and level not in {"project", "direction"}
        )
        or (
            event_type == "ExperimentSpecRevised"
            and level != "experiment"
        )
    ):
        return CommandRejected(
            "scope-event-owner-invalid",
            "semantic Scope event owner does not match proposed_node",
        )
    required_gate = load_schema()["scope"]["required_gate"].get(level)
    if binding.get("gate") != required_gate:
        return CommandRejected(
            "scope-gate",
            f"{level} transition requires gate {required_gate!r}",
        )
    body = payload.get("record")
    if not isinstance(body, dict):
        body = payload.get("patch")
    if not isinstance(body, dict):
        return CommandRejected(
            "scope-event-payload-invalid",
            "semantic Scope event requires record or patch",
        )
    if level in {"project", "direction"}:
        canonical_fields = {
            "id",
            "level",
            "parents",
            "version",
            "status",
            "spec",
            "source",
        }
        if any(body.get(field) != node.get(field) for field in canonical_fields):
            return CommandConflict(
                "scope-record-proposal-mismatch",
                "Scope record differs from its accepted proposed_node",
            )
    else:
        direction_id = (node.get("parents") or [None])[0]
        direction = state["aggregates"]["direction"].get(direction_id)
        expected = {
            "id": node.get("id"),
            "direction_id": direction_id,
            "spec": node.get("spec"),
            "scope_version": node.get("version"),
            "scope_status": node.get("status"),
            "scope_confirmation": "CONFIRMED",
            "scope_source": node.get("source"),
            "confirmed_direction_version": (
                direction.get("version") if isinstance(direction, dict) else None
            ),
        }
        if any(body.get(field) != value for field, value in expected.items()):
            return CommandConflict(
                "experiment-record-proposal-mismatch",
                "Experiment.spec record differs from its accepted proposed_node",
            )
    return None


def _validate_experiment_status_semantics(
    *,
    events: list[dict[str, Any]],
    state: dict[str, Any],
    aggregate_id: str,
    payload: dict[str, Any],
    causation_id: str | None,
) -> CommandRejected | None:
    """Keep status events from becoming an alternate Experiment.spec writer."""
    patch = payload.get("patch")
    if not isinstance(patch, dict):
        return CommandRejected(
            "experiment-status-patch-required",
            "ExperimentStatusChanged requires a patch",
        )
    scope_fields = {
        "confirmed_direction_version",
        "scope_confirmation",
        "scope_status",
        "spec",
        "stale_direction_version",
        "status_before_scope_stale",
    }
    touched_scope = scope_fields.intersection(patch)
    cause = next(
        (event for event in events if event.get("event_id") == causation_id),
        None,
    )
    if touched_scope:
        if (
            not isinstance(cause, dict)
            or cause.get("event_type") != "ScopeCommitted"
            or cause.get("aggregate_type") != "direction"
        ):
            return CommandRejected(
                "scope-effect-causation-required",
                "Experiment scope effects require a causal Direction "
                "ScopeCommitted event",
            )
        binding = cause.get("payload", {}).get("proposal_binding")
        if not isinstance(binding, dict):
            return CommandRejected(
                "scope-effect-binding-required",
                "causal Direction event has no accepted proposal binding",
            )
        explicit_effect_targets = {
            str(item)
            for field in ("invalidates", "reopens", "dial_revert")
            for item in (binding.get(field) or [])
        }
        current = state["aggregates"]["experiment"].get(aggregate_id)
        # A committed Direction revision necessarily invalidates every
        # Experiment still confirmed against an older version of that same
        # Direction.  Explicit lists remain required for reopen and dial
        # operations, but the ordinary stale fan-out is derived from the
        # accepted Direction record instead of requiring the proposal to
        # enumerate a potentially changing child set.
        direction_record = cause.get("payload", {}).get("record")
        direction_id = cause.get("aggregate_id")
        implicit_stale_target = (
            isinstance(current, dict)
            and current.get("direction_id") == direction_id
            and patch.get("scope_confirmation", "STALE") == "STALE"
            and patch.get("status", "BLOCKED") == "BLOCKED"
        )
        if aggregate_id not in explicit_effect_targets and not implicit_stale_target:
            return CommandRejected(
                "scope-effect-target-unbound",
                f"Direction proposal does not authorize effects on {aggregate_id}",
            )
        direction_version = (
            direction_record.get("version")
            if isinstance(direction_record, dict)
            else None
        )
        if (
            patch.get("scope_confirmation", "STALE") != "STALE"
            or patch.get("status", "BLOCKED") != "BLOCKED"
            or (
                "stale_direction_version" in patch
                and patch["stale_direction_version"] != direction_version
            )
            or (
                "confirmed_direction_version" in patch
                and (
                    not isinstance(direction_version, int)
                    or patch["confirmed_direction_version"]
                    != direction_version - 1
                )
            )
        ):
            return CommandRejected(
                "scope-effect-reconfirmation-forbidden",
                "Direction propagation may only mark an Experiment STALE and "
                "BLOCKED; reconfirmation requires a new accepted Experiment "
                "proposal",
            )
        if "spec" in patch:
            dial_targets = {str(item) for item in binding.get("dial_revert") or []}
            if aggregate_id not in dial_targets:
                return CommandRejected(
                    "scope-spec-effect-unbound",
                    f"Direction proposal does not authorize spec reset for "
                    f"{aggregate_id}",
                )
            current = state["aggregates"]["experiment"].get(aggregate_id)
            current_spec = (
                current.get("spec") if isinstance(current, dict) else None
            )
            proposed_spec = patch.get("spec")
            if (
                not isinstance(current_spec, dict)
                or not isinstance(proposed_spec, dict)
                or set(proposed_spec) != set(current_spec)
                or any(
                    proposed_spec.get(field) != value
                    for field, value in current_spec.items()
                    if field != "control_mode"
                )
                or proposed_spec.get("control_mode") != "SUPERVISED"
            ):
                return CommandRejected(
                    "scope-spec-effect-invalid",
                    "Direction dial_revert may only reset control_mode to "
                    "SUPERVISED",
                )
    result_fields = {"latest_result_run_id", "latest_result_sha256"}
    if result_fields.intersection(patch) and (
        not isinstance(cause, dict)
        or cause.get("event_type") != "PackageMutationApplied"
        or not isinstance(cause.get("payload", {}).get("witness"), dict)
    ):
        return CommandRejected(
            "experiment-result-causation-required",
            "Experiment result summary requires a causal package result event",
        )
    return None


@contextmanager
def management_lock(path: Path, *, timeout: float = 5.0, retry_interval: float = 0.05) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as exc:
                if time.monotonic() >= deadline:
                    raise LockBusy(
                        f"research state is busy after {timeout:.2f}s: {path}"
                    ) from exc
                time.sleep(retry_interval)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class EventStore:
    """The sole writer for management state and command audit."""

    def __init__(self, paths: ResearchPaths, *, fixture_mode: bool = False):
        """Create a store; ``fixture_mode`` is only for deterministic test data."""
        self.paths = paths
        self.fixture_mode = fixture_mode
        self.database = StateDatabase(paths.database)

    def initialize(self) -> list[Path]:
        created = self.paths.initialize()
        # Bootstrap the transactional authority from a pre-kernel JSONL ledger
        # once. JSONL and current.json remain rebuildable compatibility exports.
        with management_lock(self.paths.state_lock):
            database_created = bootstrap_database(
                self.database,
                events_path=self.paths.events,
                audit_path=self.paths.audit_actions,
            )
            if database_created:
                created.append(self.paths.database)
            state = self.database.state()
            if state.get("source_seq") and not self.paths.events.exists():
                write_bytes_atomic(
                    self.paths.events,
                    self._jsonl_bytes(self.database.events()),
                )
                created.append(self.paths.events)
            if not self.paths.current.exists():
                write_json_atomic(self.paths.current, state)
                created.append(self.paths.current)
            else:
                current = read_json(self.paths.current)
                if (
                    current.get("source_seq") != state.get("source_seq")
                    or current.get("source_hash") != state.get("source_hash")
                ):
                    # A prior command committed in SQLite but did not finish
                    # its rebuildable exports. Repair once on the next entry.
                    self._sync_compatibility_exports()
            if not self.paths.audit_actions.exists() and self.database.audit():
                write_bytes_atomic(
                    self.paths.audit_actions,
                    self._jsonl_bytes(self.database.audit()),
                )
                created.append(self.paths.audit_actions)
        return created

    def events(self) -> list[dict[str, Any]]:
        if self.paths.database.exists():
            return self.database.events()
        return read_jsonl(self.paths.events)

    def snapshot(
        self,
        *,
        verify_projection: bool = True,
        include_audit: bool = False,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        """Read one transactional snapshot and optionally verify JSON exports."""
        if self.paths.load_version() is None:
            raise UpgradeRequired(
                f"research state is not initialized at {self.paths.root}; "
                "initialize it with research-init"
            )
        with management_lock(self.paths.state_lock):
            authoritative, events, audit = self.database.snapshot(
                include_audit=include_audit,
            )
            if verify_projection and self.paths.events.exists():
                exported_events = read_jsonl(self.paths.events)
                if exported_events != events:
                    # Replay only a drifting export. Normal reads are O(1) in
                    # state size and never refold the complete ledger.
                    fold(exported_events)
                    raise CommandRejected(
                        "event-export-drift",
                        f"{self.paths.events} does not match {self.paths.database}",
                    )
            if self.paths.current.exists():
                projection = read_json(self.paths.current)
                if verify_projection and projection != authoritative:
                    raise CommandRejected(
                        "projection-drift",
                        f"{self.paths.current} does not match "
                        f"{self.paths.database}",
                    )
                state = projection
            else:
                state = authoritative
        return state, events, audit

    def state(self, *, verify_projection: bool = True) -> dict[str, Any]:
        """Read current authority without loading or replaying event history.

        The event ledger is verified by ``snapshot`` and ``recover`` when an
        audit-strength read is requested. Normal commands and projections only
        need the transactional current state, so their cost does not grow with
        the number of prior events.
        """
        if self.paths.load_version() is None:
            raise UpgradeRequired(
                f"research state is not initialized at {self.paths.root}; "
                "initialize it with research-init"
            )
        with management_lock(self.paths.state_lock):
            authoritative = self.database.state()
            if verify_projection and self.paths.current.exists():
                projection = read_json(self.paths.current)
                if projection != authoritative:
                    raise CommandRejected(
                        "projection-drift",
                        f"{self.paths.current} does not match "
                        f"{self.paths.database}",
                    )
        return authoritative

    def commit(
        self,
        *,
        event_type: str,
        aggregate_type: str,
        aggregate_id: str,
        payload: dict[str, Any],
        actor: dict[str, str],
        idempotency_key: str,
        expected_version: int | None = None,
        causation_id: str | None = None,
        command_id: str | None = None,
        event_id: str | None = None,
        entry_skill: str | None = None,
        policy: Policy | None = None,
        render: Renderer | None = None,
        lock_timeout: float = 5.0,
    ) -> dict[str, Any]:
        self.initialize()
        command_id = command_id or f"cmd_{uuid.uuid4().hex}"
        started = time.monotonic()
        committed: dict[str, Any] | None = None
        projection_before_version: int | None = None
        projection_after_version: int | None = None
        with management_lock(self.paths.state_lock, timeout=lock_timeout):
            before = self.database.state()
            before_version = int(
                before["aggregate_versions"].get(f"{aggregate_type}/{aggregate_id}", 0)
            )
            prior = (
                self.database.event_by_idempotency_key(idempotency_key)
                if isinstance(idempotency_key, str) and idempotency_key
                else None
            )
            needs_history = (
                event_type in SCOPE_COMMIT_EVENTS
                or event_type == "ExperimentStatusChanged"
                or (
                    event_type == "PackageActivated"
                    and isinstance(payload, dict)
                    and "reopen_reactivation" in payload
                )
            )
            events = self.events() if needs_history else []

            command_error: CommandRejected | None = None
            if not isinstance(idempotency_key, str) or not idempotency_key.strip():
                command_error = CommandRejected(
                    "idempotency-key-required", "idempotency_key is required"
                )
            elif event_type not in load_schema()["event_types"]:
                command_error = CommandRejected(
                    "event-type-unknown", f"unknown event_type: {event_type}"
                )
            elif event_type == "AggregateImported" and not self.fixture_mode:
                command_error = CommandRejected(
                    "historical-import-read-only",
                    "AggregateImported is retained for replay and fixture seeding only",
                )
            elif (
                event_type == "ExperimentBoundToPackage"
                and not self.fixture_mode
            ):
                command_error = CommandRejected(
                    "atomic-package-event-required",
                    "Experiment bindings must be committed atomically through "
                    "PackageMaterialized or PackageExperimentBound",
                )
            elif (
                not self.fixture_mode
                and aggregate_type in SCOPE_AGGREGATES
                and event_type in GENERIC_AGGREGATE_EVENTS
            ):
                command_error = CommandRejected(
                    "scope-semantic-event-required",
                    "Project, Direction, and Experiment.spec may only change "
                    "through a ProposalAccepted-bound semantic Scope event",
                )
            elif event_type == "ScopeCommitted" and aggregate_type not in {
                "project",
                "direction",
            }:
                command_error = CommandRejected(
                    "scope-event-owner-invalid",
                    "ScopeCommitted owns only Project and Direction aggregates",
                )
            elif (
                not self.fixture_mode
                and event_type in SCOPE_COMMIT_EVENTS
                and (
                    not isinstance(causation_id, str)
                    or not any(
                        event.get("event_id") == causation_id
                        and event.get("event_type") == "ProposalAccepted"
                        for event in events
                    )
                )
            ):
                command_error = CommandRejected(
                    "proposal-causation-required",
                    "semantic Scope events require a ProposalAccepted causation_id",
                )
            elif (
                event_type in {"ProposalAccepted", "ProposalRejected"}
                and not self.fixture_mode
                and (
                    not isinstance(actor, dict)
                    or actor.get("type") != "user"
                )
            ):
                command_error = CommandRejected(
                    "proposal-disposition-user-required",
                    "only an explicit user actor may dispose a Scope proposal",
                )
            elif (
                event_type == "PackageActivated"
                and isinstance(payload, dict)
                and (
                    "scope_finalization" in payload
                    or "reopen_reactivation" in payload
                )
                and (
                    not isinstance(actor, dict)
                    or actor.get("type") != "user"
                )
            ):
                command_error = CommandRejected(
                    "package-finalization-user-required",
                    "Package finalization or reopen reactivation requires an explicit user actor",
                )
            elif (
                event_type == "PackageActivated"
                and isinstance(payload, dict)
                and "reopen_reactivation" in payload
                and (
                    not isinstance(causation_id, str)
                    or not any(
                        event.get("event_id") == causation_id
                        and event.get("event_type") == "PackageReopenedAsDraft"
                        and event.get("aggregate_type") == "package"
                        and event.get("aggregate_id") == aggregate_id
                        for event in events
                    )
                )
            ):
                command_error = CommandRejected(
                    "package-reopen-causation-required",
                    "reopen reactivation must name the PackageReopenedAsDraft event it reverses",
                )
            elif aggregate_type not in load_schema()["aggregate_types"]:
                command_error = CommandRejected(
                    "aggregate-type-unknown", f"unknown aggregate_type: {aggregate_type}"
                )
            elif (
                event_type == "DecisionRecorded"
                and before_version != 0
                and prior is None
            ):
                command_error = CommandRejected(
                    "decision-immutable",
                    "Decision identities are immutable; record a new Decision id",
                )
            elif not isinstance(payload, dict):
                command_error = CommandRejected(
                    "payload-invalid", "payload must be a JSON object"
                )
            elif "_migration" in payload and not self.fixture_mode:
                command_error = CommandRejected(
                    "historical-import-read-only",
                    "migration-marked events are retained for replay and fixture seeding only",
                )
            if (
                command_error is None
                and not self.fixture_mode
                and event_type in SCOPE_COMMIT_EVENTS
            ):
                command_error = _validate_scope_proposal_binding(
                    events=events,
                    state=before,
                    event_type=event_type,
                    aggregate_type=aggregate_type,
                    aggregate_id=aggregate_id,
                    payload=payload,
                    causation_id=causation_id,
                )
            if (
                command_error is None
                and not self.fixture_mode
                and event_type == "ExperimentStatusChanged"
            ):
                command_error = _validate_experiment_status_semantics(
                    events=events,
                    state=before,
                    aggregate_id=aggregate_id,
                    payload=payload,
                    causation_id=causation_id,
                )
            if command_error is not None:
                self._audit_rejected(
                    command_id,
                    str(idempotency_key or ""),
                    event_type,
                    aggregate_type,
                    aggregate_id,
                    actor,
                    entry_skill,
                    payload if isinstance(payload, dict) else {"invalid_payload": payload},
                    before_version,
                    command_error.rule,
                    command_error.detail,
                    started,
                )
                command_error.audited = True
                raise command_error

            if prior is not None:
                if (
                    prior["event_type"],
                    prior["aggregate_type"],
                    prior["aggregate_id"],
                    prior["payload"],
                ) != (event_type, aggregate_type, aggregate_id, payload):
                    self._audit_rejected(
                        command_id,
                        idempotency_key,
                        event_type,
                        aggregate_type,
                        aggregate_id,
                        actor,
                        entry_skill,
                        payload,
                        before_version,
                        "idempotency-conflict",
                        "idempotency_key was already committed with different content",
                        started,
                    )
                    conflict = CommandConflict(
                        "idempotency-conflict",
                        "idempotency_key was already committed with different content",
                    )
                    conflict.audited = True
                    raise conflict
                self._audit(
                    outcome="COMMAND_COMMITTED",
                    command_id=command_id,
                    idempotency_key=idempotency_key,
                    event_type=event_type,
                    aggregate_type=aggregate_type,
                    aggregate_id=aggregate_id,
                    actor=actor,
                    entry_skill=entry_skill,
                    payload=payload,
                    state_before_version=before_version,
                    state_after_version=before_version,
                    domain_event_id=prior["event_id"],
                    validation="IDEMPOTENT",
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
                committed = copy.deepcopy(prior)
                projection_before_version = before_version
                projection_after_version = before_version
            else:
                if event_id is not None and self.database.event_by_id(event_id) is not None:
                    detail = f"event_id is already present: {event_id}"
                    self._audit_rejected(
                        command_id,
                        idempotency_key,
                        event_type,
                        aggregate_type,
                        aggregate_id,
                        actor,
                        entry_skill,
                        payload,
                        before_version,
                        "event-id-conflict",
                        detail,
                        started,
                    )
                    conflict = CommandConflict("event-id-conflict", detail)
                    conflict.audited = True
                    raise conflict
                if expected_version is not None and expected_version != before_version:
                    detail = (
                        f"expected aggregate version {expected_version}, "
                        f"current version is {before_version}"
                    )
                    self._audit_rejected(
                        command_id,
                        idempotency_key,
                        event_type,
                        aggregate_type,
                        aggregate_id,
                        actor,
                        entry_skill,
                        payload,
                        before_version,
                        "expected-version-conflict",
                        detail,
                        started,
                    )
                    conflict = CommandConflict("expected-version-conflict", detail)
                    conflict.audited = True
                    raise conflict
                command = {
                    "event_type": event_type,
                    "aggregate_type": aggregate_type,
                    "aggregate_id": aggregate_id,
                    "payload": payload,
                    "actor": actor,
                    "idempotency_key": idempotency_key,
                    "expected_version": expected_version,
                }
                try:
                    if policy is not None:
                        policy(before, command)
                except CommandRejected as exc:
                    self._audit_rejected(
                        command_id,
                        idempotency_key,
                        event_type,
                        aggregate_type,
                        aggregate_id,
                        actor,
                        entry_skill,
                        payload,
                        before_version,
                        exc.rule,
                        exc.detail,
                        started,
                    )
                    exc.audited = True
                    raise
                except (SchemaViolation, ValueError) as exc:
                    rejected = CommandRejected("policy-invalid", str(exc))
                    self._audit_rejected(
                        command_id,
                        idempotency_key,
                        event_type,
                        aggregate_type,
                        aggregate_id,
                        actor,
                        entry_skill,
                        payload,
                        before_version,
                        rejected.rule,
                        rejected.detail,
                        started,
                    )
                    rejected.audited = True
                    raise rejected from exc
                event = {
                    "seq": int(before.get("source_seq", 0)) + 1,
                    "event_id": event_id or f"evt_{uuid.uuid4().hex}",
                    "schema_version": 1,
                    "event_type": event_type,
                    "aggregate_type": aggregate_type,
                    "aggregate_id": aggregate_id,
                    "aggregate_version": before_version + 1,
                    "command_id": command_id,
                    "idempotency_key": idempotency_key,
                    "causation_id": causation_id,
                    "actor": actor,
                    "occurred_at": _now(),
                    "payload": copy.deepcopy(payload),
                    "prev_hash": str(before.get("source_hash", "")),
                }
                event["hash"] = event_hash(event)
                # Validate only the next transition against the transactional
                # snapshot. Full replay remains an explicit integrity check.
                try:
                    validate_event_shape(event)
                    if event["seq"] != int(before.get("source_seq", 0)) + 1:
                        raise EventIntegrityError("event seq does not advance current state")
                    if event["prev_hash"] != str(before.get("source_hash", "")):
                        raise EventIntegrityError("event prev_hash does not match current state")
                    after = apply_event(before, event)
                except (EventIntegrityError, SchemaViolation) as exc:
                    self._audit_rejected(
                        command_id,
                        idempotency_key,
                        event_type,
                        aggregate_type,
                        aggregate_id,
                        actor,
                        entry_skill,
                        payload,
                        before_version,
                        "event-invalid",
                        str(exc),
                        started,
                    )
                    rejected = CommandRejected("event-invalid", str(exc))
                    rejected.audited = True
                    raise rejected from exc
                audit_row = self._audit_row(
                    outcome="COMMAND_COMMITTED",
                    command_id=command_id,
                    idempotency_key=idempotency_key,
                    event_type=event_type,
                    aggregate_type=aggregate_type,
                    aggregate_id=aggregate_id,
                    actor=actor,
                    entry_skill=entry_skill,
                    payload=payload,
                    state_before_version=before_version,
                    state_after_version=before_version + 1,
                    domain_event_id=event["event_id"],
                    files_touched=[str(self.paths.database)],
                    validation="PASSED",
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
                try:
                    self.database.apply_command(
                        event=event,
                        state=after,
                        audit_row=audit_row,
                    )
                except DatabaseBusy as exc:
                    raise LockBusy(str(exc)) from exc
                self._sync_commit_exports(event, after, audit_row)
                committed = event
                projection_before_version = before_version
                projection_after_version = before_version + 1

        assert committed is not None
        assert projection_before_version is not None
        assert projection_after_version is not None
        if render is not None:
            try:
                touched = render() or []
            except Exception as exc:
                with management_lock(self.paths.state_lock):
                    self._audit(
                        outcome="PROJECTION_FAILED",
                        command_id=command_id,
                        idempotency_key=idempotency_key,
                        event_type=event_type,
                        aggregate_type=aggregate_type,
                        aggregate_id=aggregate_id,
                        actor=actor,
                        entry_skill=entry_skill,
                        payload={},
                        state_before_version=projection_before_version,
                        state_after_version=projection_after_version,
                        domain_event_id=committed["event_id"],
                        validation="STATE_COMMITTED_PROJECTION_STALE",
                        rejection_reason={
                            "rule": "projection-failed",
                            "detail": str(exc),
                        },
                        duration_ms=int((time.monotonic() - started) * 1000),
                    )
                raise ProjectionFailed(
                    f"state committed as {committed['event_id']}, but interface rebuild failed: {exc}",
                    committed_event=committed,
                ) from exc
            with management_lock(self.paths.state_lock):
                self._audit(
                    outcome="PROJECTION_RENDERED",
                    command_id=command_id,
                    idempotency_key=idempotency_key,
                    event_type=event_type,
                    aggregate_type=aggregate_type,
                    aggregate_id=aggregate_id,
                    actor=actor,
                    entry_skill=entry_skill,
                    payload={},
                    state_before_version=projection_before_version,
                    state_after_version=projection_after_version,
                    domain_event_id=committed["event_id"],
                    validation="PASSED",
                    files_touched=[str(path) for path in touched],
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
        return committed

    def write_note(
        self,
        content: str | bytes,
        *,
        mime: str = "text/markdown",
        title: str = "",
    ) -> dict[str, Any]:
        self.initialize()
        raw = content.encode("utf-8") if isinstance(content, str) else content
        digest = hashlib.sha256(raw).hexdigest()
        # NoteRef has one content identity independent of its MIME type.  The
        # schema deliberately fixes every note URI to <sha256>.md so the same
        # bytes cannot acquire parallel ".md" and ".blob" identities.
        path = self.paths.note(digest)
        if path.exists():
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != digest:
                raise CommandRejected(
                    "note-content-drift",
                    f"content-addressed note does not match its path: {path}",
                )
        else:
            write_bytes_atomic(path, raw)
        return {
            "uri": str(path.relative_to(self.paths.root)),
            "sha256": digest,
            "mime": mime,
            "title": title,
        }

    def record_rejected_attempt(
        self,
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
        """Audit a facade rejection that occurred before a domain commit call."""
        self.initialize()
        selected_command_id = command_id or f"cmd_{uuid.uuid4().hex}"
        selected_key = idempotency_key or (
            f"rejected:{command_name}:{_payload_digest(payload)}"
        )
        started = time.monotonic()
        with management_lock(self.paths.state_lock):
            before = self.database.state()
            version = int(before.get("source_seq") or 0)
            self._audit_rejected(
                selected_command_id,
                selected_key,
                "CommandAttempted",
                "command",
                command_name,
                actor,
                entry_skill,
                payload,
                version,
                rule,
                detail,
                started,
            )
        return selected_command_id

    def recover(self, *, lease_seconds: float = 30.0) -> dict[str, int]:
        """Verify SQLite authority and rebuild compatibility exports.

        Atomic local commands no longer emit a pending audit row, so there are
        no received-only attempts to reconcile. External work uses Run state.
        """
        self.initialize()
        with management_lock(self.paths.state_lock):
            self.database.verify()
            self._sync_compatibility_exports()
        return {"recovered": 0, "interrupted": 0}

    def _audit_rejected(
        self,
        command_id: str,
        idempotency_key: str,
        event_type: str,
        aggregate_type: str,
        aggregate_id: str,
        actor: dict[str, str],
        entry_skill: str | None,
        payload: dict[str, Any],
        before_version: int,
        rule: str,
        detail: Any,
        started: float,
    ) -> None:
        self._audit(
            outcome="COMMAND_REJECTED",
            command_id=command_id,
            idempotency_key=idempotency_key,
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            actor=actor,
            entry_skill=entry_skill,
            payload=payload,
            state_before_version=before_version,
            state_after_version=before_version,
            validation="OP_REJECTED",
            rejection_reason={"rule": rule, "detail": detail},
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    def _audit(
        self,
        *,
        outcome: str,
        command_id: str,
        idempotency_key: str,
        event_type: str,
        aggregate_type: str,
        aggregate_id: str,
        actor: dict[str, str],
        entry_skill: str | None,
        payload: dict[str, Any],
        state_before_version: int,
        state_after_version: int,
        duration_ms: int,
        domain_event_id: str | None = None,
        validation: str | None = None,
        rejection_reason: dict[str, Any] | None = None,
        files_touched: list[str] | None = None,
    ) -> None:
        row = self._audit_row(
            outcome=outcome,
            command_id=command_id,
            idempotency_key=idempotency_key,
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            actor=actor,
            entry_skill=entry_skill,
            payload=payload,
            state_before_version=state_before_version,
            state_after_version=state_after_version,
            duration_ms=duration_ms,
            domain_event_id=domain_event_id,
            validation=validation,
            rejection_reason=rejection_reason,
            files_touched=files_touched,
        )
        self.database.append_audit(row)
        append_jsonl_fsync(self.paths.audit_actions, row)

    def _audit_row(
        self,
        *,
        outcome: str,
        command_id: str,
        idempotency_key: str,
        event_type: str,
        aggregate_type: str,
        aggregate_id: str,
        actor: dict[str, str],
        entry_skill: str | None,
        payload: dict[str, Any],
        state_before_version: int,
        state_after_version: int,
        duration_ms: int,
        domain_event_id: str | None = None,
        validation: str | None = None,
        rejection_reason: dict[str, Any] | None = None,
        files_touched: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "audit_id": f"aud_{uuid.uuid4().hex}",
            "occurred_at": _now(),
            "outcome": outcome,
            "command_id": command_id,
            "idempotency_key": idempotency_key,
            "event_type": event_type,
            "aggregate_type": aggregate_type,
            "aggregate_id": aggregate_id,
            "actor": actor,
            "entry_skill": entry_skill,
            "payload_sha256": _payload_digest(payload),
            "payload": _redact(payload),
            "state_before_version": state_before_version,
            "state_after_version": state_after_version,
            "domain_event_id": domain_event_id,
            "validation": validation,
            "rejection_reason": (
                _redact(rejection_reason)
                if rejection_reason is not None
                else None
            ),
            "files_touched": files_touched or [],
            "duration_ms": duration_ms,
        }

    @staticmethod
    def _jsonl_bytes(rows: list[dict[str, Any]]) -> bytes:
        if not rows:
            return b""
        return ("\n".join(canonical_json(row) for row in rows) + "\n").encode(
            "utf-8"
        )

    def _sync_audit_export(self) -> None:
        rows = self.database.audit()
        if rows:
            write_bytes_atomic(self.paths.audit_actions, self._jsonl_bytes(rows))

    def _sync_commit_exports(
        self,
        event: dict[str, Any],
        state: dict[str, Any],
        audit_row: dict[str, Any],
    ) -> None:
        """Append compatibility rows after the authoritative transaction."""
        append_jsonl_fsync(self.paths.events, event)
        write_json_atomic(self.paths.current, state)
        append_jsonl_fsync(self.paths.audit_actions, audit_row)

    def _sync_compatibility_exports(self) -> None:
        state, events, audit = self.database.snapshot(include_audit=True)
        if events:
            write_bytes_atomic(self.paths.events, self._jsonl_bytes(events))
        write_json_atomic(self.paths.current, state)
        if audit:
            write_bytes_atomic(self.paths.audit_actions, self._jsonl_bytes(audit))
