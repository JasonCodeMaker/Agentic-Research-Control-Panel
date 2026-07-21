"""L1 fixture for a state-backed Experiment and canonical run directory.

This module does not create Project, Direction, Package, or Experiment state.
Tests must seed those prerequisites first, matching the production
``/research-run`` admission boundary.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

PIPELINE_ROOT = Path(__file__).resolve().parents[3]
if str(PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(PIPELINE_ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.experiments.contracts import (  # noqa: E402
    file_evidence_ref,
    verify_result_evidence,
)
from lib.experiments.report import run_summary  # noqa: E402
from lib.experiments.status import canonical_status  # noqa: E402
from lib.research_state import ResearchPaths, StateQuery  # noqa: E402
from lib.research_state.io import (  # noqa: E402
    append_jsonl_fsync,
    canonical_json,
    write_json_atomic,
)

import driver  # noqa: E402


def _paths(
    workspace_or_paths: str | Path | ResearchPaths,
    *,
    research_root: str | Path | None = None,
) -> ResearchPaths:
    if isinstance(workspace_or_paths, ResearchPaths):
        if research_root is not None:
            raise ValueError("research_root cannot accompany ResearchPaths")
        return workspace_or_paths
    return ResearchPaths.resolve(
        workspace=workspace_or_paths,
        research_root=research_root,
    )


def search_read(citations: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Partition citations by whether their source resolves on disk."""
    verified, rejected = [], []
    for citation in citations:
        target = verified if Path(citation["source"]).is_file() else rejected
        target.append(str(citation["id"]))
    return verified, rejected


