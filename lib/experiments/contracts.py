"""Small hashes that bind authorization, run metadata, and frozen context."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from lib.research_state.io import canonical_json
from lib.research_state.paths import ResearchPaths
from lib.research_state.schema import enum, require_enum
from .status import TERMINAL_STATUSES


ENV_DIGEST_KEYS = (
    "CUDA_VISIBLE_DEVICES",
    "CONDA_DEFAULT_ENV",
    "VIRTUAL_ENV",
    "PYTHONPATH",
)

# This lease covers publication of the immutable run/context envelope after
# management authorization. Once both files verify, queue and heartbeat policy
# own the run; a long scheduler wait is not an abandoned authorization.
DEFAULT_AUTHORIZATION_LEASE_SECONDS = 300

LAUNCH_SPEC_FIELDS = (
    "run_id",
    "package_id",
    "experiment_id",
    "experiment_local_id",
    "command",
    "cwd",
    "created_at",
    "created_at_unix",
    "context_source_seq",
    "context_source_hash",
    "context_sha256",
    "run_json",
    "context_json",
    "result_json",
    "log_path",
    "events_path",
    "metrics_path",
    "environment",
    "gpu_ids",
    "git_commit",
    "transport",
    "tmux_session",
    "heartbeat_timeout",
    "total_steps",
    "metrics_regexes",
    "gpu_sample",
    "retry_of",
    "resource",
    "launch_ack_decision_id",
    "telemetry",
    "expected_duration_class",
    "log_adapter",
)


def _sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def environment_envelope(environment: dict[str, Any]) -> dict[str, Any]:
    """Bind the exact launch-relevant environment, including empty values."""
    if not isinstance(environment, dict):
        raise TypeError("environment must be an object")
    selected: dict[str, str] = {}
    for key in ENV_DIGEST_KEYS:
        if key not in environment:
            continue
        value = environment[key]
        if not isinstance(value, str):
            raise TypeError(f"environment variable {key} must be a string")
        selected[key] = value
    return {"sha256": _sha256(selected), "keys": selected}


def verify_environment_envelope(envelope: Any) -> dict[str, str]:
    """Return the authorized environment after validating its recorded digest."""
    if not isinstance(envelope, dict):
        raise ValueError("run.json environment must be an object")
    selected = envelope.get("keys")
    if not isinstance(selected, dict):
        raise ValueError("run.json environment.keys must be an object")
    unknown = sorted(set(selected) - set(ENV_DIGEST_KEYS))
    if unknown:
        raise ValueError(
            f"run.json environment contains unsupported keys: {unknown}"
        )
    if any(not isinstance(value, str) for value in selected.values()):
        raise ValueError("run.json environment values must be strings")
    if envelope.get("sha256") != _sha256(selected):
        raise ValueError("run.json environment does not match its sha256")
    return dict(selected)


def context_sha256(snapshot: dict[str, Any]) -> str:
    payload = {
        "schema_version": snapshot.get("schema_version", 1),
        "source_seq": snapshot.get("source_seq"),
        "source_hash": snapshot.get("source_hash"),
        "data": snapshot.get("data"),
        "selected_experiment_id": snapshot.get("selected_experiment_id"),
        "selected_experiment_local_id": snapshot.get(
            "selected_experiment_local_id"
        ),
    }
    return _sha256(payload)


def launch_sha256(run: dict[str, Any]) -> str:
    missing = [field for field in LAUNCH_SPEC_FIELDS if field not in run]
    if missing:
        raise ValueError(f"run.json is missing launch fields: {', '.join(missing)}")
    return _sha256(
        {
            "schema_version": run.get("schema_version", 1),
            **{field: run[field] for field in LAUNCH_SPEC_FIELDS},
        }
    )


def verify_run_files(run: dict[str, Any], context: dict[str, Any]) -> None:
    actual_context = context_sha256(context)
    recorded_context = context.get("context_sha256")
    if recorded_context != actual_context:
        raise ValueError("context.json content does not match context_sha256")
    if run.get("context_sha256") != actual_context:
        raise ValueError("run.json does not bind the current context.json")
    actual_launch = launch_sha256(run)
    if run.get("launch_sha256") != actual_launch:
        raise ValueError("run.json content does not match launch_sha256")


def file_evidence_ref(
    paths: ResearchPaths,
    run: dict[str, Any],
    path: Path,
    *,
    kind: str = "FILE",
    selector: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a hash-bound EvidenceRef for one file owned by the run."""
    resolved = path.resolve()
    run_dir = paths.run_dir(
        str(run["package_id"]),
        str(run.get("experiment_local_id") or run["experiment_id"]),
        str(run["run_id"]),
    ).resolve()
    try:
        resolved.relative_to(run_dir)
    except ValueError as exc:
        raise ValueError(f"evidence file is outside its run directory: {resolved}") from exc
    raw = resolved.read_bytes()
    ref: dict[str, Any] = {
        "uri": resolved.relative_to(paths.root.resolve()).as_posix(),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
        "kind": kind,
        "package_id": str(run["package_id"]),
        "experiment_id": str(run["experiment_id"]),
        "run_id": str(run["run_id"]),
    }
    if selector:
        ref["selector"] = selector
    return ref


