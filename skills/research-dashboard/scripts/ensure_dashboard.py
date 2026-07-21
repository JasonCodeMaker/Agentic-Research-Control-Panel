#!/usr/bin/env python3
"""Build the read-only dashboard projection under .research/interface."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PIPELINE_ROOT = Path(__file__).resolve().parents[3]
if str(PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(PIPELINE_ROOT))

from lib.interface import BuildResult, build_interface  # noqa: E402
from lib.research_state import (  # noqa: E402
    ResearchPaths,
    UnsupportedResearchVersion,
    UpgradeRequired,
)
from lib.research_state.paths import add_research_root_argument  # noqa: E402


def ensure_dashboard(
    workspace: Path | ResearchPaths = Path("."),
    *,
    research_root: str | Path | None = None,
) -> list[Path]:
    """Rebuild the interface for an explicitly initialized workspace."""
    paths = (
        workspace
        if isinstance(workspace, ResearchPaths)
        else ResearchPaths.resolve(
            workspace=workspace,
            research_root=research_root,
        )
    )
    paths.load_version()
    result = build_interface(paths)
    return list(result.files)


def build_dashboard(
    *,
    workspace: str | Path = ".",
    research_root: str | Path | None = None,
) -> BuildResult:
    paths = ResearchPaths.resolve(
        workspace=workspace,
        research_root=research_root,
    )
    paths.load_version()
    return build_interface(paths)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        nargs="?",
        choices=("build",),
        default="build",
        help="projection operation (default: build)",
    )
    parser.add_argument("--workspace", default=".", help="managed project workspace")
    add_research_root_argument(parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = build_dashboard(
            workspace=args.workspace,
            research_root=args.research_root,
        )
    except UpgradeRequired as exc:
        print(str(exc), file=sys.stderr)
        print(
            "Run research-init before building the dashboard; the dashboard "
            "does not initialize or migrate managed state.",
            file=sys.stderr,
        )
        return 2
    except UnsupportedResearchVersion as exc:
        print(f"upgrade-required: {exc}", file=sys.stderr)
        return 2

    print(f"interface_root={result.root}")
    print(f"source_seq={result.source_seq}")
    print(f"source_hash={result.source_hash}")
    print(f"files_written={len(result.files)}")
    for path in result.files:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
