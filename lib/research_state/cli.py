"""CLI for the unified research-state command and query surface."""

from __future__ import annotations

import argparse
import json
from typing import Any

from .paths import ResearchPaths, UnsupportedResearchVersion, UpgradeRequired
from .query import StateQuery
from .store import CommandRejected, EventStore, LockBusy, ProjectionFailed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="research-state")
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--research-root")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init")
    sub.add_parser("recover").add_argument("--lease-seconds", type=float, default=30.0)

    show = sub.add_parser("show")
    show.add_argument("aggregate_type")
    show.add_argument("aggregate_id", nargs="?")

    context = sub.add_parser("context")
    context.add_argument("package_id")
    context.add_argument("--phase")

    history = sub.add_parser("history")
    history.add_argument("aggregate")

    audit = sub.add_parser("audit")
    audit.add_argument("command_id")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    paths = ResearchPaths.resolve(
        workspace=args.workspace,
        research_root=args.research_root,
    )
    store = EventStore(paths)
    query = StateQuery(paths)
    try:
        if args.command == "init":
            result: Any = {"created": [str(path) for path in store.initialize()]}
        elif args.command == "recover":
            result = store.recover(lease_seconds=args.lease_seconds)
        elif args.command == "show":
            result = query.show(args.aggregate_type, args.aggregate_id)
        elif args.command == "context":
            result = query.context(args.package_id, phase=args.phase)
        elif args.command == "history":
            if "/" not in args.aggregate:
                parser.error("history aggregate must use <type>/<id>")
            aggregate_type, aggregate_id = args.aggregate.split("/", 1)
            result = query.history(aggregate_type, aggregate_id)
        else:
            result = query.audit(args.command_id)
    except (
        CommandRejected,
        LockBusy,
        ProjectionFailed,
        UnsupportedResearchVersion,
        UpgradeRequired,
        KeyError,
        ValueError,
    ) as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": type(exc).__name__,
                    "detail": str(exc),
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 2
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
