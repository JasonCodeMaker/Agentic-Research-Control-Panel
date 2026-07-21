"""Validation, shaping, and query helpers for self-evolve project memory.

Self-evolve may still generate and install Skill bundles outside the workspace
research root.  Learning, oracle/admission Decision, and Rule lifecycle records
are management state. Their only writer is the typed research-op gateway.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

try:
    from ..research_state import (
        CommandConflict,
        CommandRejected,
        EventStore,
        ResearchPaths,
    )
except ImportError:
    from research_state import (  # type: ignore
        CommandConflict,
        CommandRejected,
        EventStore,
        ResearchPaths,
    )

from . import schema


ACTOR = {"type": "agent", "id": "self-evolve"}
ADMITTED = {"FULLY_ADMITTED", "TENTATIVELY_ADMITTED", "APPROVED"}
RESERVED_ORIGIN = "selfevolve"


def resolve_paths(value: str | Path | ResearchPaths) -> ResearchPaths:
    """Resolve a workspace or canonical research root."""
    if isinstance(value, ResearchPaths) or (
        hasattr(value, "workspace")
        and hasattr(value, "root")
        and hasattr(value, "events")
        and hasattr(value, "current")
    ):
        return value
    path = Path(value).expanduser().resolve()
    if path.name == ".research" or (path / "VERSION").is_file():
        return ResearchPaths.resolve(workspace=path.parent, research_root=path)
    return ResearchPaths.resolve(workspace=path)


def actor_record(actor: dict[str, str] | None) -> dict[str, str]:
    """Return the canonical actor stored on self-evolve Decisions."""
    return copy.deepcopy(actor or ACTOR)


def management_state(paths: ResearchPaths) -> dict[str, Any]:
    """Query the current management projection without writing it."""
    return EventStore(paths).state()


def _scope(rule_or_learning: dict[str, Any]) -> dict[str, Any]:
    value = rule_or_learning.get("scope")
    if not isinstance(value, dict):
        raise CommandRejected("scope-required", "self-evolve memory requires bounded scope")
    try:
        schema.validate_scope(value, "memory")
    except schema.SchemaViolation as exc:
        raise CommandRejected("scope-invalid", str(exc)) from exc
    return copy.deepcopy(value)


def _evidence_refs(
    record: dict[str, Any],
    *,
    rejection_rule: str,
) -> list[dict[str, Any]]:
    refs = record.get("evidence_refs")
    try:
        schema.validate_evidence_refs(refs)
    except schema.SchemaViolation as exc:
        raise CommandRejected(rejection_rule, str(exc)) from exc
    return copy.deepcopy(refs)


def learning_aggregate_id(rule_id: str, version: str) -> str:
    return f"learning:{rule_id}@{version}"


def rule_aggregate_id(rule_id: str, version: str) -> str:
    return f"{rule_id}@{version}"


def prepare_learning(record: dict[str, Any]) -> dict[str, Any]:
    """Validate and shape an evidence-backed, non-binding observation."""
    learning = copy.deepcopy(record)
    learning_id = learning.get("id")
    if not isinstance(learning_id, str) or not learning_id:
        raise CommandRejected("learning-id-required", "Learning requires a stable id")
    learning["scope"] = _scope(learning)
    learning["evidence_refs"] = _evidence_refs(
        learning,
        rejection_rule="learning-evidence-required",
    )
    learning["evidence"] = copy.deepcopy(learning["evidence_refs"])
    learning.setdefault("status", "CANDIDATE")
    learning.setdefault("origin", RESERVED_ORIGIN)
    if learning["origin"] != RESERVED_ORIGIN:
        raise CommandRejected(
            "learning-origin-reserved",
            f"self-evolve Learning origin must be {RESERVED_ORIGIN!r}",
        )
    return learning


def validate_learning_insert(
    state: dict[str, Any],
    learning_id: str,
) -> None:
    """Enforce immutable Learning identity against a locked state snapshot."""
    if learning_id in state["aggregates"]["learning"]:
        raise CommandConflict(
            "learning-immutable",
            f"Learning already exists; record a new Learning id: {learning_id}",
        )


def prepare_decision(
    record: dict[str, Any],
    *,
    actor: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Validate and shape an oracle, admission, or lifecycle Decision."""
    decision = copy.deepcopy(record)
    decision_id = decision.get("id")
    if not isinstance(decision_id, str) or not decision_id:
        raise CommandRejected("decision-id-required", "Decision requires a stable id")
    if not decision.get("subject_id"):
        raise CommandRejected(
            "decision-subject-required", "Decision requires subject_id"
        )
    if not (decision.get("outcome") or decision.get("admission")):
        raise CommandRejected(
            "decision-outcome-required", "Decision requires outcome or admission"
        )
    decision["evidence_refs"] = _evidence_refs(
        decision,
        rejection_rule="decision-evidence-required",
    )
    decision["actor"] = actor_record(actor)
    decision["evidence"] = copy.deepcopy(decision["evidence_refs"])
    return decision


