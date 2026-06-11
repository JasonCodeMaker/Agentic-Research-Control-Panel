#!/usr/bin/env python3
"""Extract tracker fact CSV rows from one live status.json snapshot."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

PIPELINE_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PIPELINE_ROOT))

from lib import package_facts  # noqa: E402


REQUIRED_STATUS_KEYS = ("run_id", "pkg", "exp_id", "status")


def _compact_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _local_timestamp(epoch_seconds) -> str:
    if epoch_seconds in ("", None):
        return ""
    return dt.datetime.fromtimestamp(float(epoch_seconds)).astimezone().isoformat(timespec="seconds")


def _resolve_status_path(root: Path, status_arg: str) -> tuple[Path, Path]:
    status_path = Path(status_arg)
    if status_path.is_absolute():
        status_abs = status_path
        try:
            status_rel = status_abs.relative_to(root)
        except ValueError as exc:
            raise package_facts.FactError(f"status path is outside repo root: {status_abs}") from exc
    else:
        status_rel = status_path
        status_abs = root / status_rel
    return status_abs, status_rel


def _load_status(status_abs: Path, status_rel: Path) -> dict:
    try:
        data = json.loads(status_abs.read_text(encoding="utf-8"))
    except OSError as exc:
        raise package_facts.FactError(f"{status_rel}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise package_facts.FactError(f"{status_rel}: {exc}") from exc
    if not isinstance(data, dict):
        raise package_facts.FactError(f"{status_rel}: top-level JSON value must be an object")
    return data


def _validate_status(data: dict, status_rel: Path) -> None:
    missing = [key for key in REQUIRED_STATUS_KEYS if not str(data.get(key, "")).strip()]
    if missing:
        raise package_facts.FactError(f"{status_rel}: missing required keys: {', '.join(missing)}")
    run_state = str(data["status"])
    if run_state not in package_facts.VALID_RUN_STATES:
        raise package_facts.FactError(f"{status_rel}: invalid status: {run_state}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo-root", default=".")
    p.add_argument("--status", required=True)
    p.add_argument("--agent", required=True)
    p.add_argument("--live-action", default="")
    p.add_argument("--next-check", default="")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.repo_root).resolve()
    status_abs, status_rel = _resolve_status_path(root, args.status)

    try:
        data = _load_status(status_abs, status_rel)
        _validate_status(data, status_rel)
        last_log = _local_timestamp(data.get("last_output_at"))
    except (ValueError, package_facts.FactError) as exc:
        print(f"extract_tracker_facts: {exc}", file=sys.stderr)
        return 2

    pkg = str(data["pkg"])
    exp_id = str(data["exp_id"])
    run_id = str(data["run_id"])
    run_state = str(data["status"])
    row_id = f"{exp_id}:{run_id}"
    extracted_at = dt.datetime.now(dt.UTC).astimezone().isoformat(timespec="seconds")
    source_mtime = dt.datetime.fromtimestamp(status_abs.stat().st_mtime, dt.UTC).isoformat()
    source_artifact = str(status_rel)
    resource = data.get("resource", {})

    live_row = {
        "row_id": row_id,
        "time": last_log,
        "exp_id": exp_id,
        "run_id": run_id,
        "agent": args.agent,
        "run_state": run_state,
        "last_log": last_log,
        "progress": _compact_json(data.get("progress", {})),
        "metrics": _compact_json(data.get("latest_metrics", {})),
        "resource": _compact_json(resource),
        "artifacts": _compact_json(data.get("source_map", {})),
        "eta": str(data.get("eta", "")),
        "action": args.live_action,
        "next_check": args.next_check,
        "source_artifact": source_artifact,
        "source_mtime": source_mtime,
        "extractor": "extract_tracker_facts.py",
        "extracted_at": extracted_at,
    }
    resource_row = {
        "row_id": row_id,
        "exp_id": exp_id,
        "purpose": "",
        "dependency": "",
        "target": "",
        "capacity": _compact_json(resource),
        "assigned": "",
        "reason": "",
        "agent": args.agent,
        "command_cwd_env": "",
        "session_job": "",
        "runtime_root": str(status_rel.parent),
        "log_path": "",
        "expected_duration": "",
        "status": run_state,
        "source_artifact": source_artifact,
        "source_mtime": source_mtime,
        "extractor": "extract_tracker_facts.py",
        "extracted_at": extracted_at,
    }

    live_csv = package_facts.table_csv_path(pkg, "live_checks", root=root)
    resource_csv = package_facts.table_csv_path(pkg, "resource_allocation", root=root)
    package_facts.upsert_csv_rows(live_csv, package_facts.LIVE_CHECK_COLUMNS, [live_row])
    package_facts.upsert_csv_rows(
        resource_csv,
        package_facts.RESOURCE_ALLOCATION_COLUMNS,
        [resource_row],
    )
    print(f"wrote {live_csv.relative_to(root)}")
    print(f"wrote {resource_csv.relative_to(root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
