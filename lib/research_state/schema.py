"""Load and validate the single machine-readable research-state schema."""

from __future__ import annotations

import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from .package_identity import PackageIdentityViolation
from .package_identity import validate_record as validate_package_identity


SCHEMA_PATH = Path(__file__).with_name("schema.json")


class SchemaViolation(ValueError):
    """A record contains an unknown schema version, enum, or required field."""


@lru_cache(maxsize=1)
def load_schema() -> dict[str, Any]:
    data = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise SchemaViolation("research-state schema_version must be 1")
    _validate_schema(data)
    return data


def _string_list(data: dict[str, Any], key: str) -> list[str]:
    values = data.get(key)
    if (
        not isinstance(values, list)
        or not all(isinstance(value, str) and value for value in values)
        or len(values) != len(set(values))
    ):
        raise SchemaViolation(f"{key} must be a unique list of non-empty strings")
    return values


def _validate_schema(data: dict[str, Any]) -> None:
    aggregate_types = set(_string_list(data, "aggregate_types"))
    event_types = set(_string_list(data, "event_types"))
    event_aggregate_types = data.get("event_aggregate_types")
    if not isinstance(event_aggregate_types, dict):
        raise SchemaViolation("event_aggregate_types must be an object")
    unknown_events = set(event_aggregate_types) - event_types
    unknown_aggregates = set(event_aggregate_types.values()) - aggregate_types
    if unknown_events or unknown_aggregates:
        raise SchemaViolation(
            "event_aggregate_types contains unknown events or aggregates: "
            f"events={sorted(unknown_events)}, aggregates={sorted(unknown_aggregates)}"
        )
    aggregate_schemas = data.get("aggregate_schemas")
    if not isinstance(aggregate_schemas, dict) or set(aggregate_schemas) != aggregate_types:
        raise SchemaViolation(
            "aggregate_schemas must define exactly every aggregate type"
        )
    versions = data.get("event_schema_versions")
    if (
        not isinstance(versions, list)
        or not versions
        or not all(isinstance(value, int) and value > 0 for value in versions)
    ):
        raise SchemaViolation("event_schema_versions must be positive integers")

    required_enums = {
        "package_lifecycle",
        "package_draft_status",
        "package_phase",
        "package_category_compat",
        "package_status_compat",
        "experiment_status",
        "run_status",
        "run_status_compat",
        "rule_status",
        "rule_level",
        "rule_kind",
        "scope_kind",
        "scope_kind_compat",
        "scope_status",
        "scope_confirmation",
        "scope_operation",
        "scope_gate",
        "control_mode",
        "proposal_disposition",
        "campaign_status",
        "campaign_route",
        "autonomy_mode",
        "live_action",
        "decision_route",
        "result_verdict",
        "result_validity",
        "evidence_kind",
        "resource_status",
        "resource_allocation_status",
        "knowledge_edge_type",
    }
    enums = data.get("enums")
    if not isinstance(enums, dict):
        raise SchemaViolation("enums must be an object")
    missing = sorted(required_enums - set(enums))
    if missing:
        raise SchemaViolation(f"schema is missing required enums: {missing}")
    for name, values in enums.items():
        _string_list({"values": values}, "values")

    status_groups = data.get("status_groups")
    run_groups = status_groups.get("run") if isinstance(status_groups, dict) else None
    if not isinstance(run_groups, dict) or set(run_groups) != {"active", "terminal"}:
        raise SchemaViolation(
            "status_groups.run must define exactly active and terminal"
        )
    grouped_run_statuses: set[str] = set()
    for name, values in run_groups.items():
        statuses = set(_string_list({"values": values}, "values"))
        unknown = statuses - set(enums["run_status"])
        overlap = statuses & grouped_run_statuses
        if unknown or overlap:
            raise SchemaViolation(
                f"status_groups.run.{name} has unknown or repeated statuses: "
                f"{sorted(unknown | overlap)}"
            )
        grouped_run_statuses.update(statuses)
    if grouped_run_statuses != set(enums["run_status"]):
        raise SchemaViolation(
            "status_groups.run must classify every canonical run status exactly once"
        )

    scope = data.get("scope")
    if not isinstance(scope, dict):
        raise SchemaViolation("scope must be an object")
    required_node_fields = set(
        _string_list(scope, "required_node_fields")
    )
    required_scope_fields = {
        "id", "level", "parents", "version", "status", "spec", "source"
    }
    if required_node_fields != required_scope_fields:
        raise SchemaViolation(
            "scope.required_node_fields must define the canonical node envelope"
        )
    _string_list(scope, "reading_fields")
    required_gate = scope.get("required_gate")
    specs = scope.get("specs")
    scope_kinds = set(enums["scope_kind"])
    if (
        not isinstance(required_gate, dict)
        or set(required_gate) != scope_kinds
        or set(required_gate.values()) - set(enums["scope_gate"])
    ):
        raise SchemaViolation(
            "scope.required_gate must map every scope kind to a scope_gate"
        )
    if not isinstance(specs, dict) or set(specs) != scope_kinds:
        raise SchemaViolation("scope.specs must define every canonical scope kind")
    allowed_field_kinds = {"scalar_text", "list_text", "reference", "metric", "enum"}
    for level, contract in specs.items():
        fields = contract.get("fields") if isinstance(contract, dict) else None
        if not isinstance(fields, dict) or not fields:
            raise SchemaViolation(f"scope.specs.{level}.fields must be non-empty")
        for field, field_contract in fields.items():
            if not isinstance(field_contract, dict):
                raise SchemaViolation(
                    f"scope.specs.{level}.fields.{field} must be an object"
                )
            kind = field_contract.get("kind")
            if kind not in allowed_field_kinds:
                raise SchemaViolation(
                    f"scope.specs.{level}.fields.{field} has invalid kind"
                )
            if kind in {"scalar_text", "list_text", "metric"}:
                low = field_contract.get("min_words")
                high = field_contract.get("max_words")
                if (
                    isinstance(low, bool)
                    or not isinstance(low, int)
                    or isinstance(high, bool)
                    or not isinstance(high, int)
                    or low < 1
                    or high < low
                ):
                    raise SchemaViolation(
                        f"scope.specs.{level}.fields.{field} has invalid word bounds"
                    )
            if kind == "enum" and field_contract.get("enum") not in enums:
                raise SchemaViolation(
                    f"scope.specs.{level}.fields.{field} names an unknown enum"
                )

    supported_types = {"string", "integer", "number", "boolean", "object", "array", "null"}
    for aggregate_type, contract in aggregate_schemas.items():
        if not isinstance(contract, dict):
            raise SchemaViolation(
                f"aggregate_schemas.{aggregate_type} must be an object"
            )
        required = contract.get("required")
        properties = contract.get("properties")
        if (
            not isinstance(required, list)
            or not all(isinstance(field, str) and field for field in required)
            or not isinstance(properties, dict)
        ):
            raise SchemaViolation(
                f"aggregate_schemas.{aggregate_type} requires required/properties"
            )
        if set(required) - set(properties):
            raise SchemaViolation(
                f"aggregate_schemas.{aggregate_type} requires undefined fields"
            )
        for field, field_contract in properties.items():
            if not isinstance(field_contract, dict):
                raise SchemaViolation(
                    f"aggregate_schemas.{aggregate_type}.{field} must be an object"
                )
            declared = field_contract.get("type")
            declared_types = [declared] if isinstance(declared, str) else declared
            if (
                not isinstance(declared_types, list)
                or not declared_types
                or not all(value in supported_types for value in declared_types)
            ):
                raise SchemaViolation(
                    f"aggregate_schemas.{aggregate_type}.{field} has invalid type"
                )
            enum_name = field_contract.get("enum")
            if enum_name is not None and enum_name not in enums:
                raise SchemaViolation(
                    f"aggregate_schemas.{aggregate_type}.{field} names unknown enum "
                    f"{enum_name!r}"
                )
    constraints = data.get("aggregate_constraints")
    rule_kind_by_level = (
        constraints.get("rule_kind_by_level")
        if isinstance(constraints, dict)
        else None
    )
    if not isinstance(rule_kind_by_level, dict):
        raise SchemaViolation(
            "aggregate_constraints.rule_kind_by_level must be an object"
        )
    if set(rule_kind_by_level) - set(enums["rule_level"]):
        raise SchemaViolation(
            "aggregate_constraints.rule_kind_by_level has unknown levels"
        )
    if set(rule_kind_by_level.values()) - set(enums["rule_kind"]):
        raise SchemaViolation(
            "aggregate_constraints.rule_kind_by_level has unknown kinds"
        )

    compatibility = data.get("compatibility")
    if not isinstance(compatibility, dict):
        raise SchemaViolation("compatibility must be an object")
    compat_contracts = {
        "run_status": ("run_status_compat", "run_status"),
        "experiment_status": (None, "experiment_status"),
        "package_terminal_status": ("package_status_compat", "package_lifecycle"),
    }
    for name, (source_enum, target_enum) in compat_contracts.items():
        mapping = compatibility.get(name)
        if not isinstance(mapping, dict) or not mapping:
            raise SchemaViolation(f"compatibility.{name} must be a non-empty object")
        if source_enum is not None:
            unknown_sources = set(mapping) - set(enums[source_enum])
            if unknown_sources:
                raise SchemaViolation(
                    f"compatibility.{name} has unknown source values: {sorted(unknown_sources)}"
                )
        unknown_targets = set(mapping.values()) - set(enums[target_enum])
        if unknown_targets:
            raise SchemaViolation(
                f"compatibility.{name} has unknown target values: {sorted(unknown_targets)}"
            )

    transitions = data.get("transitions")
    phase_graph = transitions.get("package_phase") if isinstance(transitions, dict) else None
    if not isinstance(phase_graph, dict):
        raise SchemaViolation("transitions.package_phase must be an object")
    phases = set(enums["package_phase"])
    if set(phase_graph) != phases:
        raise SchemaViolation(
            "transitions.package_phase must define exactly every package phase"
        )
    for source, targets in phase_graph.items():
        _string_list({"targets": targets}, "targets")
        unknown = set(targets) - phases
        if unknown:
            raise SchemaViolation(
                f"transitions.package_phase.{source} has unknown targets: {sorted(unknown)}"
            )


