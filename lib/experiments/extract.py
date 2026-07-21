#!/usr/bin/env python3
"""Build and verify a structured terminal result for one canonical run."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any, Iterable

from lib.experiments.contracts import (
    file_evidence_ref,
    verify_result_evidence,
    verify_run_files,
)
from lib.experiments.callbacks import commit_run_result_finalized
from lib.experiments.status import canonical_status, is_terminal
from lib.research_state import EventStore, ResearchPaths
from lib.research_state.io import read_json, write_json_atomic
from lib.research_state.paths import add_research_root_argument
from lib.research_state.schema import require_enum


RESULT_FIELDS = {
    "protocol",
    "measurements",
    "verdict",
    "validity",
    "supported_claims",
    "unsupported_claims",
    "decision_candidate",
}


def _load_object(value: str) -> dict[str, Any]:
    path = Path(value)
    try:
        is_file = path.is_file()
    except OSError:
        is_file = False
    raw = path.read_text(encoding="utf-8") if is_file else value
    decoded = json.loads(raw)
    if not isinstance(decoded, dict):
        raise argparse.ArgumentTypeError("payload must decode to a JSON object")
    return decoded


def extract_result(
    paths: ResearchPaths,
    run_dir: Path,
    *,
    payload: dict[str, Any],
    evidence_files: Iterable[Path] = (),
) -> dict[str, Any]:
    """Merge scientific result fields without changing run intent or status."""
    unknown = sorted(set(payload) - RESULT_FIELDS)
    if unknown:
        raise ValueError(f"unknown result fields: {unknown}")
    resolved_run_dir = Path(run_dir).resolve()
    run = read_json(resolved_run_dir / "run.json")
    context = read_json(resolved_run_dir / "context.json")
    status = read_json(resolved_run_dir / "status.json")
    current = read_json(resolved_run_dir / "result.json", {})
    if not all(isinstance(value, dict) for value in (run, context, status, current)):
        raise ValueError("run, context, status, and result must be JSON objects")
    expected = paths.run_dir(
        str(run["package_id"]),
        str(run.get("experiment_local_id") or run["experiment_id"]),
        str(run["run_id"]),
    ).resolve()
    if resolved_run_dir != expected:
        raise ValueError("run directory does not match run.json identifiers")
    verify_run_files(run, context)
    final_status = canonical_status(str(status.get("status") or ""))
    if not is_terminal(final_status):
        raise ValueError(f"result extraction requires terminal status, got {final_status}")

    result = copy.deepcopy(current)
    result.update(copy.deepcopy(payload))
    result.update(
        {
            "schema_version": 1,
            "kind": "experiment-result",
            "run_id": run["run_id"],
            "package_id": run["package_id"],
            "experiment_id": run["experiment_id"],
            "status": final_status,
            "exit_code": status.get("exit_code"),
            "ended_at": status.get("ended_at"),
        }
    )
    result["verdict"] = require_enum(
        "result_verdict",
        result.get("verdict", "INCONCLUSIVE"),
    )
    result["validity"] = require_enum(
        "result_validity",
        result.get("validity", "UNMEASURED"),
    )
    for field in ("supported_claims", "unsupported_claims"):
        value = result.get(field, [])
        if not isinstance(value, list) or not all(
            isinstance(item, str) and item.strip() for item in value
        ):
            raise ValueError(f"{field} must be a list of non-empty strings")
        result[field] = value

    refs = result.get("evidence", [])
    if not isinstance(refs, list):
        raise ValueError("existing result evidence must be a list")
    by_identity: dict[tuple[str, str], dict[str, Any]] = {}
    for ref in refs:
        if not isinstance(ref, dict):
            raise ValueError("existing result evidence entries must be objects")
        by_identity[(str(ref.get("kind")), str(ref.get("uri")))] = copy.deepcopy(ref)
    for path in evidence_files:
        ref = file_evidence_ref(paths, run, Path(path))
        by_identity[(ref["kind"], ref["uri"])] = ref
    result["evidence"] = [
        by_identity[key] for key in sorted(by_identity, key=lambda item: (item[0], item[1]))
    ]
    verify_result_evidence(paths, run, result)
    result_path = resolved_run_dir / "result.json"
    write_json_atomic(result_path, result)
    persisted = read_json(result_path)
    if persisted != result:
        raise ValueError("atomic result write did not preserve the verified value")
    verify_result_evidence(paths, run, persisted)
    commit_run_result_finalized(
        EventStore(paths),
        run,
        result=persisted,
    )
    return persisted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default=".")
    add_research_root_argument(parser)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--payload", required=True, type=_load_object)
    parser.add_argument("--evidence", action="append", default=[])
    args = parser.parse_args(argv)
    paths = ResearchPaths.resolve(
        workspace=args.workspace,
        research_root=args.research_root,
    )
    result = extract_result(
        paths,
        Path(args.run_dir),
        payload=args.payload,
        evidence_files=[Path(value) for value in args.evidence],
    )
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
