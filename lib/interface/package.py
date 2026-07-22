"""Package compatibility views and frozen-layout page rendering."""

from __future__ import annotations

import copy
import hashlib
import html
import re
import string
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from lib.research_state.migration_facts import legacy_package_fact_projection
from lib.research_state.paths import ResearchPaths
from lib.research_state.policy import to_legacy
from lib.research_state.schema import compatibility_map, transition_map
from lib.interface.project import render_brainstorm_page


PAGE_TEMPLATES: dict[str, tuple[str, str]] = {
    "index": ("index.html", "index.html"),
    "plan": ("plan.html", "plan.html"),
    "implementation": ("implementation.html", "implementation.html"),
    "results": ("results.html", "results.html"),
    "analysis": ("analysis.html", "analysis.html"),
    "tracker": ("tracker.html", "tracker.html"),
    "docs": ("docs/index.html", "docs/index.html"),
    "_agent": ("_agent/context.html", "_agent/context.html"),
}
ALWAYS_PRESENT = ("index", "tracker", "docs", "_agent")
DEFAULT_PAGES = tuple(PAGE_TEMPLATES)

EXPERIMENT_STATUS_COMPAT = {
    canonical: legacy.upper()
    for legacy, canonical in compatibility_map("experiment_status").items()
}
EXPERIMENT_STATUS_COMPAT.update(
    {
        "PLANNED": "QUEUED",
        "READY": "QUEUED",
        "ACTIVE": "RUNNING",
        "COMPLETE": "COMPLETED",
        "FAILED": "FAILED",
        "BLOCKED": "BLOCKED",
        "SKIPPED": "SKIPPED",
    }
)

PHASE_PROCESS = {
    "CONTEXT_LOADED": (
        "Inspect the loaded Scope, Package plan, implementation, and evidence "
        "needed to choose the first executable phase."
    ),
    "IMPLEMENTING": "Implement the scoped changes and produce reviewable artifacts.",
    "IMPLEMENTATION_REVIEW": (
        "Review the implementation, checks, artifacts, and launch readiness."
    ),
    "DECISION_ADJUDICATION": (
        "Resolve the consequential decision raised by implementation review."
    ),
    "READY_TO_LAUNCH": "Complete final preflight and obtain launch authorization.",
    "EXPERIMENT_RUNNING": "Execute the authorized experiment.",
    "LIVE_ANALYSIS": "Monitor active runs and inspect live evidence.",
    "RESULT_ANALYSIS": (
        "Validate result artifacts and compare measurements with the Experiment gates."
    ),
    "NEXT_ACTION_READY": "Choose the next legal state from validated result evidence.",
}


PHASE_TRANSITION_CONDITIONS = {
    ("CONTEXT_LOADED", "IMPLEMENTING"): (
        "implementation or preflight work is still required"
    ),
    ("CONTEXT_LOADED", "READY_TO_LAUNCH"): (
        "the existing implementation passes review and launch readiness"
    ),
    ("IMPLEMENTING", "IMPLEMENTATION_REVIEW"): (
        "the scoped implementation and required checks are complete"
    ),
    ("IMPLEMENTATION_REVIEW", "IMPLEMENTING"): (
        "review finds a repairable implementation or artifact defect"
    ),
    ("IMPLEMENTATION_REVIEW", "DECISION_ADJUDICATION"): (
        "review surfaces a consequential decision that requires adjudication"
    ),
    ("IMPLEMENTATION_REVIEW", "READY_TO_LAUNCH"): (
        "independent review acquits the implementation and launch readiness passes"
    ),
    ("DECISION_ADJUDICATION", "IMPLEMENTING"): (
        "the decision requires implementation changes"
    ),
    ("DECISION_ADJUDICATION", "IMPLEMENTATION_REVIEW"): (
        "the decision requires renewed independent review"
    ),
    ("DECISION_ADJUDICATION", "READY_TO_LAUNCH"): (
        "the decision is resolved and launch readiness passes"
    ),
    ("READY_TO_LAUNCH", "EXPERIMENT_RUNNING"): (
        "launch is authorized and the run starts"
    ),
    ("EXPERIMENT_RUNNING", "LIVE_ANALYSIS"): (
        "a launched run produces live status or evidence"
    ),
    ("LIVE_ANALYSIS", "EXPERIMENT_RUNNING"): (
        "another authorized run starts while execution continues"
    ),
    ("LIVE_ANALYSIS", "RESULT_ANALYSIS"): (
        "all relevant runs are terminal and result artifacts are available"
    ),
    ("LIVE_ANALYSIS", "IMPLEMENTING"): (
        "live evidence reveals a repairable implementation defect"
    ),
    ("RESULT_ANALYSIS", "NEXT_ACTION_READY"): (
        "result evidence and gate verdicts are validated"
    ),
    ("NEXT_ACTION_READY", "READY_TO_LAUNCH"): (
        "the next planned experiment is selected and launch readiness passes"
    ),
    ("NEXT_ACTION_READY", "IMPLEMENTING"): (
        "the evidence requires implementation changes before another run"
    ),
}


def _run_sort_key(
    item: tuple[str, Mapping[str, Any]],
) -> tuple[int, float | str, str]:
    run_id, run = item
    value = (
        run.get("ended_at")
        or run.get("started_at")
        or run.get("requested_at")
        or ""
    )
    try:
        return (0, float(value), run_id)
    except (TypeError, ValueError):
        return (1, str(value), run_id)