def enum(name: str) -> tuple[str, ...]:
    values = load_schema().get("enums", {}).get(name)
    if not isinstance(values, list):
        raise SchemaViolation(f"unknown enum: {name}")
    return tuple(str(value) for value in values)


def require_enum(name: str, value: Any) -> str:
    if value not in enum(name):
        raise SchemaViolation(f"{name} must be one of {list(enum(name))}, got {value!r}")
    return str(value)


def validate_event_shape(event: dict[str, Any]) -> None:
    required = {
        "seq",
        "event_id",
        "schema_version",
        "event_type",
        "aggregate_type",
        "aggregate_id",
        "aggregate_version",
        "command_id",
        "idempotency_key",
        "actor",
        "occurred_at",
        "payload",
        "prev_hash",
        "hash",
    }
    missing = sorted(required - set(event))
    if missing:
        raise SchemaViolation(f"event missing required field(s): {missing}")
    for key in ("seq", "aggregate_version"):
        value = event[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise SchemaViolation(f"event {key} must be a positive integer")
    versions = load_schema()["event_schema_versions"]
    if event["schema_version"] not in versions:
        raise SchemaViolation(
            f"unknown event schema_version {event['schema_version']!r}; supported={versions}"
        )
    for key in (
        "event_id",
        "event_type",
        "aggregate_type",
        "aggregate_id",
        "command_id",
        "idempotency_key",
        "occurred_at",
        "hash",
    ):
        if not isinstance(event[key], str) or not event[key]:
            raise SchemaViolation(f"event {key} must be a non-empty string")
    causation_id = event.get("causation_id")
    if causation_id is not None and (
        not isinstance(causation_id, str) or not causation_id
    ):
        raise SchemaViolation("event causation_id must be null or a non-empty string")
    try:
        datetime.fromisoformat(event["occurred_at"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise SchemaViolation("event occurred_at must be ISO-8601") from exc
    digest = event["hash"].lower()
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise SchemaViolation("event hash must be a 64-character hexadecimal digest")
    previous = event["prev_hash"]
    if not isinstance(previous, str) or (
        previous
        and (
            len(previous) != 64
            or any(char not in "0123456789abcdef" for char in previous.lower())
        )
    ):
        raise SchemaViolation(
            "event prev_hash must be empty or a 64-character hexadecimal digest"
        )
    if event["aggregate_type"] not in load_schema()["aggregate_types"]:
        raise SchemaViolation(f"unknown aggregate_type: {event['aggregate_type']!r}")
    if event["event_type"] not in load_schema()["event_types"]:
        raise SchemaViolation(f"unknown event_type: {event['event_type']!r}")
    required_aggregate = load_schema()["event_aggregate_types"].get(event["event_type"])
    if required_aggregate is not None and event["aggregate_type"] != required_aggregate:
        raise SchemaViolation(
            f"{event['event_type']} requires aggregate_type={required_aggregate!r}, "
            f"got {event['aggregate_type']!r}"
        )
    if not isinstance(event["payload"], dict):
        raise SchemaViolation("event payload must be an object")
    actor = event["actor"]
    if not isinstance(actor, dict) or actor.get("type") not in {"user", "agent", "system"}:
        raise SchemaViolation("event actor.type must be user, agent, or system")
    if not isinstance(actor.get("id"), str) or not actor["id"]:
        raise SchemaViolation("event actor.id must be a non-empty string")


def _matches_type(value: Any, type_name: str) -> bool:
    if type_name == "null":
        return value is None
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if type_name == "boolean":
        return isinstance(value, bool)
    if type_name == "object":
        return isinstance(value, dict)
    if type_name == "array":
        return isinstance(value, list)
    return False


def validate_aggregate_record(
    aggregate_type: str,
    record: dict[str, Any],
    *,
    allow_import: bool = False,
) -> None:
    """Validate one folded aggregate against the central field contract.

    Historical imports are intentionally shape-preserving and therefore bypass
    field validation. Every normal command is validated after its reducer has
    produced the complete next record.
    """
    if allow_import:
        return
    schema = load_schema()
    contract = schema["aggregate_schemas"].get(aggregate_type)
    if not isinstance(record, dict) or not isinstance(contract, dict):
        raise SchemaViolation(f"unknown aggregate schema: {aggregate_type!r}")
    missing = [
        field for field in contract["required"]
        if field not in record
    ]
    if missing:
        raise SchemaViolation(
            f"{aggregate_type} aggregate missing required field(s): {missing}"
        )
    for field, field_contract in contract["properties"].items():
        if field not in record:
            continue
        value = record[field]
        declared = field_contract["type"]
        declared_types = [declared] if isinstance(declared, str) else declared
        if not any(_matches_type(value, type_name) for type_name in declared_types):
            raise SchemaViolation(
                f"{aggregate_type}.{field} must have type {declared_types}, "
                f"got {type(value).__name__}"
            )
        enum_name = field_contract.get("enum")
        # A nullable enum field is checked only when it carries a value.
        if enum_name is not None and value is not None:
            require_enum(str(enum_name), value)
        if "const" in field_contract and value != field_contract["const"]:
            raise SchemaViolation(
                f"{aggregate_type}.{field} must equal {field_contract['const']!r}"
            )
    if aggregate_type == "package" and record.get("lifecycle") == "ACTIVE":
        blocker = record.get("blocker")
        if blocker is None:
            require_enum("package_phase", record.get("phase"))
        if blocker is not None and (
            not isinstance(blocker.get("code"), str)
            or not blocker["code"]
            or not isinstance(blocker.get("summary"), str)
            or not blocker["summary"]
        ):
            raise SchemaViolation(
                "package.blocker requires non-empty code and summary"
            )
    if aggregate_type == "package":
        try:
            validate_package_identity(record)
        except PackageIdentityViolation as exc:
            raise SchemaViolation(str(exc)) from exc
    if aggregate_type == "rule":
        level = record.get("level")
        kind = record.get("kind")
        expected = load_schema()["aggregate_constraints"][
            "rule_kind_by_level"
        ].get(level)
        if expected is not None and kind != expected:
            raise SchemaViolation(
                f"rule kind for level {level!r} must be {expected!r}"
            )
    if aggregate_type == "change":
        owned_files = record.get("owned_files")
        validating = record.get("validating_experiments")
        review = record.get("review")
        if (
            not isinstance(owned_files, list)
            or not owned_files
            or not all(isinstance(path, str) and path.strip() for path in owned_files)
        ):
            raise SchemaViolation(
                "change.owned_files must be a non-empty string list"
            )
        if (
            not isinstance(validating, list)
            or not validating
            or not all(
                isinstance(identity, str) and identity.strip()
                for identity in validating
            )
        ):
            raise SchemaViolation(
                "change.validating_experiments must be a non-empty string list"
            )
        if not isinstance(review, dict) or not review:
            raise SchemaViolation("change.review must be a non-empty object")
    if aggregate_type in {"decision", "learning"}:
        evidence = record.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise SchemaViolation(
                f"{aggregate_type}.evidence must be a non-empty array"
            )
    if aggregate_type == "decision":
        actor = record.get("actor")
        if (
            not isinstance(actor, dict)
            or actor.get("type") not in {"user", "agent", "system"}
            or not isinstance(actor.get("id"), str)
            or not actor["id"]
        ):
            raise SchemaViolation(
                "decision.actor requires a typed non-empty identity"
            )


def rule_kind_for_level(level: str) -> str | None:
    """Return the centrally declared Rule kind for a governed level."""
    value = load_schema()["aggregate_constraints"]["rule_kind_by_level"].get(level)
    return str(value) if value is not None else None


def compatibility_map(name: str) -> dict[str, str]:
    values = load_schema().get("compatibility", {}).get(name)
    if not isinstance(values, dict):
        raise SchemaViolation(f"unknown compatibility map: {name}")
    return {str(key): str(value) for key, value in values.items()}


def status_group(owner: str, name: str) -> frozenset[str]:
    """Return one centrally classified status group."""
    values = load_schema().get("status_groups", {}).get(owner, {}).get(name)
    if not isinstance(values, list):
        raise SchemaViolation(f"unknown status group: {owner}.{name}")
    return frozenset(str(value) for value in values)


def scope_contract() -> dict[str, Any]:
    """Return the validated Scope field and governance contract."""
    return load_schema()["scope"]


def transition_map(name: str) -> dict[str, tuple[str, ...]]:
    values = load_schema().get("transitions", {}).get(name)
    if not isinstance(values, dict):
        raise SchemaViolation(f"unknown transition map: {name}")
    out: dict[str, tuple[str, ...]] = {}
    for source, targets in values.items():
        if not isinstance(targets, list):
            raise SchemaViolation(f"transition map {name}.{source} must be a list")
        out[str(source)] = tuple(str(target) for target in targets)
    return out
