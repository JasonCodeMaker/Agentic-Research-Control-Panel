#!/usr/bin/env python3
"""Dashboard-wide consistency tool for the (category, status) state model.

Reads research_html/data/schema.js + research_html/data/research-packages.js via
the bundled node helper (dump_packages.js) and runs four kinds of checks:

  lint-status     schema compliance per package (category, status, required, forbidden,
                  methodsTried row shape, cross-references)
  lint-evidence   every methodsTried[].evidencePath and lastDecisionEvidencePath
                  resolves (file/dir exists, optional HTML anchor present)
  scan-events     three draft writers for the Learnings Update Protocol:
                    E1 result_gate_verdict_finalized (results.html)
                    E3 status_transition_pending     (tracker.html#chosen-route)
                    E4 adoption_pending              (CLAUDE.md / models/ / trainer/)
  draft-method    print one JSON methodsTried row drafted from a result-gate row
  draft-terminal  print the terminal field block drafted from tracker.html#chosen-route
  all             lint-status + lint-evidence + scan-events for every package
  readiness       research-run admission gate: per the autonomy dial's unattended
                  horizon, every experiment is fanned out to plan/impl/doc/result/tracker
  alignment       task-spine structural alignment over every experiment in a package
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_ROOT = REPO_ROOT / "research_html"
PACKAGES_DIR = DASHBOARD_ROOT / "packages"
DUMP_SCRIPT = DASHBOARD_ROOT / "scripts" / "dump_packages.js"
SCOPE_LOG = REPO_ROOT / "outputs" / "_scope" / "transitions.jsonl"

# EXPERIMENT_VERDICT canonical values (per-experiment gate outcome, SCREAMING_SNAKE).
VERDICTS = {"PASS", "FAIL", "INCONCLUSIVE", "DIAGNOSTIC"}
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _load_package_facts_module():
    parents = Path(__file__).resolve().parents
    candidates = [
        parents[5] if len(parents) > 5 else None,  # source tree
        parents[2] if len(parents) > 2 else None,  # installed dashboard
        Path.cwd(),
    ]
    for root in candidates:
        if root is not None and (root / "lib" / "package_facts").exists():
            sys.path.insert(0, str(root))
            from lib import package_facts
            return package_facts
    raise ImportError("cannot locate lib/package_facts")


package_facts = _load_package_facts_module()
import audit_fact_migration  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# data loading
# ─────────────────────────────────────────────────────────────────────────────

def _node_dump_script(root: Path) -> str:
    data_dir = root / "research_html" / "data"
    return f"""