def verify_evidence_ref(
    paths: ResearchPaths,
    ref: dict[str, Any],
    *,
    run: dict[str, Any] | None = None,
) -> Path | None:
    """Validate one EvidenceRef and verify local evidence bytes when applicable."""
    required = {
        "uri",
        "sha256",
        "size_bytes",
        "kind",
        "package_id",
        "experiment_id",
        "run_id",
    }
    missing = sorted(required - set(ref))
    if missing:
        raise ValueError(f"EvidenceRef is missing fields: {missing}")
    if ref["kind"] not in enum("evidence_kind"):
        raise ValueError(f"unknown EvidenceRef kind: {ref['kind']!r}")
    digest = str(ref["sha256"]).removeprefix("sha256:")
    if len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest.lower()
    ):
        raise ValueError("EvidenceRef sha256 must be a 64-character hexadecimal digest")
    if (
        isinstance(ref["size_bytes"], bool)
        or not isinstance(ref["size_bytes"], int)
        or ref["size_bytes"] < 0
    ):
        raise ValueError("EvidenceRef size_bytes must be a non-negative integer")
    for key in ("package_id", "experiment_id", "run_id"):
        if not isinstance(ref[key], str) or not ref[key]:
            raise ValueError(f"EvidenceRef {key} must be a non-empty string")
        if run is not None and str(run.get(key)) != ref[key]:
            raise ValueError(
                f"EvidenceRef {key}={ref[key]!r} does not match run {run.get(key)!r}"
            )

    uri = str(ref["uri"])
    if ref["kind"] == "EXTERNAL_URI" or "://" in uri:
        return None
    relative = Path(uri)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"unsafe local EvidenceRef uri: {uri!r}")
    resolved = (paths.root / relative).resolve()
    try:
        resolved.relative_to(paths.experiments.resolve())
    except ValueError as exc:
        raise ValueError(f"local EvidenceRef is outside experiments: {uri!r}") from exc
    if run is not None:
        expected_run_dir = paths.run_dir(
            str(run["package_id"]),
            str(run.get("experiment_local_id") or run["experiment_id"]),
            str(run["run_id"]),
        ).resolve()
        try:
            resolved.relative_to(expected_run_dir)
        except ValueError as exc:
            raise ValueError(
                f"EvidenceRef is outside its producer run: {uri!r}"
            ) from exc
    if not resolved.is_file():
        raise ValueError(f"EvidenceRef file is missing: {uri!r}")
    raw = resolved.read_bytes()
    if len(raw) != ref["size_bytes"]:
        raise ValueError(f"EvidenceRef size mismatch: {uri!r}")
    if hashlib.sha256(raw).hexdigest() != digest.lower():
        raise ValueError(f"EvidenceRef hash mismatch: {uri!r}")
    return resolved


def verify_result_evidence(
    paths: ResearchPaths,
    run: dict[str, Any],
    result: dict[str, Any],
) -> None:
    """Validate one complete terminal result and all evidence references."""
    if result.get("schema_version") != 1:
        raise ValueError("result.json schema_version must be 1")
    if result.get("run_id") != run.get("run_id"):
        raise ValueError("result.json run_id does not match run.json")
    if result.get("package_id") != run.get("package_id"):
        raise ValueError("result.json package_id does not match run.json")
    if result.get("experiment_id") != run.get("experiment_id"):
        raise ValueError("result.json experiment_id does not match run.json")
    if result.get("kind") not in {"runtime-terminal", "experiment-result"}:
        raise ValueError("result.json kind must identify a terminal result")
    status = require_enum("run_status", result.get("status"))
    if status not in TERMINAL_STATUSES:
        raise ValueError("result.json status must be terminal")
    for field in ("protocol", "measurements"):
        if not isinstance(result.get(field), dict):
            raise ValueError(f"result.json {field} must be an object")
    decision_candidate = result.get("decision_candidate")
    if decision_candidate is not None and not isinstance(
        decision_candidate,
        dict,
    ):
        raise ValueError(
            "result.json decision_candidate must be an object or null"
        )
    require_enum("result_verdict", result.get("verdict"))
    require_enum("result_validity", result.get("validity"))
    for field in ("supported_claims", "unsupported_claims"):
        claims = result.get(field)
        if not isinstance(claims, list) or not all(
            isinstance(claim, str) and claim.strip() for claim in claims
        ):
            raise ValueError(
                f"result.json {field} must be a list of non-empty strings"
            )
    evidence = result.get("evidence")
    if not isinstance(evidence, list):
        raise ValueError("result.json evidence must be a list")
    for ref in evidence:
        if not isinstance(ref, dict):
            raise ValueError("result.json evidence entries must be objects")
        verify_evidence_ref(paths, ref, run=run)