def _resolve_experiment(
    paths: ResearchPaths,
    package_id: str,
    requested_id: str,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    snapshot = StateQuery(paths).show("experiment")
    matches = [
        (aggregate_id, record)
        for aggregate_id, record in snapshot["data"].items()
        if isinstance(record, dict)
        and record.get("package_id") == package_id
        and (
            aggregate_id == requested_id
            or record.get("id") == requested_id
            or record.get("local_id") == requested_id
            or requested_id in (record.get("aliases") or [])
        )
    ]
    if len(matches) != 1:
        raise KeyError(
            f"expected one Experiment {requested_id!r} in {package_id}, "
            f"found {len(matches)}"
        )
    aggregate_id, record = matches[0]
    return aggregate_id, record, snapshot


def experiment(
    package_id: str,
    workspace_or_paths: str | Path | ResearchPaths,
    measured: float,
    *,
    experiment_id: str = "exp-001",
    run_id: str = "run-001",
    research_root: str | Path | None = None,
) -> dict[str, Any]:
    """Write one toy measurement inside the canonical Experiment run tree."""
    paths = _paths(workspace_or_paths, research_root=research_root)
    paths.load_version()
    aggregate_id, record, experiment_snapshot = _resolve_experiment(
        paths,
        package_id,
        experiment_id,
    )
    package = StateQuery(paths).show("package", package_id)
    if (
        experiment_snapshot["source_seq"],
        experiment_snapshot["source_hash"],
    ) != (package["source_seq"], package["source_hash"]):
        raise RuntimeError("research state changed while building the fixture")
    local_id = str(record.get("local_id") or record.get("id") or experiment_id)
    run_dir = paths.run_dir(package_id, local_id, run_id)
    if run_dir.exists():
        raise FileExistsError(f"run already exists: {run_dir}")
    files = run_dir / "files"
    files.mkdir(parents=True)
    artifact_path = files / "metric.json"
    artifact = {
        "artifact_id": f"{run_id}:metric",
        "metric": "toy_metric",
        "measured": measured,
    }
    write_json_atomic(artifact_path, artifact)
    context = {
        "schema_version": 1,
        "source_seq": package["source_seq"],
        "source_hash": package["source_hash"],
        "package": package["data"],
        "experiment": record,
    }
    run = {
        "schema_version": 1,
        "run_id": run_id,
        "package_id": package_id,
        "experiment_id": aggregate_id,
        "experiment_local_id": local_id,
        "fixture": "research-run-l1",
    }
    evidence = file_evidence_ref(
        paths,
        run,
        artifact_path,
        kind="METRIC",
    )
    status = {
        "schema_version": 1,
        "run_id": run_id,
        "package_id": package_id,
        "experiment_id": aggregate_id,
        "experiment_local_id": local_id,
        "status": canonical_status("COMPLETED"),
    }
    result = {
        "schema_version": 1,
        "kind": "runtime-terminal",
        "run_id": run_id,
        "package_id": package_id,
        "experiment_id": aggregate_id,
        "status": status["status"],
        "exit_code": 0,
        "ended_at": None,
        "protocol": {},
        "measurements": {"toy_metric": measured},
        "verdict": "INCONCLUSIVE",
        "validity": "UNMEASURED",
        "supported_claims": [],
        "unsupported_claims": [],
        "decision_candidate": None,
        "evidence": [evidence],
    }
    write_json_atomic(run_dir / "run.json", run)
    write_json_atomic(run_dir / "context.json", context)
    append_jsonl_fsync(
        run_dir / "events.jsonl",
        {"kind": "measurement", **artifact},
    )
    append_jsonl_fsync(
        run_dir / "metrics.jsonl",
        {"metric": "toy_metric", "value": measured},
    )
    write_json_atomic(run_dir / "status.json", status)
    write_json_atomic(run_dir / "result.json", result)
    verify_result_evidence(paths, run, result)
    (run_dir / "log.txt").write_text(
        canonical_json({"toy_metric": measured}) + "\n",
        encoding="utf-8",
    )
    return {
        "artifact_id": artifact["artifact_id"],
        "path": str(artifact_path),
        "run_id": run_id,
        "run_dir": str(run_dir),
        "evidence": evidence,
        "experiment": record,
        "source_seq": experiment_snapshot["source_seq"],
        "source_hash": experiment_snapshot["source_hash"],
    }


def verify(artifact_path: str | Path, spec: dict[str, Any]) -> dict[str, Any]:
    """Read the persisted metric and compare it with the Experiment gate."""
    artifact = json.loads(Path(artifact_path).read_text(encoding="utf-8"))
    gate = spec.get("gate") or spec.get("success_gate")
    match = re.search(r">=\s*([0-9]+(?:\.[0-9]+)?)", str(gate or ""))
    if not match:
        raise ValueError(f"Experiment gate needs a numeric >= threshold: {gate!r}")
    threshold = float(match.group(1))
    measured = float(artifact["measured"])
    return {
        "judge": "L1-metric-oracle",
        "result": "PASS" if measured >= threshold else "FAIL",
        "measured": measured,
        "threshold": threshold,
        "artifact_id": artifact["artifact_id"],
    }


def run(
    intent: str,
    *,
    pkg_id: str,
    workspace: str | Path | ResearchPaths,
    experiment_id: str = "exp-001",
    run_id: str = "run-001",
    citations: list[dict[str, Any]],
    measured: float,
    research_root: str | Path | None = None,
) -> dict[str, Any]:
    """Run the fixture and return research-op envelopes for result ingestion."""
    paths = _paths(workspace, research_root=research_root)
    verified_citations, rejected_citations = search_read(citations)
    artifact = experiment(
        pkg_id,
        paths,
        measured,
        experiment_id=experiment_id,
        run_id=run_id,
    )
    aggregate_id = str(artifact["evidence"]["experiment_id"])
    selected = artifact["experiment"]
    verdict = verify(artifact["path"], selected["spec"])
    summary = run_summary(Path(artifact["run_dir"]))
    local_id = str(selected.get("local_id") or selected.get("id"))
    validity = "VALID" if verdict["result"] == "PASS" else "RESULT_FAIL"
    result_envelope = {
        "op": "insert",
        "target": "results-gate-row",
        "payload": {
            "exp_id": local_id,
            "run_id": run_id,
            "validity": validity,
            "baseline": "fixture",
            "plan_gate": selected["spec"]["gate"],
            "observed_metric": verdict["measured"],
            "budget_use": "fixture",
            "seed_status": "single",
            "artifact_completeness": "complete",
            "verdict": "PASS" if verdict["result"] == "PASS" else "FAIL",
            "reason": (
                f"measured={verdict['measured']} "
                f"{'>=' if verdict['result'] == 'PASS' else '<'} "
                f"{verdict['threshold']}"
            ),
            "evidence": [artifact["evidence"]],
        },
        "idempotency_key": f"fixture:{run_id}:result",
    }
    status_envelope = {
        "op": "update",
        "target": "experiments-status",
        "payload": {
            "id": local_id,
            "to": "COMPLETE" if verdict["result"] == "PASS" else "FAILED",
        },
        "idempotency_key": f"fixture:{run_id}:experiment-status",
    }
    envelopes = [result_envelope, status_envelope]
    return {
        "chain": ["R2:search", "R4:experiment", "R5:verify"],
        "intent": intent,
        "experiment_id": aggregate_id,
        "spec": selected["spec"],
        "verdict": verdict,
        "verified_citations": verified_citations,
        "rejected_citations": rejected_citations,
        "run": summary,
        "required_mutations": envelopes,
        "research_op_commands": [
            driver.research_op_argv(paths, pkg_id, envelope)
            for envelope in envelopes
        ],
    }
