"""Pure validation for governed Project, Direction, and Experiment intent.

This module owns no persistence.  Research skills validate candidate Scope
nodes here, then route proposals and accepted transitions through the
``research-op`` management gateway.
"""

from __future__ import annotations

import re
from typing import Any

from lib.research_state.schema import enum, scope_contract


# This module owns validation behavior, while schema.json owns every field,
# enum, word bound, and gate vocabulary.
_SCOPE = scope_contract()
FIELD_CONTRACTS = {
    level: contract["fields"]
    for level, contract in _SCOPE["specs"].items()
}
SPEC_FIELDS = {
    level: frozenset(fields)
    for level, fields in FIELD_CONTRACTS.items()
}
SCALAR_TEXT_FIELDS = {
    level: frozenset(
        field
        for field, contract in fields.items()
        if contract["kind"] in {"scalar_text", "metric"}
    )
    for level, fields in FIELD_CONTRACTS.items()
}
LIST_TEXT_FIELDS = {
    level: frozenset(
        field
        for field, contract in fields.items()
        if contract["kind"] == "list_text"
    )
    for level, fields in FIELD_CONTRACTS.items()
}
REF_FIELDS = {
    level: frozenset(
        field
        for field, contract in fields.items()
        if contract["kind"] == "reference"
    )
    for level, fields in FIELD_CONTRACTS.items()
}

CONTROL_MODES = frozenset(enum("control_mode"))
COMMITTED_STATUSES = frozenset(enum("scope_status"))
WORD_RE = re.compile(
    r"[A-Za-z0-9]+(?:[@._:/+-][A-Za-z0-9]+)*|[\u4e00-\u9fff]"
)

READING_FIELDS = frozenset(_SCOPE["reading_fields"])
OPS = enum("scope_operation")
REQUIRED_GATE = dict(_SCOPE["required_gate"])


class RuleViolation(Exception):
    """A candidate Scope node violates its intent contract."""


def _word_count(value: str) -> int:
    return len(WORD_RE.findall(value))


def _check_word_range(
    *,
    field: str,
    text: str,
    bounds: tuple[int, int],
) -> None:
    low, high = bounds
    count = _word_count(text)
    if count < low or count > high:
        raise RuleViolation(
            f"spec field {field!r} must be {low}-{high} words, got {count}"
        )


def _word_bounds(level: str, field: str) -> tuple[int, int]:
    contract = FIELD_CONTRACTS[level][field]
    return int(contract["min_words"]), int(contract["max_words"])


def _validate_spec_value(level: str, field: str, value: Any) -> None:
    contract = FIELD_CONTRACTS[level][field]
    kind = contract["kind"]
    if kind == "list_text":
        if not isinstance(value, list) or not value:
            raise RuleViolation(
                f"spec field {field!r} must be a non-empty list"
            )
        for index, item in enumerate(value):
            if not isinstance(item, str):
                raise RuleViolation(
                    f"spec field {field!r}[{index}] must be a string"
                )
            _check_word_range(
                field=f"{field}[{index}]",
                text=item,
                bounds=_word_bounds(level, field),
            )
        return

    if kind == "reference":
        if not isinstance(value, str) or not value.strip():
            raise RuleViolation(
                f"spec field {field!r} must be a non-empty reference string"
            )
        return

    if kind == "enum":
        allowed = frozenset(enum(str(contract["enum"])))
        if value not in allowed:
            raise RuleViolation(
                f"spec field {field!r} must be one of {sorted(allowed)}"
            )
        return

    if kind in {"scalar_text", "metric"}:
        if isinstance(value, str):
            _check_word_range(
                field=field,
                text=value,
                bounds=_word_bounds(level, field),
            )
        elif kind != "metric":
            raise RuleViolation(f"spec field {field!r} must be a string")
        elif not isinstance(value, dict) or not value:
            raise RuleViolation(
                "spec field 'metric' must be a non-empty object or a "
                f"{_word_bounds(level, field)[0]}-"
                f"{_word_bounds(level, field)[1]} word string"
            )


def validate_node(node: dict[str, Any]) -> None:
    """Validate a complete, persistence-independent Scope node."""
    if not isinstance(node, dict):
        raise RuleViolation("Scope node must be an object")

    required = set(_SCOPE["required_node_fields"])
    missing_node_fields = sorted(required - set(node))
    if missing_node_fields:
        raise RuleViolation(
            f"Scope node missing required field(s): {missing_node_fields}"
        )

    level = node.get("level")
    if level not in SPEC_FIELDS:
        raise RuleViolation(f"illegal level: {level!r}")
    if "yardstick" in node:
        raise RuleViolation("old field 'yardstick' is rejected; use 'spec'")
    if "provenance" in node:
        raise RuleViolation("old field 'provenance' is rejected; use 'source'")

    node_id = node.get("id")
    if not isinstance(node_id, str) or not node_id.strip():
        raise RuleViolation("Scope node id must be a non-empty string")

    parents = node.get("parents")
    if not isinstance(parents, list) or not all(
        isinstance(parent, str) and parent.strip() for parent in parents
    ):
        raise RuleViolation(
            "Scope node parents must be a list of non-empty ids"
        )
    if level == "project" and parents:
        raise RuleViolation("Project Scope nodes cannot have parents")
    if level != "project" and not parents:
        raise RuleViolation(f"{level} Scope nodes require a parent")

    version = node.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise RuleViolation("Scope node version must be a positive integer")
    if node.get("status") not in COMMITTED_STATUSES:
        raise RuleViolation(
            "Scope node status must be one of "
            f"{sorted(COMMITTED_STATUSES)}"
        )
    if not isinstance(node.get("source"), str) or not node["source"].strip():
        raise RuleViolation("Scope node source must be a non-empty string")

    spec = node.get("spec")
    if not isinstance(spec, dict):
        raise RuleViolation("Scope node must carry a spec object")
    allowed = SPEC_FIELDS[level]
    missing_spec_fields = sorted(allowed - set(spec))
    if missing_spec_fields:
        raise RuleViolation(
            f"missing spec field(s) for level {level!r}: "
            f"{missing_spec_fields}"
        )
    for field, value in spec.items():
        if field in READING_FIELDS:
            raise RuleViolation(
                f"reading field {field!r} cannot live in a spec"
            )
        if field not in allowed:
            raise RuleViolation(
                f"unknown spec field {field!r} for level {level!r}"
            )
        _validate_spec_value(level, field, value)

    if level == "experiment":
        package_id = node.get("package_id")
        if package_id is not None and (
            not isinstance(package_id, str) or not package_id.strip()
        ):
            raise RuleViolation(
                "Experiment package_id must be null or a non-empty string"
            )
