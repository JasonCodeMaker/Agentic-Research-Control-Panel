"""Verified run-result facts backed by the research event store."""

from __future__ import annotations

import copy
import hashlib
import re
from pathlib import Path
from typing import Any

from lib import verifier
from lib.research_state import EventStore, ResearchPaths
from lib.research_state.io import read_json
from lib.research_state.schema import enum


class FactError(RuntimeError):
    """Raised when package fact data is malformed."""


TERMINAL_RUN_STATUSES = {"COMPLETED", "FAILED", "HALTED", "SKIPPED"}
RESULT_VERDICTS = set(enum("result_verdict"))
RESULT_VALIDITIES = set(enum("result_validity"))


def _safe_run_dir(
    paths: ResearchPaths,
    run: dict[str, Any],
) -> Path:
    raw = run.get("dir")
    if raw:
        candidate = Path(str(raw))
        candidate = candidate if candidate.is_absolute() else paths.root / candidate
    else:
        package_id = str(run.get("package_id") or "")
        local_id = str(
            run.get("experiment_local_id")
            or str(run.get("experiment_id") or "").split("::")[-1]
        )
        run_id = str(run.get("run_id") or run.get("id") or "")
        candidate = paths.run_dir(package_id, local_id, run_id)
    resolved = candidate.resolve()
    try:
        resolved.relative_to(paths.experiments.resolve())
    except ValueError as exc:
        raise FactError(f"run directory is outside experiments root: {resolved}") from exc
    return resolved