const fs = require('fs');
global.window = {{}};
global.document = {{ addEventListener: () => {{}} }};
eval(fs.readFileSync({json.dumps(str(data_dir / "schema.js"))}, 'utf8'));
eval(fs.readFileSync({json.dumps(str(data_dir / "research-packages.js"))}, 'utf8'));
process.stdout.write(JSON.stringify({{
  schema: window.RESEARCH_STATUS_SCHEMA || {{}},
  statusFamily: window.RESEARCH_STATUS_FAMILY || {{}},
  contributionSpine: window.RESEARCH_CONTRIBUTION_SPINE || [],
  methodsTriedFields: window.RESEARCH_METHODS_TRIED_FIELDS || [],
  categories: window.RESEARCH_CATEGORIES || [],
  packages: window.RESEARCH_PACKAGES || [],
}}, null, 2));
"""


def load_data(repo_root: Path | None = None) -> dict:
    """Run the node helper and parse its JSON dump."""
    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    dump_script = root / "research_html" / "scripts" / "dump_packages.js"
    cmd = ["node", str(dump_script)] if dump_script.exists() else ["node", "-e", _node_dump_script(root)]
    try:
        out = subprocess.check_output(cmd, text=True)
    except FileNotFoundError:
        sys.exit("error: 'node' is not installed; cannot read the JS data files.")
    except subprocess.CalledProcessError as e:
        sys.exit(f"error: dump_packages.js failed (exit {e.returncode}).")
    return json.loads(out)


# ─────────────────────────────────────────────────────────────────────────────
# violation reporting
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Violation:
    pkg: str
    code: str
    message: str
    severity: str = "error"  # "error" or "warning"

    def render(self) -> str:
        tag = "ERROR" if self.severity == "error" else "WARN "
        return f"  [{tag}] {self.code}: {self.message}"


@dataclass
class Report:
    title: str
    violations: list[Violation] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def add(self, v: Violation) -> None:
        self.violations.append(v)

    def errors(self) -> list[Violation]:
        return [v for v in self.violations if v.severity == "error"]

    def warnings(self) -> list[Violation]:
        return [v for v in self.violations if v.severity == "warning"]

    def render(self, strict: bool = False) -> str:
        out = [f"=== {self.title} ==="]
        by_pkg: dict[str, list[Violation]] = {}
        for v in self.violations:
            by_pkg.setdefault(v.pkg, []).append(v)
        for pkg_id, vs in sorted(by_pkg.items()):
            errs = [v for v in vs if v.severity == "error"]
            warns = [v for v in vs if v.severity == "warning"]
            badge = "X" if errs or (strict and warns) else "ok"
            out.append(f"[{badge}] {pkg_id}")
            for v in vs:
                out.append(v.render())
        for n in self.notes:
            out.append(f"  note: {n}")
        out.append(f"--- errors={len(self.errors())} warnings={len(self.warnings())}")
        return "\n".join(out)


# ─────────────────────────────────────────────────────────────────────────────
# lint-status
# ─────────────────────────────────────────────────────────────────────────────

def field_present(v) -> bool:
    if v is None:
        return False
    if isinstance(v, list):
        return len(v) > 0
    if isinstance(v, str):
        return v.strip() != ""
    return True


def lint_status(data: dict, rules: list | None = None) -> Report:
    """Schema lint per package + cross-package id/dir reconciliation."""
    rep = Report("lint-status — schema compliance")
    schema = data["schema"]
    pkgs = data["packages"]
    spine_ids = {s["id"] for s in (data.get("contributionSpine") or [])}
    pkg_ids = {p["id"] for p in pkgs}
    if rules is None:
        rules = [r for r in load_rules_registry(DASHBOARD_ROOT) if "_malformed" not in r]

    # Per-package schema lint
    for pkg in pkgs:
        pid = pkg.get("id", "(no-id)")
        if not pid or pid == "(no-id)":
            rep.add(Violation(pid, "missing-id", "package has no id", "error"))
            continue
        cat = (pkg.get("category") or "").lower()
        cat_schema = schema.get(cat)
        if not cat_schema:
            rep.add(Violation(pid, "unknown-category", f"category={cat!r} not in schema", "error"))
            continue

        status = pkg.get("status") or pkg.get("workflowState") or ""
        if not status:
            rep.add(Violation(pid, "missing-status", "no status set", "error"))
        elif status not in cat_schema["states"]:
            rep.add(Violation(
                pid, "illegal-status",
                f"status={status!r} not legal for category={cat!r} (legal: {'|'.join(cat_schema['states'])})",
                "error",
            ))

        required_rules = cat_schema.get("required") or {}
        # The _all trio applies to every state except those in _all_exempt
        # (STOPPED is terminal-within-lane and only carries its own fields).
        exempt = status in (required_rules.get("_all_exempt") or [])
        required = [] if exempt else list(required_rules.get("_all") or [])
        if status and required_rules.get(status):
            required.extend(required_rules[status])
        for f in required:
            if not field_present(pkg.get(f)):
                rep.add(Violation(pid, "missing-required", f"field {f!r} required for ({cat}, {status})", "error"))

        for f in (cat_schema.get("forbidden") or []):
            if field_present(pkg.get(f)):
                rep.add(Violation(pid, "forbidden-set", f"field {f!r} must not be set for category={cat!r}", "error"))

        # methodsTried shape
        rows = pkg.get("methodsTried") or []
        if not isinstance(rows, list):
            rep.add(Violation(pid, "methods-not-list", "methodsTried must be an array", "error"))
            rows = []
        for i, r in enumerate(rows):
            for k in ("method", "hypothesis", "gate", "measured", "verdict", "evidencePath"):
                if not r or not field_present(r.get(k)):
                    rep.add(Violation(pid, "method-row-missing-field", f"methodsTried[{i}] missing {k!r}", "error"))
            v = (r or {}).get("verdict")
            if v and str(v).upper() not in VERDICTS:
                rep.add(Violation(pid, "method-row-bad-verdict",
                                  f"methodsTried[{i}] verdict={v!r} not in {sorted(VERDICTS)}", "error"))

        # Binding rules (directive home, now registry rows) + E0 directive-propagation. A binding rule
        # row is a user directive change ("add a rule"); its row shape is lint_rules' job, but adding one
        # must have propagated to the tracker lastAction mirror + registry lastUpdated in the same turn —
        # else the package reads as unchanged (Issue 3: a rule landed with nothing else touched).
        brules = [r for r in rules
                  if r.get("level") == "package" and r.get("pkg") == pid
                  and r.get("kind") == "binding" and r.get("status", "ACTIVE") == "ACTIVE"]
        for r in brules:
            if not field_present(r.get("text")):
                rep.add(Violation(pid, "rule-row-schema",
                                  f"binding rule {r.get('id')} missing 'text'", "error"))
        if brules:
            if not _filled(pkg.get("lastAction")):
                rep.add(Violation(pid, "directive-not-propagated",
                                  "binding rules present but lastAction is unset — a directive change must "
                                  "update the tracker Resume Block in the same turn", "warning"))
            if not _filled(pkg.get("lastUpdated")):
                rep.add(Violation(pid, "directive-not-propagated",
                                  "binding rules present but lastUpdated is unset — a directive change must "
                                  "bump the registry timestamp in the same turn", "warning"))

        # Contribution spine
        cs = pkg.get("contributionSpineFlag")
        if field_present(cs) and cs not in spine_ids:
            rep.add(Violation(pid, "bad-contribution-spine",
                              f"contributionSpineFlag={cs!r} not in schema spine ids", "warning"))

        # Date format
        lu = pkg.get("lastUpdated")
        if field_present(lu) and not ISO_DATE.match(str(lu)):
            rep.add(Violation(pid, "bad-date", f"lastUpdated={lu!r} not in YYYY-MM-DD format", "warning"))

        # Cross references (within the registry)
        for ref_field in ("supersededBy", "promotedTo"):
            ref = pkg.get(ref_field)
            if field_present(ref) and ref not in pkg_ids:
                rep.add(Violation(pid, "stale-xref",
                                  f"{ref_field}={ref!r} does not match any package id", "error"))

        for v in check_scope_provenance(pkg):
            rep.add(v)

    # Cross-package: dir-on-disk ⇄ entry-in-registry
    disk_ids = set()
    if PACKAGES_DIR.exists():
        disk_ids = {p.name for p in PACKAGES_DIR.iterdir() if p.is_dir()}
    for did in sorted(disk_ids - pkg_ids):
        rep.add(Violation(did, "orphan-dir",
                          f"packages/{did}/ exists on disk but has no entry in research-packages.js", "warning"))
    for pid in sorted(pkg_ids - disk_ids):
        # Allowed if pkg.pages == [] (archived to research/<active|archive>/ instead)
        pkg = next((p for p in pkgs if p["id"] == pid), None)
        if pkg and (pkg.get("pages") or []) == []:
            continue
        rep.add(Violation(pid, "missing-dir",
                          f"registry entry has pages but packages/{pid}/ does not exist on disk", "warning"))

    return rep


def read_scope_records() -> list[dict]:
    if not SCOPE_LOG.exists():
        return []
    records = []
    for line in SCOPE_LOG.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def fold_scope(records: list[dict]) -> dict:
    projection = {}
    for rec in records:
        node = rec.get("node")
        if node:
            projection[rec["node_id"]] = node
    return projection


def latest_scope_records(records: list[dict]) -> dict:
    latest = {}
    for rec in records:
        latest[rec["node_id"]] = rec
    return latest


def check_scope_provenance(pkg: dict) -> list[Violation]:
    """Check package links back to committed Scope Direction and Milestones."""
    pid = pkg.get("id", "(no-id)")
    has_scope_link = (
        field_present(pkg.get("sourceDirection")) or
        field_present(pkg.get("sourceTasks")) or
        any(field_present((exp or {}).get("sourceTask")) for exp in (pkg.get("experiments") or []))
    )
    if not has_scope_link:
        return []

    if not SCOPE_LOG.exists():
        return [Violation(pid, "scope-log-missing",
                          f"package carries Scope provenance but {SCOPE_LOG.relative_to(REPO_ROOT)} is missing",
                          "error")]

    records = read_scope_records()
    projection = fold_scope(records)
    latest = latest_scope_records(records)
    violations: list[Violation] = []

    direction_id = pkg.get("sourceDirection")
    if not field_present(direction_id):
        violations.append(Violation(pid, "scope-source-missing",
                                    "sourceDirection is required when experiments carry sourceTask links",
                                    "error"))
        return violations

    direction = projection.get(direction_id)
    if not direction:
        violations.append(Violation(pid, "scope-source-stale",
                                    f"sourceDirection={direction_id!r} not found in Scope projection", "error"))
        return violations
    if direction.get("level") != "direction":
        violations.append(Violation(pid, "scope-source-not-direction",
                                    f"sourceDirection={direction_id!r} has level={direction.get('level')!r}", "error"))
    if direction.get("status") != "ACTIVE":
        violations.append(Violation(pid, "scope-source-inactive",
                                    f"sourceDirection={direction_id!r} has status={direction.get('status')!r}", "error"))

    declared_version = pkg.get("sourceVersion")
    latest_rec = latest.get(direction_id)
    if field_present(declared_version) and latest_rec and str(declared_version) != str(latest_rec.get("scope_version")):
        violations.append(Violation(pid, "scope-source-version-drift",
                                    f"sourceVersion={declared_version!r} but latest Scope version is {latest_rec.get('scope_version')!r}",
                                    "error"))

    active_milestones = {
        node_id for node_id, node in projection.items()
        if node.get("level") == "task"
        and node.get("status") == "ACTIVE"
        and direction_id in (node.get("parents") or [])
    }
    milestone_rows = pkg.get("sourceTasks") or []
    if not isinstance(milestone_rows, list):
        violations.append(Violation(pid, "scope-milestones-not-list",
                                    "sourceTasks must be an array", "error"))
        milestone_rows = []
    declared_milestones = {
        row.get("id") for row in milestone_rows
        if isinstance(row, dict) and field_present(row.get("id"))
    }
    if not declared_milestones:
        violations.append(Violation(pid, "scope-milestones-missing",
                                    "sourceTasks is required for Scope-materialized packages", "error"))

    for mid in sorted(declared_milestones - active_milestones):
        violations.append(Violation(pid, "scope-milestone-stale",
                                    f"sourceTasks id={mid!r} is not an active Task child of {direction_id!r}",
                                    "error"))
    for mid in sorted(active_milestones - declared_milestones):
        violations.append(Violation(pid, "scope-milestone-uncovered",
                                    f"active Scope Milestone {mid!r} is not listed in sourceTasks",
                                    "error"))

    experiments = pkg.get("experiments") or []
    parent_tasks = set()
    for i, exp in enumerate(experiments):
        parent = (exp or {}).get("sourceTask")
        if not field_present(parent):
            violations.append(Violation(pid, "scope-parent-task-missing",
                                        f"experiments[{i}] has no sourceTask", "error"))
            continue
        parent_tasks.add(parent)
        if parent not in declared_milestones:
            violations.append(Violation(pid, "scope-parent-task-stale",
                                        f"experiments[{i}].sourceTask={parent!r} is not in sourceTasks",
                                        "error"))
    for mid in sorted(declared_milestones - parent_tasks):
        violations.append(Violation(pid, "scope-milestone-no-experiment",
                                    f"sourceTask {mid!r} has no experiment row", "error"))

    return violations


# ─────────────────────────────────────────────────────────────────────────────
# lint-evidence
# ─────────────────────────────────────────────────────────────────────────────

ANCHOR_PATTERNS = [
    re.compile(r'id\s*=\s*"([^"]+)"'),
    re.compile(r'data-card\s*=\s*"([^"]+)"'),
    re.compile(r'data-exp-id\s*=\s*"([^"]+)"'),
    re.compile(r'data-section\s*=\s*"([^"]+)"'),
    re.compile(r'data-anchor\s*=\s*"([^"]+)"'),
    re.compile(r'name\s*=\s*"([^"]+)"'),
    re.compile(r'data-field\s*=\s*"([^"]+)"'),
]


def resolve_path(raw: str) -> Path | None:
    """Try a small set of candidate roots and return the first that exists."""
    raw = raw.strip()
    if not raw:
        return None
    candidates = [
        REPO_ROOT / raw,
        DASHBOARD_ROOT / raw,
    ]
    if raw.startswith("research_html/"):
        candidates.append(REPO_ROOT / raw)
    if raw.startswith("/"):
        candidates.append(Path(raw))
    for c in candidates:
        if c.exists():
            return c
    return None


def anchor_exists(file_path: Path, anchor: str) -> bool:
    try:
        text = file_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    for pat in ANCHOR_PATTERNS:
        for m in pat.finditer(text):
            if m.group(1) == anchor:
                return True
    return False


def check_evidence(pkg_id: str, label: str, raw: str) -> list[Violation]:
    vs: list[Violation] = []
    if not raw or not raw.strip():
        return vs
    file_part, _, anchor = raw.partition("#")
    file_part = file_part.strip()
    anchor = anchor.strip()
    resolved = resolve_path(file_part) if file_part else None
    if file_part and resolved is None:
        vs.append(Violation(pkg_id, "evidence-file-missing",
                            f"{label}: file not found at any root: {file_part!r}",
                            "warning"))
        return vs
    if anchor and resolved is not None:
        if resolved.is_dir():
            vs.append(Violation(pkg_id, "evidence-anchor-on-dir",
                                f"{label}: anchor {'#' + anchor!r} given but {file_part!r} is a directory",
                                "error"))
        elif not anchor_exists(resolved, anchor):
            vs.append(Violation(pkg_id, "evidence-anchor-missing",
                                f"{label}: anchor #{anchor!r} not found in {file_part!r}",
                                "error"))
    return vs


def lint_evidence(data: dict) -> Report:
    rep = Report("lint-evidence — evidencePath resolution")
    for pkg in data["packages"]:
        pid = pkg["id"]
        # lastDecisionEvidencePath
        for v in check_evidence(pid, "lastDecisionEvidencePath", pkg.get("lastDecisionEvidencePath") or ""):
            rep.add(v)
        # methodsTried evidence paths
        for i, r in enumerate(methods_tried_rows(pid, pkg)):
            ep = (r or {}).get("evidencePath") or ""
            for v in check_evidence(pid, f"methodsTried[{i}].evidencePath", ep):
                rep.add(v)
    return rep


# ─────────────────────────────────────────────────────────────────────────────
# lint-rules — the unified rules registry (data/rules.js)
# ─────────────────────────────────────────────────────────────────────────────

RULES_PREFIX = "window.RESEARCH_RULES = "
RULE_LEVELS = {"universal", "project", "package"}
RULE_KINDS = {"form", "trust", "constraint", "binding", "lesson"}
RULE_LEVEL_KINDS = {
    "universal": {"form", "trust"},
    "project": {"constraint"},
    "package": {"binding", "lesson"},
}
RULE_STATUSES = {"ACTIVE", "RETIRED", "PROMOTED"}
RULE_REQUIRED = ("id", "level", "kind", "title", "source", "origin", "status", "addedAt")
RULE_CARD_RE = re.compile(r'data-rule="([RT]\d+)"')
RULE_LI_RE = re.compile(r'<li\b[^>]*id=["\']rule-([^"\']+)["\']', re.IGNORECASE)
RULE_FILES = ("html-rules.html", "trustworthy-research-rules.html")


def load_rules_registry(root: Path) -> list:
    """Parse data/rules.js ([] if absent; malformed sentinel row on a bad prefix)."""
    p = Path(root) / "data" / "rules.js"
    if not p.exists():
        return []
    text = p.read_text(encoding="utf-8").strip()
    if not text.startswith(RULES_PREFIX):
        return [{"_malformed": str(p)}]
    try:
        rows = json.loads(text[len(RULES_PREFIX):].rstrip(";"))
    except json.JSONDecodeError:
        return [{"_malformed": str(p)}]
    return rows if isinstance(rows, list) else [{"_malformed": str(p)}]


def painted_rule_slugs(analysis_path: Path) -> set[str]:
    """Slugs currently painted in analysis.html's Rules block."""
    if not analysis_path.exists():
        return set()
    return set(RULE_LI_RE.findall(analysis_path.read_text(encoding="utf-8")))


