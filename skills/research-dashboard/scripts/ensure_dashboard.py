#!/usr/bin/env python3
"""Create or repair a research_html dashboard from bundled chrome files."""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent
DASHBOARD_BUNDLE = SKILL_ROOT / "assets" / "dashboard"
RULE_FILES = ("html-rules.html", "trustworthy-research-rules.html")
HELPER_SCRIPTS = ("render_scope_projection.py",)

# data/research-packages.js stays inline so every new project gets a clean
# minimal inventory — bundling the live file would leak the source project's
# package list into every fresh scaffold.
#
# The chrome owns no protocol content (核心问题 #1): the objective renders from
# the Scope SSOT projection, routes from schema.js (NEXT_ROUTE + meanings), and
# binding rules from data/rules.js — each fact has exactly one owning module.
DATA_JS = """window.RESEARCH_PROJECT_PROFILE = {};

window.RESEARCH_CATEGORIES = [
  { id: "brainstorm", title: "Brainstorm", summary: "Pre-package ideas (not packages, not in the SSOT). Convert one or more into a Direction + package.", href: "categories/brainstorm/" },
  { id: "in-progress", title: "In Progress", summary: "Active packages with ongoing implementation, execution, or analysis.", href: "categories/in-progress/" },
  { id: "success", title: "Success", summary: "Packages adopted into the active project system.", href: "categories/success/" },
  { id: "fail", title: "Fail", summary: "Directions judged failed, stopped, or not promotable.", href: "categories/fail/" },
];

window.RESEARCH_TAG_ROLES = {
  brainstorm: { role: "optimization_direction", label: "Optimization direction", meaning: "The research or optimization direction this package explores.", examples: ["metric contract", "data quality"] },
  "in-progress": { role: "current_status", label: "Current status", meaning: "The current execution state or next active workflow status.", examples: ["pilot running", "paused analysis"] },
  success: { role: "adapted_model_part", label: "Adapted model part", meaning: "The model or pipeline part adopted into the active project system.", examples: ["export path", "quality gate"] },
  fail: { role: "failure_reason", label: "Failure reason", meaning: "The core technical reason the direction failed or was not promoted.", examples: ["budget miss", "training collapse"] },
};

// Package object schema. Required-by-(category, status) is enforced by
// data/schema.js; missing required fields render with a ⚠ marker on the
// card. Universal fields (additive, optional unless noted):
//   id (required), name (required), category (required), tag, tagMeaning,
//   status (enum from schema.js — the (category, status) state machine),
//   sourcePath, runtime, detailPath, problem, objective, motivation,
//   hypothesis, noChangeBoundary, activeGate, primaryMetricVsGate,
//   lastDecision, lastDecisionEvidencePath, nextRoute, currentBlocker,
//   lastAction, openRuns, lastUpdated (ISO date), pages, experiments,
//   contributionSpineFlag (id from RESEARCH_CONTRIBUTION_SPINE in schema.js).
// Terminal-state fields (success / fail):
//   terminationMessage (≤200 char one-sentence why-this-ended),
//   methodsTried (array of {method, hypothesis, gate, measured, verdict,
//     evidencePath} rows; verdict ∈ {PASS, FAIL, INCONCLUSIVE, DIAGNOSTIC}),
//   adoptionPath (success only — where the win was adopted),
//   supersededBy / promotedTo / reopenTrigger (per (category, status)).
// Brainstorm is not a package category — pre-package ideas live in
// data/brainstorms.js (window.BRAINSTORMS), rendered on the brainstorm lane.
// Run `python research_html/scripts/learnings_lint.py all` to verify
// schema compliance and evidencePath resolution across all packages.
window.RESEARCH_PACKAGES = [];
"""

SCOPE_PROJECTION_JSON = "{}\n"
SCOPE_PROJECTION_JS = "window.RESEARCH_SCOPE_PROJECTION = {};\n"

# Pre-package idea store for the brainstorm lane. Written inline-empty (like
# research-packages.js) so a fresh scaffold never inherits another project's ideas.
BRAINSTORMS_JS = "window.BRAINSTORMS = [];\n"

