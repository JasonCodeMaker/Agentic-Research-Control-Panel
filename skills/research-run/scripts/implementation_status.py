#!/usr/bin/env python3
"""Synchronize state-backed Implementation checkboxes for one Package."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


PIPELINE_ROOT = Path(__file__).resolve().parents[3]
OP_SCRIPTS = PIPELINE_ROOT / "skills" / "research-op" / "scripts"
for import_root in (PIPELINE_ROOT, OP_SCRIPTS):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from lib.implementation import (  # noqa: E402
    completion_counts,
    sync_observations,
    verification_input_fingerprint,
)
from lib.research_state import EventStore, ResearchPaths  # noqa: E402

import management  # noqa: E402


def _json_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _selected_changes(
    state: Mapping[str, Any],
    package_id: str,
    change_id: str | None,
) -> list[dict[str, Any]]:
    prefix = f"{package_id}::change::"
    selected = []
    for aggregate_id, record in sorted(
        state.get("aggregates", {}).get("change", {}).items()
    ):
        if (
            not isinstance(record, dict)
            or record.get("package_id") != package_id
            or not isinstance(record.get("plan"), dict)
        ):
            continue
        local_id = str(record.get("local_id") or aggregate_id.removeprefix(prefix))
        if change_id and change_id not in {aggregate_id, local_id}:
            continue
        selected.append(copy.deepcopy(record))
    if change_id and not selected:
        raise ValueError(f"planned Change not found: {change_id}")
    if not selected:
        raise ValueError(f"Package has no planned Changes: {package_id}")
    return selected


def _verification_command(
    paths: ResearchPaths,
    verification: Mapping[str, Any],
) -> dict[str, Any]:
    command = verification.get("command")
    if not isinstance(command, list) or not command:
        return {
            "state": "PENDING",
            "reason": "verification command is not declared",
        }
    cwd = paths.workspace
    if verification.get("cwd"):
        cwd = paths.workspace / str(verification["cwd"])
    started_at = datetime.now(timezone.utc).isoformat()
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=int(verification.get("timeout_seconds") or 300),
        )
        output = (result.stdout or "") + "\n" + (result.stderr or "")
        return {
            "checked_at": started_at,
            "command_sha256": _json_digest(command),
            "exit_code": result.returncode,
            "output_sha256": hashlib.sha256(
                output.encode("utf-8", errors="replace")
            ).hexdigest(),
            "reason": (
                "verification command passed"
                if result.returncode == 0
                else f"verification command exited {result.returncode}"
            ),
            "state": "PASS" if result.returncode == 0 else "FAIL",
        }
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "") + "\n" + (exc.stderr or "")
        return {
            "checked_at": started_at,
            "command_sha256": _json_digest(command),
            "output_sha256": hashlib.sha256(
                str(output).encode("utf-8", errors="replace")
            ).hexdigest(),
            "reason": "verification command timed out",
            "state": "FAIL",
        }
    except OSError as exc:
        return {
            "checked_at": started_at,
            "command_sha256": _json_digest(command),
            "reason": f"verification command could not start: {exc}",
            "state": "FAIL",
        }


def _run_selected_verifications(
    paths: ResearchPaths,
    plan: Mapping[str, Any],
    observations: dict[str, Any],
    selected_id: str | None,
) -> None:
    declared_ids = {
        str(verification["id"]) for verification in plan.get("verifications", [])
    }
    if selected_id and selected_id not in declared_ids:
        raise ValueError(f"verification not found: {selected_id}")
    for verification in plan.get("verifications", []):
        verification_id = str(verification["id"])
        if selected_id and verification_id != selected_id:
            continue
        result = _verification_command(paths, verification)
        result["input_fingerprint"] = verification_input_fingerprint(
            verification,
            observations["code_locations"],
        )
        observations["verifications"][verification_id] = result


def _commit_observations(
    paths: ResearchPaths,
    package_id: str,
    record: Mapping[str, Any],
    observations: Mapping[str, Any],
    actor_id: str,
) -> bool:
    if record.get("observations") == observations:
        return False
    local_id = str(record.get("local_id") or "")
    management.commit_change_operation(
        paths,
        package_id,
        "update",
        {
            "change_id": local_id,
            "observations": copy.deepcopy(dict(observations)),
        },
        actor={"type": "agent", "id": actor_id},
        idempotency_key=(
            f"implementation-status:{package_id}:{local_id}:"
            f"{_json_digest(observations)}"
        ),
    )
    return True


def synchronize(
    paths: ResearchPaths,
    package_id: str,
    *,
    change_id: str | None = None,
    verification_id: str | None = None,
    run_verifications: bool = False,
    actor_id: str = "implementation-status",
) -> dict[str, Any]:
    store = EventStore(paths)
    state = store.state()
    if package_id not in state.get("aggregates", {}).get("package", {}):
        raise ValueError(f"Package not found: {package_id}")
    rows = []
    for record in _selected_changes(state, package_id, change_id):
        plan = record["plan"]
        observations = sync_observations(
            paths.workspace,
            paths.root,
            plan,
            record.get("observations"),
        )
        if run_verifications:
            _run_selected_verifications(
                paths,
                plan,
                observations,
                verification_id,
            )
            observations = sync_observations(
                paths.workspace,
                paths.root,
                plan,
                observations,
            )
        changed = _commit_observations(
            paths,
            package_id,
            record,
            observations,
            actor_id,
        )
        counts = completion_counts(plan, observations)
        rows.append(
            {
                "change_id": record.get("local_id"),
                "changed": changed,
                "complete": (
                    counts["code_complete"] == counts["code_total"]
                    and counts["verification_passed"]
                    == counts["verification_total"]
                ),
                **counts,
            }
        )
    return {
        "package_id": package_id,
        "changes": rows,
        "complete": all(row["complete"] for row in rows),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Synchronize read-only Implementation checkbox state"
    )
    parser.add_argument("command", choices=("check", "sync", "verify"))
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--research-root")
    parser.add_argument("--package", required=True)
    parser.add_argument("--change")
    parser.add_argument("--verification")
    parser.add_argument("--actor-id", default="implementation-status")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.verification and args.command != "verify":
        raise SystemExit("--verification is valid only with verify")
    paths = ResearchPaths.resolve(
        workspace=args.workspace,
        research_root=args.research_root,
    )
    try:
        result = synchronize(
            paths,
            args.package,
            change_id=args.change,
            verification_id=args.verification,
            run_verifications=args.command == "verify",
            actor_id=args.actor_id,
        )
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if args.command in {"check", "verify"} and not result["complete"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
