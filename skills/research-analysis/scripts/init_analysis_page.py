#!/usr/bin/env python3
"""Initialize an empty `analysis.html` for an existing research package.

Writes the per-package `analysis.html` from this skill's template, then opts
the package into the inventory `pages` array so the package-nav link renders
enabled. Refuses to overwrite an existing analysis page unless `--force` is
passed.

Also verifies (but does not patch) that the dashboard's bundled JS/CSS
registers the analysis slot and the per-page Rules-grid override. If either
is missing, prints a warning telling the user to re-run `/research-dashboard`.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import string
import sys
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = SKILL_DIR / "templates" / "analysis.html"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def fail(message: str) -> "int":
    print(f"error: {message}", file=sys.stderr)
    return 2


def warn(message: str) -> None:
    print(f"warn: {message}", file=sys.stderr)


def find_package_name(packages_js: str, package_id: str) -> str | None:
    """Extract `name: "..."` from the matching package entry in research-packages.js."""
    pattern = re.compile(
        r"id:\s*[\"']" + re.escape(package_id) + r"[\"'][^}]*?name:\s*([\"'])(?P<name>.*?)\1",
        re.DOTALL,
    )
    m = pattern.search(packages_js)
    return m.group("name") if m else None


def package_entry_span(packages_js: str, package_id: str) -> tuple[int, int] | None:
    """Return the (start, end) char span of one inventory object `{ ... }`."""
    needle = f'id: "{package_id}"'
    idx = packages_js.find(needle)
    if idx == -1:
        needle = f"id: '{package_id}'"
        idx = packages_js.find(needle)
    if idx == -1:
        return None
    # Walk back to the nearest unmatched `{`.
    depth = 0
    start = idx
    while start > 0:
        ch = packages_js[start]
        if ch == "}":
            depth += 1
        elif ch == "{":
            if depth == 0:
                break
            depth -= 1
        start -= 1
    # Walk forward from idx to find the matching `}`.
    depth = 0
    end = idx
    while end < len(packages_js):
        ch = packages_js[end]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end += 1
                break
        end += 1
    return start, end


def ensure_pages_has_analysis(packages_js: str, package_id: str) -> tuple[str, bool]:
    """Add `"analysis"` to the package's `pages` array. Returns (new_text, changed)."""
    span = package_entry_span(packages_js, package_id)
    if span is None:
        raise ValueError(f"could not locate inventory entry for {package_id}")
    start, end = span
    block = packages_js[start:end]

    pages_match = re.search(r"pages:\s*\[(?P<list>[^\]]*)\]", block)
    if not pages_match:
        # No pages: key at all — append one after id: line.
        new_block = re.sub(
            r"(id:\s*[\"']" + re.escape(package_id) + r"[\"'],)",
            r'\1\n  pages: ["analysis"],',
            block,
            count=1,
        )
        return packages_js[:start] + new_block + packages_js[end:], True

    pages_inner = pages_match.group("list")
    if re.search(r"[\"']analysis[\"']", pages_inner):
        return packages_js, False

    # Insert "analysis" between "results" and "next-action" if both present,
    # otherwise append at the end of the array.
    new_inner = pages_inner
    if re.search(r"[\"']results[\"']", new_inner) and re.search(r"[\"']next-action[\"']", new_inner):
        new_inner = re.sub(
            r"([\"']results[\"'])(\s*,\s*)([\"']next-action[\"'])",
            r'\1\2"analysis", \3',
            new_inner,
            count=1,
        )
    else:
        if new_inner.strip().endswith(","):
            new_inner = new_inner + ' "analysis"'
        elif new_inner.strip():
            new_inner = new_inner + ', "analysis"'
        else:
            new_inner = '"analysis"'

    new_block = block[:pages_match.start()] + f"pages: [{new_inner}]" + block[pages_match.end():]
    return packages_js[:start] + new_block + packages_js[end:], True


def verify_dashboard(root: Path) -> list[str]:
    """Return a list of dashboard-skill warnings (empty = clean)."""
    issues: list[str] = []
    js_path = root / "assets" / "research.js"
    css_path = root / "assets" / "research.css"

    if js_path.exists():
        js_text = read_text(js_path)
        if 'slug: "analysis"' not in js_text and "slug: 'analysis'" not in js_text:
            issues.append(
                f"{js_path}: STAGE_PAGES does not include `analysis`. "
                f"Re-run /research-dashboard to pull the current dashboard skill."
            )
    else:
        issues.append(f"{js_path}: missing — re-run /research-dashboard.")

    if css_path.exists():
        css_text = read_text(css_path)
        if 'body[data-page="analysis"] #rules' not in css_text:
            issues.append(
                f"{css_path}: missing `body[data-page=\"analysis\"] #rules` override. "
                f"Re-run /research-dashboard."
            )
    else:
        issues.append(f"{css_path}: missing — re-run /research-dashboard.")

    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="path to <project>/research_html")
    parser.add_argument("--package-id", required=True, dest="package_id",
                        help="YYYY-MM-DD-slug under research_html/packages/")
    parser.add_argument("--force", action="store_true",
                        help="overwrite an existing analysis.html")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not (root / "index.html").exists():
        return fail(f"{root}/index.html not found — run /research-dashboard first.")

    package_dir = root / "packages" / args.package_id
    if not (package_dir / "index.html").exists():
        return fail(
            f"{package_dir}/index.html not found — run /research-package for this id first."
        )

    packages_js_path = root / "data" / "research-packages.js"
    if not packages_js_path.exists():
        return fail(f"{packages_js_path} not found.")

    packages_js = read_text(packages_js_path)
    name = find_package_name(packages_js, args.package_id)
    if name is None:
        return fail(
            f"inventory has no entry with id={args.package_id!r}. "
            f"Add the package via /research-package first."
        )

    out_path = package_dir / "analysis.html"
    if out_path.exists() and not args.force:
        return fail(f"{out_path} already exists — pass --force to overwrite.")

    if not TEMPLATE_PATH.exists():
        return fail(f"template missing: {TEMPLATE_PATH}")

    template = read_text(TEMPLATE_PATH)
    rendered = string.Template(template).safe_substitute(
        name=name,
        package_id=args.package_id,
        last_updated=dt.date.today().isoformat(),
    )
    out_path.write_text(rendered, encoding="utf-8")

    new_packages_js, changed = ensure_pages_has_analysis(packages_js, args.package_id)
    if changed:
        packages_js_path.write_text(new_packages_js, encoding="utf-8")

    print(f"package_id={args.package_id}")
    print(f"package_name={name}")
    print(f"analysis_page={out_path}")
    print(f"inventory_pages_updated={changed}")

    issues = verify_dashboard(root)
    for issue in issues:
        warn(issue)

    print("next: add the first insight with `/research-analysis add-insight " + args.package_id + " <slug> <title>`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