# Durable Context Pack core for the Agent Context surface (context.html). Written
# inline-empty; regenerated with real cross-package knowledge by lib/context_pack/build.py.
CONTEXT_CORE_JS = 'window.RESEARCH_CONTEXT_CORE = {"stamp": {}, "sections": []};\n'

RULES_PREFIX = "window.RESEARCH_RULES = "
RULE_CARD_RE = re.compile(
    r'data-rule="([RT]\d+)"[^>]*data-kind="([^"]+)"[\s\S]*?<h3 class="title">([^<]+)</h3>')
RULE_FILE_KIND = {"html-rules.html": "form", "trustworthy-research-rules.html": "trust"}


def mirror_universal_rules(root: Path) -> list[dict]:
    """Parse data-rule cards out of <root>/rules/*.html into write-locked mirror rows."""
    rows = []
    for name, kind in RULE_FILE_KIND.items():
        f = root / "rules" / name
        if not f.exists():
            continue
        for rid, _card_kind, title in RULE_CARD_RE.findall(f.read_text(encoding="utf-8")):
            rows.append({"id": rid, "level": "universal", "kind": kind,
                         "title": title.strip(), "source": f"rules/{name}#{rid}",
                         "origin": "mirror", "status": "ACTIVE", "addedAt": "bundled"})
    return rows


def write_rules_store(root: Path) -> list[Path]:
    """Create/refresh data/rules.js: rebuild the universal mirror, keep all other rows."""
    dst = root / "data" / "rules.js"
    existing = []
    if dst.exists():
        text = dst.read_text(encoding="utf-8").strip()
        if not text.startswith(RULES_PREFIX):
            raise ValueError(f"Refusing to overwrite malformed rules registry: {dst}")
        existing = json.loads(text[len(RULES_PREFIX):].rstrip(";"))
    kept = [r for r in existing if r.get("origin") != "mirror"]
    rows = mirror_universal_rules(root) + kept
    dst.parent.mkdir(parents=True, exist_ok=True)
    new_text = RULES_PREFIX + json.dumps(rows, indent=2, ensure_ascii=False) + ";\n"
    if dst.exists() and dst.read_text(encoding="utf-8") == new_text:
        return []
    dst.write_text(new_text, encoding="utf-8")
    return [dst]


def write_if_missing(path: Path, source: Path | None, text: str | None, force: bool) -> bool:
    """Copy/write a file when it does not already exist (or when force is set)."""
    if path.exists() and not force:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    if source is not None:
        shutil.copyfile(source, path)
    else:
        assert text is not None, "either source or text must be provided"
        path.write_text(text, encoding="utf-8")
    return True


# data/ files that hold project state — never overwritten by --refresh-chrome.
USER_DATA = {"data/research-packages.js", "data/brainstorms.js", "data/context-core.js",
             "data/scope-projection.json", "data/scope-projection.js", "data/rules.js"}


def copy_bundled_chrome(root: Path, force: bool, refresh: bool = False) -> list[Path]:
    """Mirror every file under assets/dashboard/ into <root>/. With refresh,
    chrome files are overwritten but USER_DATA stores are never touched."""
    written: list[Path] = []
    if not DASHBOARD_BUNDLE.is_dir():
        raise FileNotFoundError(f"Missing dashboard bundle: {DASHBOARD_BUNDLE}")
    for src in DASHBOARD_BUNDLE.rglob("*"):
        if not src.is_file():
            continue
        rel = src.relative_to(DASHBOARD_BUNDLE)
        if "__pycache__" in rel.parts or rel.suffix == ".pyc":
            continue
        dst = root / rel
        overwrite = force or (refresh and rel.as_posix() not in USER_DATA)
        if write_if_missing(dst, src, None, overwrite):
            written.append(dst)
    return written


def copy_rule_files(root: Path, force: bool) -> list[Path]:
    """Copy the binding rule HTMLs from the skill's assets/ into <root>/rules/."""
    written: list[Path] = []
    for name in RULE_FILES:
        src = SKILL_ROOT / "assets" / name
        if not src.exists():
            continue
        dst = root / "rules" / name
        if write_if_missing(dst, src, None, force):
            written.append(dst)
    return written


