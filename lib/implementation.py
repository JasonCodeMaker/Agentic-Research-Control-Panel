"""Implementation-plan normalization and checkbox-state evaluation.

The browser renders these records but never owns them.  A checked item means
that the current workspace satisfies a declared code-location predicate or
that a verification command passed against the current input fingerprint.
"""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any, Mapping


CODE_ACTIONS = frozenset({"ADD", "LINK", "MODIFY", "OUTPUT", "REUSE"})
OBSERVATION_STATES = frozenset({"FAIL", "PASS", "PENDING", "STALE"})
LOCATION_ROOTS = frozenset({"research", "workspace"})
LOCATION_PREDICATES = frozenset({"exists", "git_clean"})


class ImplementationPlanError(ValueError):
    """Raised when an implementation Change cannot be evaluated safely."""


def _digest(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _relative_path(value: Any, *, field: str) -> str:
    text = str(value or "").strip().replace("\\", "/")
    path = PurePosixPath(text)
    if (
        not text
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ImplementationPlanError(
            f"{field} must be a non-empty relative path without '.' or '..'"
        )
    return path.as_posix()


def _location_base(
    workspace: Path,
    research_root: Path,
    location: Mapping[str, Any],
) -> Path:
    root = str(location.get("root") or "workspace").lower()
    if root not in LOCATION_ROOTS:
        raise ImplementationPlanError(
            f"code location root must be one of {sorted(LOCATION_ROOTS)}"
        )
    return research_root if root == "research" else workspace


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _path_snapshot(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        target = path.readlink().as_posix()
        return {
            "kind": "SYMLINK",
            "fingerprint": _digest(
                {
                    "kind": "SYMLINK",
                    "target": target,
                    "resolved": path.exists(),
                }
            ),
            "resolved": path.exists(),
            "target": target,
        }
    if not path.exists():
        return {"kind": "MISSING", "fingerprint": _digest({"kind": "MISSING"})}
    if path.is_file():
        return {
            "kind": "FILE",
            "fingerprint": _digest(
                {"kind": "FILE", "sha256": _file_sha256(path)}
            ),
        }
    if path.is_dir():
        return {
            "kind": "DIRECTORY",
            "fingerprint": _digest({"kind": "DIRECTORY"}),
        }
    return {
        "kind": "OTHER",
        "fingerprint": _digest({"kind": "OTHER"}),
    }


def snapshot_location(
    workspace: Path,
    research_root: Path,
    location: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a bounded, deterministic snapshot for one declared location."""
    relative = _relative_path(location.get("path"), field="code location path")
    base = _location_base(workspace, research_root, location)
    if any(char in relative for char in "*?["):
        if str(location.get("action") or "").upper() != "OUTPUT":
            raise ImplementationPlanError("glob paths are allowed only for OUTPUT")
        matches = []
        for match in sorted(base.glob(relative)):
            snapshot = _path_snapshot(match)
            matches.append(
                {
                    "path": match.relative_to(base).as_posix(),
                    "fingerprint": snapshot["fingerprint"],
                    "kind": snapshot["kind"],
                }
            )
        return {
            "kind": "GLOB",
            "fingerprint": _digest(matches),
            "matches": matches,
        }
    return _path_snapshot(base / relative)


def _normalized_location(raw: Any, *, index: int) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ImplementationPlanError(
            f"plan.code_locations[{index}] must be an object"
        )
    location = copy.deepcopy(dict(raw))
    location_id = str(location.get("id") or "").strip()
    if not location_id:
        raise ImplementationPlanError(
            f"plan.code_locations[{index}].id is required"
        )
    action = str(location.get("action") or "").upper()
    if action not in CODE_ACTIONS:
        raise ImplementationPlanError(
            f"code location {location_id!r} action must be one of "
            f"{sorted(CODE_ACTIONS)}"
        )
    root = str(location.get("root") or "workspace").lower()
    if root not in LOCATION_ROOTS:
        raise ImplementationPlanError(
            f"code location {location_id!r} root must be one of "
            f"{sorted(LOCATION_ROOTS)}"
        )
    predicate = str(location.get("predicate") or "exists").lower()
    if predicate not in LOCATION_PREDICATES:
        raise ImplementationPlanError(
            f"code location {location_id!r} predicate must be one of "
            f"{sorted(LOCATION_PREDICATES)}"
        )
    if predicate == "git_clean" and action != "REUSE":
        raise ImplementationPlanError(
            f"code location {location_id!r} uses git_clean outside REUSE"
        )
    location.update(
        {
            "id": location_id,
            "action": action,
            "path": _relative_path(
                location.get("path"),
                field=f"code location {location_id!r} path",
            ),
            "root": root,
            "predicate": predicate,
        }
    )
    return location


def _normalized_verification(raw: Any, *, index: int) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ImplementationPlanError(
            f"plan.verifications[{index}] must be an object"
        )
    verification = copy.deepcopy(dict(raw))
    verification_id = str(verification.get("id") or "").strip()
    label = str(verification.get("label") or "").strip()
    if not verification_id or not label:
        raise ImplementationPlanError(
            f"plan.verifications[{index}] requires id and label"
        )
    command = verification.get("command")
    if command is not None and (
        not isinstance(command, list)
        or not command
        or not all(isinstance(part, str) and part for part in command)
    ):
        raise ImplementationPlanError(
            f"verification {verification_id!r} command must be a non-empty "
            "argument list"
        )
    cwd = verification.get("cwd")
    if cwd is not None:
        verification["cwd"] = _relative_path(
            cwd,
            field=f"verification {verification_id!r} cwd",
        )
    depends_on = verification.get("depends_on")
    if depends_on is not None and (
        not isinstance(depends_on, list)
        or not all(isinstance(item, str) and item.strip() for item in depends_on)
    ):
        raise ImplementationPlanError(
            f"verification {verification_id!r} depends_on must be a string list"
        )
    timeout = verification.get("timeout_seconds", 300)
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, int)
        or timeout < 1
        or timeout > 3600
    ):
        raise ImplementationPlanError(
            f"verification {verification_id!r} timeout_seconds must be 1..3600"
        )
    verification.update(
        {
            "id": verification_id,
            "label": label,
            "timeout_seconds": timeout,
        }
    )
    return verification


def normalize_plan(
    workspace: Path,
    research_root: Path,
    plan: Any,
    *,
    previous_plan: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate a plan and freeze baselines before implementation edits."""
    if not isinstance(plan, Mapping):
        raise ImplementationPlanError("change.plan must be an object")
    normalized = copy.deepcopy(dict(plan))
    how = str(normalized.get("how_it_changes") or "").strip()
    if not how:
        raise ImplementationPlanError("change.plan.how_it_changes is required")
    raw_locations = normalized.get("code_locations")
    raw_verifications = normalized.get("verifications")
    if not isinstance(raw_locations, list) or not raw_locations:
        raise ImplementationPlanError(
            "change.plan.code_locations must be a non-empty list"
        )
    if not isinstance(raw_verifications, list) or not raw_verifications:
        raise ImplementationPlanError(
            "change.plan.verifications must be a non-empty list"
        )

    previous_locations = {}
    if isinstance(previous_plan, Mapping):
        previous_locations = {
            str(item.get("id")): item
            for item in previous_plan.get("code_locations", [])
            if isinstance(item, Mapping) and item.get("id")
        }

    locations = []
    location_ids: set[str] = set()
    for index, raw in enumerate(raw_locations):
        location = _normalized_location(raw, index=index)
        location_id = location["id"]
        if location_id in location_ids:
            raise ImplementationPlanError(
                f"duplicate code location id: {location_id}"
            )
        location_ids.add(location_id)
        previous = previous_locations.get(location_id)
        same_contract = isinstance(previous, Mapping) and all(
            previous.get(field) == location.get(field)
            for field in ("action", "path", "predicate", "root")
        )
        if same_contract and isinstance(previous.get("baseline"), Mapping):
            location["baseline"] = copy.deepcopy(previous["baseline"])
        else:
            location["baseline"] = snapshot_location(
                workspace,
                research_root,
                location,
            )
        baseline_kind = str(location["baseline"].get("kind") or "")
        if location["action"] == "ADD" and baseline_kind != "MISSING":
            raise ImplementationPlanError(
                f"ADD location {location_id!r} already exists; use REUSE or MODIFY"
            )
        locations.append(location)

    verifications = []
    verification_ids: set[str] = set()
    default_dependencies = [
        item["id"] for item in locations if item["action"] != "OUTPUT"
    ]
    for index, raw in enumerate(raw_verifications):
        verification = _normalized_verification(raw, index=index)
        verification_id = verification["id"]
        if verification_id in verification_ids:
            raise ImplementationPlanError(
                f"duplicate verification id: {verification_id}"
            )
        verification_ids.add(verification_id)
        dependencies = verification.get("depends_on", default_dependencies)
        unknown = sorted(set(dependencies) - location_ids)
        if unknown:
            raise ImplementationPlanError(
                f"verification {verification_id!r} has unknown dependencies: "
                f"{unknown}"
            )
        verification["depends_on"] = list(dict.fromkeys(dependencies))
        verifications.append(verification)

    normalized.update(
        {
            "how_it_changes": how,
            "code_locations": locations,
            "verifications": verifications,
        }
    )
    return normalized


def validate_observations(plan: Mapping[str, Any], observations: Any) -> None:
    if observations is None:
        return
    if not isinstance(observations, Mapping):
        raise ImplementationPlanError("change.observations must be an object")
    expected = {
        "code_locations": {
            str(item["id"]) for item in plan.get("code_locations", [])
        },
        "verifications": {
            str(item["id"]) for item in plan.get("verifications", [])
        },
    }
    for group, valid_ids in expected.items():
        values = observations.get(group, {})
        if not isinstance(values, Mapping):
            raise ImplementationPlanError(
                f"change.observations.{group} must be an object"
            )
        unknown = sorted(set(map(str, values)) - valid_ids)
        if unknown:
            raise ImplementationPlanError(
                f"change.observations.{group} has unknown ids: {unknown}"
            )
        for item_id, observation in values.items():
            if not isinstance(observation, Mapping):
                raise ImplementationPlanError(
                    f"observation {group}.{item_id} must be an object"
                )
            state = str(observation.get("state") or "")
            if state not in OBSERVATION_STATES:
                raise ImplementationPlanError(
                    f"observation {group}.{item_id} state must be one of "
                    f"{sorted(OBSERVATION_STATES)}"
                )


def validate_change_plan_record(record: Mapping[str, Any]) -> None:
    """Validate the stored, already-normalized Change plan shape."""
    plan = record.get("plan")
    if not isinstance(plan, Mapping):
        raise ImplementationPlanError("change.plan must be an object")
    title = str(record.get("title") or "").strip()
    if not title:
        raise ImplementationPlanError("planned Change requires title")
    order = record.get("order")
    if isinstance(order, bool) or not isinstance(order, int) or order < 1:
        raise ImplementationPlanError(
            "planned Change requires a positive integer order"
        )
    how = str(plan.get("how_it_changes") or "").strip()
    locations = plan.get("code_locations")
    verifications = plan.get("verifications")
    if not how or not isinstance(locations, list) or not locations:
        raise ImplementationPlanError(
            "planned Change requires how_it_changes and code_locations"
        )
    if not isinstance(verifications, list) or not verifications:
        raise ImplementationPlanError(
            "planned Change requires at least one verification"
        )
    location_ids = {
        str(item.get("id"))
        for item in locations
        if isinstance(item, Mapping) and item.get("id")
    }
    if len(location_ids) != len(locations):
        raise ImplementationPlanError(
            "planned Change code location ids must be unique and non-empty"
        )
    for index, item in enumerate(locations):
        normalized = _normalized_location(item, index=index)
        baseline = item.get("baseline")
        if (
            not isinstance(baseline, Mapping)
            or not isinstance(baseline.get("kind"), str)
            or not isinstance(baseline.get("fingerprint"), str)
            or len(baseline["fingerprint"]) != 64
        ):
            raise ImplementationPlanError(
                f"code location {normalized['id']!r} requires a frozen baseline "
                "fingerprint"
            )
    verification_ids = set()
    for index, item in enumerate(verifications):
        normalized = _normalized_verification(item, index=index)
        verification_id = normalized["id"]
        if verification_id in verification_ids:
            raise ImplementationPlanError(
                f"duplicate verification id: {verification_id}"
            )
        verification_ids.add(verification_id)
        unknown = sorted(set(normalized.get("depends_on") or []) - location_ids)
        if unknown:
            raise ImplementationPlanError(
                f"verification {verification_id!r} has unknown dependencies: "
                f"{unknown}"
            )
    validate_observations(plan, record.get("observations"))


def _git_clean_snapshot(path: Path, base_snapshot: Mapping[str, Any]) -> tuple[bool, str]:
    try:
        top = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        if Path(top).resolve() != path.resolve():
            return False, _digest(
                {"base": base_snapshot, "git": "declared path is not a repository root"}
            )
        head = subprocess.run(
            ["git", "-C", top, "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "-C", top, "status", "--porcelain=v1"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return False, _digest({"base": base_snapshot, "git": "unavailable"})
    return not status.strip(), _digest(
        {"base": base_snapshot, "head": head, "status": status}
    )


def evaluate_location(
    workspace: Path,
    research_root: Path,
    location: Mapping[str, Any],
) -> dict[str, Any]:
    current = snapshot_location(workspace, research_root, location)
    action = str(location.get("action") or "").upper()
    baseline = location.get("baseline")
    baseline = baseline if isinstance(baseline, Mapping) else {}
    state = "PENDING"
    reason = "planned action is not yet satisfied"
    fingerprint = current["fingerprint"]

    if action == "REUSE":
        if current["kind"] == "MISSING":
            reason = "reuse source is missing"
        elif location.get("predicate") == "git_clean":
            relative = _relative_path(
                location.get("path"),
                field="code location path",
            )
            base = _location_base(workspace, research_root, location)
            clean, fingerprint = _git_clean_snapshot(base / relative, current)
            if clean:
                state, reason = "PASS", "reuse source exists and is clean"
            else:
                reason = "working tree is dirty or unavailable"
        else:
            state, reason = "PASS", "reuse source exists"
    elif action == "ADD":
        if baseline.get("kind") == "MISSING" and current["kind"] != "MISSING":
            state, reason = "PASS", "planned path was added"
        elif current["kind"] == "MISSING":
            reason = "planned path has not been added"
        else:
            reason = "path existed before this plan"
    elif action == "MODIFY":
        if current["kind"] == "MISSING":
            reason = "planned source is missing"
        elif current["fingerprint"] != baseline.get("fingerprint"):
            state, reason = "PASS", "content differs from the frozen baseline"
        else:
            reason = "content still matches the frozen baseline"
    elif action == "LINK":
        if current["kind"] == "SYMLINK" and current.get("resolved"):
            state, reason = "PASS", "symlink resolves"
        elif current["kind"] == "SYMLINK":
            reason = "symlink target does not resolve"
        else:
            reason = "planned symlink is missing"
    elif action == "OUTPUT":
        present = (
            bool(current.get("matches"))
            if current["kind"] == "GLOB"
            else current["kind"] != "MISSING"
        )
        if present:
            state, reason = "PASS", "expected output exists"
        else:
            reason = "expected output is missing"

    return {
        "fingerprint": fingerprint,
        "reason": reason,
        "state": state,
    }


def verification_input_fingerprint(
    verification: Mapping[str, Any],
    code_observations: Mapping[str, Any],
) -> str:
    inputs = []
    for location_id in verification.get("depends_on", []):
        observation = code_observations.get(location_id, {})
        inputs.append(
            {
                "id": location_id,
                "fingerprint": observation.get("fingerprint"),
                "state": observation.get("state"),
            }
        )
    return _digest(inputs)


def sync_observations(
    workspace: Path,
    research_root: Path,
    plan: Mapping[str, Any],
    previous: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Recompute code state and invalidate checks whose inputs changed."""
    previous = previous if isinstance(previous, Mapping) else {}
    code = {
        str(location["id"]): evaluate_location(
            workspace,
            research_root,
            location,
        )
        for location in plan.get("code_locations", [])
    }
    prior_verifications = previous.get("verifications", {})
    if not isinstance(prior_verifications, Mapping):
        prior_verifications = {}
    verifications = {}
    for verification in plan.get("verifications", []):
        verification_id = str(verification["id"])
        fingerprint = verification_input_fingerprint(verification, code)
        prior = prior_verifications.get(verification_id)
        if isinstance(prior, Mapping):
            observation = copy.deepcopy(dict(prior))
            if (
                observation.get("state") in {"FAIL", "PASS"}
                and observation.get("input_fingerprint") != fingerprint
            ):
                observation.update(
                    {
                        "state": "STALE",
                        "reason": "implementation inputs changed after this check",
                    }
                )
        else:
            observation = {
                "state": "PENDING",
                "reason": (
                    "verification command has not run"
                    if verification.get("command")
                    else "verification command is not declared"
                ),
            }
        observation["input_fingerprint"] = fingerprint
        verifications[verification_id] = observation
    return {
        "code_locations": code,
        "verifications": verifications,
    }


def completion_counts(
    plan: Mapping[str, Any],
    observations: Mapping[str, Any] | None,
) -> dict[str, int]:
    observations = observations if isinstance(observations, Mapping) else {}
    code = observations.get("code_locations", {})
    checks = observations.get("verifications", {})
    code = code if isinstance(code, Mapping) else {}
    checks = checks if isinstance(checks, Mapping) else {}
    return {
        "code_complete": sum(
            1
            for item in plan.get("code_locations", [])
            if code.get(str(item["id"]), {}).get("state") == "PASS"
        ),
        "code_total": len(plan.get("code_locations", [])),
        "verification_passed": sum(
            1
            for item in plan.get("verifications", [])
            if checks.get(str(item["id"]), {}).get("state") == "PASS"
        ),
        "verification_total": len(plan.get("verifications", [])),
    }
