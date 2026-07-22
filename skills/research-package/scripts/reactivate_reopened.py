#!/usr/bin/env python3
"""Reactivate one unchanged Package reopen through a compensating event."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
PIPELINE_ROOT = Path(__file__).resolve().parents[3]
for candidate in (
    SCRIPT_DIR,
    PIPELINE_ROOT,
    PIPELINE_ROOT / "lib",
    PIPELINE_ROOT / "skills/research-op/scripts",
):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import management  # noqa: E402
from lib.research_state import ResearchPaths  # noqa: E402


def reactivate(
    paths: ResearchPaths,
    *,
    package_id: str,
    actor_id: str,
    expected_version: int | None = None,
) -> dict[str, Any]:
    event = management.reactivate_unchanged_reopen(
        paths,
        package_id,
        actor={"type": "user", "id": actor_id},
        expected_version=expected_version,
    )
    projection = event.get("_interface_projection")
    if not isinstance(projection, dict):
        projection = {}
    record = event["payload"]["record"]
    return {
        "status": "reactivated",
        "package_id": package_id,
        "event_id": event["event_id"],
        "aggregate_version": event["aggregate_version"],
        "lifecycle": record["lifecycle"],
        "phase": record["phase"],
        "category": "in-progress",
        "experiments": [
            row["aggregate_id"]
            for row in event["payload"]["experiment_restorations"]
        ],
        "interface_written": bool(projection.get("written")),
        "interface_root": projection.get("root"),
        **(
            {"interface_error": projection["error"]}
            if projection.get("error")
            else {}
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--research-root")
    parser.add_argument("--package-id", required=True)
    parser.add_argument("--actor-id", required=True)
    parser.add_argument("--expected-version", type=int)
    parser.add_argument("--json", action="store_true", dest="json_output")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = ResearchPaths.resolve(
        workspace=args.workspace,
        research_root=args.research_root,
    )
    try:
        result = reactivate(
            paths,
            package_id=args.package_id,
            actor_id=args.actor_id,
            expected_version=args.expected_version,
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "rejected": True,
                    "package_id": args.package_id,
                    "rule": getattr(exc, "rule", type(exc).__name__),
                    "detail": str(exc),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2
    if args.json_output:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        print(f"status: {result['status']}")
        print(f"package: {result['package_id']}")
        print(f"state: {result['lifecycle']} / {result['phase']}")
        print("restored Experiments: " + ", ".join(result["experiments"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