def write_data_js(root: Path, force: bool) -> list[Path]:
    """Write the project-agnostic minimal inventory if missing."""
    written: list[Path] = []
    dst = root / "data" / "research-packages.js"
    if write_if_missing(dst, None, DATA_JS, force):
        written.append(dst)
    return written


def write_brainstorms_store(root: Path, force: bool) -> list[Path]:
    """Write the empty pre-package idea store if missing."""
    written: list[Path] = []
    dst = root / "data" / "brainstorms.js"
    if write_if_missing(dst, None, BRAINSTORMS_JS, force):
        written.append(dst)
    return written


def write_context_core_store(root: Path, force: bool) -> list[Path]:
    """Write the empty durable Context Pack core if missing (Agent Context surface)."""
    written: list[Path] = []
    dst = root / "data" / "context-core.js"
    if write_if_missing(dst, None, CONTEXT_CORE_JS, force):
        written.append(dst)
    return written


def write_scope_projection_defaults(root: Path, force: bool) -> list[Path]:
    """Write empty read-only Scope projection files when missing."""
    written: list[Path] = []
    for rel, text in (
        ("data/scope-projection.json", SCOPE_PROJECTION_JSON),
        ("data/scope-projection.js", SCOPE_PROJECTION_JS),
    ):
        dst = root / rel
        if write_if_missing(dst, None, text, force):
            written.append(dst)
    return written


def copy_helper_scripts(root: Path, force: bool) -> list[Path]:
    """Install project-local helpers that operate on dashboard data."""
    written: list[Path] = []
    for name in HELPER_SCRIPTS:
        src = SKILL_ROOT / "scripts" / name
        if not src.exists():
            continue
        dst = root / "scripts" / name
        if write_if_missing(dst, src, None, force):
            written.append(dst)
    return written


LIVE_PILL = '<a class="pill" href="live.html">Live Runs</a>'
LIVE_NAV_LINK = '<a href="live.html">Live Runs</a>'
SCOPE_PILL = '<a class="pill" href="scope.html">Scope Tree</a>'
SCOPE_NAV_LINK = '<a href="scope.html">Scope Tree</a>'


def ensure_live_nav(root: Path) -> list[Path]:
    """Insert the Live Runs links into a pre-existing index.html that predates live.html."""
    index = root / "index.html"
    if not index.exists():
        return []
    text = index.read_text(encoding="utf-8")
    patched = text
    if LIVE_PILL not in patched and SCOPE_PILL in patched:
        patched = patched.replace(SCOPE_PILL, SCOPE_PILL + "\n        " + LIVE_PILL, 1)
    if LIVE_NAV_LINK not in patched and SCOPE_NAV_LINK in patched:
        patched = patched.replace(SCOPE_NAV_LINK, SCOPE_NAV_LINK + "\n      " + LIVE_NAV_LINK, 1)
    if patched == text:
        return []
    index.write_text(patched, encoding="utf-8")
    return [index]


def ensure_dashboard(root: Path, force: bool, refresh: bool = False) -> list[Path]:
    written: list[Path] = []
    written.extend(copy_bundled_chrome(root, force, refresh))
    written.extend(write_data_js(root, force))
    written.extend(write_brainstorms_store(root, force))
    written.extend(write_context_core_store(root, force))
    written.extend(write_scope_projection_defaults(root, force))
    written.extend(copy_helper_scripts(root, force or refresh))
    written.extend(copy_rule_files(root, force or refresh))
    written.extend(write_rules_store(root))
    written.extend(ensure_live_nav(root))
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="research_html", help="dashboard root directory")
    parser.add_argument("--force", action="store_true", help="overwrite existing dashboard files")
    parser.add_argument("--refresh-chrome", action="store_true",
                        help="overwrite chrome files (index, assets, scripts, rules, schema) "
                             "but never the data/ user stores — the safe upgrade path")
    args = parser.parse_args()

    root = Path(args.root)
    written = ensure_dashboard(root, args.force, args.refresh_chrome)
    print(f"dashboard_root={root}")
    print(f"files_written={len(written)}")
    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