def _evidence_ref(
    paths: ResearchPaths,
    run_dir: Path,
    value: Any,
) -> dict[str, Any]:
    if isinstance(value, dict):
        kind = str(value.get("kind") or "FILE")
        uri = str(value.get("uri") or "")
    else:
        kind = "FILE"
        uri = str(value or "")
    if kind not in set(enum("evidence_kind")):
        raise FactError(f"unknown evidence kind: {kind}")
    relative = Path(uri)
    if not uri or relative.is_absolute() or ".." in relative.parts:
        raise FactError(f"unsafe run evidence reference: {uri!r}")
    # The experiment harness emits root-relative URIs
    # (``experiments/<pkg>/<exp>/<run>/...``).  Hand-authored result records
    # may use a path relative to the producer run.  Both forms are accepted,
    # but the resolved evidence must stay inside that exact run directory.
    root_candidate = (paths.root / relative).resolve()
    run_candidate = (run_dir / relative).resolve()
    try:
        root_candidate.relative_to(run_dir.resolve())
        path = root_candidate
    except ValueError:
        path = run_candidate
    try:
        path.relative_to(run_dir.resolve())
    except ValueError as exc:
        raise FactError(f"run evidence escapes its run directory: {uri!r}") from exc
    if not path.is_file():
        raise FactError(f"run evidence is missing: {path}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if isinstance(value, dict) and value.get("sha256") not in (None, "", digest):
        raise FactError(f"run evidence hash mismatch: {uri!r}")
    root_relative = path.relative_to(paths.root.resolve()).as_posix()
    return {
        "kind": kind,
        "uri": root_relative,
        "sha256": digest,
        "size_bytes": path.stat().st_size,
    }


def _metric_from_gate(gate: str) -> str:
    match = re.match(r"\s*([^<>=]+?)\s*(?:>=|<=|>|<)", gate)
    return match.group(1).strip() if match else ""


def _measured_value(
    result: dict[str, Any],
    status: dict[str, Any],
    gate: str,
) -> tuple[str, Any]:
    if result.get("measured") not in (None, ""):
        return str(result.get("metric") or _metric_from_gate(gate)), result["measured"]
    metrics = result.get("measurements")
    if not isinstance(metrics, dict):
        metrics = result.get("metrics")
    if not isinstance(metrics, dict):
        metrics = status.get("latest_metrics")
    if not isinstance(metrics, dict) or not metrics:
        return str(result.get("metric") or _metric_from_gate(gate)), "unmeasured"
    preferred = str(result.get("metric") or _metric_from_gate(gate))
    if preferred and preferred in metrics:
        return preferred, metrics[preferred]
    if len(metrics) == 1:
        metric, measured = next(iter(metrics.items()))
        return str(metric), measured
    return preferred or "metrics", copy.deepcopy(metrics)


def load_run_result(
    paths: ResearchPaths,
    package_id: str,
    run_id: str,
    *,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Load, hash, and normalize one terminal run result plus its evidence."""
    if not run_id:
        raise FactError("run_id is required")
    # Policies run while EventStore owns the management lock.  Accepting the
    # policy's authoritative ``before`` snapshot avoids a recursive lock
    # acquisition while still binding all file checks to one state revision.
    if state is None:
        state = EventStore(paths).state()
    package = state["aggregates"]["package"].get(package_id)
    if not isinstance(package, dict):
        raise FactError(f"unknown package: {package_id}")
    run = state["aggregates"]["run"].get(run_id)
    if not isinstance(run, dict):
        raise FactError(f"unknown run: {run_id}")
    if run.get("package_id") != package_id:
        raise FactError(f"run {run_id} does not belong to package {package_id}")
    if run.get("status") not in TERMINAL_RUN_STATUSES:
        raise FactError(f"run is not terminal: {run_id}")
    experiment_id = str(run.get("experiment_id") or "")
    experiment = state["aggregates"]["experiment"].get(experiment_id)
    if not isinstance(experiment, dict) or experiment.get("package_id") != package_id:
        raise FactError(f"run references unknown package experiment: {experiment_id}")
    local_id = str(
        run.get("experiment_local_id")
        or experiment.get("local_id")
        or experiment.get("id")
        or experiment_id.split("::")[-1]
    )
    run_dir = _safe_run_dir(paths, run)
    result_path = run_dir / "result.json"
    if not result_path.is_file():
        raise FactError(f"run result is missing: {result_path}")
    result = read_json(result_path)
    if not isinstance(result, dict):
        raise FactError(f"run result must be an object: {result_path}")
    if result.get("run_id") not in (None, "", run_id):
        raise FactError(f"result run_id mismatch: {result.get('run_id')!r}")
    verdict = str(result.get("verdict") or "INCONCLUSIVE")
    validity = str(result.get("validity") or "UNMEASURED")
    if verdict not in RESULT_VERDICTS:
        raise FactError(
            f"result verdict must be one of {sorted(RESULT_VERDICTS)}"
        )
    if validity not in RESULT_VALIDITIES:
        raise FactError(
            f"result validity must be one of {sorted(RESULT_VALIDITIES)}"
        )
    status = read_json(run_dir / "status.json", {})
    if not isinstance(status, dict):
        status = {}
    evidence: list[dict[str, Any]] = [
        {
            "kind": "FILE",
            "uri": result_path.relative_to(paths.root.resolve()).as_posix(),
            "sha256": hashlib.sha256(result_path.read_bytes()).hexdigest(),
            "size_bytes": result_path.stat().st_size,
        }
    ]
    for raw in result.get("evidence") or []:
        ref = _evidence_ref(paths, run_dir, raw)
        if ref not in evidence:
            evidence.append(ref)
    spec = experiment.get("spec") if isinstance(experiment.get("spec"), dict) else {}
    gate = str(spec.get("gate") or experiment.get("gate") or "")
    metric, measured = _measured_value(result, status, gate)
    verdict_conflict = verifier.assess_metric_verdict(
        measured,
        gate,
        verdict,
    )
    if verdict_conflict:
        raise FactError(verdict_conflict)
    evidence_path = evidence[0]["uri"]
    hypothesis = str(
        result.get("hypothesis")
        or experiment.get("hypothesis")
        or package.get("hypothesis")
        or ""
    )
    method = str(
        result.get("method")
        or experiment.get("label")
        or spec.get("purpose")
        or local_id
    )
    normalized = {
        "id": f"{local_id}::{run_id}",
        "row_id": f"{local_id}::{run_id}",
        "package_id": package_id,
        "experiment_id": experiment_id,
        "exp_id": local_id,
        "run_id": run_id,
        "metric": metric,
        "measured": measured,
        "gate": gate,
        "method": method,
        "hypothesis": hypothesis,
        "verdict": verdict,
        "validity": validity,
        "evidence": evidence,
        "evidencePath": evidence_path,
        "source_artifact": evidence_path,
        "result_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest(),
        "result": copy.deepcopy(result),
    }
    # EvidenceRef identity belongs to the producer Run, not to the package
    # projection that happens to display it.
    for ref in evidence:
        ref.update(
            {
                "package_id": package_id,
                "experiment_id": experiment_id,
                "run_id": run_id,
            }
        )
    return normalized
