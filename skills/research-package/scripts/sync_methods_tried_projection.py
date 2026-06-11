#!/usr/bin/env python3
"""Sync research-packages.js methodsTried[] from methods_tried.csv."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PIPELINE_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PIPELINE_ROOT))

from lib import package_facts  # noqa: E402


COMPAT_FIELDS = ["method", "hypothesis", "gate", "measured", "verdict", "evidencePath"]


def _skip_string(text: str, i: int) -> int | None:
    if i >= len(text) or text[i] not in ("'", '"'):
        return None
    quote = text[i]
    j = i + 1
    while j < len(text):
        if text[j] == "\\":
            j += 2
            continue
        if text[j] == quote:
            return j + 1
        j += 1
    return j


def _skip_comment(text: str, i: int) -> int | None:
    if text.startswith("//", i):
        newline = text.find("\n", i)
        return len(text) if newline < 0 else newline + 1
    if text.startswith("/*", i):
        end = text.find("*/", i + 2)
        return len(text) if end < 0 else end + 2
    return None


def _find_matching_close(text: str, open_idx: int) -> int:
    open_ch = text[open_idx]
    close_ch = {"{": "}", "[": "]", "(": ")"}[open_ch]
    depth = 0
    i = open_idx
    while i < len(text):
        string_end = _skip_string(text, i)
        if string_end is not None:
            i = string_end
            continue
        comment_end = _skip_comment(text, i)
        if comment_end is not None:
            i = comment_end
            continue
        if text[i] == open_ch:
            depth += 1
        elif text[i] == close_ch:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise package_facts.FactError(f"unbalanced {open_ch!r} in research-packages.js")


def _find_package_block(text: str, pkg: str) -> tuple[int, int] | None:
    pat = re.compile(
        r"\{\s*(?:id|['\"]id['\"])\s*:\s*['\"]" + re.escape(pkg) + r"['\"]",
        re.DOTALL,
    )
    match = pat.search(text)
    if not match:
        return None
    start = match.start()
    return start, _find_matching_close(text, start)


def _find_top_level_field_value(block: str, field: str) -> tuple[int, int] | None:
    if not block or block[0] != "{":
        raise package_facts.FactError("package block must begin with '{'")
    i = 1
    while i < len(block) - 1:
        comment_end = _skip_comment(block, i)
        if comment_end is not None:
            i = comment_end
            continue
        if block[i] in "{[":
            i = _find_matching_close(block, i)
            continue
        match = re.match(
            r"(?:(['\"])([A-Za-z_$][A-Za-z0-9_$]*)\1|([A-Za-z_$][A-Za-z0-9_$]*))\s*:",
            block[i:],
        )
        if match and (match.group(2) or match.group(3)) == field:
            j = i + match.end()
            while j < len(block) and block[j].isspace():
                j += 1
            if j >= len(block):
                return None
            if block[j] in "{[":
                return j, _find_matching_close(block, j)
            string_end = _skip_string(block, j)
            if string_end is not None:
                return j, string_end
            end = j
            while end < len(block) and block[end] not in ",\n}":
                end += 1
            return j, end
        string_end = _skip_string(block, i)
        if string_end is not None:
            i = string_end
            continue
        i += 1
    return None


def _projection_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [{field: row.get(field, "") for field in COMPAT_FIELDS} for row in rows]


def _render_methods_tried(rows: list[dict[str, str]]) -> str:
    return json.dumps(_projection_rows(rows), ensure_ascii=False, indent=6)


def sync_methods_tried_projection(pkg: str, root: Path) -> Path | None:
    paths = package_facts.fact_paths(pkg, root=root)
    methods_csv = paths.tables_dir / "methods_tried.csv"
    if not methods_csv.exists():
        return None

    registry = root / "research_html" / "data" / "research-packages.js"
    text = registry.read_text(encoding="utf-8")
    bounds = _find_package_block(text, pkg)
    if bounds is None:
        raise package_facts.FactError(f"package {pkg} not found in research-packages.js")

    rows = package_facts.read_csv_rows(methods_csv)
    rendered = _render_methods_tried(rows)
    pkg_start, pkg_end = bounds
    block = text[pkg_start:pkg_end]
    field_bounds = _find_top_level_field_value(block, "methodsTried")
    if field_bounds is None:
        insert_at = len(block) - 1
        while insert_at > 0 and block[insert_at - 1] in " \t":
            insert_at -= 1
        new_block = block[:insert_at] + f"\n    methodsTried: {rendered},\n  " + block[insert_at:]
    else:
        value_start, value_end = field_bounds
        new_block = block[:value_start] + rendered + block[value_end:]

    package_facts.atomic_write(registry, text[:pkg_start] + new_block + text[pkg_end:])
    return registry


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo-root", default=".")
    p.add_argument("--pkg", required=True)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.repo_root)
    try:
        updated = sync_methods_tried_projection(args.pkg, root)
    except (OSError, package_facts.FactError) as exc:
        print(f"sync_methods_tried_projection: {exc}", file=sys.stderr)
        return 2

    if updated is None:
        print("methods_tried.csv not found; left methodsTried projection unchanged")
    else:
        print(f"wrote {updated.relative_to(root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
