"""One reusable contract for semantic, multi-aggregate management commands."""

from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass
from typing import Any

from .io import canonical_json
from .schema import validate_aggregate_record


class TransactionViolation(ValueError):
    """A semantic command violates its versioned transaction contract."""


@dataclass(frozen=True)
class CommandSpec:
    kind: str
    owner_type: str
    participant_types: frozenset[str]
    required_types: frozenset[str]
    actor_types: frozenset[str]
    approval_action: str | None = None


COMMAND_SPECS: dict[str, CommandSpec] = {
    "PROJECT_COMMIT": CommandSpec(
        kind="PROJECT_COMMIT",
        owner_type="project",
        participant_types=frozenset({"project"}),
        required_types=frozenset({"project"}),
        actor_types=frozenset({"user"}),
        approval_action="COMMIT_PROJECT",
    ),
    "DRAFT_MATERIALIZE": CommandSpec(
        kind="DRAFT_MATERIALIZE",
        owner_type="package",
        participant_types=frozenset({"brainstorm", "package"}),
        required_types=frozenset({"brainstorm", "package"}),
        actor_types=frozenset({"agent", "user"}),
    ),
    "DRAFT_REVISE": CommandSpec(
        kind="DRAFT_REVISE",
        owner_type="package",
        participant_types=frozenset({"package"}),
        required_types=frozenset({"package"}),
        actor_types=frozenset({"agent", "user"}),
    ),
    "SCOPE_BUNDLE_COMMIT": CommandSpec(
        kind="SCOPE_BUNDLE_COMMIT",
        owner_type="package",
        participant_types=frozenset({"direction", "experiment", "package"}),
        required_types=frozenset({"direction", "experiment", "package"}),
        actor_types=frozenset({"user"}),
        approval_action="COMMIT_SCOPE_BUNDLE",
    ),
    "PACKAGE_PAUSE": CommandSpec(
        kind="PACKAGE_PAUSE",
        owner_type="package",
        participant_types=frozenset({"package"}),
        required_types=frozenset({"package"}),
        actor_types=frozenset({"user"}),
        approval_action="PAUSE_PACKAGE",
    ),
    "PACKAGE_IDENTITY_RENAME": CommandSpec(
        kind="PACKAGE_IDENTITY_RENAME",
        owner_type="package",
        participant_types=frozenset({"package", "experiment", "brainstorm"}),
        required_types=frozenset({"package"}),
        actor_types=frozenset({"user"}),
        approval_action="RENAME_PACKAGE",
    ),
    "PACKAGE_DECIDE": CommandSpec(
        kind="PACKAGE_DECIDE",
        owner_type="package",
        participant_types=frozenset({"decision", "package"}),
        required_types=frozenset({"decision", "package"}),
        actor_types=frozenset({"user"}),
        approval_action="DECIDE_PACKAGE",
    ),
    "ANALYSIS_RECORD": CommandSpec(
        kind="ANALYSIS_RECORD",
        owner_type="learning",
        participant_types=frozenset({"learning"}),
        required_types=frozenset({"learning"}),
        actor_types=frozenset({"agent", "user"}),
    ),
    "RULE_PROMOTE": CommandSpec(
        kind="RULE_PROMOTE",
        owner_type="rule",
        participant_types=frozenset({"rule"}),
        required_types=frozenset({"rule"}),
        actor_types=frozenset({"agent", "user"}),
    ),
}


