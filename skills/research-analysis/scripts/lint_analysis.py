#!/usr/bin/env python3
"""Lint the state contract that drives each rendered analysis page."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

PIPELINE_ROOT = Path(__file__).resolve().parents[3]
for candidate in (PIPELINE_ROOT, PIPELINE_ROOT / "lib"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from lib.research_state import ResearchPaths, StateQuery  # noqa: E402


SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
HTML_RE = re.compile(r"<[^>]+>")


def _analysis_rules(
    view: dict[str, Any],
    package_id: str,
) -> list[dict[str, Any]]:
    return [
        row
        for row in view["rules"]
        if isinstance(row, dict)
        and row.get("package_id") == package_id
        and row.get("kind") == "lesson"
        and row.get("status") in {"ACTIVE", "PROMOTED"}
    ]


def lint_package(
    view: dict[str, Any],
    package_id: str,
) -> list[str]:
    errors: list[str] = []
    package = next(
        (row for row in view["packages"] if row.get("id") == package_id),
        None,
    )
    anchor = f"package/{package_id}"
    if not isinstance(package, dict):
        return [f"{anchor}: package does not exist"]
    pages = package.get("pages")
    if not isinstance(pages, list) or "analysis" not in pages:
        errors.append(f"{anchor}.pages: missing analysis")
    insights = package.get("analysisInsights", [])
    if not isinstance(insights, list):
        errors.append(f"{anchor}.analysisInsights: must be a list")
        insights = []
    ids: set[str] = set()
    for index, row in enumerate(insights):
        row_anchor = f"{anchor}.analysisInsights[{index}]"
        if not isinstance(row, dict):
            errors.append(f"{row_anchor}: must be an object")
            continue
        insight_id = str(row.get("id") or "")
        if not SLUG_RE.fullmatch(insight_id):
            errors.append(f"{row_anchor}.id: must be a kebab-case slug")
        elif insight_id in ids:
            errors.append(f"{row_anchor}.id: duplicate {insight_id}")
        ids.add(insight_id)
        if not str(row.get("title") or "").strip():
            errors.append(f"{row_anchor}.title: required")
        if not any(
            str(row.get(field) or "").strip()
            for field in ("lead", "reading", "mechanism")
        ):
            errors.append(
                f"{row_anchor}: requires lead, reading, or mechanism content"
            )
        if not str(row.get("provenance") or "").strip():
            errors.append(f"{row_anchor}.provenance: evidence reference required")
    for rule in _analysis_rules(view, package_id):
        rule_id = str(rule.get("id") or "")
        text = str(rule.get("text") or "")
        if not text.strip():
            errors.append(f"rule/{rule_id}.text: required")
        if HTML_RE.search(text):
            errors.append(f"rule/{rule_id}.text: HTML is not allowed")
        rationale = str(rule.get("rationale") or "")
        if not any(
            insight_id in rationale or f"insight-{insight_id}" in rationale
            for insight_id in ids
        ):
            errors.append(
                f"rule/{rule_id}.rationale: must cite an existing insight id"
            )
    return errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--research-root")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--package-id")
    group.add_argument("--all", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = ResearchPaths.resolve(
        workspace=args.workspace,
        research_root=args.research_root,
    )
    if paths.load_version() is None:
        print(
            f"error: research state is not initialized at {paths.root}",
            file=sys.stderr,
        )
        return 2
    view = StateQuery(paths).analysis(
        None if args.all else str(args.package_id)
    )["data"]
    if args.all:
        package_ids = [
            str(package["id"])
            for package in view["packages"]
        ]
    else:
        package_ids = [args.package_id]
    errors = [
        error
        for package_id in sorted(package_ids)
        for error in lint_package(view, str(package_id))
    ]
    for error in errors:
        print(error)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
