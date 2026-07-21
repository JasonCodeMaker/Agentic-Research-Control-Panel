#!/usr/bin/env python3
"""Read bounded run summaries from state plus canonical run directories."""

from __future__ import annotations

import argparse
import json
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable

from lib.experiments.status import TERMINAL_STATUSES, canonical_status
from lib.research_state import ResearchPaths, StateQuery
from lib.research_state.io import read_json, read_jsonl
from lib.research_state.paths import add_research_root_argument


def _safe_run_dir(paths: ResearchPaths, record: dict[str, Any]) -> Path | None:
    raw = record.get("dir")
    if raw:
        candidate = Path(str(raw))
        candidate = candidate if candidate.is_absolute() else paths.root / candidate
    else:
        package_id = record.get("package_id")
        experiment_id = record.get("experiment_id")
        experiment_local_id = record.get("experiment_local_id") or experiment_id
        run_id = record.get("run_id") or record.get("id")
        if not all(
            isinstance(value, str) and value
            for value in (package_id, experiment_local_id, run_id)
        ):
            return None
        candidate = paths.run_dir(package_id, experiment_local_id, run_id)
    resolved = candidate.resolve()
    try:
        resolved.relative_to(paths.experiments.resolve())
    except ValueError:
        return None
    return resolved


def _tail_lines(path: Path, tail: int) -> list[str]:
    if not path.exists() or tail <= 0:
        return []
    rows: deque[str] = deque(maxlen=tail)
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            rows.append(line.rstrip("\n"))
    return list(rows)


def open_runs(
    paths: ResearchPaths,
    *,
    now: Callable[[], float] = time.time,
) -> list[dict[str, Any]]:
    """List management-open runs without consulting a second live index."""
    stamp = StateQuery(paths).show("open_run")
    timestamp = now()
    items: list[dict[str, Any]] = []
    for run_id, open_record in sorted(stamp["data"].items()):
        state_record = StateQuery(paths).show("run", run_id)["data"]
        run_dir = _safe_run_dir(paths, {**state_record, **open_record})
        snapshot = (
            read_json(run_dir / "status.json", {})
            if run_dir is not None
            else {}
        )
        raw_status = snapshot.get("status") or state_record.get("status") or "RUNNING"
        try:
            status = canonical_status(raw_status)
        except ValueError:
            status = "INVALID"
        reference = (
            snapshot.get("last_output_at")
            or snapshot.get("started_at")
            or state_record.get("started_at")
            or state_record.get("requested_at")
        )
        age = None if reference is None else max(0, int(timestamp - float(reference)))
        heartbeat = int(snapshot.get("heartbeat_timeout") or 600)
        if status in {"QUEUED", "RUNNING"} and age is not None and age > heartbeat:
            status = "STALE"
        items.append(
            {
                "run_id": run_id,
                "package_id": open_record.get("package_id"),
                "experiment_id": open_record.get("experiment_id"),
                "experiment_local_id": state_record.get(
                    "experiment_local_id"
                ),
                "status": status,
                "last_output_age_s": age,
                "dir": str(run_dir) if run_dir is not None else None,
                "reconciliation_required": status in TERMINAL_STATUSES,
                "source_seq": stamp["source_seq"],
                "source_hash": stamp["source_hash"],
            }
        )
    return items


def run_summary(run_dir: Path, *, tail: int = 50) -> dict[str, Any]:
    run_dir = Path(run_dir).resolve()
    events = read_jsonl(run_dir / "events.jsonl")
    anomalies = [event for event in events if event.get("kind") == "anomaly"]
    if len(anomalies) > 10:
        anomalies = anomalies[:5] + anomalies[-5:]
    return {
        "run_dir": str(run_dir),
        "run": read_json(run_dir / "run.json", {}),
        "context": read_json(run_dir / "context.json", {}),
        "status": read_json(run_dir / "status.json", {}),
        "result": read_json(run_dir / "result.json", {}),
        "anomalies": anomalies,
        "tail": _tail_lines(run_dir / "log.txt", tail),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default=".")
    add_research_root_argument(parser)
    parser.add_argument("--run")
    parser.add_argument("--tail", type=int, default=50)
    parser.add_argument("--open", action="store_true", dest="show_open")
    args = parser.parse_args(argv)

    paths = ResearchPaths.resolve(
        workspace=args.workspace,
        research_root=args.research_root,
    )
    if args.show_open:
        print(json.dumps(open_runs(paths), indent=2, sort_keys=True))
        return 0
    if args.run:
        print(
            json.dumps(
                run_summary(Path(args.run), tail=args.tail),
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    parser.error("choose --open or --run")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