def transaction_content(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the exact reviewable content, excluding its approval receipt."""
    return {
        "command_kind": payload.get("command_kind"),
        "contract_version": payload.get("contract_version"),
        "owner": copy.deepcopy(payload.get("owner")),
        "participants": copy.deepcopy(payload.get("participants")),
        "evidence": copy.deepcopy(payload.get("evidence", [])),
    }


def transaction_digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        canonical_json(transaction_content(payload)).encode("utf-8")
    ).hexdigest()


def approval_receipt(
    *,
    action: str,
    subject: str,
    content_sha256: str,
    actor_id: str,
    review_id: str,
) -> dict[str, Any]:
    """Create the single receipt consumed by a user-authorized transaction."""
    return {
        "action": action,
        "subject": subject,
        "content_sha256": content_sha256,
        "actor": {"type": "user", "id": actor_id},
        "review_id": review_id,
    }


def _participants(payload: dict[str, Any]) -> list[dict[str, Any]]:
    value = payload.get("participants")
    if not isinstance(value, list) or not value:
        raise TransactionViolation("transaction requires participants")
    return value


def validate_transaction(
    state: dict[str, Any],
    payload: dict[str, Any],
    *,
    actor: dict[str, Any],
    aggregate_type: str,
    aggregate_id: str,
    aggregate_version: int,
) -> list[dict[str, Any]]:
    """Validate authority, participants, and versions exactly once."""
    if payload.get("contract_version") != 1:
        raise TransactionViolation("transaction contract_version must be 1")
    kind = payload.get("command_kind")
    spec = COMMAND_SPECS.get(str(kind))
    if spec is None:
        raise TransactionViolation(f"unknown command_kind: {kind!r}")
    owner = payload.get("owner")
    if owner != {"aggregate_type": aggregate_type, "aggregate_id": aggregate_id}:
        raise TransactionViolation("transaction owner does not match event envelope")
    if aggregate_type != spec.owner_type:
        raise TransactionViolation(
            f"{spec.kind} requires owner_type={spec.owner_type!r}"
        )
    if not isinstance(actor, dict) or actor.get("type") not in spec.actor_types:
        raise TransactionViolation(
            f"{spec.kind} actor.type must be one of {sorted(spec.actor_types)}"
        )
    if not isinstance(actor.get("id"), str) or not actor["id"]:
        raise TransactionViolation("transaction actor.id is required")
    receipt = payload.get("approval")
    if spec.approval_action is None:
        if receipt is not None:
            raise TransactionViolation(
                f"{spec.kind} does not consume a formal approval receipt"
            )
    else:
        if not isinstance(receipt, dict):
            raise TransactionViolation(f"{spec.kind} requires an approval receipt")
        if (
            receipt.get("action") != spec.approval_action
            or receipt.get("subject") != aggregate_id
            or receipt.get("actor") != actor
            or receipt.get("content_sha256") != transaction_digest(payload)
            or not isinstance(receipt.get("review_id"), str)
            or not receipt["review_id"]
        ):
            raise TransactionViolation(
                f"{spec.kind} approval receipt does not bind this reviewed transaction"
            )

    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    observed_types: set[str] = set()
    for raw in _participants(payload):
        if not isinstance(raw, dict):
            raise TransactionViolation("transaction participant must be an object")
        operation = raw.get("operation")
        required = {
            "aggregate_type",
            "aggregate_id",
            "expected_version",
            "aggregate_version",
            "operation",
        }
        allowed = required | ({"record"} if operation == "put" else set())
        if set(raw) != allowed or operation not in {"put", "remove"}:
            raise TransactionViolation("transaction participant shape is invalid")
        participant_type = raw.get("aggregate_type")
        participant_id = raw.get("aggregate_id")
        if participant_type not in spec.participant_types:
            raise TransactionViolation(
                f"{spec.kind} cannot write aggregate type {participant_type!r}"
            )
        if not isinstance(participant_id, str) or not participant_id:
            raise TransactionViolation("transaction participant id is required")
        identity = (str(participant_type), participant_id)
        if identity in seen:
            raise TransactionViolation(f"duplicate transaction participant: {identity}")
        seen.add(identity)
        observed_types.add(str(participant_type))
        current_version = int(
            state.get("aggregate_versions", {}).get(
                f"{participant_type}/{participant_id}", 0
            )
        )
        if (
            raw.get("expected_version") != current_version
            or raw.get("aggregate_version") != current_version + 1
        ):
            raise TransactionViolation(
                f"stale transaction participant: {participant_type}/{participant_id}"
            )
        if identity == (aggregate_type, aggregate_id) and raw.get(
            "aggregate_version"
        ) != aggregate_version:
            raise TransactionViolation(
                "owner participant version does not match event aggregate_version"
            )
        if operation == "put":
            record = raw.get("record")
            if not isinstance(record, dict) or record.get("id") != participant_id:
                raise TransactionViolation(
                    f"put participant requires exact record id: {participant_id}"
                )
            validate_aggregate_record(str(participant_type), record)
        normalized.append(copy.deepcopy(raw))
    if not spec.required_types.issubset(observed_types):
        raise TransactionViolation(
            f"{spec.kind} is missing participant types: "
            f"{sorted(spec.required_types - observed_types)}"
        )
    if (aggregate_type, aggregate_id) not in seen:
        raise TransactionViolation("transaction must include its owner participant")
    evidence = payload.get("evidence", [])
    if not isinstance(evidence, list):
        raise TransactionViolation("transaction evidence must be an array")
    return normalized


def apply_transaction(
    state: dict[str, Any],
    payload: dict[str, Any],
    *,
    actor: dict[str, Any],
    aggregate_type: str,
    aggregate_id: str,
    aggregate_version: int,
) -> None:
    participants = validate_transaction(
        state,
        payload,
        actor=actor,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        aggregate_version=aggregate_version,
    )
    for participant in participants:
        participant_type = participant["aggregate_type"]
        participant_id = participant["aggregate_id"]
        if participant["operation"] == "put":
            state["aggregates"][participant_type][participant_id] = copy.deepcopy(
                participant["record"]
            )
        else:
            state["aggregates"][participant_type].pop(participant_id, None)
        state["aggregate_versions"][
            f"{participant_type}/{participant_id}"
        ] = participant["aggregate_version"]
