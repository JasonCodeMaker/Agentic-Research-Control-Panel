#!/usr/bin/env python3
"""Enable the state-backed Analysis page and refresh the interface."""

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

from lib.research_state import ResearchPaths, StateQuery  # noqa: E402
import management  # noqa: E402


def enable_analysis(paths: ResearchPaths, package_id: str) -> dict:
    if paths.load_version() is None:
        raise FileNotFoundError(
            f"research state is not initialized at {paths.root}"
        )
    view = StateQuery(paths).analysis(package_id)["data"]
    package = next(
        (row for row in view["packages"] if row["id"] == package_id),
        None,
    )
    if not isinstance(package, dict):
        raise KeyError(f"unknown package: {package_id}")
    pages = list(package.get("pages") or [])
    if "analysis" in pages:
        return {
            "changed": False,
            "package_id": package_id,
            "pages": pages,
            "event_id": None,
            "interface_written": False,
        }
    pages.append("analysis")
    event = management.commit_package_pages(
        paths,
        package_id,
        pages,
        entry_skill="research-analysis",
    )
    return {
        "changed": True,
        "package_id": package_id,
        "pages": pages,
        "event_id": event["event_id"],
        "interface_written": bool(
            event.get("_interface_projection", {}).get("written")
        ),
        "interface_root": event.get("_interface_projection", {}).get("root"),
        "interface_error": event.get("_interface_projection", {}).get("error"),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--research-root")
    parser.add_argument("--package-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = ResearchPaths.resolve(
        workspace=args.workspace,
        research_root=args.research_root,
    )
    try:
        result = enable_analysis(paths, args.package_id)
    except (FileNotFoundError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
