#!/usr/bin/env python3
"""Review or commit one canonical pre-run Package identity rename."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PIPELINE_ROOT = Path(__file__).resolve().parents[3]
for candidate in (
    PIPELINE_ROOT,
    PIPELINE_ROOT / "lib",
    PIPELINE_ROOT / "skills" / "research-op" / "scripts",
):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from lib.research_state import ResearchPaths  # noqa: E402
import management  # noqa: E402


def _add_identity_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--package-id", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--rationale", required=True)
    parser.add_argument("--identity-date")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--research-root")
    sub = parser.add_subparsers(dest="command", required=True)

    review = sub.add_parser("review")
    _add_identity_arguments(review)

    commit = sub.add_parser("commit")
    _add_identity_arguments(commit)
    commit.add_argument("--review-sha256", required=True)
    commit.add_argument("--actor-id", required=True)
    commit.add_argument("--review-id", required=True)
    commit.add_argument("--idempotency-key")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = ResearchPaths.resolve(
        workspace=args.workspace,
        research_root=args.research_root,
    )
    if args.command == "review":
        result = management.prepare_package_identity_rename(
            paths,
            args.package_id,
            args.title,
            args.rationale,
            identity_date=args.identity_date,
        )
    else:
        event = management.rename_package_identity(
            paths,
            args.package_id,
            args.title,
            args.rationale,
            args.review_sha256,
            actor={"type": "user", "id": args.actor_id},
            review_id=args.review_id,
            identity_date=args.identity_date,
            idempotency_key=args.idempotency_key,
        )
        result = {
            "ok": True,
            "event_id": event["event_id"],
            "old_package_id": args.package_id,
            "new_package_id": next(
                participant["aggregate_id"]
                for participant in event["payload"]["participants"]
                if participant.get("aggregate_type") == "package"
                and participant.get("operation") == "put"
            ),
            "interface_projection": event.get("_interface_projection"),
        }
    print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
