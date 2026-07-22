#!/usr/bin/env python3
"""Reopen one never-run ACTIVE Package as the same non-executable Draft."""

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
from lib.research_state import EventStore, ResearchPaths  # noqa: E402


def reopen(
    paths: ResearchPaths,
    *,
    package_id: str,
    reason: str,
    actor_id: str,
    source_document: str | None = None,
    expected_version: int | None = None,
) -> dict[str, Any]:
    store = EventStore(paths)
    state = store.state()
    package = state["aggregates"]["package"].get(package_id)
    if not isinstance(package, dict):
        raise KeyError(f"unknown Package: {package_id}")
    if package.get("lifecycle") == "DRAFT":
        return {
            "status": "already_draft",
            "package_id": package_id,
            "draft_revision": package.get("draftRevision"),
            "event_id": None,
            "detached_experiments": [],
            "interface_written": False,
        }
    version = int(
        state["aggregate_versions"].get(f"package/{package_id}", 0)
    )
    if expected_version is not None and expected_version != version:
        raise ValueError(
            f"expected Package version {expected_version}, current version is {version}"
        )
    event = management.commit_package_reopen_as_draft(
        paths,
        package_id,
        reason=reason,
        expected_version=version,
        actor={"type": "user", "id": actor_id},
        source_document=source_document,
    )
    projection = event.get("_interface_projection")
    if not isinstance(projection, dict):
        projection = {}
    return {
        "status": "reopened_as_draft",
        "package_id": package_id,
        "draft_revision": event["payload"]["record"]["draftRevision"],
        "event_id": event["event_id"],
        "aggregate_version": event["aggregate_version"],
        "detached_experiments": [
            row["aggregate_id"]
            for row in event["payload"]["experiment_unbindings"]
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
    parser.add_argument("--reason", required=True)
    parser.add_argument("--actor-id", required=True)
    parser.add_argument("--source-document")
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
        result = reopen(
            paths,
            package_id=args.package_id,
            reason=args.reason,
            actor_id=args.actor_id,
            source_document=args.source_document,
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
        print(f"draft revision: {result['draft_revision']}")
        print(
            "detached Experiments: "
            + ", ".join(result["detached_experiments"])
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
