#!/usr/bin/env python3
"""Render package page projections and record source revisions."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PIPELINE_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PIPELINE_ROOT))

from lib import package_facts  # noqa: E402


SCRIPT_DIR = Path(__file__).resolve().parent


def _run_renderer(renderer: str, root: Path, pkg: str) -> None:
    subprocess.run(
        [
            sys.executable,
            str(SCRIPT_DIR / renderer),
            "--repo-root",
            str(root),
            "--pkg",
            pkg,
        ],
        check=True,
    )


def _results_sources(pkg: str, root: Path) -> list[str]:
    paths = package_facts.fact_paths(pkg, root=root)
    sources = []
    if (paths.tables_dir / "result_gate.csv").exists():
        sources.append("tables/result_gate.csv")
    sources.extend(f"tables/{path.name}" for path in sorted(paths.tables_dir.glob("result_table_*.csv")))
    return sources


def _tracker_sources(pkg: str, root: Path) -> list[str]:
    paths = package_facts.fact_paths(pkg, root=root)
    sources = []
    if (paths.tables_dir / "live_checks.csv").exists():
        sources.append("tables/live_checks.csv")
    if (paths.tables_dir / "resource_allocation.csv").exists():
        sources.append("tables/resource_allocation.csv")
    return sources


def _record_projection(pkg: str, root: Path, page: str, renderer: str, sources: list[str]) -> None:
    html_path = root / "research_html" / "packages" / pkg / page
    package_facts.record_page_projection(pkg, page, sources, html_path, renderer, root=root)


def render_results(pkg: str, root: Path) -> None:
    renderer = "render_result_facts.py"
    _run_renderer(renderer, root, pkg)
    _record_projection(pkg, root, "results.html", renderer, _results_sources(pkg, root))


def render_tracker(pkg: str, root: Path) -> None:
    renderer = "render_tracker_facts.py"
    _run_renderer(renderer, root, pkg)
    _record_projection(pkg, root, "tracker.html", renderer, _tracker_sources(pkg, root))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--pkg", required=True)
    parser.add_argument("--page", required=True, choices=["all", "results", "tracker"])
    args = parser.parse_args(argv)

    root = Path(args.repo_root)
    page_names = ["results", "tracker"] if args.page == "all" else [args.page]
    try:
        for page in page_names:
            if page == "results":
                render_results(args.pkg, root)
            elif page == "tracker":
                render_tracker(args.pkg, root)
    except (subprocess.CalledProcessError, package_facts.FactError) as exc:
        print(f"render_package_projection: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
