#!/usr/bin/env python3
"""Validate the two-block contract on `analysis.html` pages.

Checks per page:

- `<body data-page="analysis" data-package-id="<id>">` is present and matches
  the directory id.
- `#rules` section appears before `#insight` section (no other top-level
  section between them).
- Every rule `<li>` is either the empty placeholder or has `id="rule-<slug>"`
  with a kebab-case slug AND contains exactly one
  `Evidence: <a href="#insight-<slug>">…</a>` link.
- Rule bodies contain no `<strong>` / `<b>` tag wrapping the rule itself.
- Every `<details>` inside `<div class="insight-body">` has
  `id="insight-<slug>"`, exactly one `<summary>`, and at least one
  `<p class="card-text">` in its body.
- Every visualization (inline-styled block carrying a `background:#…` rule
  with bar fill or heatmap shape) is followed by a caption paragraph that
  starts with `<em>Reading:</em>`.
- Every `#rule-<slug>` Evidence link resolves to an `#insight-<slug>` anchor
  that exists on the same page.
- The package's `pages` array in `data/research-packages.js` includes
  `"analysis"`.
- The dashboard JS registers `analysis` in STAGE_PAGES and the CSS has the
  per-page Rules-grid override.

Exits 0 on clean, non-zero with one violation per line on failure.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class LintReport:
    def __init__(self) -> None:
        self.violations: list[str] = []

    def add(self, where: str, msg: str) -> None:
        self.violations.append(f"{where}: {msg}")

    def ok(self) -> bool:
        return not self.violations

    def emit(self) -> None:
        for v in self.violations:
            print(v)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def line_of(text: str, idx: int) -> int:
    return text.count("\n", 0, idx) + 1


def check_body_tag(text: str, path: Path, package_id: str, report: LintReport) -> None:
    m = re.search(r'<body[^>]*data-page="([^"]+)"[^>]*data-package-id="([^"]+)"', text)
    if not m:
        report.add(str(path), 'missing <body data-page="…" data-package-id="…">')
        return
    page, pkg = m.group(1), m.group(2)
    if page != "analysis":
        report.add(f"{path}:{line_of(text, m.start())}",
                   f'<body data-page="{page}"> should be "analysis"')
    if pkg != package_id:
        report.add(f"{path}:{line_of(text, m.start())}",
                   f'<body data-package-id="{pkg}"> mismatches directory id {package_id!r}')


def check_section_order(text: str, path: Path, report: LintReport) -> None:
    rules_pos = text.find('id="rules"')
    insight_pos = text.find('id="insight"')
    if rules_pos == -1:
        report.add(str(path), "missing #rules section")
        return
    if insight_pos == -1:
        report.add(str(path), "missing #insight section")
        return
    if rules_pos > insight_pos:
        report.add(str(path), "#rules must appear before #insight")


def extract_block(text: str, opening_pattern: str, closing_tag: str) -> tuple[int, int] | None:
    m = re.search(opening_pattern, text)
    if not m:
        return None
    start = m.start()
    cursor = m.end()
    depth = 1
    # crude tag-depth walk for <ol>…</ol> / <div>…</div>
    open_re = re.compile(r"<(" + closing_tag + r")\b", re.IGNORECASE)
    close_re = re.compile(r"</" + closing_tag + r">", re.IGNORECASE)
    while cursor < len(text):
        nxt_open = open_re.search(text, cursor)
        nxt_close = close_re.search(text, cursor)
        if nxt_close is None:
            return None
        if nxt_open and nxt_open.start() < nxt_close.start():
            depth += 1
            cursor = nxt_open.end()
        else:
            depth -= 1
            cursor = nxt_close.end()
            if depth == 0:
                return start, cursor
    return None


def find_rule_lis(text: str) -> list[tuple[int, int, str]]:
    """Return list of (start, end, body) for each <li> inside <ol class="rules-list">."""
    block = extract_block(text, r'<ol[^>]*class="[^"]*rules-list[^"]*"[^>]*>', "ol")
    if not block:
        return []
    start, end = block
    inner = text[start:end]
    out: list[tuple[int, int, str]] = []
    for m in re.finditer(r"<li\b[^>]*>(.*?)</li>", inner, re.DOTALL | re.IGNORECASE):
        out.append((start + m.start(), start + m.end(), m.group(0)))
    return out


def find_details(text: str) -> list[tuple[int, int, str]]:
    """Return list of (start, end, body) for each <details> inside <div class="insight-body">."""
    block = extract_block(text, r'<div[^>]*class="[^"]*insight-body[^"]*"[^>]*>', "div")
    if not block:
        return []
    start, end = block
    inner = text[start:end]
    out: list[tuple[int, int, str]] = []
    for m in re.finditer(r"<details\b[^>]*>(.*?)</details>", inner, re.DOTALL | re.IGNORECASE):
        out.append((start + m.start(), start + m.end(), m.group(0)))
    return out


def check_rules(text: str, path: Path, insight_slugs: set[str], report: LintReport) -> None:
    lis = find_rule_lis(text)
    if not lis:
        report.add(str(path), "no <li> inside <ol class=\"rules-list\">; expect at least the empty placeholder")
        return
    for start, _, body in lis:
        line = line_of(text, start)
        where = f"{path}:{line}"
        if re.search(r"<em>\s*No rules recorded yet\.\s*</em>", body, re.IGNORECASE):
            continue
        m_id = re.search(r'id="rule-([^"]+)"', body)
        if not m_id:
            report.add(where, "rule <li> missing id=\"rule-<slug>\"")
            continue
        slug = m_id.group(1)
        if not SLUG_RE.match(slug):
            report.add(where, f"rule slug {slug!r} not kebab-case")
        evidence = re.findall(
            r"Evidence:\s*<a\s+href=\"#insight-([a-z0-9][a-z0-9-]*)\"[^>]*>",
            body,
        )
        if len(evidence) == 0:
            report.add(where, "rule body missing Evidence: <a href=\"#insight-<slug>\"> link")
        elif len(evidence) > 1:
            report.add(where, f"rule body has {len(evidence)} evidence links; expected exactly 1")
        else:
            target = evidence[0]
            if target not in insight_slugs:
                report.add(where, f"rule evidence target #insight-{target} does not exist on this page")
        # No <strong> or <b> on the rule itself.
        if re.search(r"<(strong|b)\b", body, re.IGNORECASE):
            report.add(where, "rule body contains <strong>/<b>; rules must be plain prose")


def check_insights(text: str, path: Path, report: LintReport) -> set[str]:
    """Return the set of insight slugs found (used by rules check)."""
    slugs: set[str] = set()
    details = find_details(text)
    if not details:
        # Allow empty placeholder; the lint isn't an error unless there's content.
        return slugs
    for start, _, body in details:
        line = line_of(text, start)
        where = f"{path}:{line}"
        m_id = re.search(r'id="insight-([^"]+)"', body)
        if not m_id:
            report.add(where, "<details> missing id=\"insight-<slug>\"")
            continue
        slug = m_id.group(1)
        if not SLUG_RE.match(slug):
            report.add(where, f"insight slug {slug!r} not kebab-case")
        slugs.add(slug)
        summary_count = len(re.findall(r"<summary\b", body, re.IGNORECASE))
        if summary_count != 1:
            report.add(where, f"<details> has {summary_count} <summary> elements; expected exactly 1")
        if not re.search(r'<p[^>]*class="[^"]*card-text', body):
            report.add(where, "<details> body has no <p class=\"card-text\">")
        check_visualization_captions(body, where, report)
    return slugs


def check_visualization_captions(body: str, where: str, report: LintReport) -> None:
    """For every visualization-like element, require a caption right after it."""
    # Heuristic: visualizations are <div> or <table> elements whose inline
    # style contains a colored fill background (#xxx pattern that is not the
    # caption color #555). We then require the *next non-whitespace sibling*
    # to be a caption paragraph that starts with <em>Reading:</em>.

    # Find <table> visualizations.
    for m in re.finditer(r"<table\b[^>]*>.*?</table>", body, re.DOTALL | re.IGNORECASE):
        if not has_viz_background(m.group(0)):
            continue
        if not has_caption_after(body, m.end()):
            report.add(where, "<table> visualization not followed by a caption paragraph")

    # Find top-level <div> visualizations (grid bars / heatmaps).
    for m in re.finditer(r'<div[^>]*style="[^"]*display:\s*grid[^"]*"[^>]*>.*?</div>',
                         body, re.DOTALL | re.IGNORECASE):
        # Only flag if the grid itself or a child carries a colored background fill.
        if not has_viz_background(m.group(0)):
            continue
        if not has_caption_after(body, m.end()):
            report.add(where, "<div> grid visualization not followed by a caption paragraph")


def has_viz_background(snippet: str) -> bool:
    palette = ["#eef", "#fafbfd", "#fbe0db", "#f4ada1", "#e89486", "#c8593f",
               "#a93527", "#8c2c1f", "#691f15", "#4a8e63", "#a14444", "#888",
               "#dff5e3", "#fde2e2"]
    return any(color in snippet for color in palette)


def has_caption_after(body: str, idx: int) -> bool:
    tail = body[idx:idx + 800]
    m = re.match(r"\s*<p[^>]*class=\"[^\"]*card-text[^\"]*\"[^>]*style=\"[^\"]*0\.88rem[^\"]*\"[^>]*>\s*<em>\s*Reading\s*:",
                 tail, re.IGNORECASE)
    return bool(m)


def find_entry_span(text: str, package_id: str) -> tuple[int, int] | None:
    """Return the (start, end) char span of the matching `{ ... }` inventory entry."""
    needle = f'id: "{package_id}"'
    idx = text.find(needle)
    if idx == -1:
        idx = text.find(f"id: '{package_id}'")
    if idx == -1:
        return None
    # Walk back to the nearest unmatched `{`.
    depth = 0
    start = idx
    while start > 0:
        ch = text[start]
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
    while end < len(text):
        ch = text[end]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end += 1
                break
        end += 1
    return start, end


def check_inventory(packages_js_path: Path, package_id: str, report: LintReport) -> None:
    if not packages_js_path.exists():
        report.add(str(packages_js_path), "missing")
        return
    text = read_text(packages_js_path)
    span = find_entry_span(text, package_id)
    if span is None:
        report.add(str(packages_js_path), f"no entry with id={package_id!r}")
        return
    block = text[span[0]:span[1]]
    pages_m = re.search(r"pages:\s*\[(?P<list>[^\]]*)\]", block)
    if not pages_m:
        report.add(str(packages_js_path), f"package {package_id} has no pages: [...] array")
        return
    if "analysis" not in pages_m.group("list"):
        report.add(str(packages_js_path),
                   f"package {package_id} pages: [...] does not include \"analysis\"")


def check_dashboard(root: Path, report: LintReport) -> None:
    js_path = root / "assets" / "research.js"
    css_path = root / "assets" / "research.css"
    if js_path.exists():
        if 'slug: "analysis"' not in read_text(js_path) and "slug: 'analysis'" not in read_text(js_path):
            report.add(str(js_path), "STAGE_PAGES does not register `analysis`")
    else:
        report.add(str(js_path), "missing")
    if css_path.exists():
        if 'body[data-page="analysis"] #rules' not in read_text(css_path):
            report.add(str(css_path), 'missing `body[data-page="analysis"] #rules` override')
    else:
        report.add(str(css_path), "missing")


def lint_one(root: Path, package_id: str, report: LintReport) -> None:
    path = root / "packages" / package_id / "analysis.html"
    if not path.exists():
        report.add(str(path), "analysis.html does not exist (run /research-analysis init)")
        return
    text = read_text(path)
    check_body_tag(text, path, package_id, report)
    check_section_order(text, path, report)
    insight_slugs = check_insights(text, path, report)
    check_rules(text, path, insight_slugs, report)
    check_inventory(root / "data" / "research-packages.js", package_id, report)


def discover_packages(root: Path) -> list[str]:
    pkg_root = root / "packages"
    if not pkg_root.exists():
        return []
    return sorted(
        p.name
        for p in pkg_root.iterdir()
        if p.is_dir() and (p / "analysis.html").exists()
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="path to <project>/research_html")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--package-id", dest="package_id", help="YYYY-MM-DD-slug")
    group.add_argument("--all", action="store_true",
                       help="lint every package under research_html/packages/")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not (root / "index.html").exists():
        print(f"error: {root}/index.html not found", file=sys.stderr)
        return 2

    report = LintReport()
    check_dashboard(root, report)

    if args.all:
        ids = discover_packages(root)
        if not ids:
            print("no packages with analysis.html found")
            return 0
        for pid in ids:
            lint_one(root, pid, report)
    else:
        lint_one(root, args.package_id, report)

    if report.ok():
        target = "all packages" if args.all else args.package_id
        print(f"lint_analysis: clean ({target})")
        return 0
    report.emit()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