def lint_rules(root: Path) -> Report:
    """Registry lint: row schema, id uniqueness, pkg resolution, universal-mirror sync."""
    root = Path(root)
    rep = Report("lint-rules — unified rules registry")
    rules = load_rules_registry(root)
    if rules and "_malformed" in rules[0]:
        rep.add(Violation("_registry", "rule-store-malformed",
                          "data/rules.js must start with window.RESEARCH_RULES ="))
        return rep
    seen = set()
    for r in rules:
        rid = r.get("id", "<missing>")
        missing = [f for f in RULE_REQUIRED if not str(r.get(f, "")).strip()]
        if r.get("level") in {"project", "package"}:
            missing.extend(f for f in ("text", "rationale") if not str(r.get(f, "")).strip())
        bad_enum = (r.get("level") not in RULE_LEVELS or r.get("kind") not in RULE_KINDS
                    or r.get("status") not in RULE_STATUSES)
        if missing or bad_enum:
            rep.add(Violation(rid, "rule-row-schema",
                              f"missing={missing} level/kind/status legal={not bad_enum}"))
            continue
        if r["kind"] not in RULE_LEVEL_KINDS[r["level"]]:
            rep.add(Violation(rid, "rule-kind-mismatch",
                              f"level={r['level']} only allows kind={sorted(RULE_LEVEL_KINDS[r['level']])}"))
        if rid in seen:
            rep.add(Violation(rid, "rule-id-duplicate", "duplicate rule id"))
        seen.add(rid)
        if r["level"] == "package":
            pkg = r.get("pkg", "")
            if not pkg or not rid.startswith(pkg + "#"):
                rep.add(Violation(rid, "rule-row-schema", "package rule needs pkg + <pkg>#<slug> id"))
            elif not (root / "packages" / pkg).is_dir():
                rep.add(Violation(rid, "rule-pkg-missing", f"packages/{pkg}/ not found",
                                  severity="warning"))
        if r["status"] == "RETIRED" and not str(r.get("retireReason", "")).strip():
            rep.add(Violation(rid, "rule-row-schema", "RETIRED needs retireReason"))
        if r["status"] == "PROMOTED" and not str(r.get("promotedTo", "")).strip():
            rep.add(Violation(rid, "rule-row-schema", "PROMOTED needs promotedTo"))
    active_lessons: dict[str, set[str]] = {}
    for r in rules:
        if (r.get("level") == "package" and r.get("kind") == "lesson"
                and r.get("status") == "ACTIVE" and "#" in str(r.get("id", ""))):
            active_lessons.setdefault(r.get("pkg", ""), set()).add(r["id"].split("#", 1)[1])
    pkgs = set(active_lessons)
    pkgs.update(p.parent.name for p in (root / "packages").glob("*/analysis.html"))
    for pkg in sorted(p for p in pkgs if p):
        analysis = root / "packages" / pkg / "analysis.html"
        painted = painted_rule_slugs(analysis)
        expected = active_lessons.get(pkg, set())
        for slug in sorted(expected - painted):
            rep.add(Violation(pkg, "rule-paint-drift",
                              f"ACTIVE lesson row #rule-{slug} is not painted in packages/{pkg}/analysis.html"))
        for slug in sorted(painted - expected):
            rep.add(Violation(pkg, "rule-paint-drift",
                              f"painted #rule-{slug} has no ACTIVE lesson row in data/rules.js"))
    # Universal mirror sync against the copied rule files.
    shipped = set()
    for name in RULE_FILES:
        f = root / "rules" / name
        if f.exists():
            shipped |= set(RULE_CARD_RE.findall(f.read_text(encoding="utf-8")))
    mirrored = {r["id"] for r in rules if r.get("origin") == "mirror"}
    for rid in sorted(shipped - mirrored):
        rep.add(Violation(rid, "rule-mirror-drift",
                          "shipped rule card not mirrored — re-run ensure_dashboard.py"))
    for rid in sorted(mirrored - shipped):
        rep.add(Violation(rid, "rule-mirror-drift", "mirror row has no shipped rule card"))
    return rep


# ─────────────────────────────────────────────────────────────────────────────
# scan-events — the three draft writers
# ─────────────────────────────────────────────────────────────────────────────

TR_SPLIT = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL)
TD_SPLIT = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL)
TABLE_GATE = re.compile(
    r'<table[^>]*data-table\s*=\s*"result-gate"[^>]*>(.*?)</table>',
    re.DOTALL,
)
VALIDITY_CHIP = re.compile(r'data-validity\s*=\s*"([^"]+)"')
DATA_FIELD_BLOCK = re.compile(
    r'<div[^>]*data-field\s*=\s*"([^"]+)"[^>]*>(.*?)</div>',
    re.DOTALL,
)


