#!/usr/bin/env python3
"""CLI for the resource registry/allocator: register|list|snapshot|recommend|allocate|link|release|status."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lib import resource_alloc as ra  # noqa: E402
from lib.resource_alloc import allocate as alc  # noqa: E402
from lib.resource_alloc import probe  # noqa: E402


def _requirement(args):
    req = {"pkg": args.pkg, "exp_id": args.exp, "gpu_count": args.gpu_count}
    if args.gpu_type:
        req["gpu_type"] = args.gpu_type
    if args.min_mem_gb:
        req["min_mem_gb"] = args.min_mem_gb
    if args.min_hours:
        req["min_hours"] = args.min_hours
    if args.tag:
        req["tags"] = args.tag
    return req


def _add_requirement_args(parser):
    parser.add_argument("--pkg", required=True)
    parser.add_argument("--exp", required=True)
    parser.add_argument("--gpu-count", type=int, default=1)
    parser.add_argument("--gpu-type")
    parser.add_argument("--min-mem-gb", type=float)
    parser.add_argument("--min-hours", type=float)
    parser.add_argument("--tag", action="append")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outputs-root", default="outputs")
    sub = parser.add_subparsers(dest="command", required=True)

    register = sub.add_parser("register", help="upsert one server (JSON on stdin or --file)")
    register.add_argument("--file")

    sub.add_parser("list", help="print the registry")

    snapshot = sub.add_parser("snapshot", help="record an availability snapshot for a server")
    snapshot.add_argument("--server", required=True)
    group = snapshot.add_mutually_exclusive_group(required=True)
    group.add_argument("--probe", action="store_true", help="run nvidia-smi on this machine")
    group.add_argument("--from-nvidia-smi", help="file holding remote nvidia-smi query output")

    recommend = sub.add_parser("recommend", help="rank servers for a requirement")
    _add_requirement_args(recommend)

    allocate = sub.add_parser("allocate", help="record an allocation (reject-before-write)")
    allocate.add_argument("--server", required=True)
    allocate.add_argument("--reason", default="")
    allocate.add_argument("--gpu-ids")
    _add_requirement_args(allocate)

    link = sub.add_parser("link", help="bind a run/job id to an open allocation")
    link.add_argument("--alloc", required=True)
    link.add_argument("--run-id")
    link.add_argument("--job-id")

    release = sub.add_parser("release", help="close an open allocation")
    release.add_argument("--alloc", required=True)
    release.add_argument("--outcome", required=True)

    sub.add_parser("status", help="occupancy, snapshot ages, open allocations, leaks")

    args = parser.parse_args(argv)
    root = Path(args.outputs_root)

    try:
        if args.command == "register":
            text = Path(args.file).read_text(encoding="utf-8") if args.file else sys.stdin.read()
            result = ra.register_server(root, json.loads(text))
        elif args.command == "list":
            result = ra.load_registry(root)
        elif args.command == "snapshot":
            gpus = probe.probe_local() if args.probe else probe.parse_nvidia_smi(
                Path(args.from_nvidia_smi).read_text(encoding="utf-8"))
            result = {"path": str(probe.write_snapshot(root, args.server, gpus)), "gpus": gpus}
        elif args.command == "recommend":
            result = alc.recommend(root, _requirement(args))
        elif args.command == "allocate":
            gpu_ids = args.gpu_ids.split(",") if args.gpu_ids else None
            result = alc.allocate(root, args.server, _requirement(args), reason=args.reason, gpu_ids=gpu_ids)
        elif args.command == "link":
            result = alc.link(root, args.alloc, run_id=args.run_id, job_id=args.job_id)
        elif args.command == "release":
            result = alc.release(root, args.alloc, outcome=args.outcome)
        else:
            result = alc.status(root)
    except ra.RuleViolation as exc:
        print(f"REJECTED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
