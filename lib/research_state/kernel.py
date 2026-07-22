"""Semantic command façade over the transactional EventStore."""

from __future__ import annotations

import copy
import uuid
from typing import Any

from .paths import ResearchPaths
from .store import EventStore
from .transaction import transaction_digest


def build_transaction_payload(
    *,
    command_kind: str,
    owner_type: str,
    owner_id: str,
    participants: list[dict[str, Any]],
    evidence: list[dict[str, Any]] | None = None,
    approval: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "command_kind": command_kind,
        "contract_version": 1,
        "owner": {
            "aggregate_type": owner_type,
            "aggregate_id": owner_id,
        },
        "participants": copy.deepcopy(participants),
        "evidence": copy.deepcopy(evidence or []),
        "approval": copy.deepcopy(approval),
    }
    return payload


def review_digest(payload: dict[str, Any]) -> str:
    return transaction_digest(payload)


def commit_transaction(
    paths: ResearchPaths,
    *,
    payload: dict[str, Any],
    actor: dict[str, str],
    idempotency_key: str,
    entry_skill: str,
    event_id: str | None = None,
) -> dict[str, Any]:
    owner = payload["owner"]
    owner_type = str(owner["aggregate_type"])
    owner_id = str(owner["aggregate_id"])
    owner_participant = next(
        participant
        for participant in payload["participants"]
        if participant.get("aggregate_type") == owner_type
        and participant.get("aggregate_id") == owner_id
    )
    return EventStore(paths).commit(
        event_type="TransactionCommitted",
        aggregate_type=owner_type,
        aggregate_id=owner_id,
        payload=copy.deepcopy(payload),
        actor=copy.deepcopy(actor),
        idempotency_key=idempotency_key,
        expected_version=int(owner_participant["expected_version"]),
        event_id=event_id or f"evt_txn_{uuid.uuid4().hex}",
        entry_skill=entry_skill,
    )
