#!/usr/bin/env python3
"""Create or repair a research_html dashboard from bundled chrome files."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent
DASHBOARD_BUNDLE = SKILL_ROOT / "assets" / "dashboard"
RULE_FILES = ("html-rules.html", "trustworthy-research-rules.html")
HELPER_SCRIPTS = ("render_scope_projection.py",)

# data/research-packages.js stays inline so every new project gets a clean
# minimal inventory — bundling the live file would leak the source project's
# package list into every fresh scaffold.
DATA_JS = """window.RESEARCH_GLOBAL_CONTEXT = {
  objective: "Create trustworthy research progress with explicit hypotheses, measurable claim gates, verified evidence, and one clear next route.",
  dashboardRole: "The dashboard is the reusable research-system protocol and routing surface.",
  successRule: "Success means the package outcome has been adopted into the active method, pipeline, paper, product, or decision record.",
  sourceOfTruth: "Package pages must preserve exact paths, commands, decisions, artifacts, and evidence anchors.",
};

window.RESEARCH_GLOBAL_PROTOCOL = {
  purpose: "Run a trustworthy auto-research pipeline by tying every package to verified evidence and explicit claim gates.",
  objectiveCards: [
    { title: "Project Objective", body: "Every project must define the system-level objective." },
    { title: "Optimization Target", body: "Separate primary evidence from diagnostic evidence and resource-side effects." },
    { title: "Claim Boundary", body: "A claim needs a gate, baseline, budget, repeat status, artifacts, and evaluation protocol." },
  ],
  agentRules: [
    { title: "Build Context First", body: "Read the invocation, project profile, package state, active plan, results, and docs before work." },
    { title: "Runtime Truth Wins", body: "Validate live runs, logs, outputs, summaries, and artifact roots before changing state." },
    { title: "Consult Learnings Before New Directions", body: "Open research_html/learnings.html before proposing a new direction, refinement, or experiment idea, and before promoting a brainstorm package to in-progress. It is the cross-package index of structured methodsTried rows for every adopted win, archived failure, and abandoned brainstorm; reading it first prevents re-deriving a method that already has a recorded verdict." },
  ],
  evidenceGates: [
    { title: "Before Implementation", body: "Ground work in active plan clauses, verified anchors, boundaries, and checks." },
    { title: "Before Launch", body: "Do not launch if purpose, config, command, artifacts, owner, resources, or stop gates are unclear." },
    { title: "Before Results", body: "Record metrics only after artifacts match experiment id, config, and protocol." },
    { title: "Before Success", body: "Move to Success only after adoption into active project state." },
  ],
  routeRules: [
    { route: "run_next_experiment_from_step4", meaning: "Use when the active plan defines the next run." },
    { route: "fix_implementation", meaning: "Use for concrete code or artifact issues." },
    { route: "revise_plan", meaning: "Use when the executable plan changes." },
    { route: "archive_or_stop", meaning: "Use when evidence says the direction should stop or archive." },
    { route: "ask_user", meaning: "Use when a user-level decision blocks progress." },
  ],
  hardConstraints: [
    "Do not infer missing metrics, baselines, paths, commands, or ownership.",
    "Do not promote diagnostic-only evidence as claim support.",
    "Do not compare mismatched budgets, datasets, seeds, or protocols without labeling the comparison diagnostic.",
  ],
};

window.RESEARCH_PROJECT_PROFILE = {};

window.RESEARCH_CATEGORIES = [
  { id: "brainstorm", title: "Brain Storm", summary: "Ideas, audits, reviews, and reference packages.", href: "categories/brainstorm/" },
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
// Terminal-state fields (success / fail / brainstorm-ABANDONED):
//   terminationMessage (≤200 char one-sentence why-this-ended),
//   methodsTried (array of {method, hypothesis, gate, measured, verdict,
//     evidencePath} rows; verdict ∈ {pass, fail, inconclusive}),
//   adoptionPath (success only — where the win was adopted),
//   supersededBy / promotedTo / reopenTrigger (per (category, status)).
// Brainstorm fields: direction, contributionSpineFlag (both required).
// Run `python research_html/scripts/learnings_lint.py all` to verify
// schema compliance and evidencePath resolution across all packages.
window.RESEARCH_PACKAGES = [];
"""

SCOPE_PROJECTION_JSON = "{}\n"
SCOPE_PROJECTION_JS = "window.RESEARCH_SCOPE_PROJECTION = {};\n"


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


def copy_bundled_chrome(root: Path, force: bool) -> list[Path]:
    """Mirror every file under assets/dashboard/ into <root>/."""
    written: list[Path] = []
    if not DASHBOARD_BUNDLE.is_dir():
        raise FileNotFoundError(f"Missing dashboard bundle: {DASHBOARD_BUNDLE}")
    for src in DASHBOARD_BUNDLE.rglob("*"):
        if not src.is_file():
            continue
        rel = src.relative_to(DASHBOARD_BUNDLE)
        dst = root / rel
        if write_if_missing(dst, src, None, force):
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


def ensure_dashboard(root: Path, force: bool) -> list[Path]:
    written: list[Path] = []
    written.extend(copy_bundled_chrome(root, force))
    written.extend(write_data_js(root, force))
    written.extend(write_scope_projection_defaults(root, force))
    written.extend(copy_helper_scripts(root, force))
    written.extend(copy_rule_files(root, force))
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="research_html", help="dashboard root directory")
    parser.add_argument("--force", action="store_true", help="overwrite existing dashboard files")
    args = parser.parse_args()

    root = Path(args.root)
    written = ensure_dashboard(root, args.force)
    print(f"dashboard_root={root}")
    print(f"files_written={len(written)}")
    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