def validate_decision_insert(
    state: dict[str, Any],
    decision: dict[str, Any],
) -> None:
    """Enforce Decision immutability and subject existence."""
    decision_id = str(decision["id"])
    if decision_id in state["aggregates"]["decision"]:
        raise CommandConflict(
            "decision-immutable",
            f"Decision already exists; record a new Decision id: {decision_id}",
        )
    subject_id = str(decision["subject_id"])
    if subject_id.startswith("learning:"):
        if subject_id not in state["aggregates"]["learning"]:
            raise CommandRejected(
                "decision-subject-missing",
                f"Decision references unknown Learning: {subject_id}",
            )
    elif decision.get("decision_type") == "RULE_LIFECYCLE":
        if subject_id not in state["aggregates"]["rule"]:
            raise CommandRejected(
                "decision-subject-missing",
                f"Decision references unknown Rule: {subject_id}",
            )


def _validate_rule_shape(rule: dict[str, Any]) -> dict[str, Any]:
    candidate = copy.deepcopy(rule)
    rule_id = candidate.get("id")
    version = candidate.get("version")
    if not isinstance(rule_id, str) or not rule_id:
        raise CommandRejected("rule-id-required", "Rule requires a stable id")
    if not isinstance(version, str) or not version:
        raise CommandRejected("rule-version-required", "Rule requires an immutable version")
    candidate["scope"] = _scope(candidate)
    origin = candidate.get("origin", RESERVED_ORIGIN)
    if origin != RESERVED_ORIGIN:
        raise CommandRejected(
            "rule-origin-reserved",
            f"self-evolve promotion origin must be {RESERVED_ORIGIN!r}",
        )
    candidate["origin"] = origin
    packages = [str(value) for value in candidate["scope"].get("packages", [])]
    if packages == ["*"]:
        level, kind = "project", "constraint"
    else:
        level, kind = "package", "binding"
    if candidate.get("level", level) != level:
        raise CommandRejected(
            "rule-level-scope-mismatch",
            f"bounded scope requires level={level}",
        )
    if candidate.get("kind", kind) != kind:
        raise CommandRejected(
            "rule-kind-scope-mismatch",
            f"{level} self-evolve rules require kind={kind}",
        )
    candidate["level"] = level
    candidate["kind"] = kind
    if level == "package" and len(packages) == 1:
        candidate["package_id"] = packages[0]
    return candidate