def _bucket(state: Mapping[str, Any], aggregate_type: str) -> Mapping[str, Any]:
    aggregates = state.get("aggregates", {})
    bucket = aggregates.get(aggregate_type, {}) if isinstance(aggregates, Mapping) else {}
    return bucket if isinstance(bucket, Mapping) else {}


def _safe_segment(value: str, *, label: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", value):
        raise ValueError(f"unsafe {label}: {value!r}")
    return value


def _legacy_state(record: Mapping[str, Any]) -> dict[str, str]:
    if record.get("lifecycle"):
        return to_legacy(dict(record))
    category = str(record.get("category") or "")
    status = str(record.get("status") or record.get("workflowState") or "")
    if category not in {"in-progress", "success", "fail"} or not status:
        raise ValueError(
            f"package {record.get('id')!r} has no canonical lifecycle or legacy state"
        )
    return {"category": category, "status": status}


def _project_experiment(
    experiment_id: str,
    record: Mapping[str, Any],
    runs: list[tuple[str, Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    projected = copy.deepcopy(dict(record))
    projected.setdefault("id", experiment_id)
    local_id = projected.get("local_id") or projected.get("localId")
    if local_id:
        projected["local_id"] = str(local_id)
        projected["localId"] = str(local_id)
    status = str(projected.get("status") or "PLANNED")
    ordered_runs = sorted(runs or [], key=_run_sort_key)
    run_statuses = {
        str(run.get("status") or "")
        for _, run in ordered_runs
        if isinstance(run, Mapping)
    }
    finalized = [
        (run_id, run.get("latest_scientific_result"))
        for run_id, run in ordered_runs
        if isinstance(run.get("latest_scientific_result"), Mapping)
    ]
    # Experiment status is a deterministic read model over all its Runs.  A
    # single terminal callback never writes the Experiment aggregate.
    if "RUNNING" in run_statuses or "STALE" in run_statuses:
        status = "ACTIVE"
    elif "QUEUED" in run_statuses:
        status = "READY"
    elif any(
        result.get("verdict") == "PASS" and result.get("validity") == "VALID"
        for _, result in finalized
    ):
        status = "COMPLETE"
    elif ordered_runs and all(
        str(run.get("status") or "") in {"FAILED", "HALTED", "SKIPPED"}
        for _, run in ordered_runs
    ):
        status = "FAILED"
    if finalized:
        latest_run_id, latest = finalized[-1]
        projected["latest_result_run_id"] = latest_run_id
        projected["latest_result_sha256"] = latest.get("result_sha256")
    projected["status"] = EXPERIMENT_STATUS_COMPAT.get(status, status)
    spec = projected.get("spec") if isinstance(projected.get("spec"), Mapping) else {}
    projected.setdefault("purpose", spec.get("purpose") or "")
    projected.setdefault("config", spec.get("config_ref") or "")
    projected.setdefault("gate", spec.get("gate") or "")
    projected.setdefault("controlMode", spec.get("control_mode") or "")
    return projected


def _snapshot_value(record: Mapping[str, Any], *labels: str) -> str:
    raw = record.get("idea_snapshot")
    wanted = {label.casefold() for label in labels}
    if isinstance(raw, Mapping):
        for label, value in raw.items():
            if str(label).strip().casefold() in wanted and str(value or "").strip():
                return str(value).strip()
    elif isinstance(raw, list):
        for item in raw:
            if not isinstance(item, Mapping):
                continue
            label = str(item.get("label") or "").strip().casefold()
            value = str(item.get("value") or "").strip()
            if label in wanted and value:
                return value
    return ""


def _package_card_summary(record: Mapping[str, Any]) -> dict[str, str] | None:
    """Select concise, governed copy for a package-grid card.

    Full Direction and gate text remains available on the package detail pages.
    A compact summary is emitted only when the Package carries the richer Draft
    snapshot or objective contract, so legacy cards retain their frozen output.
    """
    contract = (
        record.get("objectiveContract")
        if isinstance(record.get("objectiveContract"), Mapping)
        else {}
    )
    question = _snapshot_value(record, "Core question", "Research question", "核心问题")
    title = str(record.get("title") or "").strip()
    if not contract and not question and not title:
        return None
    return {
        "title": title or _first(record, "name", default=str(record.get("id") or "")),
        "question": question or _first(record, "problem", default="unmeasured"),
        "hypothesis": str(contract.get("hypothesisOneLine") or "").strip()
        or _first(record, "hypothesis", "objective", default="unmeasured"),
        "motivation": _first(record, "motivation", default="unmeasured"),
        "completionGate": str(contract.get("successPredicate") or "").strip()
        or _first(record, "activeGate", default="unmeasured"),
        "measurements": str(contract.get("metric") or "").strip()
        or _first(
            record,
            "primaryMetricVsGate",
            "primaryMetric",
            default="unmeasured",
        ),
    }


def _merge_rows(
    existing: Any,
    derived: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge migration-era rows with canonical projections by stable id."""
    rows = (
        [copy.deepcopy(row) for row in existing if isinstance(row, Mapping)]
        if isinstance(existing, list)
        else []
    )
    index = {
        str(row.get("id") or row.get("row_id")): offset
        for offset, row in enumerate(rows)
        if row.get("id") or row.get("row_id")
    }
    for raw in derived:
        row = copy.deepcopy(raw)
        identity = str(row.get("id") or row.get("row_id") or "")
        if identity and identity in index:
            rows[index[identity]] = row
        else:
            if identity:
                index[identity] = len(rows)
            rows.append(row)
    return rows


def _first_evidence_path(result: Mapping[str, Any]) -> str:
    evidence = result.get("evidence")
    if not isinstance(evidence, list):
        return ""
    for item in evidence:
        if isinstance(item, Mapping) and item.get("uri"):
            return str(item["uri"])
        if isinstance(item, str) and item:
            return item
    return ""


def _result_projection(
    run_id: str,
    run: Mapping[str, Any],
    experiment: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None:
    result = run.get("latest_scientific_result")
    if not isinstance(result, Mapping):
        return None
    local_id = str(
        result.get("experiment_local_id")
        or run.get("experiment_local_id")
        or experiment.get("local_id")
        or experiment.get("id")
        or run.get("experiment_id")
        or ""
    )
    spec = experiment.get("spec")
    spec = spec if isinstance(spec, Mapping) else {}
    measurements = result.get("measurements")
    measurements = measurements if isinstance(measurements, Mapping) else {}
    metric = str(result.get("metric") or "")
    measured = copy.deepcopy(result.get("measured"))
    if not metric and len(measurements) == 1:
        metric, measured = next(iter(measurements.items()))
        metric = str(metric)
    elif measured is None:
        measured = copy.deepcopy(measurements) if measurements else "unmeasured"
    gate = str(result.get("gate") or spec.get("gate") or "")
    method = str(result.get("method") or spec.get("purpose") or local_id)
    hypothesis = str(result.get("hypothesis") or "")
    evidence = copy.deepcopy(result.get("evidence") or [])
    evidence_path = _first_evidence_path(result)
    row_id = f"{local_id}::{run_id}"
    method_row = {
        "id": row_id,
        "run_id": run_id,
        "exp_id": local_id,
        "method": method,
        "hypothesis": hypothesis,
        "gate": gate,
        "measured": measured,
        "verdict": result.get("verdict"),
        "validity": result.get("validity"),
        "evidence": evidence,
        "evidencePath": evidence_path,
    }
    gate_row = {
        "id": row_id,
        "row_id": row_id,
        "run_id": run_id,
        "exp_id": local_id,
        "metric": metric,
        "value": copy.deepcopy(measured),
        "observed_metric": copy.deepcopy(measured),
        "plan_gate": gate,
        "verdict": result.get("verdict"),
        "validity": result.get("validity"),
        "evidence": evidence,
        "evidencePath": evidence_path,
        "source_artifact": result.get("result_json") or evidence_path,
        "result_sha256": result.get("result_sha256"),
    }
    block = {
        "id": row_id,
        "phaseId": local_id,
        "title": f"{local_id} — {method}",
        "summary": (
            f"{result.get('verdict')}: {metric}={measured} vs {gate}"
        ),
        "detail": (
            f"Run {run_id} · validity {result.get('validity')} · evidence "
            f"{evidence_path}"
        ),
        "mainTable": {
            "columns": ["metric", "measured", "gate", "verdict", "validity"],
            "rows": [
                {
                    "metric": metric,
                    "measured": copy.deepcopy(measured),
                    "gate": gate,
                    "verdict": result.get("verdict"),
                    "validity": result.get("validity"),
                }
            ],
        },
        "insights": copy.deepcopy(result.get("supported_claims") or []),
        "ablations": [],
    }
    return method_row, gate_row, block


def _blocker(record: Mapping[str, Any]) -> dict[str, str] | None:
    raw = record.get("blocker")
    if isinstance(raw, Mapping) and str(raw.get("summary") or "").strip():
        return {
            "code": str(raw.get("code") or "PACKAGE_BLOCKED"),
            "summary": str(raw["summary"]).strip(),
        }
    if "blocker" in record:
        return None
    legacy = str(record.get("currentBlocker") or "").strip()
    if legacy and legacy.casefold() != "none":
        return {"code": "LEGACY_BLOCKER", "summary": legacy}
    return None


def _current_state_projection(record: Mapping[str, Any]) -> dict[str, Any]:
    lifecycle = str(record.get("lifecycle") or "").strip()
    phase = str(record.get("phase") or "").strip()
    blocker = _blocker(record)
    if lifecycle == "ACTIVE":
        base = phase or str(record.get("status") or "ACTIVE")
    elif lifecycle == "DRAFT":
        base = str(record.get("draftStatus") or "DRAFT")
    else:
        base = lifecycle or str(record.get("status") or "unmeasured")
    label = f"{base} · BLOCKED" if blocker else base
    return {
        "lifecycle": lifecycle or None,
        "phase": phase or None,
        "blocked": blocker is not None,
        "label": label,
        "blockerCode": blocker["code"] if blocker else None,
        "blockerReason": blocker["summary"] if blocker else None,
    }


def _current_process_projection(
    record: Mapping[str, Any],
    live_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    lifecycle = str(record.get("lifecycle") or "")
    phase = str(record.get("phase") or "")
    blocker = _blocker(record)
    if blocker:
        return {
            "step": f"Resolve the blocker before continuing {phase}: {blocker['summary']}",
            "evidence": f"Blocker {blocker['code']}",
        }
    if lifecycle == "DRAFT":
        return {
            "step": "Refine the Package document and prepare its Scope bundle for ratification.",
            "evidence": "Package lifecycle: DRAFT",
        }
    if lifecycle != "ACTIVE":
        return {
            "step": f"No active process; the Package lifecycle is {lifecycle or 'unmeasured'}.",
            "evidence": "Package lifecycle",
        }

    active_runs = [
        " / ".join(
            value
            for value in (
                str(row.get("exp_id") or "").strip(),
                str(row.get("run_id") or "").strip(),
            )
            if value
        )
        for row in live_rows
        if row.get("run_state") in {"QUEUED", "RUNNING", "STALE"}
    ]
    evidence = f"Current phase: {phase or 'unmeasured'}"
    if phase in {"EXPERIMENT_RUNNING", "LIVE_ANALYSIS"} and active_runs:
        evidence += f" · Active runs: {'; '.join(active_runs)}"
    return {
        "step": PHASE_PROCESS.get(
            phase,
            f"Complete the work owned by the current phase {phase or 'unmeasured'}.",
        ),
        "evidence": evidence,
    }


def _last_transition_projection(record: Mapping[str, Any]) -> dict[str, Any]:
    explicit = record.get("lastTransition")
    if isinstance(explicit, Mapping):
        return {
            "summary": str(
                explicit.get("summary")
                or explicit.get("label")
                or "Transition recorded"
            ),
            "at": str(explicit.get("at") or explicit.get("recorded_at") or ""),
            "evidence": str(explicit.get("evidence") or "Package.lastTransition"),
            "certainty": "RECORDED",
        }
    if str(explicit or "").strip():
        return {
            "summary": str(explicit).strip(),
            "at": str(record.get("lastUpdated") or ""),
            "evidence": "Package.lastTransition",
            "certainty": "RECORDED",
        }

    last_action = str(record.get("lastAction") or "").strip()
    routed = re.search(r"routed (?:state=|to )([A-Z_]+)", last_action)
    if routed:
        return {
            "summary": f"Entered {routed.group(1)}",
            "at": str(record.get("lastUpdated") or ""),
            "evidence": last_action,
            "certainty": "RECORDED",
        }
    closed = re.search(r"Package closed as ([A-Z_]+)", last_action)
    if closed:
        return {
            "summary": f"ACTIVE → {closed.group(1)}",
            "at": str(record.get("lastUpdated") or ""),
            "evidence": last_action,
            "certainty": "RECORDED",
        }

    phase = str(record.get("phase") or "").strip()
    if record.get("scopeBinding") and phase == "CONTEXT_LOADED":
        return {
            "summary": f"Activated → {phase}",
            "at": "",
            "evidence": "Package.scopeBinding",
            "certainty": "INFERRED",
        }
    return {
        "summary": "No state transition is recorded",
        "at": "",
        "evidence": "",
        "certainty": "UNMEASURED",
    }


def _next_state_conditions_projection(
    record: Mapping[str, Any],
) -> list[dict[str, str]]:
    lifecycle = str(record.get("lifecycle") or "")
    if lifecycle == "DRAFT":
        return [
            {
                "condition": "the Scope bundle is ratified and the Package is activated",
                "nextState": "CONTEXT_LOADED",
            }
        ]
    if lifecycle != "ACTIVE":
        return []

    phase = str(record.get("phase") or "")
    return [
        {
            "condition": PHASE_TRANSITION_CONDITIONS[(phase, next_state)],
            "nextState": next_state,
        }
        for next_state in transition_map("package_phase").get(phase, ())
    ]


def package_view_models(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Join canonical aggregates into the existing, read-only browser shape."""
    runs_by_experiment: dict[str, list[tuple[str, Mapping[str, Any]]]] = {}
    runs_by_package: dict[str, list[tuple[str, Mapping[str, Any]]]] = {}
    for run_id, raw in sorted(
        _bucket(state, "run").items(), key=lambda item: str(item[0])
    ):
        if not isinstance(raw, Mapping) or not raw.get("experiment_id"):
            continue
        runs_by_experiment.setdefault(str(raw["experiment_id"]), []).append(
            (str(run_id), raw)
        )
        if raw.get("package_id"):
            runs_by_package.setdefault(str(raw["package_id"]), []).append(
                (str(run_id), raw)
            )

    experiments_by_package: dict[str, list[dict[str, Any]]] = {}
    experiments_by_id: dict[str, Mapping[str, Any]] = {}
    for experiment_id, raw in sorted(
        _bucket(state, "experiment").items(), key=lambda item: str(item[0])
    ):
        if isinstance(raw, Mapping):
            experiments_by_id[str(experiment_id)] = raw
        if not isinstance(raw, Mapping) or not raw.get("package_id"):
            continue
        package_id = str(raw["package_id"])
        experiments_by_package.setdefault(package_id, []).append(
            _project_experiment(
                str(experiment_id),
                raw,
                runs_by_experiment.get(str(experiment_id), []),
            )
        )

    learnings_by_package: dict[str, list[dict[str, Any]]] = {}
    for learning_id, raw in sorted(
        _bucket(state, "learning").items(), key=lambda item: str(item[0])
    ):
        if not isinstance(raw, Mapping) or not raw.get("package_id"):
            continue
        row = copy.deepcopy(dict(raw))
        row["id"] = str(row.get("local_id") or row.get("id") or learning_id)
        learnings_by_package.setdefault(str(raw["package_id"]), []).append(row)

    changes_by_package: dict[str, list[dict[str, Any]]] = {}
    for change_id, raw in sorted(
        _bucket(state, "change").items(), key=lambda item: str(item[0])
    ):
        if not isinstance(raw, Mapping) or not raw.get("package_id"):
            continue
        row = copy.deepcopy(dict(raw))
        row["id"] = str(row.get("local_id") or row.get("id") or change_id)
        row.setdefault("change_id", row["id"])
        changes_by_package.setdefault(str(raw["package_id"]), []).append(row)

    decisions_by_package: dict[str, list[dict[str, Any]]] = {}
    for decision_id, raw in sorted(
        _bucket(state, "decision").items(), key=lambda item: str(item[0])
    ):
        if not isinstance(raw, Mapping) or not raw.get("package_id"):
            continue
        row = copy.deepcopy(dict(raw))
        row.setdefault("id", str(decision_id))
        decisions_by_package.setdefault(str(raw["package_id"]), []).append(row)

    projected_packages: list[dict[str, Any]] = []
    for package_id, raw in sorted(
        _bucket(state, "package").items(), key=lambda item: str(item[0])
    ):
        if not isinstance(raw, Mapping):
            continue
        package_id = str(package_id)
        projected = copy.deepcopy(dict(raw))
        projected.setdefault("id", package_id)
        slug = _safe_segment(
            str(projected.get("slug") or package_id),
            label=f"package slug for {package_id}",
        )
        state_cell = _legacy_state(projected)
        projected["slug"] = slug
        projected["category"] = state_cell["category"]
        projected["status"] = state_cell["status"]
        projected["workflowState"] = state_cell["status"]
        projected["detailPath"] = (
            f"packages/{slug}/docs/proposal.html"
            if projected.get("lifecycle") == "DRAFT"
            else f"packages/{slug}/"
        )
        projected.pop("cardSummary", None)
        card_summary = _package_card_summary(projected)
        if card_summary is not None:
            projected["cardSummary"] = card_summary
        if projected.get("lifecycle") == "DRAFT":
            projected.setdefault("problem", projected.get("idea") or "unmeasured")
            projected.setdefault(
                "objective",
                projected.get("idea") or projected.get("title") or "unmeasured",
            )
            projected.setdefault(
                "motivation",
                projected.get("abstract") or "Align the proposal before Scope.",
            )
            projected.setdefault("nextRoute", "ASK_USER")
            projected.setdefault(
                "nextAction",
                "Refine or ratify this Draft Package",
            )
            projected.setdefault(
                "lastUpdated",
                str(projected.get("updated_at") or projected.get("created_at") or "")[:10],
            )
        projected["experiments"] = experiments_by_package.get(package_id, [])
        legacy_facts = legacy_package_fact_projection(projected)
        projected["analysisInsights"] = _merge_rows(
            projected.get("analysisInsights"),
            learnings_by_package.get(package_id, []),
        )
        package_changes = changes_by_package.get(package_id, [])
        projected["implementationReviews"] = _merge_rows(
            projected.get("implementationReviews"),
            package_changes,
        )
        implementation = (
            copy.deepcopy(projected.get("implementation"))
            if isinstance(projected.get("implementation"), Mapping)
            else {}
        )
        implementation_changes: list[dict[str, Any]] = []
        for change in package_changes:
            review = (
                change.get("review")
                if isinstance(change.get("review"), Mapping)
                else {}
            )
            tests = review.get("tests")
            tests = copy.deepcopy(tests) if isinstance(tests, list) else []
            owned_files = change.get("owned_files")
            owned_files = (
                [str(path) for path in owned_files]
                if isinstance(owned_files, list)
                else []
            )
            validating = change.get("validating_experiments")
            validating = (
                [str(identity) for identity in validating]
                if isinstance(validating, list)
                else []
            )
            implementation_changes.append(
                {
                    **copy.deepcopy(change),
                    "id": str(
                        change.get("local_id")
                        or change.get("change_id")
                        or change.get("id")
                    ),
                    "title": change.get("title")
                    or change.get("purpose")
                    or change.get("summary")
                    or "Implementation change",
                    "oneLineSummary": change.get("summary")
                    or review.get("summary")
                    or review.get("status")
                    or "unmeasured",
                    "codeAnchors": owned_files,
                    "validatingExp": ", ".join(validating),
                    "tests": tests,
                }
            )
        implementation["changes"] = _merge_rows(
            implementation.get("changes"),
            implementation_changes,
        )
        package_decisions = sorted(
            decisions_by_package.get(package_id, []),
            key=lambda row: (
                str(row.get("recorded_at") or ""),
                str(row.get("id") or ""),
            ),
        )
        acknowledgements = []
        route_decisions = []
        for decision in package_decisions:
            if decision.get("ack_type") or str(decision.get("kind") or "").endswith(
                "ACK"
            ) or decision.get("kind") == "ACKNOWLEDGEMENT":
                acknowledgement = copy.deepcopy(decision)
                acknowledgement["to"] = acknowledgement.get(
                    "value",
                    acknowledgement.get("to"),
                )
                acknowledgements.append(acknowledgement)
            if decision.get("route"):
                route_decisions.append(decision)
        projected["acknowledgements"] = _merge_rows(
            projected.get("acknowledgements"),
            acknowledgements,
        )
        launch_acknowledgements = [
            row
            for row in acknowledgements
            if row.get("kind") in {"LAUNCH_ACK", "READY_TO_LAUNCH_ACK"}
            or row.get("ack_type") in {"LAUNCH_ACK", "READY_TO_LAUNCH_ACK"}
        ]
        if launch_acknowledgements:
            latest_ack = launch_acknowledgements[-1]
            ack_actor = latest_ack.get("actor")
            ack_actor = ack_actor if isinstance(ack_actor, Mapping) else {}
            implementation["adjudication"] = {
                "decision": latest_ack.get("kind")
                or latest_ack.get("ack_type"),
                "evidenceUsed": _first_evidence_path(latest_ack),
                "userAck": ack_actor.get("id")
                or latest_ack.get("value")
                or "unmeasured",
                "ackLockedAt": latest_ack.get("recorded_at") or "",
            }
        projected["implementation"] = implementation
        if route_decisions:
            latest = route_decisions[-1]
            evidence_path = _first_evidence_path(latest)
            decision_actor = latest.get("actor")
            decision_actor = (
                decision_actor if isinstance(decision_actor, Mapping) else {}
            )
            projected["chosenRoute"] = {
                "route": latest.get("route"),
                "reason": latest.get("reason") or latest.get("rationale") or "",
                "userAck": latest.get("user_ack")
                or latest.get("ack")
                or decision_actor.get("id"),
                "evidencePath": evidence_path,
            }
            projected["nextRoute"] = latest.get("route")
            projected["lastDecision"] = (
                latest.get("reason") or latest.get("rationale") or latest.get("route")
            )
            projected["lastDecisionEvidencePath"] = evidence_path

        method_rows: list[dict[str, Any]] = []
        gate_rows: list[dict[str, Any]] = []
        result_blocks: list[dict[str, Any]] = []
        experiment_bucket = _bucket(state, "experiment")
        for run_id, run in sorted(
            (
                (str(run_id), run)
                for run_id, run in _bucket(state, "run").items()
                if isinstance(run, Mapping)
                and run.get("package_id") == package_id
            ),
            key=lambda item: item[0],
        ):
            experiment = experiment_bucket.get(str(run.get("experiment_id") or ""))
            if not isinstance(experiment, Mapping):
                continue
            rows = _result_projection(run_id, run, experiment)
            if rows is None:
                continue
            method_row, gate_row, block = rows
            method_rows.append(method_row)
            gate_rows.append(gate_row)
            result_blocks.append(block)
        legacy_methods = legacy_facts["methodsTried"]
        methods_base = (
            legacy_methods
            if legacy_methods
            else projected.get("methodsTried")
        )
        projected["methodsTried"] = _merge_rows(
            methods_base,
            method_rows,
        )
        legacy_gates = legacy_facts["resultGateRows"]
        gates_base = (
            legacy_gates
            if legacy_gates
            else projected.get("resultGateRows")
        )
        projected["resultGateRows"] = _merge_rows(
            gates_base,
            gate_rows,
        )
        legacy_blocks = legacy_facts["resultBlocks"]
        blocks_base = (
            legacy_blocks
            if legacy_blocks
            else projected.get("resultBlocks")
        )
        projected["resultBlocks"] = _merge_rows(
            blocks_base,
            result_blocks,
        )
        if legacy_facts["resultSchemas"] and not projected.get("resultSchemas"):
            projected["resultSchemas"] = copy.deepcopy(
                legacy_facts["resultSchemas"]
            )
        if legacy_facts["factPages"]:
            projected["legacyFactPages"] = copy.deepcopy(
                legacy_facts["factPages"]
            )

        local_experiment_ids = {
            experiment_id: str(
                experiment.get("local_id")
                or experiment.get("localId")
                or experiment_id
            )
            for experiment_id, experiment in experiments_by_id.items()
            if experiment.get("package_id") == package_id
        }
        live_rows: list[dict[str, Any]] = []
        for run_id, run in runs_by_package.get(package_id, []):
            experiment_id = str(run.get("experiment_id") or "")
            result = run.get("latest_scientific_result")
            result = result if isinstance(result, Mapping) else {}
            measurements = result.get("measurements")
            resource = run.get("resource")
            resource = resource if isinstance(resource, Mapping) else {}
            live_rows.append(
                {
                    "id": run_id,
                    "row_id": run_id,
                    "time": run.get("ended_at")
                    or run.get("started_at")
                    or run.get("requested_at")
                    or "",
                    "exp_id": local_experiment_ids.get(
                        experiment_id,
                        str(run.get("experiment_local_id") or experiment_id),
                    ),
                    "run_id": run_id,
                    "agent": run.get("actor_id") or "research-run",
                    "run_state": run.get("status") or "unmeasured",
                    "last_log": run.get("last_log") or "",
                    "progress": run.get("progress") or "",
                    "metrics": copy.deepcopy(measurements)
                    if isinstance(measurements, Mapping)
                    else "",
                    "resource": resource.get("alloc_id") or "",
                    "artifacts": run.get("dir") or "",
                    "eta": run.get("eta") or "",
                    "action": run.get("attention_action") or "",
                    "next_check": run.get("next_check") or "",
                }
            )
        projected["liveChecks"] = _merge_rows(
            legacy_facts["liveChecks"],
            live_rows,
        )
        active_runs = [
            row["run_id"]
            for row in live_rows
            if row.get("run_state") in {"QUEUED", "RUNNING", "STALE"}
        ]
        projected["openRuns"] = (
            ", ".join(active_runs) if active_runs else "none"
        )
        current_state = _current_state_projection(projected)
        projected["currentState"] = current_state
        if current_state["blockerReason"]:
            projected["currentBlocker"] = current_state["blockerReason"]
        projected["currentProcess"] = _current_process_projection(
            projected,
            live_rows,
        )
        projected["lastTransition"] = _last_transition_projection(projected)
        projected["nextStateConditions"] = _next_state_conditions_projection(projected)

        allocation_rows: list[dict[str, Any]] = []
        for allocation_id, allocation in sorted(
            _bucket(state, "resource_allocation").items(),
            key=lambda item: str(item[0]),
        ):
            if (
                not isinstance(allocation, Mapping)
                or allocation.get("package_id", allocation.get("pkg"))
                != package_id
            ):
                continue
            experiment_id = str(
                allocation.get("experiment_id")
                or allocation.get("exp_id")
                or ""
            )
            gpu_ids = allocation.get("gpu_ids")
            gpu_ids = gpu_ids if isinstance(gpu_ids, list) else []
            gpu_type = str(allocation.get("gpu_type") or "GPU")
            gpu_count = allocation.get("gpu_count")
            allocation_rows.append(
                {
                    **copy.deepcopy(dict(allocation)),
                    "id": str(allocation_id),
                    "row_id": str(allocation_id),
                    "exp_id": local_experiment_ids.get(
                        experiment_id,
                        str(
                            allocation.get("experiment_local_id")
                            or allocation.get("exp_id")
                            or experiment_id
                        ),
                    ),
                    "purpose": allocation.get("purpose")
                    or allocation.get("reason")
                    or "",
                    "dependency": allocation.get("dependency") or "",
                    "target": allocation.get("server") or "",
                    "capacity": (
                        f"{gpu_count} x {gpu_type}"
                        if gpu_count not in (None, "")
                        else ""
                    ),
                    "assigned": ", ".join(str(value) for value in gpu_ids),
                    "agent": allocation.get("actor_id") or "research-resource",
                    "command_cwd_env": "governed launch envelope",
                    "session_job": allocation.get("job_id")
                    or allocation.get("run_id")
                    or "",
                    "runtime_root": allocation.get("runtime_root") or "",
                    "log_path": allocation.get("log_path") or "",
                    "expected_duration": allocation.get("expected_duration")
                    or "",
                }
            )
        projected["resourceAllocations"] = _merge_rows(
            legacy_facts["resourceAllocations"],
            allocation_rows,
        )
        pages = projected.get("pages")
        if not isinstance(pages, list):
            pages = list(DEFAULT_PAGES)
        normalized_pages = [
            str(page) for page in pages if str(page) in PAGE_TEMPLATES
        ]
        for page in ALWAYS_PRESENT:
            if page not in normalized_pages:
                normalized_pages.append(page)
        projected["pages"] = normalized_pages
        projected_packages.append(projected)
    return projected_packages


def _first(record: Mapping[str, Any], *keys: str, default: str = "") -> str:
    for key in keys:
        value = record.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return default


def _template_mapping(record: Mapping[str, Any]) -> dict[str, str]:
    package_id = _safe_segment(str(record["id"]), label="package id")
    objective_contract = (
        record.get("objectiveContract")
        if isinstance(record.get("objectiveContract"), Mapping)
        else {}
    )
    values = {
        "package_id": package_id,
        "name": _first(record, "name", "title", default=package_id),
        "abstract": _first(record, "abstract", "problem", default="unmeasured"),
        "category": _first(record, "category", default="in-progress"),
        "tag": _first(record, "tag", default="untagged"),
        "tag_meaning": _first(
            record,
            "tagMeaning",
            "tag_meaning",
            default="No tag meaning has been recorded.",
        ),
        "problem": _first(record, "problem", default="unmeasured"),
        "objective": _first(record, "objective", default="unmeasured"),
        "motivation": _first(record, "motivation", default="unmeasured"),
        "hypothesis": _first(
            record,
            "hypothesis",
            default=str(objective_contract.get("hypothesisOneLine") or "unmeasured"),
        ),
        "primary_metric": _first(
            record,
            "primaryMetric",
            "primary_metric",
            default=str(objective_contract.get("metric") or "unmeasured"),
        ),
        "baseline": _first(
            record,
            "baseline",
            default=str(objective_contract.get("baseline") or "unmeasured"),
        ),
        "budget": _first(
            record,
            "budget",
            default=str(objective_contract.get("budget") or "unmeasured"),
        ),
        "no_change_boundary": _first(
            record, "noChangeBoundary", "no_change_boundary", default="unmeasured"
        ),
        "source_path": _first(record, "sourcePath", "source_path", default="unmeasured"),
        "artifact_root": f".research/experiments/{package_id}/",
        "next_action": _first(
            record, "nextAction", "next_action", "lastAction", default="unmeasured"
        ),
        "last_updated": _first(
            record, "lastUpdated", "last_updated", default="unmeasured"
        ),
        "doc_title": "Source document",
    }
    # Template fields are text nodes or attributes. IDs and categories have
    # already passed the segment/state checks, so HTML escaping is sufficient.
    return {key: html.escape(value, quote=True) for key, value in values.items()}


def rewrite_projected_text(text: str) -> str:
    """Apply only the path/help-text differences allowed by the frozen UI contract."""
    text = text.replace("research_html/", ".research/interface/")
    text = text.replace(
        "outputs/&lt;pkg&gt;/manifests/&lt;exp&gt;.json",
        ".research/experiments/&lt;pkg&gt;/&lt;experiment&gt;/&lt;run&gt;/result.json",
    )
    text = re.sub(
        r"Read <code>outputs/([^<]+)/context_pack\.md</code> for Scope, failed "
        r"methods, adopted wins, active rules, and open gaps\.",
        r"Use <code>research-op context \1</code> for the governed, minimal "
        r"package context.",
        text,
    )
    text = text.replace("outputs/", ".research/experiments/")
    return text


def _note_path(paths: ResearchPaths, ref: Mapping[str, Any]) -> Path:
    uri = ref.get("uri")
    digest = str(ref.get("sha256") or "")
    if not isinstance(uri, str) or not uri:
        raise ValueError("interface NoteRef has no uri")
    relative = PurePosixPath(uri)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"unsafe interface NoteRef uri: {uri!r}")
    path = (paths.root / Path(*relative.parts)).resolve()
    notes = paths.notes.resolve()
    try:
        path.relative_to(notes)
    except ValueError as exc:
        raise ValueError(f"interface NoteRef is outside state/notes: {uri!r}") from exc
    if not path.is_file():
        raise FileNotFoundError(f"interface NoteRef is missing: {path}")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError(f"interface NoteRef hash mismatch: {uri!r}")
    return path


def read_note_text(paths: ResearchPaths, ref: Mapping[str, Any]) -> str:
    """Read and hash-check one state-owned text NoteRef."""
    return _note_path(paths, ref).read_text(encoding="utf-8")


def _safe_relative_output(value: str) -> Path:
    relative = PurePosixPath(value)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or not relative.parts
        or relative.suffix.lower() not in {".html", ".md", ".txt"}
    ):
        raise ValueError(f"unsafe package interface note path: {value!r}")
    return Path(*relative.parts)


def render_package_pages(
    *,
    paths: ResearchPaths,
    package: Mapping[str, Any],
    templates_dir: Path,
    output_root: Path,
) -> list[Path]:
    """Render one package without reading any prior interface output."""
    mapping = _template_mapping(package)
    package_id = str(package["id"])
    slug = _safe_segment(
        str(package.get("slug") or package_id),
        label=f"package slug for {package_id}",
    )
    package_root = output_root / slug
    written: list[Path] = []
    pages = package.get("pages")
    page_keys = (
        [str(page) for page in pages if str(page) in PAGE_TEMPLATES]
        if isinstance(pages, list)
        else list(DEFAULT_PAGES)
    )
    for page in ALWAYS_PRESENT:
        if page not in page_keys:
            page_keys.append(page)
    for page in page_keys:
        template_rel, output_rel = PAGE_TEMPLATES[page]
        source = templates_dir / template_rel
        if not source.is_file():
            raise FileNotFoundError(f"missing package template: {source}")
        rendered = string.Template(source.read_text(encoding="utf-8")).safe_substitute(
            mapping
        )
        rendered = rewrite_projected_text(rendered)
        destination = package_root / output_rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(rendered, encoding="utf-8")
        written.append(destination)

    rendered_note_paths: set[str] = set()
    document_ref = package.get("document_note")
    document_path = package.get("documentPath")
    if isinstance(document_ref, Mapping) and isinstance(document_path, str):
        relative = _safe_relative_output(document_path)
        content = read_note_text(paths, document_ref)
        mime = str(document_ref.get("mime") or "")
        if mime == "text/html;profile=brainstorm-fragment":
            content = render_brainstorm_page(
                package,
                document_html=content,
                presentation=(
                    "draft-package"
                    if package.get("lifecycle") == "DRAFT"
                    else "package-reference"
                ),
                asset_prefix="../" * (len(relative.parts) + 1),
                back_href="../index.html",
            )
        if relative.suffix.lower() == ".html":
            content = rewrite_projected_text(content)
        destination = package_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
        written.append(destination)
        rendered_note_paths.add(relative.as_posix())

    notes = package.get("interface_notes")
    source_by_path = {
        str(row.get("documentPath")): row
        for row in package.get("sourceBrainstorms", [])
        if isinstance(row, Mapping) and row.get("documentPath")
    } if isinstance(package.get("sourceBrainstorms"), list) else {}
    if isinstance(notes, Mapping):
        for relative_name, raw_ref in sorted(
            notes.items(), key=lambda item: str(item[0])
        ):
            if str(relative_name) in rendered_note_paths:
                continue
            if not isinstance(raw_ref, Mapping):
                raise ValueError(
                    f"package {package_id!r} has malformed interface NoteRef "
                    f"for {relative_name!r}"
                )
            relative = _safe_relative_output(str(relative_name))
            content = read_note_text(paths, raw_ref)
            if raw_ref.get("mime") == "text/html;profile=brainstorm-fragment":
                source_record = source_by_path.get(str(relative_name))
                if not isinstance(source_record, Mapping):
                    raise ValueError(
                        f"package {package_id!r} has a Brainstorm fragment without "
                        f"a Package-owned source descriptor for {relative_name!r}"
                    )
                content = render_brainstorm_page(
                    source_record,
                    document_html=content,
                    presentation="package-reference",
                    asset_prefix="../" * (len(relative.parts) + 1),
                    back_href="index.html",
                )
            if relative.suffix.lower() == ".html":
                content = rewrite_projected_text(content)
            destination = package_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8")
            if destination not in written:
                written.append(destination)
    return written
