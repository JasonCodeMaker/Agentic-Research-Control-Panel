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

    if event_type in {"AggregateImported", "AggregateUpserted", "ScopeCommitted"}:
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
    elif event_type == "PackageMaterialized":
        if aggregate_id in bucket:
            raise EventIntegrityError(f"package already exists: {aggregate_id}")
        record = _record(payload)
        if record.get("id", aggregate_id) != aggregate_id:
            raise EventIntegrityError(
                "PackageMaterialized record id must equal aggregate_id"
            )
        record["id"] = aggregate_id
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
                "Package sourceExperiments must match experiment bindings exactly"
            )
        bucket[aggregate_id] = record
        _apply_experiment_bindings(out, payload, package_id=aggregate_id)
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
        if event["event_type"] in {
            "PackageMaterialized",
            "PackageExperimentBound",
        }:
            for binding in _experiment_bindings(event["payload"]):
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