def strip_html(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"&amp;", "&", s)
    s = re.sub(r"&minus;", "-", s)
    s = re.sub(r"&ge;", ">=", s)
    s = re.sub(r"&le;", "<=", s)
    s = re.sub(r"&nbsp;", " ", s)
    s = re.sub(r"&rarr;", "->", s)
    s = re.sub(r"&[a-z]+;", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def validity_to_verdict(text_chip: str, raw: str) -> str:
    """Map the result-gate verdict cell to a methodsTried verdict (EXPERIMENT_VERDICT).

    Matching is case-insensitive so it tolerates both the canonical SCREAMING_SNAKE
    chip/body values and any legacy lowercase residue.
    """
    chip = (text_chip or "").lower()
    body = (raw or "").lower()
    if chip in {"ok", "pass", "valid"} or "pass" in body:
        return "PASS"
    if chip in {"fail", "failed", "result_fail"} or "fail" in body:
        return "FAIL"
    if chip in {"partial", "diagnostic_only", "diagnostic-only", "unmeasured", "missing", "inconclusive"}:
        return "INCONCLUSIVE"
    if "inconclusive" in body or "diagnostic" in body or "pending" in body:
        return "INCONCLUSIVE"
    return "INCONCLUSIVE"


def parse_result_gate(html: str) -> list[dict]:
    """Extract result-gate rows. Each row → dict with the 10 columns by name."""
    m = TABLE_GATE.search(html)
    if not m:
        return []
    block = m.group(1)
    tbody = re.search(r"<tbody[^>]*>(.*?)</tbody>", block, re.DOTALL)
    body = tbody.group(1) if tbody else block
    rows = []
    for tr_html in TR_SPLIT.findall(body):
        tds = TD_SPLIT.findall(tr_html)
        if len(tds) < 9:
            continue
        # Columns per resultsContent() template:
        # 0:Exp ID, 1:Validity, 2:Baseline, 3:PLAN Gate, 4:Observed Metric,
        # 5:Budget, 6:Seed, 7:Artifact, 8:Verdict, 9:Reason
        cells = [strip_html(t) for t in tds]
        chips = [VALIDITY_CHIP.search(t).group(1) if VALIDITY_CHIP.search(t) else "" for t in tds]
        rows.append({
            "exp_id": cells[0],
            "validity_chip": chips[1] if len(chips) > 1 else "",
            "baseline": cells[2] if len(cells) > 2 else "",
            "gate": cells[3] if len(cells) > 3 else "",
            "measured": cells[4] if len(cells) > 4 else "",
            "budget": cells[5] if len(cells) > 5 else "",
            "seed": cells[6] if len(cells) > 6 else "",
            "artifact_chip": chips[7] if len(chips) > 7 else "",
            "verdict_chip": chips[8] if len(chips) > 8 else "",
            "verdict_text": cells[8] if len(cells) > 8 else "",
            "reason": cells[9] if len(cells) > 9 else "",
        })
    return rows


def _repo_root(repo_root: Path | None = None) -> Path:
    return Path(repo_root) if repo_root is not None else REPO_ROOT


def _repo_root_from_package_dir(base_dir: Path) -> Path:
    try:
        return Path(base_dir).resolve().parents[2]
    except IndexError:
        return REPO_ROOT


def package_fact_tables(pid: str, repo_root: Path | None = None) -> dict[str, Path]:
    paths = package_facts.fact_paths(pid, root=_repo_root(repo_root))
    if not paths.tables_dir.exists():
        return {}
    return {path.stem: path for path in sorted(paths.tables_dir.glob("*.csv"))}


def _require_csv_fields(path: Path, rows: list[dict[str, str]], required: set[str]) -> None:
    if rows:
        available = set(rows[0].keys())
    else:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        available = {field.strip().lstrip("\ufeff") for field in lines[0].split(",")} if lines else set()
    missing = sorted(required - available)
    if missing:
        raise package_facts.FactError(f"malformed CSV fact table {path}: missing columns {missing}")


def _csv_result_gate_row(row: dict[str, str]) -> dict[str, str]:
    metric = (row.get("metric") or "").strip()
    value = (row.get("value") or "").strip()
    unit = (row.get("unit") or "").strip()
    measured = ""
    if metric and value:
        measured = f"{metric}={value}{unit}"
    elif value:
        measured = f"{value}{unit}"
    elif metric:
        measured = metric
    verdict = (row.get("verdict") or "").strip()
    return {
        "exp_id": row.get("exp_id", ""),
        "validity_chip": row.get("validity", ""),
        "baseline": row.get("baseline", ""),
        "gate": metric,
        "measured": measured,
        "budget": row.get("budget", ""),
        "seed": row.get("seed", ""),
        "artifact_chip": row.get("source_artifact", ""),
        "artifact": row.get("source_artifact", ""),
        "verdict_chip": verdict,
        "verdict_text": verdict,
        "reason": row.get("reason", ""),
    }


def result_gate_rows(
    pid: str,
    html_fallback: bool = True,
    *,
    repo_root: Path | None = None,
    html: str | None = None,
) -> list[dict]:
    tables = package_fact_tables(pid, repo_root=repo_root)
    gate_csv = tables.get("result_gate")
    if gate_csv is not None:
        rows = package_facts.read_csv_rows(gate_csv)
        _require_csv_fields(gate_csv, rows, {"row_id", "exp_id", "metric", "value", "verdict", "validity"})
        return [_csv_result_gate_row(row) for row in rows]
    if not html_fallback:
        return []
    if html is None:
        path = _repo_root(repo_root) / "research_html" / "packages" / pid / "results.html"
        html = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
    return parse_result_gate(html)


def methods_tried_rows(
    pid: str,
    registry_pkg: dict,
    registry_fallback: bool = True,
    *,
    repo_root: Path | None = None,
) -> list[dict]:
    tables = package_fact_tables(pid, repo_root=repo_root)
    methods_csv = tables.get("methods_tried")
    if methods_csv is not None:
        rows = package_facts.read_csv_rows(methods_csv)
        _require_csv_fields(methods_csv, rows, set(METHODS_COMPAT_FIELDS))
        return _methods_projection_rows(rows)
    if package_facts.is_fact_backed(pid, root=_repo_root(repo_root)):
        return []
    if not registry_fallback:
        return []
    return [
        {field: str((row or {}).get(field, "")) for field in METHODS_COMPAT_FIELDS}
        for row in (registry_pkg.get("methodsTried") or [])
    ]


def pkg_dir(pkg_id: str) -> Path:
    return PACKAGES_DIR / pkg_id


def detect_e1(pkg: dict) -> list[dict]:
    """E1 result_gate_verdict_finalized: drafts for rows that are not yet in methodsTried."""
    pid = pkg["id"]
    pdir = pkg_dir(pid)
    results = pdir / "results.html"
    html = results.read_text(encoding="utf-8", errors="ignore") if results.exists() else ""
    rows = result_gate_rows(pid, html_fallback=bool(html), html=html)
    if not rows:
        return []
    # What's already represented in methodsTried. Match a row as represented when:
    #   - its exp_id token (leading P0/V0/E1/...) appears in any methodsTried.method, OR
    #   - the full exp_id appears as a substring of any methodsTried.method (case-insensitive), OR
    #   - the full exp_id appears as a substring of any methodsTried.measured (covers aggregation).
    method_texts = []
    represented_tokens = set()
    for r in methods_tried_rows(pid, pkg):
        m = (r.get("method") or "")
        measured = (r.get("measured") or "")
        method_texts.append((m.lower(), measured.lower()))
        token = re.match(r"^\s*([A-Za-z][\w-]*?\d[\w-]*)", m)
        if token:
            represented_tokens.add(token.group(1).lower())

    def is_represented(eid: str) -> bool:
        e = eid.lower()
        if e in represented_tokens:
            return True
        for method_l, measured_l in method_texts:
            if e in method_l or e in measured_l:
                return True
        return False
    drafts = []
    for r in rows:
        eid = (r["exp_id"] or "").strip()
        if not eid:
            continue
        # Skip rows still in flight (no decided verdict).
        v_chip = (r["verdict_chip"] or "").lower()
        v_text = (r["verdict_text"] or "").lower()
        if v_chip in {"unmeasured", "missing", ""} and "pending" in v_text + " " + v_chip:
            continue
        # Already represented?
        if is_represented(eid):
            continue
        verdict = validity_to_verdict(r["verdict_chip"], r["verdict_text"])
        # Anchor presence: is there id=<eid> or data-exp-id=<eid> on the row?
        anchor_present = bool(re.search(rf'(id|data-exp-id|data-card)\s*=\s*"{re.escape(eid)}"', html))
        drafts.append({
            "event": "E1 result_gate_verdict_finalized",
            "exp_id": eid,
            "anchor_present": anchor_present,
            "draft": {
                "method": f"{eid} {r['gate'][:60]}".strip(),
                "hypothesis": r["gate"] or "(fill from plan.html)",
                "gate": r["gate"] or "(fill)",
                "measured": r["measured"] or "(fill)",
                "verdict": verdict,
                "evidencePath": f"packages/{pid}/results.html#{eid}" if anchor_present
                                else f"packages/{pid}/results.html   ⚠ anchor id=\"{eid}\" missing — add it first",
            },
            "reason_text": r["reason"],
        })
    return drafts


def detect_e3(pkg: dict) -> dict | None:
    """E3 status_transition_pending: a terminal route is declared but status is not yet terminal.

    The chosen-route panel was folded from the retired next-action.html into
    tracker.html#chosen-route (page-7 canon); read that surface first and fall back to a
    legacy next-action.html for packages scaffolded before the fold.
    """
    pid = pkg["id"]
    pdir = pkg_dir(pid)
    tracker = pdir / "tracker.html"
    legacy = pdir / "next-action.html"
    if tracker.exists():
        fields = {k: strip_html(v) for k, v in DATA_FIELD_BLOCK.findall(tracker.read_text(encoding="utf-8", errors="ignore"))}
        route = (fields.get("chosen-route") or "").lower()
        reason = (fields.get("chosen-route-reason") or "")
        target_state = ""
        verdict = ""
    elif legacy.exists():
        fields = {k: strip_html(v) for k, v in DATA_FIELD_BLOCK.findall(legacy.read_text(encoding="utf-8", errors="ignore"))}
        route = (fields.get("route") or "").lower()
        target_state = (fields.get("target-state") or "")
        reason = (fields.get("reason") or "")
        verdict = (fields.get("verdict") or "")
    else:
        return None
    # Terminal signals: route is TERMINATE (lowercased here), or target_state
    # mentions STOPPED/ADOPTED/WIN_SUPERSEDED.
    terminal_route = ("terminate" in route) or ("adopt" in route) or ("promote" in route)
    cat = (pkg.get("category") or "").lower()
    status = (pkg.get("status") or "").upper()
    if cat in {"success", "fail"}:
        return None
    if cat == "in-progress" and not terminal_route and "STOPPED" not in target_state.upper():
        return None
    # Suggest a destination category + status from the route language.
    is_adoption = ("adopt" in route) or ("promote" in route) or ("adopt" in verdict.lower())
    suggested_cat = "success" if is_adoption else ("fail" if "terminate" in route else None)
    suggested_status = None
    if suggested_cat == "success":
        suggested_status = "ADOPTED_UNCONFIRMED"
    elif suggested_cat == "fail":
        suggested_status = "ARCHIVED"
    return {
        "event": "E3 status_transition_pending",
        "route": route,
        "target_state": target_state,
        "verdict": verdict,
        "suggested_category": suggested_cat,
        "suggested_status": suggested_status,
        "current_category": cat,
        "current_status": status,
        "draft": {
            "category": suggested_cat or "(decide)",
            "status": suggested_status or "(decide)",
            "terminationMessage": (reason[:180] + "…") if len(reason) > 180 else reason or "(distill from tracker.html#chosen-route reason)",
            "adoptionPath": "(fill if adopting — AGENTS.md#current-best, CLAUDE.md#current-best, or downstream pkg id)" if suggested_cat == "success" else None,
        },
        "user_ack_required": True,
    }


def detect_e4(pkg: dict) -> dict | None:
    """E4 adoption_pending: AGENTS.md, CLAUDE.md, or model code newly cites the package."""
    pid = pkg["id"]
    if (pkg.get("category") or "").lower() != "success":
        return None
    if field_present(pkg.get("adoptionPath")):
        return None  # already filled
    # Scan agent context files for the pkg id or any of its checkpoint slugs.
    context_files = [p for p in (REPO_ROOT / "AGENTS.md", REPO_ROOT / "CLAUDE.md") if p.exists()]
    if not context_files:
        return None
    hits = []
    for context_file in context_files:
        text = context_file.read_text(encoding="utf-8", errors="ignore")
        label = context_file.name
        if pid in text:
            hits.append(label)
        # Also try the tag (often the checkpoint slug)
        for r in pkg.get("methodsTried") or []:
            method = r.get("method") or ""
            # Pull a slug-like token (letters/digits/_)
            m = re.search(r"([a-z][a-z0-9_]{6,})", method)
            if m and m.group(1) in text:
                hits.append(f"{label} (mentions {m.group(1)!r})")
    if not hits:
        return None
    return {
        "event": "E4 adoption_pending",
        "hits": hits,
        "draft": {
            "adoptionPath": "AGENTS.md#current-best  (or CLAUDE.md#current-best; cite the exact subsection)",
        },
        "user_ack_required": True,
    }


def scan_events(data: dict, pkg_filter: str | None = None) -> Report:
    rep = Report("scan-events — Learnings Update Protocol drafts")
    for pkg in data["packages"]:
        if pkg_filter and pkg["id"] != pkg_filter:
            continue
        pid = pkg["id"]
        e1s = detect_e1(pkg)
        e3 = detect_e3(pkg)
        e4 = detect_e4(pkg)
        any_event = bool(e1s) or bool(e3) or bool(e4)
        if not any_event:
            rep.notes.append(f"{pid}: no pending events")
            continue
        rep.notes.append(f"{pid}: {len(e1s)} E1, {1 if e3 else 0} E3, {1 if e4 else 0} E4")
        for d in e1s:
            block = "  E1 (verdict finalized) — exp_id=" + d["exp_id"]
            block += " [anchor: " + ("YES" if d["anchor_present"] else "MISSING") + "]"
            block += "\n  draft methodsTried row:\n"
            block += json.dumps(d["draft"], indent=4)
            rep.notes.append(block)
        if e3:
            block = "  E3 (status transition pending) — route=" + (e3["route"] or "(unknown)")
            block += f" current=({e3['current_category']}/{e3['current_status']})"
            block += f" suggested=({e3['suggested_category']}/{e3['suggested_status']})"
            block += "\n  draft terminal block:\n"
            block += json.dumps(e3["draft"], indent=4)
            block += "\n  T1 user ack required."
            rep.notes.append(block)
        if e4:
            block = "  E4 (adoption pending) — hits=" + ", ".join(e4["hits"])
            block += "\n  draft adoption field:\n"
            block += json.dumps(e4["draft"], indent=4)
            block += "\n  T1 user ack required."
            rep.notes.append(block)
    return rep


# ─────────────────────────────────────────────────────────────────────────────
# draft-method / draft-terminal
# ─────────────────────────────────────────────────────────────────────────────

def cmd_draft_method(data: dict, pkg_id: str, anchor: str) -> int:
    pkg = next((p for p in data["packages"] if p["id"] == pkg_id), None)
    if not pkg:
        print(f"error: pkg {pkg_id!r} not in registry", file=sys.stderr)
        return 2
    drafts = detect_e1(pkg)
    match = next((d for d in drafts if d["exp_id"] == anchor), None)
    if not match:
        print(f"no E1 draft found for {pkg_id}#{anchor}", file=sys.stderr)
        print("hint: either the row is already in methodsTried, or the anchor does not exist.", file=sys.stderr)
        return 1
    print(json.dumps(match, indent=2))
    return 0


def cmd_draft_terminal(data: dict, pkg_id: str) -> int:
    pkg = next((p for p in data["packages"] if p["id"] == pkg_id), None)
    if not pkg:
        print(f"error: pkg {pkg_id!r} not in registry", file=sys.stderr)
        return 2
    e3 = detect_e3(pkg)
    if not e3:
        print(f"no E3 draft for {pkg_id} (no terminal route in tracker.html#chosen-route, or status already terminal).",
              file=sys.stderr)
        return 1
    print(json.dumps(e3, indent=2))
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# readiness — research-run admission gate (horizon-by-dial over 5 criteria)
# ─────────────────────────────────────────────────────────────────────────────

PLACEHOLDERS = {"", "unmeasured", "file:function", "tbd", "n/a", "none"}


def _filled(text) -> bool:
    """A surface cell counts as authored when it is not a scaffold placeholder."""
    return (text or "").strip().lower() not in PLACEHOLDERS


def horizon(dial: str | None, experiments: list[dict]) -> list[dict]:
    """The experiments the agent reaches before its next forced human pause.

    SUPERVISED pauses at every gate -> only the runnable frontier. Every other level
    (CHECKPOINTED pauses only at the terminal end-of-direction gate; DEFERRED /
    AUTONOMOUS never pause) -> the whole remaining DAG. Unknown dial -> whole DAG
    (fail-safe: require everything when we cannot prove a human will be present).

    Experiment status is run_execution_status (COMPLETED is matched case-insensitively).
    """
    active = [e for e in experiments if (e.get("status") or "").upper() != "COMPLETED"]
    if (dial or "").upper() == "SUPERVISED":
        done = {e.get("id") for e in experiments if (e.get("status") or "").upper() == "COMPLETED"}
        return [e for e in active if all(a in done for a in (e.get("after") or []))]
    return active


COMPARATOR = re.compile(r"(?:>=|<=|==|!=|>|<)")


def gate_is_compound(gate: str) -> bool:
    """Return True when a gate hides multiple predicates in one task."""
    text = gate or ""
    if ";" in text:
        return True
    if re.search(r"\b(AND|OR)\b", text, re.IGNORECASE):
        return True
    return len(COMPARATOR.findall(text)) >= 2


def check_plan_row(pid: str, e: dict, all_ids: set) -> list[Violation]:
    """C1: the experiment's plan row is complete and well-formed."""
    vs: list[Violation] = []
    eid = e.get("id", "(no-id)")
    for fname in ("purpose", "gate", "output"):
        if not _filled(e.get(fname)):
            vs.append(Violation(pid, "readiness-plan-incomplete",
                                f"{eid}: experiments[].{fname} is blank", "error"))
    purpose = (e.get("purpose") or "").strip()
    if _filled(purpose) and len(purpose.split()) > 12:
        vs.append(Violation(pid, "readiness-purpose-too-long",
                            f"{eid}: purpose is {len(purpose.split())} words (cap 12)", "error"))
    if _filled(e.get("gate")) and gate_is_compound(e.get("gate") or ""):
        vs.append(Violation(pid, "readiness-gate-compound",
                            f"{eid}: gate has multiple predicates; split the phase", "error"))
    for a in (e.get("after") or []):
        if a not in all_ids:
            vs.append(Violation(pid, "readiness-after-unresolved",
                                f"{eid}: after={a!r} resolves to no experiment", "error"))
    return vs


CHANGE_LIST = re.compile(r'data-list\s*=\s*"changes-agent-detail"[^>]*>(.*?)</ul>', re.DOTALL)
LI_SPLIT = re.compile(r"<li[^>]*>(.*?)</li>", re.DOTALL)
FIELD_VAL = re.compile(r'data-field\s*=\s*"([^"]+)"[^>]*>(.*?)<', re.DOTALL)


def parse_change_items(html: str) -> list[dict]:
    """Each <li> under data-list='changes-agent-detail' -> its data-field map."""
    m = CHANGE_LIST.search(html)
    if not m:
        return []
    return [{k: strip_html(v) for k, v in FIELD_VAL.findall(li)}
            for li in LI_SPLIT.findall(m.group(1))]


def check_impl(pid: str, e: dict, items: list[dict]) -> list[Violation]:
    """C2: an experiment that requires code has a filled change card bound to it."""
    if not e.get("requiresCode"):
        return []
    eid = e.get("id", "(no-id)")
    for it in items:
        bound = eid in re.split(r"[,\s]+", it.get("validating-exp", ""))
        if bound and _filled(it.get("code-anchor")) and _filled(it.get("expected-sign")):
            return []
    return [Violation(pid, "readiness-impl-missing",
                      f"{eid}: requiresCode but no change card binds it "
                      f"(validating-exp={eid} with code-anchor + expected-sign filled)", "error")]


def check_doc(pid: str, e: dict, base_dir: Path) -> list[Violation]:
    """C3: a complex experiment's docsAnchor resolves to a real file (and anchor)."""
    if not e.get("complex"):
        return []
    eid = e.get("id", "(no-id)")
    anchor = e.get("docsAnchor") or f"docs/pipeline.html#{eid.lower()}"
    file_part, _, frag = anchor.partition("#")
    target = base_dir / file_part.strip()
    if not target.exists():
        return [Violation(pid, "readiness-doc-missing",
                          f"{eid}: complex but doc {anchor!r} does not resolve", "error")]
    if frag and not anchor_exists(target, frag.strip()):
        return [Violation(pid, "readiness-doc-missing",
                          f"{eid}: complex but anchor #{frag} not found in {file_part}", "error")]
    return []


def check_result_row(pid: str, e: dict, rows: list[dict]) -> list[Violation]:
    """C4: a result-gate row exists with the gate pre-filled (blank value = READY)."""
    eid = e.get("id", "(no-id)")
    row = next((r for r in rows if r.get("exp_id") == eid), None)
    if row is None:
        return [Violation(pid, "readiness-result-row-missing",
                          f"{eid}: no result-gate row scaffolded in results.html", "error")]
    if not _filled(row.get("gate")):
        return [Violation(pid, "readiness-result-gate-blank",
                          f"{eid}: result-gate row present but PLAN gate is blank", "error")]
    return []


TODO_LIST = re.compile(r'data-field\s*=\s*"todo-list"[^>]*>(.*?)</ul>', re.DOTALL)
# The ledger tables the tracker template actually ships. workflow.ts also names an
# implementation-review table as required, but the scaffold does not yet ship it, so
# it is not gated here (tracked as a template-compliance follow-up).
LEDGERS = ("resource-allocation", "live-check")


def check_tracker(pid: str, html: str) -> list[Violation]:
    """C5: tracker has a non-empty checkbox todo list and the three ledger tables."""
    vs: list[Violation] = []
    m = TODO_LIST.search(html)
    items = LI_SPLIT.findall(m.group(1)) if m else []
    if not any(_filled(strip_html(li)) for li in items):
        vs.append(Violation(pid, "readiness-todo-empty",
                            "tracker todo-list has no authored checkbox item", "error"))
    for name in LEDGERS:
        if f'data-table="{name}"' not in html:
            vs.append(Violation(pid, "readiness-ledger-missing",
                                f"tracker is missing the {name} ledger table", "error"))
    return vs


def assess_readiness(pkg: dict, dial: str | None, base_dir: Path) -> Report:
    """Run the full admission gate for one package at a given autonomy dial."""
    pid = pkg.get("id", "(no-id)")
    rep = Report(f"readiness — {pid} @ {dial or 'AUTONOMOUS'}")
    experiments = pkg.get("experiments") or []
    if not experiments:
        rep.add(Violation(pid, "readiness-no-experiments",
                          "package has no experiments[] plan to run", "error"))
        return rep

    def read(name: str) -> str:
        p = base_dir / name
        return p.read_text(encoding="utf-8", errors="ignore") if p.exists() else ""

    impl_items = parse_change_items(read("implementation.html"))
    gate_rows = result_gate_rows(
        pid,
        html_fallback=True,
        repo_root=_repo_root_from_package_dir(base_dir),
        html=read("results.html"),
    )
    for v in check_tracker(pid, read("tracker.html")):
        rep.add(v)

    all_ids = {e.get("id") for e in experiments}
    for e in horizon(dial, experiments):
        for v in check_plan_row(pid, e, all_ids):
            rep.add(v)
        for v in check_impl(pid, e, impl_items):
            rep.add(v)
        for v in check_doc(pid, e, base_dir):
            rep.add(v)
        for v in check_result_row(pid, e, gate_rows):
            rep.add(v)
    return rep


def lint_readiness(data: dict, dial: str | None, pkg_filter: str | None = None) -> Report:
    """CLI wrapper: assess every (filtered) package against PACKAGES_DIR."""
    rep = Report(f"readiness — research-run admission gate @ {dial or 'AUTONOMOUS'}")
    for pkg in data["packages"]:
        if pkg_filter and pkg.get("id") != pkg_filter:
            continue
        for v in assess_readiness(pkg, dial, pkg_dir(pkg["id"])).violations:
            rep.add(v)
    return rep


# ─────────────────────────────────────────────────────────────────────────────
# alignment — task-spine structural lint over every experiment
# ─────────────────────────────────────────────────────────────────────────────

def _alignment(v: Violation) -> Violation:
    return Violation(v.pkg, v.code.replace("readiness-", "alignment-", 1), v.message, v.severity)


def _task_flags_set(e: dict) -> bool:
    return any(k in e for k in ("measures", "requiresCode", "complex"))


def _measures(e: dict) -> bool:
    return bool(e.get("measures", True))


def _exp_status(e: dict) -> str:
    return str(e.get("status") or "").strip().lower()


def result_slot_exists(html: str, eid: str) -> bool:
    table = re.compile(
        r'<table\b(?=[^>]*data-table="[^"]*' + re.escape(eid) + r'[^"]*")'
        r'(?=[^>]*data-exp-id="' + re.escape(eid) + r'")[^>]*>',
        re.DOTALL,
    )
    return bool(table.search(html))


def result_row_block(html: str, eid: str) -> str:
    # Full <tr> including attributes — derived rows carry data-exp-id on the tag itself.
    for m in re.finditer(r"<tr[^>]*>.*?</tr>", html, re.DOTALL):
        tr = m.group(0)
        if f'data-exp-id="{eid}"' in tr or re.search(r'data-field="exp-id"[^>]*>\s*' + re.escape(eid) + r'\s*<', tr):
            return tr
    return ""


def row_has_decided_verdict(row: dict | None) -> bool:
    if not row:
        return False
    chip = str(row.get("verdict_chip") or "").upper()
    text = str(row.get("verdict_text") or "").upper()
    return chip in VERDICTS or text in VERDICTS


def row_is_unmeasured(row: dict | None) -> bool:
    if not row:
        return True
    return not _filled(row.get("measured")) and not row_has_decided_verdict(row)


def change_exp_ids(items: list[dict]) -> set[str]:
    ids: set[str] = set()
    for item in items:
        raw = item.get("validating-exp", "")
        for token in re.split(r"[,\s]+", raw):
            token = token.strip()
            if token and token.lower() not in PLACEHOLDERS:
                ids.add(token)
    return ids


def change_bound(items: list[dict], eid: str) -> bool:
    return eid in change_exp_ids(items)


def todo_bound(html: str, eid: str) -> bool:
    if f'data-exp-id="{eid}"' in html:
        return True
    return bool(re.search(r'<li[^>]*>.*\b' + re.escape(eid) + r'\b.*?</li>', html, re.DOTALL))


def assess_alignment(pkg: dict, base_dir: Path, terminal: bool = False) -> Report:
    pid = pkg.get("id", "(no-id)")
    rep = Report(f"alignment — {pid}")
    experiments = pkg.get("experiments") or []
    if not experiments:
        return rep

    def read(name: str) -> str:
        p = base_dir / name
        return p.read_text(encoding="utf-8", errors="ignore") if p.exists() else ""

    impl_html = read("implementation.html")
    results_html = read("results.html")
    tracker_html = read("tracker.html")
    impl_items = parse_change_items(impl_html)
    gate_rows = result_gate_rows(
        pid,
        html_fallback=True,
        repo_root=_repo_root_from_package_dir(base_dir),
        html=results_html,
    )
    gate_by_id = {r.get("exp_id"): r for r in gate_rows if r.get("exp_id")}
    all_ids = {e.get("id") for e in experiments if e.get("id")}

    for e in experiments:
        eid = e.get("id", "(no-id)")
        # Field caps (purpose/gate/output/after) are always-on; only the flag-keyed
        # derived-block checks below are grandfathered for legacy rows.
        for v in check_plan_row(pid, e, all_ids):
            rep.add(_alignment(v))
        if not _task_flags_set(e):
            rep.add(Violation(pid, "alignment-flags-unset",
                              f"{eid}: no measures/requiresCode/complex flags; legacy row is grandfathered",
                              "warning"))
            continue
        if not todo_bound(tracker_html, str(eid)):
            rep.add(Violation(pid, "alignment-todo-missing",
                              f"{eid}: no tracker to-do item keyed by data-exp-id", "error"))
        if e.get("requiresCode") and not change_bound(impl_items, str(eid)):
            rep.add(Violation(pid, "alignment-impl-missing",
                              f"{eid}: requiresCode but no change card binds validating-exp={eid}", "error"))
        if e.get("complex"):
            for v in check_doc(pid, e, base_dir):
                rep.add(_alignment(v))
        if _measures(e):
            row = gate_by_id.get(eid)
            for v in check_result_row(pid, e, gate_rows):
                rep.add(_alignment(v))
            if not result_slot_exists(results_html, str(eid)):
                rep.add(Violation(pid, "alignment-result-table-missing",
                                  f"{eid}: no predefined result table slot keyed by data-exp-id", "error"))
            status = _exp_status(e)
            if status == "completed" and row_is_unmeasured(row):
                rep.add(Violation(pid, "alignment-status-contradiction",
                                  f"{eid}: status=completed but result-gate row is still unmeasured", "error"))
            if status in {"pending", "queued"} and row_has_decided_verdict(row):
                rep.add(Violation(pid, "alignment-status-contradiction",
                                  f"{eid}: result-gate row has a verdict while status={status}", "error"))
            if terminal and status not in {"skipped", "blocked"} and not row_has_decided_verdict(row):
                rep.add(Violation(pid, "alignment-terminal-unresolved",
                                  f"{eid}: terminal mode requires a resolved verdict or skipped/blocked status",
                                  "error"))
            row_block = result_row_block(results_html, str(eid))
            if row_block and f'data-exp-id="{eid}"' not in row_block:
                rep.add(Violation(pid, "alignment-thread-anchor-missing",
                                  f"{eid}: result-gate row lacks data-exp-id", "warning"))

    for row in gate_rows:
        eid = row.get("exp_id")
        if eid and eid.lower() not in PLACEHOLDERS and eid not in all_ids:
            rep.add(Violation(pid, "alignment-orphan-gate-row",
                              f"result-gate row exp_id={eid!r} resolves to no experiments[] entry", "error"))

    for eid in sorted(change_exp_ids(impl_items) - all_ids):
        rep.add(Violation(pid, "alignment-orphan-change-card",
                          f"change card validating-exp={eid!r} resolves to no experiments[] entry", "error"))

    if any(_task_flags_set(e) for e in experiments):
        for v in check_tracker(pid, tracker_html):
            rep.add(_alignment(v))
    return rep


def lint_alignment(data: dict, pkg_filter: str | None = None, terminal: bool = False) -> Report:
    rep = Report("alignment — task-spine structural lint")
    for pkg in data["packages"]:
        if pkg_filter and pkg.get("id") != pkg_filter:
            continue
        for v in assess_alignment(pkg, pkg_dir(pkg["id"]), terminal=terminal).violations:
            rep.add(v)
    return rep


# ─────────────────────────────────────────────────────────────────────────────
# fact-alignment — JS/CSV package fact projection checks
# ─────────────────────────────────────────────────────────────────────────────

DATA_SOURCE = re.compile(r'data-source\s*=\s*"([^"]+)"')
DATA_SOURCE_ROW = re.compile(r'data-source-row\s*=\s*"([^"]+)"')
DATA_SOURCE_ROW_ELEMENT = re.compile(
    r'<(?P<tag>[a-zA-Z][\w:-]*)\b(?=[^>]*data-source-row\s*=\s*"(?P<ref>[^"]+)")[^>]*>'
    r'(?P<body>.*?)</(?P=tag)>',
    re.DOTALL,
)
METHODS_COMPAT_FIELDS = ["method", "hypothesis", "gate", "measured", "verdict", "evidencePath"]


def _scan_fact_projection_text(
    rep: Report,
    pid: str,
    text: str,
    paths,
    root: Path,
    display_rows: dict[str, set[str]],
) -> bool:
    has_projection = "data-source" in text or "data-source-row" in text
    if not has_projection:
        return False
    for source in DATA_SOURCE.findall(text):
        source_path = paths.package_data_dir / source if source.startswith("tables/") else root / source
        if not source_path.exists():
            rep.add(Violation(pid, "fact-source-missing", f"data-source={source!r} does not exist", "error"))
    for ref in DATA_SOURCE_ROW.findall(text):
        try:
            table_id, row_id = package_facts.split_source_ref(ref)
            row = package_facts.find_row_by_ref(paths.tables_dir, ref)
        except package_facts.FactError as exc:
            rep.add(Violation(pid, "fact-source-row-missing", str(exc), "error"))
            continue
        if row.get("source_type") == "manual" and row.get("verdict") == "PASS":
            rep.add(Violation(pid, "manual-pass-forbidden", f"{table_id}:{row_id} is manual but verdict=PASS", "error"))
    for match in DATA_SOURCE_ROW_ELEMENT.finditer(text):
        display = strip_html(match.group("body"))
        if not _filled(display):
            continue
        try:
            _, row_id = package_facts.split_source_ref(match.group("ref"))
        except package_facts.FactError:
            continue
        display_rows.setdefault(display, set()).add(row_id)
    return True


def _methods_projection_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [{field: row.get(field, "") for field in METHODS_COMPAT_FIELDS} for row in rows]


def _required_projection_pages(paths, facts: dict | None = None) -> list[str]:
    pages = []
    has_result_table = bool(list(paths.tables_dir.glob("result_table_*.csv")))
    has_schema_table = bool(_result_schemas_by_table(facts or {}))
    if (paths.tables_dir / "result_gate.csv").exists() or has_result_table or has_schema_table:
        pages.append("results.html")
    if (paths.tables_dir / "live_checks.csv").exists() or (paths.tables_dir / "resource_allocation.csv").exists():
        pages.append("tracker.html")
    return pages


def _projection_error_code(exc: Exception) -> str:
    text = str(exc)
    if "stale source" in text:
        return "projection-stale-source"
    if "stale html" in text:
        return "projection-stale-html"
    return "projection-metadata-missing"


def _check_duplicate_display_rows(rep: Report, pid: str, display_rows: dict[str, set[str]]) -> None:
    for display, row_ids in sorted(display_rows.items()):
        if len(row_ids) <= 1:
            continue
        rep.add(Violation(
            pid,
            "fact-duplicate-display-row-mismatch",
            f"display {display!r} references multiple row ids: {sorted(row_ids)}",
            "error",
        ))


def _result_table_requires_manifest(path: Path) -> bool:
    return any((row.get("extractor") or "").strip() for row in package_facts.read_csv_rows(path))


def _check_result_table_manifests(rep: Report, pid: str, paths, root: Path, facts: dict) -> None:
    schemas = _result_schemas_by_table(facts)
    for table_path in _result_table_fact_paths(paths, facts):
        if not _result_table_requires_manifest(table_path):
            continue
        exp_id = str((schemas.get(table_path.stem) or {}).get("expId") or table_path.stem.removeprefix("result_table_"))
        manifest = paths.extractors_dir / f"{exp_id}.json"
        expected_csv = str(table_path.relative_to(root))
        if not manifest.exists():
            rep.add(Violation(
                pid,
                "extractor-manifest-missing",
                f"{table_path.relative_to(root)} has extractor rows but {manifest.relative_to(root)} is missing",
                "error",
            ))
            continue
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            rep.add(Violation(pid, "extractor-manifest-malformed", f"{manifest.relative_to(root)}: {exc}", "error"))
            continue
        if payload.get("output_csv") != expected_csv:
            rep.add(Violation(
                pid,
                "extractor-manifest-output-mismatch",
                f"{manifest.relative_to(root)} output_csv={payload.get('output_csv')!r}, expected {expected_csv!r}",
                "error",
            ))


def _result_schemas_by_table(facts: dict) -> dict[str, dict]:
    schemas = facts.get("resultSchemas") or {}
    if isinstance(schemas, list):
        return {str(item.get("tableId") or ""): item for item in schemas if isinstance(item, dict)}
    if isinstance(schemas, dict):
        return {str(item.get("tableId") or ""): item for item in schemas.values() if isinstance(item, dict)}
    return {}


def _result_table_fact_paths(paths, facts: dict) -> list[Path]:
    by_name = {path.name: path for path in sorted(paths.tables_dir.glob("result_table_*.csv"))}
    for table_id in _result_schemas_by_table(facts):
        if not table_id:
            continue
        path = paths.tables_dir / f"{table_id}.csv"
        if path.exists():
            by_name.setdefault(path.name, path)
    return [by_name[name] for name in sorted(by_name)]


def _planned_schema_cell_ids(schema: dict) -> list[str]:
    exp_id = str(schema.get("expId") or "").strip()
    row_axis = schema.get("rowAxis") if isinstance(schema.get("rowAxis"), dict) else {}
    planned_rows = row_axis.get("plannedRows") if isinstance(row_axis.get("plannedRows"), list) else []
    columns = schema.get("columns") if isinstance(schema.get("columns"), list) else []
    planned = []
    for row in planned_rows:
        if not isinstance(row, dict):
            continue
        row_key = str(row.get("key") or "").strip()
        if not row_key:
            continue
        for column in columns:
            if not isinstance(column, dict):
                continue
            column_key = str(column.get("key") or "").strip()
            if column_key:
                planned.append(f"{exp_id}:{row_key}:{column_key}")
    return planned


def _check_result_schemas(rep: Report, pid: str, facts: dict, paths, root: Path) -> None:
    for table_id, schema in sorted(_result_schemas_by_table(facts).items()):
        if not table_id:
            rep.add(Violation(pid, "result-schema-table-missing", f"{schema.get('id', '(no-id)')}: tableId is blank", "error"))
            continue
        table_path = paths.tables_dir / f"{table_id}.csv"
        if not table_path.exists():
            rep.add(Violation(pid, "result-schema-table-missing", f"{table_id}.csv is declared by resultSchemas but missing", "error"))
            continue
        row_ids = {str(row.get("row_id") or "") for row in package_facts.read_csv_rows(table_path)}
        for cell_id in _planned_schema_cell_ids(schema):
            if cell_id not in row_ids:
                rep.add(Violation(
                    pid,
                    "result-schema-cell-missing",
                    f"{cell_id} is declared by {schema.get('id', '(no-id)')} but missing from {table_path.relative_to(root)}",
                    "error",
                ))


def lint_fact_alignment(data: dict, pkg_filter: str | None = None, repo_root: Path | None = None) -> Report:
    root = repo_root or REPO_ROOT
    rep = Report("fact-alignment — JS/CSV fact projection")
    packages = data.get("packages") or []
    for pkg in packages:
        pid = pkg.get("id", "(no-id)")
        if pkg_filter and pid != pkg_filter:
            continue
        paths = package_facts.fact_paths(pid, root=root)
        package_dir = root / "research_html" / "packages" / pid
        try:
            facts = package_facts.load_facts_js(pid, root=root)
        except package_facts.FactError as exc:
            facts = {}
            rep.add(Violation(pid, "fact-js-malformed", str(exc), "error"))
        migration = audit_fact_migration.package_migration_state(pid, root)
        present_tables = ",".join(name for name, present in migration["tables"].items() if present) or "none"
        rep.notes.append(f"{pid}: migration-state={migration['state']} fact-tables={present_tables}")
        saw_projection = False
        display_rows: dict[str, set[str]] = {}
        for page in ("results.html", "tracker.html"):
            html_path = package_dir / page
            if not html_path.exists():
                continue
            text = html_path.read_text(encoding="utf-8", errors="ignore")
            saw_projection = _scan_fact_projection_text(rep, pid, text, paths, root, display_rows) or saw_projection
        _check_duplicate_display_rows(rep, pid, display_rows)

        if package_facts.is_fact_backed(pid, root=root):
            _check_result_schemas(rep, pid, facts, paths, root)
            _check_result_table_manifests(rep, pid, paths, root, facts)
            for page in _required_projection_pages(paths, facts):
                html_path = package_dir / page
                if not html_path.exists():
                    rep.add(Violation(pid, "projection-page-missing", f"{page} is required by package facts", "error"))
                    continue
                text = html_path.read_text(encoding="utf-8", errors="ignore")
                if "data-fact-projection" not in text:
                    rep.add(Violation(pid, "projection-marker-missing", f"{page} lacks data-fact-projection", "error"))
                try:
                    package_facts.assert_page_projection_fresh(pid, page, root=root)
                except package_facts.FactError as exc:
                    rep.add(Violation(pid, _projection_error_code(exc), str(exc), "error"))

        methods_csv = paths.tables_dir / "methods_tried.csv"
        if methods_csv.exists():
            saw_projection = True
            csv_rows = _methods_projection_rows(package_facts.read_csv_rows(methods_csv))
            registry_rows = [
                {field: str((row or {}).get(field, "")) for field in METHODS_COMPAT_FIELDS}
                for row in (pkg.get("methodsTried") or [])
            ]
            if csv_rows != registry_rows:
                rep.add(Violation(pid, "methods-projection-stale",
                                  "research-packages.js methodsTried[] differs from methods_tried.csv",
                                  "error"))

        if not saw_projection and (package_dir / "results.html").exists():
            if facts.get("createdByScaffold"):
                rep.add(Violation(pid, "fact-projection-missing", "scaffolded fact package has no projection", "error"))
            else:
                rep.add(Violation(pid, "fact-no-projection", "no fact-backed result projection found", "warning"))
    return rep


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--strict", action="store_true",
                        help="treat warnings as errors in the exit code")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("lint-status")
    sub.add_parser("lint-evidence")
    sub.add_parser("lint-rules")
    p = sub.add_parser("scan-events"); p.add_argument("--pkg")
    p = sub.add_parser("draft-method"); p.add_argument("pkg_id"); p.add_argument("anchor")
    p = sub.add_parser("draft-terminal"); p.add_argument("pkg_id")
    p = sub.add_parser("all"); p.add_argument("--pkg")
    p = sub.add_parser("readiness"); p.add_argument("--pkg")
    p.add_argument("--dial", default="AUTONOMOUS",
                   help="autonomy dial; sets the unattended horizon (default: AUTONOMOUS = whole DAG)")
    p = sub.add_parser("alignment"); p.add_argument("--pkg"); p.add_argument("--terminal", action="store_true")
    p = sub.add_parser("fact-alignment"); p.add_argument("--pkg"); p.add_argument("--repo-root", type=Path)
    args = parser.parse_args()

    repo_root = args.repo_root if getattr(args, "cmd", "") == "fact-alignment" else None
    data = load_data(repo_root=repo_root)

    def fail(report: Report) -> bool:
        return bool(report.errors()) or (args.strict and bool(report.warnings()))

    if args.cmd == "lint-status":
        rep = lint_status(data)
        print(rep.render(strict=args.strict))
        return 1 if fail(rep) else 0
    if args.cmd == "lint-evidence":
        rep = lint_evidence(data)
        print(rep.render(strict=args.strict))
        return 1 if fail(rep) else 0
    if args.cmd == "lint-rules":
        rep = lint_rules(DASHBOARD_ROOT)
        print(rep.render(strict=args.strict))
        return 1 if fail(rep) else 0
    if args.cmd == "scan-events":
        rep = scan_events(data, pkg_filter=args.pkg)
        print(rep.render(strict=args.strict))
        return 0
    if args.cmd == "draft-method":
        return cmd_draft_method(data, args.pkg_id, args.anchor)
    if args.cmd == "draft-terminal":
        return cmd_draft_terminal(data, args.pkg_id)
    if args.cmd == "readiness":
        rep = lint_readiness(data, args.dial, pkg_filter=args.pkg)
        print(rep.render(strict=args.strict))
        return 1 if fail(rep) else 0
    if args.cmd == "alignment":
        rep = lint_alignment(data, pkg_filter=args.pkg, terminal=args.terminal)
        print(rep.render(strict=args.strict))
        return 1 if fail(rep) else 0
    if args.cmd == "fact-alignment":
        rep = lint_fact_alignment(data, pkg_filter=args.pkg, repo_root=args.repo_root)
        print(rep.render(strict=args.strict))
        return 1 if fail(rep) else 0
    if args.cmd == "all":
        r1 = lint_status(data); print(r1.render(strict=args.strict)); print()
        r2 = lint_evidence(data); print(r2.render(strict=args.strict)); print()
        r3 = scan_events(data, pkg_filter=args.pkg); print(r3.render(strict=args.strict)); print()
        r4 = lint_alignment(data, pkg_filter=args.pkg); print(r4.render(strict=args.strict))
        print()
        r5 = lint_fact_alignment(data, pkg_filter=args.pkg); print(r5.render(strict=args.strict))
        print()
        r6 = lint_rules(DASHBOARD_ROOT); print(r6.render(strict=args.strict))
        return 1 if (fail(r1) or fail(r2) or fail(r4) or fail(r5) or fail(r6)) else 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