def shape_rule_promotion(
    state: dict[str, Any],
    *,
    learning_id: str,
    decision_id: str,
    rule: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Shape the RulePromoted record from an immutable Learning."""
    promoted = _validate_rule_shape(rule)
    aggregate_id = rule_aggregate_id(promoted["id"], promoted["version"])
    learning = state["aggregates"]["learning"].get(learning_id, {})
    promoted.update(
        {
            "aggregate_id": aggregate_id,
            "source_learning_id": learning_id,
            "promotion_decision_id": decision_id,
            "evidence_refs": copy.deepcopy(learning.get("evidence_refs") or []),
            "lifecycle_state": "RULE_ACTIVE",
        }
    )
    return aggregate_id, promoted


def validate_rule_promotion(
    state: dict[str, Any],
    *,
    learning_id: str,
    decision_id: str,
    rule: dict[str, Any],
) -> None:
    """Enforce the evidence-backed admission policy on a locked state snapshot."""
    promoted = _validate_rule_shape(rule)
    aggregate_id = rule_aggregate_id(promoted["id"], promoted["version"])
    learning = state["aggregates"]["learning"].get(learning_id)
    if not isinstance(learning, dict):
        raise CommandRejected(
            "promotion-learning-missing",
            f"promotion references unknown Learning: {learning_id}",
        )
    try:
        schema.validate_evidence_refs(learning.get("evidence_refs"))
    except schema.SchemaViolation as exc:
        raise CommandRejected(
            "learning-evidence-required",
            f"Learning {learning_id} has no valid EvidenceRef: {exc}",
        ) from exc
    decision = state["aggregates"]["decision"].get(decision_id)
    if not isinstance(decision, dict):
        raise CommandRejected(
            "promotion-decision-missing",
            f"promotion references unknown Decision: {decision_id}",
        )
    if decision.get("subject_id") != learning_id:
        raise CommandRejected(
            "promotion-decision-subject-mismatch",
            f"Decision {decision_id} does not govern Learning {learning_id}",
        )
    try:
        schema.validate_evidence_refs(decision.get("evidence_refs"))
    except schema.SchemaViolation as exc:
        raise CommandRejected(
            "promotion-decision-evidence-required",
            f"Decision {decision_id} has no valid EvidenceRef: {exc}",
        ) from exc
    admission = decision.get("admission") or decision.get("outcome")
    if admission not in ADMITTED:
        raise CommandRejected(
            "promotion-not-admitted",
            f"Decision {decision_id} is {admission!r}, not admitted",
        )
    existing = state["aggregates"]["rule"].get(aggregate_id)
    if isinstance(existing, dict):
        raise CommandConflict(
            "rule-version-immutable",
            f"Rule version already exists; create a new version: {aggregate_id}",
        )


def preflight_promotion(
    paths: ResearchPaths,
    *,
    learning_id: str,
    rule: dict[str, Any],
    admission: str | None,
) -> dict[str, Any]:
    """Check promotion invariants before the admission Decision is committed."""
    promoted = _validate_rule_shape(rule)
    if admission not in ADMITTED:
        raise CommandRejected(
            "promotion-not-admitted",
            f"promotion admission is {admission!r}, not admitted",
        )
    state = EventStore(paths).state()
    learning = state["aggregates"]["learning"].get(learning_id)
    if not isinstance(learning, dict):
        raise CommandRejected(
            "promotion-learning-missing",
            f"promotion references unknown Learning: {learning_id}",
        )
    try:
        schema.validate_evidence_refs(learning.get("evidence_refs"))
    except schema.SchemaViolation as exc:
        raise CommandRejected(
            "learning-evidence-required",
            f"Learning {learning_id} has no valid EvidenceRef: {exc}",
        ) from exc
    aggregate_id = rule_aggregate_id(promoted["id"], promoted["version"])
    if aggregate_id in state["aggregates"]["rule"]:
        raise CommandConflict(
            "rule-version-immutable",
            f"Rule version already exists; create a new version: {aggregate_id}",
        )
    return promoted


def shape_rule_retirement(
    state: dict[str, Any],
    *,
    rule_id: str,
    version: str,
    decision_id: str,
    lifecycle_state: str,
) -> tuple[str, dict[str, Any]]:
    """Shape a RuleRetired record without mutating management state."""
    aggregate_id = rule_aggregate_id(rule_id, version)
    current = copy.deepcopy(state["aggregates"]["rule"].get(aggregate_id, {}))
    current.update(
        {
            "retirement_decision_id": decision_id,
            "lifecycle_state": lifecycle_state,
        }
    )
    return aggregate_id, current


def validate_rule_retirement(
    state: dict[str, Any],
    *,
    rule_id: str,
    version: str,
    decision_id: str,
) -> None:
    """Enforce reserved-origin retirement policy on a locked state snapshot."""
    aggregate_id = rule_aggregate_id(rule_id, version)
    current = state["aggregates"]["rule"].get(aggregate_id)
    if not isinstance(current, dict):
        raise CommandRejected(
            "rule-missing", f"cannot retire unknown Rule: {aggregate_id}"
        )
    if current.get("origin") != RESERVED_ORIGIN:
        raise CommandRejected(
            "rule-origin-retire-only",
            "self-evolve may retire only selfevolve-origin Rules",
        )
    if current.get("status") not in {"PROMOTED", "ACTIVE", "RULE_ACTIVE"}:
        raise CommandRejected(
            "rule-not-active",
            f"cannot retire Rule in status {current.get('status')!r}",
        )
    if decision_id not in state["aggregates"]["decision"]:
        raise CommandRejected(
            "retirement-decision-missing",
            f"retirement references unknown Decision: {decision_id}",
        )
    decision = state["aggregates"]["decision"][decision_id]
    if decision.get("subject_id") != aggregate_id:
        raise CommandRejected(
            "retirement-decision-subject-mismatch",
            f"Decision {decision_id} does not govern Rule {aggregate_id}",
        )


def preflight_retirement(
    paths: ResearchPaths,
    *,
    rule_id: str,
    version: str,
) -> dict[str, Any]:
    """Check retire-only origin/lifecycle constraints before recording Decision."""
    aggregate_id = rule_aggregate_id(rule_id, version)
    current = EventStore(paths).state()["aggregates"]["rule"].get(aggregate_id)
    if not isinstance(current, dict):
        raise CommandRejected(
            "rule-missing", f"cannot retire unknown Rule: {aggregate_id}"
        )
    if current.get("origin") != RESERVED_ORIGIN:
        raise CommandRejected(
            "rule-origin-retire-only",
            "self-evolve may retire only selfevolve-origin Rules",
        )
    if current.get("status") not in {"PROMOTED", "ACTIVE", "RULE_ACTIVE"}:
        raise CommandRejected(
            "rule-not-active",
            f"cannot retire Rule in status {current.get('status')!r}",
        )
    return copy.deepcopy(current)


def lifecycle_state(paths: ResearchPaths, rule_id: str, version: str) -> str:
    """Return the governed lifecycle state for one candidate/version."""
    store = EventStore(paths)
    aggregate_id = rule_aggregate_id(rule_id, version)
    learning_id = learning_aggregate_id(rule_id, version)
    current = "OBSERVED"
    for event in store.events():
        if (
            event["aggregate_type"] == "learning"
            and event["aggregate_id"] == learning_id
        ):
            current = "CANDIDATE"
        elif event["aggregate_type"] == "decision":
            record = event.get("payload", {}).get("record") or {}
            if (
                record.get("subject_id") in {learning_id, aggregate_id}
                and record.get("to_state")
            ):
                current = str(record["to_state"])
        elif (
            event["aggregate_type"] == "rule"
            and event["aggregate_id"] == aggregate_id
        ):
            record = event.get("payload", {}).get("record") or {}
            current = str(record.get("lifecycle_state") or current)
    return current
