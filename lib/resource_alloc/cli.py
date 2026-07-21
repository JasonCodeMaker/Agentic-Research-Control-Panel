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
from lib.research_state.paths import ResearchPaths, add_research_root_argument  # noqa: E402


class _ArgumentRejected(ValueError):
    pass


class _ResourceArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise _ArgumentRejected(message)


_COMMANDS = {
    "register",
    "list",
    "snapshot",
    "recommend",
    "allocate",
    "link",
    "release",
    "status",
}


def _root_from_raw_argv(argv):
    for index, value in enumerate(argv):
        if value == "--research-root" and index + 1 < len(argv):
            candidate = argv[index + 1]
            if not candidate.startswith("--"):
                return candidate
        if value.startswith("--research-root="):
            return value.split("=", 1)[1]
    return None


def _command_from_raw_argv(argv):
    return next((value for value in argv if value in _COMMANDS), "unknown")


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


def _audit_summary(args):
    """Return only typed resource identifiers, never argv or raw input."""
    summary = {"operation": args.command}
    for source, target in (
        ("server", "server"),
        ("pkg", "package_id"),
        ("exp", "experiment_local_id"),
        ("gpu_count", "gpu_count"),
        ("gpu_type", "gpu_type"),
        ("alloc", "alloc_id"),
        ("run_id", "run_id"),
        ("job_id", "job_id"),
        ("outcome", "outcome"),
    ):
        value = getattr(args, source, None)
        if value is not None:
            summary[target] = value
    gpu_ids = getattr(args, "gpu_ids", None)
    if gpu_ids is not None:
        summary["gpu_ids"] = gpu_ids.split(",")
    return summary


def main(argv=None):
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    parser = _ResourceArgumentParser(description=__doc__)
    add_research_root_argument(parser)
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

    try:
        args = parser.parse_args(raw_argv)
    except _ArgumentRejected:
        root = ResearchPaths.resolve(research_root=_root_from_raw_argv(raw_argv))
        command = _command_from_raw_argv(raw_argv)
        violation = ra.RuleViolation(
            "invalid resource CLI arguments",
            rule="resource-cli-arguments-invalid",
        )
        ra.audit_rejection(
            root,
            command=f"resource-{command}",
            payload={"operation": command},
            error=violation,
            actor={"type": "user", "id": "resource-cli"},
        )
        print(f"REJECTED: {violation}", file=sys.stderr)
        return 2
    root = ResearchPaths.resolve(research_root=args.research_root)

    try:
        if args.command == "register":
            try:
                text = (
                    Path(args.file).read_text(encoding="utf-8")
                    if args.file
                    else sys.stdin.read()
                )
            except OSError as exc:
                raise ra.RuleViolation(
                    "register input file could not be read",
                    rule="resource-register-input-unreadable",
                ) from exc
            try:
                server = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ra.RuleViolation(
                    "register input must be one valid JSON object",
                    rule="resource-register-json-invalid",
                ) from exc
            result = ra.register_server(root, server)
        elif args.command == "list":
            result = ra.load_registry(root)
        elif args.command == "snapshot":
            try:
                gpus = (
                    probe.probe_local()
                    if args.probe
                    else probe.parse_nvidia_smi(
                        Path(args.from_nvidia_smi).read_text(encoding="utf-8")
                    )
                )
            except OSError as exc:
                raise ra.RuleViolation(
                    "probe input file could not be read",
                    rule="resource-probe-input-unreadable",
                ) from exc
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
        ra.audit_rejection(
            root,
            command=f"resource-{args.command}",
            payload=_audit_summary(args),
            error=exc,
            actor={"type": "user", "id": "resource-cli"},
        )
        print(f"REJECTED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
