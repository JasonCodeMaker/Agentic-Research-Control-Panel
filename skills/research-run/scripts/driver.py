"""Experiment dispatch seam for ``/research-run``.

The driver reads bounded state, validates role reports, and emits research-op
command envelopes.  It never reads the generated interface or writes
management state directly.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

PIPELINE_ROOT = Path(__file__).resolve().parents[3]
if str(PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(PIPELINE_ROOT))

from lib.experiments.report import open_runs  # noqa: E402
from lib.implementation import completion_counts  # noqa: E402
from lib.research_state import (  # noqa: E402
    ResearchPaths,
    StateQuery,
    resolve_bound_experiment as _resolve_bound_experiment,
)


ROLE_RETURN_FIELDS = (
    "agent_role",
    "assigned_scope",
    "status",
    "evidence",
    "blockers",
    "recommended_next_action",
    "source_seq",
    "source_hash",
    "sourceDirection",
    "sourceExperiment",
)
ROLE_STATUSES = {"ROLE_OK", "ROLE_BLOCKED", "ROLE_FAILED"}
REQUIRED_ENVELOPE_FIELDS = {"op", "target", "payload"}
OPTIONAL_ENVELOPE_FIELDS = {"idempotency_key", "expected_version"}
ALLOWED_OPS = {"insert", "update", "delete", "check", "scan-events"}
RESEARCH_OP_TARGETS = {
    "tracker-live-check-row",
    "tracker-resource-allocation-row",
    "tracker-impl-review-row",
    "tracker-chosen-route",
    "results-gate-row",
    "results-block",
    "experiments-status",
    "status",
    "openRuns",
    "currentBlocker",
    "lastAction",
}


def validate_mutation(envelope: Any) -> list[str]:
    """Validate one research-op command envelope."""
    if not isinstance(envelope, dict):
        return ["mutation must be an object"]
    errors = []
    keys = set(envelope)
    missing = REQUIRED_ENVELOPE_FIELDS - keys
    extra = keys - REQUIRED_ENVELOPE_FIELDS - OPTIONAL_ENVELOPE_FIELDS
    if missing:
        errors.append(f"envelope is missing {sorted(missing)}")
    if extra:
        errors.append(f"envelope has unsupported keys {sorted(extra)}")
    operation = envelope.get("op")
    if operation not in ALLOWED_OPS:
        errors.append(
            f"op {operation!r} is not a research-op command; direct writes are forbidden"
        )
    target = envelope.get("target")
    if operation == "scan-events":
        if target not in {None, ""}:
            errors.append("scan-events does not accept a target")
    elif operation == "check":
        if target not in {None, "", "package"}:
            errors.append("check target must be package or empty")
    elif target not in RESEARCH_OP_TARGETS:
        errors.append(f"target {target!r} is not a supported research-op target")
    if "payload" in envelope and not isinstance(envelope["payload"], dict):
        errors.append("payload must be an object")
    expected = envelope.get("expected_version")
    if expected is not None and (
        isinstance(expected, bool) or not isinstance(expected, int) or expected < 0
    ):
        errors.append("expected_version must be a non-negative integer")
    key = envelope.get("idempotency_key")
    if key is not None and (not isinstance(key, str) or not key.strip()):
        errors.append("idempotency_key must be a non-empty string")
    return errors


def research_op_argv(
    paths: ResearchPaths,
    package_id: str,
    envelope: dict[str, Any],
    *,
    actor_id: str = "research-run",
) -> list[str]:
    """Compile a validated envelope into the canonical research-op CLI call."""
    errors = validate_mutation(envelope)
    if errors:
        raise ValueError("; ".join(errors))
    operation = str(envelope["op"])
    payload = copy.deepcopy(envelope["payload"])
    expected = envelope.get("expected_version", payload.pop("expected_version", None))
    command = [
        sys.executable,
        str(
            PIPELINE_ROOT
            / "skills"
            / "research-op"
            / "scripts"
            / "research_op.py"
        ),
        "--workspace",
        str(paths.workspace),
        "--research-root",
        str(paths.root),
        "--pkg",
        package_id,
        "--op",
        operation,
        "--payload",
        json.dumps(payload, sort_keys=True, ensure_ascii=False),
        "--actor-type",
        "agent",
        "--actor-id",
        actor_id,
    ]
    target = envelope.get("target")
    if target:
        command.extend(["--target", str(target)])
    idempotency_key = envelope.get("idempotency_key")
    if idempotency_key:
        command.extend(["--idempotency-key", str(idempotency_key)])
    if expected is not None:
        command.extend(["--expected-version", str(expected)])
    return command


def _validate_experiment(experiment: Any, package_id: str) -> list[str]:
    if not isinstance(experiment, dict):
        return ["experiment must be an object"]
    errors = []
    if not experiment.get("id"):
        errors.append("experiment id is required")
    if experiment.get("package_id") != package_id:
        errors.append(f"experiment does not belong to package {package_id}")
    spec = experiment.get("spec")
    if not isinstance(spec, dict):
        errors.append("experiment spec is required")
    else:
        for field in ("purpose", "config_ref", "gate", "control_mode"):
            if not spec.get(field):
                errors.append(f"experiment spec.{field} is required")
    return errors


def resolve_bound_experiment(
    experiments: dict[str, Any],
    package_id: str,
    requested: Any,
) -> tuple[str, dict[str, Any]]:
    """Compatibility export of the central bounded-state resolver."""
    return _resolve_bound_experiment(experiments, package_id, requested)


def _experiment_identity(experiment: dict[str, Any]) -> str:
    aggregate_id = experiment.get("aggregate_id")
    if aggregate_id:
        return str(aggregate_id)
    return str(experiment.get("id") or "")


def validate_role_return(
    report: Any,
    *,
    context: dict[str, Any] | None = None,
) -> list[str]:
    """Validate one role report against the state snapshot used for dispatch."""
    if not isinstance(report, dict):
        return ["role return must be an object"]
    context = context or {}
    errors = [
        f"missing field: {field}"
        for field in ROLE_RETURN_FIELDS
        if field not in report
    ]
    if errors:
        return errors
    if report["status"] not in ROLE_STATUSES:
        errors.append(f"status {report['status']!r} not in {sorted(ROLE_STATUSES)}")
    if report["status"] == "ROLE_OK" and not report["evidence"]:
        errors.append("status 'ROLE_OK' requires non-empty evidence")
    if report["status"] == "ROLE_BLOCKED" and not report["blockers"]:
        errors.append("status 'ROLE_BLOCKED' requires blockers")
    for field in ("source_seq", "source_hash"):
        expected = context.get(field)
        if expected is not None and report.get(field) != expected:
            errors.append(
                f"stale state report: {field} {report.get(field)!r} "
                f"does not match {expected!r}"
            )
    for field in ("sourceDirection", "sourceExperiment"):
        expected = context.get(field)
        actual = report.get(field)
        if not actual:
            errors.append(f"{field} must be non-empty")
        elif expected is not None and actual != expected:
            errors.append(
                f"stale state report: {field} {actual!r} does not match "
                f"{expected!r}"
            )
    for envelope in report.get("mutations", []):
        errors.extend(
            f"mutation: {error}" for error in validate_mutation(envelope)
        )
    return errors


def load_workflow_snapshot(
    paths: ResearchPaths,
    package_id: str,
) -> dict[str, Any]:
    """Build the workflow input from state and canonical run snapshots."""
    query = StateQuery(paths)
    package = query.show("package", package_id)
    experiments = query.show("experiment")
    changes = query.show("change")
    opened = query.show("open_run")
    stamps = {
        (item["source_seq"], item["source_hash"])
        for item in (package, experiments, changes, opened)
    }
    if len(stamps) != 1:
        raise RuntimeError("research state changed while building workflow snapshot")
    source_seq, source_hash = next(iter(stamps))
    package_record = package["data"]
    selected_experiments = [
        record
        for _, record in sorted(experiments["data"].items())
        if isinstance(record, dict) and record.get("package_id") == package_id
    ]
    package_changes = [
        record
        for _, record in sorted(
            changes["data"].items(),
            key=lambda item: (
                (
                    int(item[1].get("order"))
                    if isinstance(item[1], dict)
                    and isinstance(item[1].get("order"), int)
                    and not isinstance(item[1].get("order"), bool)
                    else 10**9
                ),
                str(item[0]),
            ),
        )
        if isinstance(record, dict) and record.get("package_id") == package_id
    ]

    def implementation_state(
        record: dict[str, Any],
    ) -> tuple[str, str | None, str | None]:
        identities = {
            str(value)
            for value in (
                record.get("id"),
                record.get("local_id"),
                record.get("localId"),
            )
            if value
        }
        aliases = record.get("aliases")
        if isinstance(aliases, list):
            identities.update(str(value) for value in aliases if value)
        matching = [
            change
            for change in package_changes
            if identities.intersection(
                str(value)
                for value in (change.get("validating_experiments") or [])
            )
        ]
        if not matching:
            return (
                ("BLOCKED", None, None)
                if record.get("requiresCode") is True
                else ("NOT_REQUIRED", None, None)
            )
        for change in matching:
            plan = change.get("plan")
            observations = change.get("observations")
            if not isinstance(plan, dict):
                return (
                    "BLOCKED",
                    str(
                        change.get("local_id")
                        or change.get("change_id")
                        or change.get("id")
                    ),
                    None,
                )
            counts = completion_counts(
                plan,
                observations if isinstance(observations, dict) else None,
            )
            complete = (
                counts["code_total"] > 0
                and counts["code_complete"] == counts["code_total"]
                and counts["verification_total"] > 0
                and counts["verification_passed"]
                == counts["verification_total"]
            )
            if not complete:
                return (
                    "BLOCKED",
                    str(
                        change.get("local_id")
                        or change.get("change_id")
                        or change.get("id")
                    ),
                    None,
                )
        reviewed = next(
            (
                change
                for change in reversed(matching)
                if isinstance(change.get("review"), dict)
            ),
            None,
        )
        return (
            "PASS",
            None,
            (
                str(
                    reviewed.get("local_id")
                    or reviewed.get("change_id")
                    or reviewed.get("id")
                )
                if reviewed
                else None
            ),
        )

    experiment_rows = []
    for record in selected_experiments:
        readiness, current_change_id, review_change_id = implementation_state(record)
        experiment_rows.append(
            {
                "expId": record.get("local_id") or record.get("id"),
                "status": record.get("status"),
                "implementationReadiness": readiness,
                "currentChangeId": current_change_id,
                "reviewChangeId": review_change_id,
            }
        )
    run_rows = [
        row for row in open_runs(paths) if row.get("package_id") == package_id
    ]
    history_snapshot = query.history("package", package_id)
    final_snapshot = query.show("package", package_id)
    observed_stamps = {
        (history_snapshot["source_seq"], history_snapshot["source_hash"]),
        (final_snapshot["source_seq"], final_snapshot["source_hash"]),
        *(
            (row["source_seq"], row["source_hash"])
            for row in run_rows
        ),
    }
    if observed_stamps != {(source_seq, source_hash)}:
        raise RuntimeError("research state changed while reading run snapshots")
    history = history_snapshot["data"]
    return {
        "pkgId": package_id,
        "sourceDirection": package_record.get("direction_id")
        or package_record.get("sourceDirection"),
        "packageLifecycle": package_record.get("lifecycle"),
        "packagePhase": package_record.get("phase"),
        "packageBlocker": package_record.get("blocker"),
        "packageVersion": history[-1]["aggregate_version"] if history else 0,
        "nextRoute": package_record.get("nextRoute"),
        "experiments": experiment_rows,
        "openRuns": [
            {
                "runId": row["run_id"],
                "expId": row.get("experiment_local_id")
                or row.get("experiment_id"),
                "status": row["status"],
                "runtimeRoot": row.get("dir"),
            }
            for row in run_rows
        ],
        "source_seq": source_seq,
        "source_hash": source_hash,
    }


def _continuity_candidate(
    experiment: dict[str, Any],
    role_returns: list[dict[str, Any]],
) -> dict[str, Any]:
    evidence = [
        item
        for report in role_returns
        for item in report.get("evidence", [])
    ]
    blockers = [
        item
        for report in role_returns
        for item in report.get("blockers", [])
    ]
    last = role_returns[-1] if role_returns else {}
    return {
        "experiment_id": _experiment_identity(experiment),
        "attempted": [report["agent_role"] for report in role_returns],
        "evidence": evidence,
        "purpose": experiment["spec"]["purpose"],
        "next_action": last.get("recommended_next_action") or "none",
        "blockers": blockers,
    }


def run_tick(
    package_id: str,
    experiment: dict[str, Any],
    role_sequence: list[str],
    adapters: dict[str, Any],
    *,
    context: dict[str, Any] | None = None,
    paths: ResearchPaths | None = None,
) -> dict[str, Any]:
    """Run one adapter tick and return commands for research-op to apply."""
    tick_context = dict(context or {})
    if paths is not None:
        snapshot = load_workflow_snapshot(paths, package_id)
        experiment_snapshot = StateQuery(paths).show("experiment")
        if (
            experiment_snapshot["source_seq"],
            experiment_snapshot["source_hash"],
        ) != (snapshot["source_seq"], snapshot["source_hash"]):
            raise RuntimeError(
                "research state changed while selecting the Experiment"
            )
        aggregate_id, canonical_experiment = resolve_bound_experiment(
            experiment_snapshot["data"],
            package_id,
            experiment,
        )
        experiment = {
            **copy.deepcopy(canonical_experiment),
            "aggregate_id": aggregate_id,
        }
        expected_context = {
            "source_seq": snapshot["source_seq"],
            "source_hash": snapshot["source_hash"],
            "sourceDirection": snapshot.get("sourceDirection"),
            "sourceExperiment": _experiment_identity(experiment),
        }
        stale = [
            field
            for field, expected in expected_context.items()
            if field in tick_context
            and tick_context[field] != expected
        ]
        if stale:
            return {
                "pkg": package_id,
                "experiment_id": _experiment_identity(experiment),
                "roles_run": [],
                "role_returns": [],
                "proposed_mutations": [],
                "research_op_commands": [],
                "continuity": _continuity_candidate(experiment, []),
                "workflow_snapshot": snapshot,
                "rejection": {
                    "role": None,
                    "errors": [
                        "stale dispatch context: "
                        + ", ".join(
                            f"{field}={tick_context[field]!r} "
                            f"does not match {expected_context[field]!r}"
                            for field in stale
                        )
                    ],
                },
            }
        tick_context.update(expected_context)
    else:
        snapshot = None
        experiment = copy.deepcopy(experiment)

    experiment_errors = _validate_experiment(experiment, package_id)
    if experiment_errors:
        raise ValueError("; ".join(experiment_errors))
    tick_context["experiment"] = copy.deepcopy(experiment)
    tick_context.setdefault("sourceExperiment", _experiment_identity(experiment))
    dispatch_identity = {
        field: tick_context.get(field)
        for field in (
            "source_seq",
            "source_hash",
            "sourceDirection",
            "sourceExperiment",
        )
    }

    roles_run: list[str] = []
    role_returns: list[dict[str, Any]] = []
    proposed: list[dict[str, Any]] = []
    rejection = None
    for role in role_sequence:
        if role not in adapters:
            rejection = {"role": role, "errors": ["role adapter is missing"]}
            break
        report = adapters[role](copy.deepcopy(tick_context))
        errors = validate_role_return(report, context=dispatch_identity)
        if errors:
            rejection = {"role": role, "errors": errors}
            break
        roles_run.append(role)
        role_returns.append(report)
        proposed.extend(copy.deepcopy(report.get("mutations", [])))
        tick_context.setdefault("evidence", []).extend(report["evidence"])

    continuity = _continuity_candidate(experiment, role_returns)
    commands = (
        [
            research_op_argv(paths, package_id, envelope)
            for envelope in proposed
        ]
        if paths is not None and rejection is None
        else []
    )
    return {
        "pkg": package_id,
        "experiment_id": _experiment_identity(experiment),
        "roles_run": roles_run,
        "role_returns": role_returns,
        "proposed_mutations": [] if rejection else proposed,
        "research_op_commands": commands,
        "continuity": continuity,
        "workflow_snapshot": snapshot,
        "rejection": rejection,
    }
