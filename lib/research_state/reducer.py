"""Deterministic fold for the append-only management event log."""

from __future__ import annotations

import copy
import hashlib
from typing import Any, Iterable

from .io import canonical_json
from .schema import (
    enum,
    load_schema,
    require_enum,
    status_group,
    validate_aggregate_record,
    validate_event_shape,
)
from .transaction import TransactionViolation, apply_transaction


class EventIntegrityError(ValueError):
    """The event sequence, aggregate version, or hash chain is invalid."""


EXPERIMENT_BINDING_PATCH_FIELDS = {
    "after",
    "complex",
    "docsAnchor",
    "label",
    "local_id",
    "measures",
    "output",
    "package_id",
    "requiresCode",
    "resultSchema",
    "resultSchemaRef",
    "runLink",
    "status",
}
EXPERIMENT_STATUS_PATCH_FIELDS = {
    "confirmed_direction_version",
    "latest_result_run_id",
    "latest_result_sha256",
    "scope_confirmation",
    "scope_status",
    "spec",
    "stale_direction_version",
    "status",
    "status_before_scope_stale",
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


def event_hash(event: dict[str, Any]) -> str:
    payload = {key: value for key, value in event.items() if key != "hash"}
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def empty_state() -> dict[str, Any]:
    aggregate_types = load_schema()["aggregate_types"]
    return {
        "schema_version": 1,
        "source_seq": 0,
        "source_hash": "",
        "aggregate_versions": {},
        "aggregates": {aggregate_type: {} for aggregate_type in aggregate_types},
        "open_runs": {},
    }


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _record(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("record", payload.get("data"))
    if not isinstance(value, dict):
        raise EventIntegrityError("upsert/import event payload requires record object")
    return copy.deepcopy(value)


def _experiment_bindings(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate the participant streams in an atomic Package event."""
    bindings = payload.get("experiment_bindings")
    if not isinstance(bindings, list) or not bindings:
        raise EventIntegrityError(
            "atomic Package event requires experiment_bindings"
        )
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for binding in bindings:
        if not isinstance(binding, dict):
            raise EventIntegrityError(
                "experiment binding must be an object"
            )
        aggregate_id = binding.get("aggregate_id")
        expected_version = binding.get("expected_version")
        aggregate_version = binding.get("aggregate_version")
        patch = binding.get("patch")
        if not isinstance(aggregate_id, str) or not aggregate_id:
            raise EventIntegrityError(
                "experiment binding aggregate_id is required"
            )
        if aggregate_id in seen:
            raise EventIntegrityError(
                f"duplicate experiment binding: {aggregate_id}"
            )
        if (
            isinstance(expected_version, bool)
            or not isinstance(expected_version, int)
            or expected_version < 0
            or isinstance(aggregate_version, bool)
            or not isinstance(aggregate_version, int)
            or aggregate_version != expected_version + 1
        ):
            raise EventIntegrityError(
                f"experiment binding has invalid version edge: {aggregate_id}"
            )
        if not isinstance(patch, dict) or not patch:
            raise EventIntegrityError(
                f"experiment binding requires a non-empty patch: {aggregate_id}"
            )
        unknown = sorted(set(patch) - EXPERIMENT_BINDING_PATCH_FIELDS)
        if unknown or not {"local_id", "package_id", "status"}.issubset(patch):
            raise EventIntegrityError(
                f"experiment binding patch has forbidden or missing fields "
                f"for {aggregate_id}: {unknown}"
            )
        seen.add(aggregate_id)
        normalized.append(copy.deepcopy(binding))
    return normalized


def _experiment_unbindings(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate Experiment participants detached by a Package reopen event."""
    unbindings = payload.get("experiment_unbindings")
    if not isinstance(unbindings, list) or not unbindings:
        raise EventIntegrityError(
            "Package reopen requires experiment_unbindings"
        )
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for unbinding in unbindings:
        if not isinstance(unbinding, dict):
            raise EventIntegrityError("experiment unbinding must be an object")
        aggregate_id = unbinding.get("aggregate_id")
        expected_version = unbinding.get("expected_version")
        aggregate_version = unbinding.get("aggregate_version")
        record = unbinding.get("record")
        if not isinstance(aggregate_id, str) or not aggregate_id:
            raise EventIntegrityError(
                "experiment unbinding aggregate_id is required"
            )
        if aggregate_id in seen:
            raise EventIntegrityError(
                f"duplicate experiment unbinding: {aggregate_id}"
            )
        if (
            isinstance(expected_version, bool)
            or not isinstance(expected_version, int)
            or expected_version < 1
            or isinstance(aggregate_version, bool)
            or not isinstance(aggregate_version, int)
            or aggregate_version != expected_version + 1
        ):
            raise EventIntegrityError(
                f"experiment unbinding has invalid version edge: {aggregate_id}"
            )
        if not isinstance(record, dict) or record.get("id") != aggregate_id:
            raise EventIntegrityError(
                f"experiment unbinding requires the full restored record: {aggregate_id}"
            )
        if record.get("package_id") is not None:
            raise EventIntegrityError(
                f"experiment unbinding must clear package_id: {aggregate_id}"
            )
        if record.get("scope_confirmation") != "STALE" or record.get(
            "status"
        ) != "BLOCKED":
            raise EventIntegrityError(
                f"detached Experiment must require Scope reconfirmation: {aggregate_id}"
            )
        seen.add(aggregate_id)
        normalized.append(copy.deepcopy(unbinding))
    return normalized


def _experiment_restorations(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate Experiment records restored by cancelling an unchanged reopen."""
    restorations = payload.get("experiment_restorations")
    if not isinstance(restorations, list) or not restorations:
        raise EventIntegrityError(
            "Package reopen reactivation requires experiment_restorations"
        )
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    required = {
        "aggregate_id",
        "expected_version",
        "aggregate_version",
        "record",
    }
    for restoration in restorations:
        if not isinstance(restoration, dict) or set(restoration) != required:
            raise EventIntegrityError(
                "experiment restoration must contain aggregate_id, "
                "expected_version, aggregate_version, and record"
            )
        aggregate_id = restoration.get("aggregate_id")
        expected_version = restoration.get("expected_version")
        aggregate_version = restoration.get("aggregate_version")
        record = restoration.get("record")
        if not isinstance(aggregate_id, str) or not aggregate_id:
            raise EventIntegrityError(
                "experiment restoration aggregate_id is required"
            )
        if aggregate_id in seen:
            raise EventIntegrityError(
                f"duplicate experiment restoration: {aggregate_id}"
            )
        if (
            isinstance(expected_version, bool)
            or not isinstance(expected_version, int)
            or expected_version < 1
            or isinstance(aggregate_version, bool)
            or not isinstance(aggregate_version, int)
            or aggregate_version != expected_version + 1
        ):
            raise EventIntegrityError(
                f"experiment restoration has invalid version edge: {aggregate_id}"
            )
        if not isinstance(record, dict) or record.get("id") != aggregate_id:
            raise EventIntegrityError(
                f"experiment restoration requires the full prior record: {aggregate_id}"
            )
        seen.add(aggregate_id)
        normalized.append(copy.deepcopy(restoration))
    return normalized


def _reopen_reactivation(payload: dict[str, Any]) -> dict[str, Any] | None:
    value = payload.get("reopen_reactivation")
    if value is None:
        return None
    required = {"reopen_event_id", "source_package", "prior_package_version"}
    if not isinstance(value, dict) or set(value) != required:
        raise EventIntegrityError(
            "reopen_reactivation must contain reopen_event_id, source_package, "
            "and prior_package_version"
        )
    if not isinstance(value.get("reopen_event_id"), str) or not value[
        "reopen_event_id"
    ]:
        raise EventIntegrityError("reopen_reactivation reopen_event_id is required")
    prior_version = value.get("prior_package_version")
    if (
        isinstance(prior_version, bool)
        or not isinstance(prior_version, int)
        or prior_version < 1
    ):
        raise EventIntegrityError(
            "reopen_reactivation prior_package_version must be positive"
        )
    source = value.get("source_package")
    if not isinstance(source, dict) or set(source) != {
        "id",
        "draft_revision",
        "document_sha256",
    }:
        raise EventIntegrityError(
            "reopen_reactivation source_package is malformed"
        )
    return copy.deepcopy(value)


def _brainstorm_consumptions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate Brainstorms transferred into a Package-owned document surface."""
    consumptions = payload.get("brainstorm_consumptions", [])
    if not isinstance(consumptions, list):
        raise EventIntegrityError("brainstorm_consumptions must be a list")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    required = {
        "aggregate_id",
        "expected_version",
        "document_path",
        "document_note",
    }
    for consumption in consumptions:
        if not isinstance(consumption, dict) or set(consumption) != required:
            raise EventIntegrityError(
                "brainstorm consumption must contain exactly aggregate_id, "
                "expected_version, document_path, and document_note"
            )
        aggregate_id = consumption.get("aggregate_id")
        expected_version = consumption.get("expected_version")
        document_path = consumption.get("document_path")
        document_note = consumption.get("document_note")
        if not isinstance(aggregate_id, str) or not aggregate_id:
            raise EventIntegrityError("brainstorm consumption aggregate_id is required")
        if aggregate_id in seen:
            raise EventIntegrityError(
                f"duplicate brainstorm consumption: {aggregate_id}"
            )
        if (
            isinstance(expected_version, bool)
            or not isinstance(expected_version, int)
            or expected_version < 1
        ):
            raise EventIntegrityError(
                f"brainstorm consumption has invalid expected_version: {aggregate_id}"
            )
        if (
            not isinstance(document_path, str)
            or not document_path.startswith("docs/")
            or not document_path.endswith(".html")
            or ".." in document_path.split("/")
        ):
            raise EventIntegrityError(
                f"brainstorm consumption has unsafe document_path: {aggregate_id}"
            )
        if not isinstance(document_note, dict):
            raise EventIntegrityError(
                f"brainstorm consumption requires document_note: {aggregate_id}"
            )
        seen.add(aggregate_id)
        normalized.append(copy.deepcopy(consumption))
    return normalized


def _apply_package_operations(
    current: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    operations = payload.get("operations")
    if not isinstance(operations, list) or not operations:
        raise EventIntegrityError("Package mutation requires operations")
    updated = copy.deepcopy(current)
    for operation in operations:
        if not isinstance(operation, dict):
            raise EventIntegrityError("package mutation operation must be an object")
        target = operation.get("target")
        mode = operation.get("operation")
        value = copy.deepcopy(operation.get("value"))
        if not isinstance(target, str) or not target:
            raise EventIntegrityError("package mutation target is required")
        if mode == "set":
            updated[target] = value
        elif mode == "append":
            rows = updated.setdefault(target, [])
            if not isinstance(rows, list):
                raise EventIntegrityError(
                    f"package append target is not a list: {target}"
                )
            rows.append(value)
        elif mode == "upsert_by_id":
            rows = updated.setdefault(target, [])
            if not isinstance(rows, list) or not isinstance(value, dict):
                raise EventIntegrityError(
                    f"package upsert_by_id requires list/object: {target}"
                )
            row_id = value.get("id")
            index = next(
                (
                    position
                    for position, row in enumerate(rows)
                    if isinstance(row, dict) and row.get("id") == row_id
                ),
                None,
            )
            if index is None:
                rows.append(value)
            else:
                rows[index] = _deep_merge(rows[index], value)
        elif mode == "remove_by_id":
            rows = updated.get(target, [])
            if not isinstance(rows, list):
                raise EventIntegrityError(
                    f"package remove_by_id target is not a list: {target}"
                )
            updated[target] = [
                row
                for row in rows
                if not isinstance(row, dict) or row.get("id") != value
            ]
        else:
            raise EventIntegrityError(
                f"unknown package mutation operation: {mode!r}"
            )
    return updated


def _apply_experiment_bindings(
    state: dict[str, Any],
    payload: dict[str, Any],
    *,
    package_id: str,
) -> None:
    bucket = state["aggregates"]["experiment"]
    bindings = _experiment_bindings(payload)
    binding_ids = {binding["aggregate_id"] for binding in bindings}
    local_owners = {
        str(record.get("local_id")): str(aggregate_id)
        for aggregate_id, record in bucket.items()
        if isinstance(record, dict)
        and record.get("package_id") == package_id
        and record.get("local_id")
        and aggregate_id not in binding_ids
    }
    for binding in bindings:
        aggregate_id = binding["aggregate_id"]
        key = f"experiment/{aggregate_id}"
        current_version = int(state["aggregate_versions"].get(key, 0))
        if current_version != binding["expected_version"]:
            raise EventIntegrityError(
                f"{key} participant version must be "
                f"{binding['expected_version']}, got {current_version}"
            )
        current = bucket.get(aggregate_id)
        if not isinstance(current, dict):
            raise EventIntegrityError(
                f"package binding references unknown experiment: {aggregate_id}"
            )
        patch = binding["patch"]
        if patch.get("package_id") != package_id:
            raise EventIntegrityError(
                f"experiment binding package_id must equal {package_id}: "
                f"{aggregate_id}"
            )
        if current.get("package_id") not in {None, "", package_id}:
            raise EventIntegrityError(
                f"experiment is already bound to another package: {aggregate_id}"
            )
        local_id = str(patch["local_id"])
        owner = local_owners.get(local_id)
        if owner is not None and owner != aggregate_id:
            raise EventIntegrityError(
                f"duplicate local Experiment id in {package_id}: {local_id}"
            )
        local_owners[local_id] = aggregate_id
        updated = _deep_merge(current, patch)
        updated.setdefault("id", aggregate_id)
        validate_aggregate_record("experiment", updated)
        bucket[aggregate_id] = updated
        state["aggregate_versions"][key] = binding["aggregate_version"]


def _apply_experiment_unbindings(
    state: dict[str, Any],
    payload: dict[str, Any],
    *,
    package_id: str,
) -> None:
    bucket = state["aggregates"]["experiment"]
    for unbinding in _experiment_unbindings(payload):
        aggregate_id = unbinding["aggregate_id"]
        key = f"experiment/{aggregate_id}"
        current_version = int(state["aggregate_versions"].get(key, 0))
        if current_version != unbinding["expected_version"]:
            raise EventIntegrityError(
                f"{key} participant version must be "
                f"{unbinding['expected_version']}, got {current_version}"
            )
        current = bucket.get(aggregate_id)
        if not isinstance(current, dict):
            raise EventIntegrityError(
                f"package reopen references unknown experiment: {aggregate_id}"
            )
        if current.get("package_id") != package_id:
            raise EventIntegrityError(
                f"experiment is not bound to Package {package_id}: {aggregate_id}"
            )
        record = copy.deepcopy(unbinding["record"])
        validate_aggregate_record("experiment", record)
        bucket[aggregate_id] = record
        state["aggregate_versions"][key] = unbinding["aggregate_version"]


def _detached_reopen_projection(record: dict[str, Any]) -> dict[str, Any]:
    """Reproduce the exact Experiment projection written by a reopen event."""
    detached = copy.deepcopy(record)
    for field in PACKAGE_LOCAL_EXPERIMENT_FIELDS:
        detached.pop(field, None)
    prior_status = detached.get("status")
    if prior_status == "BLOCKED":
        prior_status = detached.get("status_before_scope_stale") or "PLANNED"
    detached["package_id"] = None
    detached["status_before_scope_stale"] = prior_status
    detached["status"] = "BLOCKED"
    detached["scope_confirmation"] = "STALE"
    if isinstance(detached.get("confirmed_direction_version"), int):
        detached["stale_direction_version"] = detached[
            "confirmed_direction_version"
        ]
    return detached


def _apply_experiment_restorations(
    state: dict[str, Any],
    payload: dict[str, Any],
    *,
    package_id: str,
    direction_id: str,
    direction_version: int,
) -> None:
    """Restore only the exact Experiment records detached by an unchanged reopen."""
    bucket = state["aggregates"]["experiment"]
    local_owners: dict[str, str] = {}
    for restoration in _experiment_restorations(payload):
        aggregate_id = restoration["aggregate_id"]
        key = f"experiment/{aggregate_id}"
        current_version = int(state["aggregate_versions"].get(key, 0))
        if current_version != restoration["expected_version"]:
            raise EventIntegrityError(
                f"{key} participant version must be "
                f"{restoration['expected_version']}, got {current_version}"
            )
        current = bucket.get(aggregate_id)
        restored = copy.deepcopy(restoration["record"])
        if not isinstance(current, dict) or current != _detached_reopen_projection(
            restored
        ):
            raise EventIntegrityError(
                f"Experiment changed after Package reopen: {aggregate_id}"
            )
        if (
            restored.get("package_id") != package_id
            or restored.get("direction_id") != direction_id
            or restored.get("scope_confirmation") != "CONFIRMED"
            or restored.get("scope_status") != "ACTIVE"
            or restored.get("confirmed_direction_version") != direction_version
        ):
            raise EventIntegrityError(
                f"Experiment restoration does not match active Scope: {aggregate_id}"
            )
        local_id = restored.get("local_id")
        if not isinstance(local_id, str) or not local_id:
            raise EventIntegrityError(
                f"Experiment restoration requires local_id: {aggregate_id}"
            )
        owner = local_owners.get(local_id)
        if owner is not None and owner != aggregate_id:
            raise EventIntegrityError(
                f"duplicate restored local Experiment id in {package_id}: {local_id}"
            )
        local_owners[local_id] = aggregate_id
        validate_aggregate_record("experiment", restored)
        bucket[aggregate_id] = restored
        state["aggregate_versions"][key] = restoration["aggregate_version"]


def _apply_brainstorm_consumptions(
    state: dict[str, Any],
    payload: dict[str, Any],
    *,
    package: dict[str, Any],
) -> None:
    """Bind exact Brainstorm documents to a Package without deleting history."""
    consumptions = _brainstorm_consumptions(payload)
    if not consumptions:
        return
    package_sources = package.get("sourceBrainstorms")
    package_notes = package.get("interface_notes")
    if not isinstance(package_sources, list) or not isinstance(package_notes, dict):
        raise EventIntegrityError(
            "brainstorm consumption requires Package sourceBrainstorms and interface_notes"
        )
    source_by_id = {
        str(row.get("id")): row
        for row in package_sources
        if isinstance(row, dict) and row.get("id")
    }
    bucket = state["aggregates"]["brainstorm"]
    for consumption in consumptions:
        aggregate_id = consumption["aggregate_id"]
        key = f"brainstorm/{aggregate_id}"
        current_version = int(state["aggregate_versions"].get(key, 0))
        if current_version != consumption["expected_version"]:
            raise EventIntegrityError(
                f"{key} participant version must be "
                f"{consumption['expected_version']}, got {current_version}"
            )
        current = bucket.get(aggregate_id)
        if not isinstance(current, dict) or current.get("status") != "ACTIVE":
            raise EventIntegrityError(
                f"package conversion requires an ACTIVE Brainstorm: {aggregate_id}"
            )
        document_note = consumption["document_note"]
        document_path = consumption["document_path"]
        if current.get("document_note") != document_note:
            raise EventIntegrityError(
                f"brainstorm document changed before conversion: {aggregate_id}"
            )
        source = source_by_id.get(aggregate_id)
        if (
            not isinstance(source, dict)
            or source.get("documentPath") != document_path
            or source.get("document_note") != document_note
            or package_notes.get(document_path) != document_note
        ):
            raise EventIntegrityError(
                f"Package does not own the transferred Brainstorm document: {aggregate_id}"
            )
        materialized = copy.deepcopy(current)
        materialized["status"] = "MATERIALIZED"
        materialized["materialized_as"] = package.get("id")
        bucket[aggregate_id] = materialized


def _scope_finalization(payload: dict[str, Any]) -> dict[str, Any] | None:
    value = payload.get("scope_finalization")
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {
        "proposal",
        "direction",
        "experiments",
        "source_package",
        "finalized_draft",
    }:
        raise EventIntegrityError(
            "scope_finalization must contain proposal, direction, experiments, source_package, and finalized_draft"
        )
    if not isinstance(value.get("experiments"), list) or not value["experiments"]:
        raise EventIntegrityError("scope_finalization requires Experiments")
    return copy.deepcopy(value)


def _apply_scope_finalization(
    state: dict[str, Any],
    payload: dict[str, Any],
    *,
    package_id: str,
    current_draft: dict[str, Any],
) -> None:
    """Atomically accept one full proposal and create its Scope participants."""
    finalization = _scope_finalization(payload)
    if finalization is None:
        return
    source_package = finalization["source_package"]
    note = current_draft.get("document_note")
    expected_source = {
        "id": package_id,
        "draft_revision": current_draft.get("draftRevision"),
        "document_sha256": note.get("sha256") if isinstance(note, dict) else None,
    }
    if source_package != expected_source:
        raise EventIntegrityError(
            "scope_finalization source_package does not match the current Draft"
        )
    finalized_draft = finalization["finalized_draft"]
    expected_draft = copy.deepcopy(current_draft)
    expected_draft["draftStatus"] = "SCOPE_READY"
    if finalized_draft != expected_draft:
        raise EventIntegrityError(
            "scope_finalization must preserve the exact Draft revision while setting SCOPE_READY"
        )

    proposal = finalization["proposal"]
    if not isinstance(proposal, dict) or set(proposal) != {
        "aggregate_id",
        "expected_version",
        "aggregate_version",
        "record",
    }:
        raise EventIntegrityError("scope_finalization proposal participant is invalid")
    proposal_id = proposal["aggregate_id"]
    proposal_key = f"proposal/{proposal_id}"
    proposal_version = int(state["aggregate_versions"].get(proposal_key, 0))
    current_proposal = state["aggregates"]["proposal"].get(proposal_id)
    accepted_record = proposal["record"]
    if (
        not isinstance(proposal_id, str)
        or not proposal_id
        or proposal.get("expected_version") != proposal_version
        or proposal.get("aggregate_version") != proposal_version + 1
        or not isinstance(current_proposal, dict)
        or current_proposal.get("disposition") != "PENDING"
        or current_proposal.get("proposal_kind") != "package_finalization"
        or current_proposal.get("source_package") != source_package
        or not isinstance(accepted_record, dict)
        or accepted_record.get("id") != proposal_id
        or accepted_record.get("decision") != "ACCEPTED"
        or accepted_record.get("proposal_hash")
        != current_proposal.get("proposal_hash")
        or accepted_record.get("accepted_proposal")
        != {
            key: copy.deepcopy(value)
            for key, value in current_proposal.items()
            if key != "disposition"
        }
    ):
        raise EventIntegrityError(
            "scope_finalization does not match the pending proposal snapshot"
        )
    accepted = copy.deepcopy(accepted_record)
    accepted["disposition"] = "ACCEPTED"
    validate_aggregate_record("proposal", accepted)
    state["aggregates"]["proposal"][proposal_id] = accepted
    state["aggregate_versions"][proposal_key] = proposal["aggregate_version"]

    direction = finalization["direction"]
    if not isinstance(direction, dict) or set(direction) != {
        "aggregate_id",
        "expected_version",
        "aggregate_version",
        "record",
    }:
        raise EventIntegrityError("scope_finalization direction participant is invalid")
    direction_id = direction["aggregate_id"]
    direction_key = f"direction/{direction_id}"
    direction_version = int(state["aggregate_versions"].get(direction_key, 0))
    direction_record = direction["record"]
    proposed_direction = current_proposal.get("proposed_node")
    canonical_fields = {"id", "level", "parents", "version", "status", "spec", "source"}
    if (
        not isinstance(direction_id, str)
        or not direction_id
        or direction.get("expected_version") != direction_version
        or direction.get("aggregate_version") != direction_version + 1
        or direction_version != 0
        or state["aggregates"]["direction"].get(direction_id) is not None
        or not isinstance(direction_record, dict)
        or not isinstance(proposed_direction, dict)
        or any(
            direction_record.get(field) != proposed_direction.get(field)
            for field in canonical_fields
        )
    ):
        raise EventIntegrityError(
            "scope_finalization Direction does not match the proposed node"
        )
    parents = direction_record.get("parents")
    parent = (
        state["aggregates"]["project"].get(parents[0])
        if isinstance(parents, list) and len(parents) == 1
        else None
    )
    if not isinstance(parent, dict) or parent.get("status") != "ACTIVE":
        raise EventIntegrityError(
            "scope_finalization Direction requires an ACTIVE Project parent"
        )
    validate_aggregate_record("direction", direction_record)
    state["aggregates"]["direction"][direction_id] = copy.deepcopy(direction_record)
    state["aggregate_versions"][direction_key] = direction["aggregate_version"]

    proposed_experiments = current_proposal.get("proposed_experiments")
    proposed_by_id = {
        row.get("id"): row
        for row in proposed_experiments
        if isinstance(row, dict) and row.get("id")
    } if isinstance(proposed_experiments, list) else {}
    experiment_bindings = {
        row["aggregate_id"]: row for row in _experiment_bindings(payload)
    }
    experiments = finalization["experiments"]
    if set(proposed_by_id) != {
        row.get("aggregate_id") for row in experiments if isinstance(row, dict)
    } or set(proposed_by_id) != set(experiment_bindings):
        raise EventIntegrityError(
            "scope_finalization Experiments must match the proposal and Package bindings"
        )
    for participant in experiments:
        if not isinstance(participant, dict) or set(participant) != {
            "aggregate_id",
            "expected_version",
            "aggregate_version",
            "record",
        }:
            raise EventIntegrityError(
                "scope_finalization Experiment participant is invalid"
            )
        experiment_id = participant["aggregate_id"]
        key = f"experiment/{experiment_id}"
        current_version = int(state["aggregate_versions"].get(key, 0))
        proposed = proposed_by_id.get(experiment_id)
        record = participant["record"]
        expected_record = {
            "id": experiment_id,
            "direction_id": direction_id,
            "package_id": None,
            "spec": proposed.get("spec") if isinstance(proposed, dict) else None,
            "status": "PLANNED" if proposed.get("status") == "ACTIVE" else "SKIPPED",
            "scope_version": proposed.get("version") if isinstance(proposed, dict) else None,
            "scope_status": proposed.get("status") if isinstance(proposed, dict) else None,
            "scope_confirmation": "CONFIRMED",
            "confirmed_direction_version": direction_record.get("version"),
            "scope_source": proposed.get("source") if isinstance(proposed, dict) else None,
        }
        if (
            participant.get("expected_version") != current_version
            or participant.get("aggregate_version") != current_version + 1
            or current_version != 0
            or state["aggregates"]["experiment"].get(experiment_id) is not None
            or not isinstance(record, dict)
            or any(record.get(field) != value for field, value in expected_record.items())
            or experiment_bindings[experiment_id].get("expected_version") != current_version
            or experiment_bindings[experiment_id].get("aggregate_version")
            != current_version + 1
        ):
            raise EventIntegrityError(
                f"scope_finalization Experiment does not match the proposed node: {experiment_id}"
            )
        validate_aggregate_record("experiment", record)
        state["aggregates"]["experiment"][experiment_id] = copy.deepcopy(record)


def _run_record(state: dict[str, Any], aggregate_id: str) -> dict[str, Any]:
    record = state["aggregates"]["run"].get(aggregate_id)
    if not isinstance(record, dict):
        raise EventIntegrityError(f"run event references unknown run: {aggregate_id}")
    return record


def _scientific_result_summary(
    payload: dict[str, Any],
    current: dict[str, Any],
    run_id: str,
) -> dict[str, Any]:
    summary = payload.get("result")
    if not isinstance(summary, dict):
        raise EventIntegrityError("RunResultFinalized requires result object")
    required = {
        "run_id",
        "package_id",
        "experiment_id",
        "kind",
        "result_json",
        "result_sha256",
        "protocol",
        "verdict",
        "validity",
        "measurements",
        "supported_claims",
        "unsupported_claims",
        "evidence",
        "evidence_count",
    }
    missing = sorted(required - set(summary))
    if missing:
        raise EventIntegrityError(
            f"RunResultFinalized result is missing fields: {missing}"
        )
    identities = {
        "run_id": run_id,
        "package_id": current.get("package_id"),
        "experiment_id": current.get("experiment_id"),
    }
    for field, expected in identities.items():
        if summary.get(field) != expected:
            raise EventIntegrityError(
                f"RunResultFinalized {field} does not match the Run"
            )
    result_json = summary.get("result_json")
    if not isinstance(result_json, str) or not result_json:
        raise EventIntegrityError(
            "RunResultFinalized result_json must be a non-empty string"
        )
    if summary.get("kind") != "experiment-result":
        raise EventIntegrityError(
            "RunResultFinalized kind must be 'experiment-result'"
        )
    digest = str(summary.get("result_sha256") or "").lower()
    if len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise EventIntegrityError(
            "RunResultFinalized result_sha256 must be a 64-character "
            "hexadecimal digest"
        )
    require_enum("result_verdict", summary.get("verdict"))
    require_enum("result_validity", summary.get("validity"))
    if not isinstance(summary.get("protocol"), dict):
        raise EventIntegrityError(
            "RunResultFinalized protocol must be an object"
        )
    if not isinstance(summary.get("measurements"), dict):
        raise EventIntegrityError(
            "RunResultFinalized measurements must be an object"
        )
    for field in ("supported_claims", "unsupported_claims"):
        claims = summary.get(field)
        if not isinstance(claims, list) or not all(
            isinstance(claim, str) and claim.strip() for claim in claims
        ):
            raise EventIntegrityError(
                f"RunResultFinalized {field} must be a list of non-empty strings"
            )
    evidence = summary.get("evidence")
    if not isinstance(evidence, list):
        raise EventIntegrityError("RunResultFinalized evidence must be an array")
    evidence_count = summary.get("evidence_count")
    if (
        isinstance(evidence_count, bool)
        or not isinstance(evidence_count, int)
        or evidence_count != len(evidence)
    ):
        raise EventIntegrityError(
            "RunResultFinalized evidence_count must equal the evidence length"
        )
    evidence_kinds = set(enum("evidence_kind"))
    for ref in evidence:
        if not isinstance(ref, dict):
            raise EventIntegrityError(
                "RunResultFinalized evidence entries must be objects"
            )
        for field, expected in identities.items():
            if ref.get(field) != expected:
                raise EventIntegrityError(
                    f"RunResultFinalized evidence {field} does not match the Run"
                )
        if ref.get("kind") not in evidence_kinds:
            raise EventIntegrityError(
                f"RunResultFinalized evidence has invalid kind: {ref.get('kind')!r}"
            )
        uri = ref.get("uri")
        if not isinstance(uri, str) or not uri:
            raise EventIntegrityError(
                "RunResultFinalized evidence uri must be a non-empty string"
            )
        ref_digest = str(ref.get("sha256") or "").lower()
        if len(ref_digest) != 64 or any(
            character not in "0123456789abcdef" for character in ref_digest
        ):
            raise EventIntegrityError(
                "RunResultFinalized evidence sha256 must be a 64-character "
                "hexadecimal digest"
            )
        size_bytes = ref.get("size_bytes")
        if (
            isinstance(size_bytes, bool)
            or not isinstance(size_bytes, int)
            or size_bytes < 0
        ):
            raise EventIntegrityError(
                "RunResultFinalized evidence size_bytes must be non-negative"
            )
    return copy.deepcopy(summary)


def apply_event(state: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(state)
    aggregate_type = event["aggregate_type"]
    aggregate_id = event["aggregate_id"]
    payload = event["payload"]
    event_type = event["event_type"]
    bucket = out["aggregates"][aggregate_type]

    if event_type == "TransactionCommitted":
        try:
            apply_transaction(
                out,
                payload,
                actor=event["actor"],
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                aggregate_version=event["aggregate_version"],
            )
        except TransactionViolation as exc:
            raise EventIntegrityError(str(exc)) from exc
    elif event_type in {"AggregateImported", "AggregateUpserted", "ScopeCommitted"}:
        record = _record(payload)
        record.setdefault("id", aggregate_id)
        bucket[aggregate_id] = record
        if aggregate_type == "run":
            if record.get("status") in {"QUEUED", "RUNNING", "STALE"}:
                out["open_runs"][aggregate_id] = {
                    "run_id": aggregate_id,
                    "package_id": record.get("package_id"),
                    "experiment_id": record.get("experiment_id"),
                    "dir": record.get("dir"),
                    "imported": True,
                }
            else:
                out["open_runs"].pop(aggregate_id, None)
    elif event_type == "AggregatePatched":
        patch = payload.get("patch")
        if not isinstance(patch, dict):
            raise EventIntegrityError("AggregatePatched payload requires patch object")
        current = bucket.get(aggregate_id)
        if not isinstance(current, dict):
            raise EventIntegrityError(
                f"cannot patch missing {aggregate_type} aggregate: {aggregate_id}"
            )
        bucket[aggregate_id] = _deep_merge(current, patch)
    elif event_type == "AggregateRemoved":
        bucket.pop(aggregate_id, None)
    elif event_type in {"ProposalSubmitted", "ProposalAccepted", "ProposalRejected"}:
        current = copy.deepcopy(bucket.get(aggregate_id, {}))
        current.update(_record(payload))
        current.setdefault("id", aggregate_id)
        current["disposition"] = {
            "ProposalSubmitted": "PENDING",
            "ProposalAccepted": "ACCEPTED",
            "ProposalRejected": "REJECTED",
        }[event_type]
        bucket[aggregate_id] = current
    elif event_type in {"BrainstormCreated", "BrainstormRevised", "BrainstormArchived"}:
        if event_type == "BrainstormCreated":
            record = _record(payload)
            if aggregate_id in bucket:
                raise EventIntegrityError(f"brainstorm already exists: {aggregate_id}")
        else:
            current = bucket.get(aggregate_id)
            if not isinstance(current, dict):
                raise EventIntegrityError(
                    f"brainstorm event references unknown idea: {aggregate_id}"
                )
            patch = payload.get("patch")
            if not isinstance(patch, dict):
                raise EventIntegrityError(f"{event_type} requires patch")
            record = _deep_merge(current, patch)
        record.setdefault("id", aggregate_id)
        if event_type == "BrainstormArchived":
            record["status"] = "ARCHIVED"
        else:
            record.setdefault("status", "ACTIVE")
        bucket[aggregate_id] = record
    elif event_type in {
        "PackageDraftCreated",
        "PackageDraftRevised",
        "PackageDraftArchived",
    }:
        if event_type == "PackageDraftCreated":
            consumptions = _brainstorm_consumptions(payload)
            if consumptions:
                if len(consumptions) != 1:
                    raise EventIntegrityError(
                        "normal Draft Package conversion consumes exactly one Brainstorm"
                    )
            if aggregate_id in bucket:
                raise EventIntegrityError(f"package already exists: {aggregate_id}")
            record = _record(payload)
        else:
            current = bucket.get(aggregate_id)
            if not isinstance(current, dict) or current.get("lifecycle") != "DRAFT":
                raise EventIntegrityError(
                    f"draft event references unknown Draft Package: {aggregate_id}"
                )
            patch = payload.get("patch")
            if not isinstance(patch, dict):
                raise EventIntegrityError(f"{event_type} requires patch")
            record = _deep_merge(current, patch)
        record.setdefault("id", aggregate_id)
        if event_type == "PackageDraftArchived":
            record["draftStatus"] = "ARCHIVED_DRAFT"
        if record.get("lifecycle") != "DRAFT":
            raise EventIntegrityError("PackageDraft events must preserve DRAFT lifecycle")
        bucket[aggregate_id] = record
        if event_type == "PackageDraftCreated":
            _apply_brainstorm_consumptions(
                out,
                payload,
                package=bucket[aggregate_id],
            )
    elif event_type in {"PackageMaterialized", "PackageActivated"}:
        current_package = bucket.get(aggregate_id)
        if event_type == "PackageMaterialized" and current_package is not None:
            raise EventIntegrityError(f"package already exists: {aggregate_id}")
        if event_type == "PackageActivated" and (
            not isinstance(current_package, dict)
            or current_package.get("lifecycle") != "DRAFT"
        ):
            raise EventIntegrityError(
                f"PackageActivated requires an existing Draft Package: {aggregate_id}"
            )
        finalization = _scope_finalization(payload)
        reactivation = _reopen_reactivation(payload)
        if finalization is not None and reactivation is not None:
            raise EventIntegrityError(
                "PackageActivated cannot combine Scope finalization with reopen reactivation"
            )
        if finalization is not None:
            if event_type != "PackageActivated" or event.get("actor", {}).get(
                "type"
            ) != "user":
                raise EventIntegrityError(
                    "atomic Scope finalization requires a user-owned PackageActivated event"
                )
            _apply_scope_finalization(
                out,
                payload,
                package_id=aggregate_id,
                current_draft=current_package,
            )
        if reactivation is not None:
            current_version = int(
                out["aggregate_versions"].get(f"package/{aggregate_id}", 0)
            )
            note = current_package.get("document_note")
            expected_source = {
                "id": aggregate_id,
                "draft_revision": current_package.get("draftRevision"),
                "document_sha256": (
                    note.get("sha256") if isinstance(note, dict) else None
                ),
            }
            if (
                event_type != "PackageActivated"
                or event.get("actor", {}).get("type") != "user"
                or event.get("causation_id") != reactivation["reopen_event_id"]
                or current_version != reactivation["prior_package_version"] + 1
                or reactivation["source_package"] != expected_source
            ):
                raise EventIntegrityError(
                    "reopen reactivation requires the unchanged user-owned Draft and causal reopen event"
                )
        record = _record(payload)
        if record.get("id", aggregate_id) != aggregate_id:
            raise EventIntegrityError(
                f"{event_type} record id must equal aggregate_id"
            )
        record["id"] = aggregate_id
        if finalization is not None:
            scope_binding = record.get("scopeBinding")
            if (
                record.get("lifecycle") != "ACTIVE"
                or record.get("phase") != "CONTEXT_LOADED"
                or record.get("executionAuthorized") is not True
                or record.get("sourceChange") != event["event_id"]
                or not isinstance(scope_binding, dict)
                or scope_binding.get("source_package")
                != finalization["source_package"]
                or record.get("document_note")
                != finalization["finalized_draft"].get("document_note")
            ):
                raise EventIntegrityError(
                    "scope_finalization must activate the exact finalized Draft at ACTIVE/CONTEXT_LOADED"
                )
        if reactivation is not None:
            scope_binding = record.get("scopeBinding")
            direction_id = record.get("direction_id")
            direction_version = record.get("sourceVersion")
            direction = out["aggregates"]["direction"].get(direction_id)
            restorations = _experiment_restorations(payload)
            participant_ids = [
                restoration["aggregate_id"] for restoration in restorations
            ]
            if (
                record.get("lifecycle") != "ACTIVE"
                or record.get("phase") != "CONTEXT_LOADED"
                or record.get("executionAuthorized") is not True
                or record.get("draftStatus") != "SCOPE_READY"
                or record.get("documentPath")
                != current_package.get("documentPath")
                or record.get("document_note")
                != current_package.get("document_note")
                or not isinstance(scope_binding, dict)
                or scope_binding.get("source_package")
                != reactivation["source_package"]
                or scope_binding.get("direction_id") != direction_id
                or scope_binding.get("direction_version") != direction_version
                or scope_binding.get("experiment_ids") != participant_ids
                or not isinstance(direction, dict)
                or direction.get("status") != "ACTIVE"
                or direction.get("version") != direction_version
            ):
                raise EventIntegrityError(
                    "reopen reactivation must restore the unchanged Draft against its active Scope"
                )
            binding_ids = set(participant_ids)
        else:
            binding_ids = {
                binding["aggregate_id"]
                for binding in _experiment_bindings(payload)
            }
        provenance = record.get("sourceExperiments")
        provenance_ids = {
            item.get("id")
            for item in provenance
            if isinstance(item, dict)
        } if isinstance(provenance, list) else set()
        if (
            not isinstance(provenance, list)
            or provenance_ids != binding_ids
            or len(provenance_ids) != len(provenance)
        ):
            raise EventIntegrityError(
                "Package sourceExperiments must match Experiment participants exactly"
            )
        bucket[aggregate_id] = record
        if reactivation is not None:
            _apply_experiment_restorations(
                out,
                payload,
                package_id=aggregate_id,
                direction_id=str(record["direction_id"]),
                direction_version=int(record["sourceVersion"]),
            )
        else:
            _apply_experiment_bindings(out, payload, package_id=aggregate_id)
        _apply_brainstorm_consumptions(
            out,
            payload,
            package=bucket[aggregate_id],
        )
    elif event_type == "PackageReopenedAsDraft":
        current = bucket.get(aggregate_id)
        if not isinstance(current, dict) or current.get("lifecycle") != "ACTIVE":
            raise EventIntegrityError(
                f"Package reopen requires an ACTIVE Package: {aggregate_id}"
            )
        record = _record(payload)
        if record.get("id", aggregate_id) != aggregate_id:
            raise EventIntegrityError(
                "PackageReopenedAsDraft record id must equal aggregate_id"
            )
        record["id"] = aggregate_id
        if (
            record.get("lifecycle") != "DRAFT"
            or record.get("phase") is not None
            or record.get("executionAuthorized") is not False
        ):
            raise EventIntegrityError(
                "PackageReopenedAsDraft must produce a non-executable Draft Package"
            )
        bucket[aggregate_id] = record
        _apply_experiment_unbindings(out, payload, package_id=aggregate_id)
    elif event_type == "PackageExperimentBound":
        current = bucket.get(aggregate_id)
        if not isinstance(current, dict):
            raise EventIntegrityError(
                f"package binding references unknown package: {aggregate_id}"
        )
        bucket[aggregate_id] = _apply_package_operations(current, payload)
        binding_ids = {
            binding["aggregate_id"]
            for binding in _experiment_bindings(payload)
        }
        provenance = bucket[aggregate_id].get("sourceExperiments")
        provenance_ids = {
            item.get("id")
            for item in provenance
            if isinstance(item, dict)
        } if isinstance(provenance, list) else set()
        if not binding_ids.issubset(provenance_ids):
            raise EventIntegrityError(
                "Package binding must update sourceExperiments provenance"
            )
        _apply_experiment_bindings(out, payload, package_id=aggregate_id)
    elif event_type == "PackageMutationApplied":
        current = bucket.get(aggregate_id)
        if not isinstance(current, dict):
            raise EventIntegrityError(
                f"package mutation references unknown package: {aggregate_id}"
            )
        bucket[aggregate_id] = _apply_package_operations(current, payload)
        _apply_brainstorm_consumptions(
            out,
            payload,
            package=bucket[aggregate_id],
        )
    elif event_type in {
        "DecisionRecorded",
        "CampaignUpdated",
        "ExperimentBoundToPackage",
        "ExperimentSpecRevised",
        "ExperimentStatusChanged",
    }:
        current = copy.deepcopy(bucket.get(aggregate_id, {}))
        patch = payload.get("patch")
        record = payload.get("record")
        if isinstance(record, dict):
            updated = copy.deepcopy(record)
        elif isinstance(patch, dict):
            if event_type == "ExperimentStatusChanged":
                unknown = sorted(set(patch) - EXPERIMENT_STATUS_PATCH_FIELDS)
                if unknown:
                    raise EventIntegrityError(
                        "ExperimentStatusChanged patch has forbidden fields: "
                        f"{unknown}"
                    )
            updated = _deep_merge(current, patch)
        else:
            raise EventIntegrityError(f"{event_type} requires record or patch")
        updated.setdefault("id", aggregate_id)
        bucket[aggregate_id] = updated
    elif event_type == "RunLaunchAuthorized":
        record = _record(payload)
        lease = record.get("authorization_lease_seconds")
        if lease is not None and (
            isinstance(lease, bool)
            or not isinstance(lease, int)
            or lease <= 0
        ):
            raise EventIntegrityError(
                "RunLaunchAuthorized authorization_lease_seconds must be "
                "a positive integer"
            )
        record.setdefault("id", aggregate_id)
        record["status"] = "QUEUED"
        record["launch_authorized"] = True
        bucket[aggregate_id] = record
    elif event_type == "RunLaunched":
        current = _run_record(out, aggregate_id)
        launched = _deep_merge(current, payload.get("patch", {}))
        launched["status"] = "RUNNING"
        launched["launched_event_id"] = event["event_id"]
        bucket[aggregate_id] = launched
        out["open_runs"][aggregate_id] = {
            "run_id": aggregate_id,
            "package_id": launched.get("package_id"),
            "experiment_id": launched.get("experiment_id"),
            "dir": launched.get("dir"),
            "launched_event_id": event["event_id"],
        }
    elif event_type == "RunLaunchFailed":
        current = _run_record(out, aggregate_id)
        failed = _deep_merge(current, payload.get("patch", {}))
        failed["status"] = "FAILED"
        failed["launch_failed"] = True
        failed["launch_failed_event_id"] = event["event_id"]
        bucket[aggregate_id] = failed
        out["open_runs"].pop(aggregate_id, None)
    elif event_type == "RunTerminal":
        current = _run_record(out, aggregate_id)
        if not current.get("launched_event_id"):
            raise EventIntegrityError(
                f"RunTerminal requires an earlier RunLaunched event: {aggregate_id}"
            )
        final_status = payload.get("status")
        if final_status not in status_group("run", "terminal"):
            raise EventIntegrityError(f"invalid terminal run status: {final_status!r}")
        terminal = _deep_merge(current, payload.get("patch", {}))
        terminal["status"] = final_status
        terminal["terminal_event_id"] = event["event_id"]
        bucket[aggregate_id] = terminal
        out["open_runs"].pop(aggregate_id, None)
    elif event_type == "RunResultFinalized":
        current = _run_record(out, aggregate_id)
        if (
            not current.get("terminal_event_id")
            or current.get("status") not in status_group("run", "terminal")
        ):
            raise EventIntegrityError(
                f"RunResultFinalized requires an earlier RunTerminal event: "
                f"{aggregate_id}"
            )
        finalized = copy.deepcopy(current)
        finalized["latest_scientific_result"] = _scientific_result_summary(
            payload,
            current,
            aggregate_id,
        )
        finalized["result_finalized_event_id"] = event["event_id"]
        bucket[aggregate_id] = finalized
    elif event_type == "RunAttentionAcknowledged":
        current = _run_record(out, aggregate_id)
        acknowledged = _deep_merge(current, payload.get("patch", {}))
        acknowledged["attention_acknowledged"] = True
        acknowledged["attention_acknowledged_event_id"] = event["event_id"]
        bucket[aggregate_id] = acknowledged
    elif event_type == "ResourceRegistered":
        record = _record(payload)
        record.setdefault("name", aggregate_id)
        record.setdefault("id", aggregate_id)
        bucket[aggregate_id] = record
    elif event_type == "ResourceAllocationCreated":
        record = _record(payload)
        record.setdefault("alloc_id", aggregate_id)
        record.setdefault("id", aggregate_id)
        record["status"] = "OPEN"
        bucket[aggregate_id] = record
    elif event_type == "ResourceAllocationLinked":
        current = bucket.get(aggregate_id)
        if not isinstance(current, dict) or current.get("status") != "OPEN":
            raise EventIntegrityError(
                f"cannot link missing or closed allocation: {aggregate_id}"
            )
        patch = payload.get("patch")
        if not isinstance(patch, dict):
            raise EventIntegrityError("ResourceAllocationLinked requires patch")
        bucket[aggregate_id] = _deep_merge(current, patch)
    elif event_type == "ResourceAllocationReleased":
        current = bucket.get(aggregate_id)
        if not isinstance(current, dict) or current.get("status") != "OPEN":
            raise EventIntegrityError(
                f"cannot release missing or closed allocation: {aggregate_id}"
            )
        patch = payload.get("patch")
        if not isinstance(patch, dict):
            raise EventIntegrityError("ResourceAllocationReleased requires patch")
        released = _deep_merge(current, patch)
        released["status"] = "RELEASED"
        bucket[aggregate_id] = released
    elif event_type in {"LearningRecorded", "RulePromoted", "RuleRetired"}:
        record = _record(payload)
        record.setdefault("id", aggregate_id)
        if event_type == "RulePromoted":
            record["status"] = "PROMOTED"
        elif event_type == "RuleRetired":
            record["status"] = "RETIRED"
        bucket[aggregate_id] = record
    else:
        raise EventIntegrityError(f"unhandled event_type: {event_type}")

    key = f"{aggregate_type}/{aggregate_id}"
    # Legacy records may be structurally incomplete by construction.  Follow-up
    # migration events carry a signed source marker, so replay can distinguish
    # them deterministically from ordinary post-cutover mutations.  The first
    # normal event against an imported aggregate still enforces the current
    # schema and therefore fails closed until the record is normalized.
    migration_event = event_type == "AggregateImported" or isinstance(
        payload.get("_migration"), dict
    )
    if (
        not migration_event
        and aggregate_type in {"change", "decision", "learning"}
        and isinstance(bucket.get(aggregate_id), dict)
        and not bucket[aggregate_id].get("recorded_at")
    ):
        # Facade payloads stay retry-stable; the event envelope supplies the
        # authoritative observation time during the deterministic fold.
        bucket[aggregate_id]["recorded_at"] = event["occurred_at"]
    if not migration_event and aggregate_id in bucket:
        validate_aggregate_record(aggregate_type, bucket[aggregate_id])
    out["aggregate_versions"][key] = event["aggregate_version"]
    out["source_seq"] = event["seq"]
    out["source_hash"] = event["hash"]
    return out


def fold(events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    state = empty_state()
    expected_seq = 1
    expected_prev_hash = ""
    versions: dict[str, int] = {}
    for event in events:
        validate_event_shape(event)
        if event["seq"] != expected_seq:
            raise EventIntegrityError(
                f"event seq must be {expected_seq}, got {event['seq']!r}"
            )
        if event["prev_hash"] != expected_prev_hash:
            raise EventIntegrityError(
                f"event {event['event_id']} prev_hash does not match the chain"
            )
        calculated = event_hash(event)
        if event["hash"] != calculated:
            raise EventIntegrityError(
                f"event {event['event_id']} hash mismatch"
            )
        key = f"{event['aggregate_type']}/{event['aggregate_id']}"
        expected_version = versions.get(key, 0) + 1
        if event["aggregate_version"] != expected_version:
            raise EventIntegrityError(
                f"{key} aggregate_version must be {expected_version}, "
                f"got {event['aggregate_version']!r}"
            )
        state = apply_event(state, event)
        versions[key] = expected_version
        if event["event_type"] == "TransactionCommitted":
            participants = event["payload"].get("participants", [])
            for participant in participants:
                participant_key = (
                    f"{participant['aggregate_type']}/{participant['aggregate_id']}"
                )
                if participant_key == key:
                    if participant["aggregate_version"] != expected_version:
                        raise EventIntegrityError(
                            "transaction owner participant version does not match "
                            "the event envelope"
                        )
                    continue
                participant_expected = versions.get(participant_key, 0) + 1
                if participant["aggregate_version"] != participant_expected:
                    raise EventIntegrityError(
                        f"{participant_key} aggregate_version must be "
                        f"{participant_expected}, got "
                        f"{participant['aggregate_version']!r}"
                    )
                versions[participant_key] = participant_expected
        if event["event_type"] == "PackageActivated":
            finalization = _scope_finalization(event["payload"])
            if finalization is not None:
                for aggregate_type, participant in (
                    ("proposal", finalization["proposal"]),
                    ("direction", finalization["direction"]),
                ):
                    participant_key = (
                        f"{aggregate_type}/{participant['aggregate_id']}"
                    )
                    participant_expected = versions.get(participant_key, 0) + 1
                    if participant["aggregate_version"] != participant_expected:
                        raise EventIntegrityError(
                            f"{participant_key} aggregate_version must be "
                            f"{participant_expected}, got "
                            f"{participant['aggregate_version']!r}"
                        )
                    versions[participant_key] = participant_expected
        if event["event_type"] in {
            "PackageMaterialized",
            "PackageActivated",
            "PackageExperimentBound",
            "PackageReopenedAsDraft",
        }:
            if event["event_type"] == "PackageReopenedAsDraft":
                participants = _experiment_unbindings(event["payload"])
            elif (
                event["event_type"] == "PackageActivated"
                and _reopen_reactivation(event["payload"]) is not None
            ):
                participants = _experiment_restorations(event["payload"])
            else:
                participants = _experiment_bindings(event["payload"])
            for binding in participants:
                participant_key = f"experiment/{binding['aggregate_id']}"
                participant_expected = versions.get(participant_key, 0) + 1
                if binding["aggregate_version"] != participant_expected:
                    raise EventIntegrityError(
                        f"{participant_key} aggregate_version must be "
                        f"{participant_expected}, got "
                        f"{binding['aggregate_version']!r}"
                    )
                versions[participant_key] = participant_expected
        expected_prev_hash = event["hash"]
        expected_seq += 1
    return state
