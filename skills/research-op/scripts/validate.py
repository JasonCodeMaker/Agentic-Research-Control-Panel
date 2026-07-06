"""Pattern B reject-before-write checks.

Each rule is a function `rule_<id>(pkg, op, target, payload) -> Reject | None`.
The dispatcher calls all rules applicable to (op, target) and returns the first
rejection, or None if all pass.
"""

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

PIPELINE_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PIPELINE_ROOT))
sys.path.insert(0, str(PIPELINE_ROOT / "lib"))
import verifier  # noqa: E402
from lib import package_facts  # noqa: E402
sys.path.insert(0, str(PIPELINE_ROOT / "skills" / "research-package" / "scripts"))
import task_spine  # noqa: E402


@dataclass
class Reject:
    rule: str
    file: str | None
    anchor: str | None
    field: str | None
    expected: str
    actual: str
    suggested_fix: str

    def envelope(self, *, op: str, target: str | None, phase: str = "invariant-check") -> dict:
        return {
            "rejected": True,
            "phase": phase,
            "rule": self.rule,
            "file": self.file,
            "anchor": self.anchor,
            "field": self.field,
            "expected": self.expected,
            "actual": self.actual,
            "suggested_fix": self.suggested_fix,
            "op": op,
            "target": target,
        }


# ---- Universal rules ----

def rule_payload_json_valid(pkg: str, op: str, target: str | None, payload_raw: str) -> Reject | None:
    try:
        json.loads(payload_raw)
        return None
    except json.JSONDecodeError as e:
        return Reject(
            rule="payload-json-valid",
            file=None, anchor=None, field="payload",
            expected="valid JSON object",
            actual=f"JSONDecodeError: {e.msg} at pos {e.pos}",
            suggested_fix="Wrap the payload in single quotes and check for missing braces or trailing commas.",
        )


# ---- Per-target rules ----

_METHODSTRIED_FIELDS = {"method", "hypothesis", "gate", "measured", "verdict", "evidencePath"}
_METHODSTRIED_SOURCE_REF_FIELDS = {"method", "hypothesis", "gate"}
_VERDICT_ALLOWED    = {"PASS", "FAIL", "INCONCLUSIVE"}


def _is_fact_backed(pkg: str) -> bool:
    return (Path("research_html") / "data" / "packages" / pkg).exists()


RULE_KINDS_PACKAGE = {"binding", "lesson"}
RULE_REQUIRED_PACKAGE = ("slug", "title", "text", "rationale", "addedAt")
RULE_RESERVED_INSERT_ORIGINS = {"mirror", "selfevolve"}
RULE_HTML_TAG_RE = re.compile(r"<[^>]+>")
FINALIZED_VERDICT_CELL_RE = re.compile(
    r"<t[dh]\b[^>]*>\s*(PASS|FAIL|INCONCLUSIVE|DIAGNOSTIC)\s*</t[dh]>",
    re.IGNORECASE,
)


def rule_rule_universal_writelock(pkg, op, target, payload) -> Reject | None:
    """Universal rules (R/T) ship with the dashboard skill and are immutable in-project."""
    if target != "rule" or payload.get("level") != "universal":
        return None
    return Reject(
        rule="rule-universal-writelock",
        file=None, anchor=None, field="level",
        expected="level in {project, package}",
        actual="level=universal",
        suggested_fix="Universal rules (R/T) are write-locked. Edit the dashboard skill's "
                      "assets and re-run ensure_dashboard.py instead.",
    )


def rule_rule_level_routable(pkg, op, target, payload) -> Reject | None:
    """The package state-gated path only handles level=package; project goes via --pkg _project."""
    if target != "rule" or payload.get("level") in (None, "package", "universal"):
        return None
    return Reject(
        rule="rule-level-routable",
        file=None, anchor=None, field="level",
        expected="level=package on the package path",
        actual=f"level={payload.get('level')}",
        suggested_fix="Project-level rule ops use --pkg _project.",
    )


def rule_rule_store_parseable(pkg, op, target, payload) -> Reject | None:
    """The registry must parse before any package-level rule mutation writes it back."""
    if target != "rule" or op not in ("insert", "update", "delete"):
        return None
    import rules_store
    try:
        rules_store.load_rules(Path("research_html"))
    except rules_store.RuleRowError as e:
        return Reject(
            rule="rule-store-malformed",
            file="research_html/data/rules.js", anchor=None, field=None,
            expected="window.RESEARCH_RULES = <valid JSON array>;",
            actual=str(e),
            suggested_fix="Repair data/rules.js before mutating rules.",
        )
    return None


def rule_rule_required_fields(pkg, op, target, payload) -> Reject | None:
    """Insert needs the full typed row; update/delete need the rule id."""
    if target != "rule":
        return None
    if op == "insert":
        if payload.get("kind") not in RULE_KINDS_PACKAGE:
            return Reject(
                rule="rule-required-fields",
                file=None, anchor=None, field="kind",
                expected=f"kind in {sorted(RULE_KINDS_PACKAGE)}",
                actual=f"kind={payload.get('kind')!r}",
                suggested_fix="Package rules are kind=binding (directives) or kind=lesson (distilled).",
            )
        missing = [f for f in RULE_REQUIRED_PACKAGE if not str(payload.get(f, "")).strip()]
        if missing:
            return Reject(
                rule="rule-required-fields",
                file=None, anchor=None, field=missing[0],
                expected=f"fields {RULE_REQUIRED_PACKAGE}",
                actual=f"missing {missing}",
                suggested_fix="Provide the full typed rule row.",
            )
        slug = payload["slug"]
        if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", slug):
            return Reject(
                rule="rule-required-fields",
                file=None, anchor=None, field="slug",
                expected="kebab-case slug",
                actual=slug,
                suggested_fix="Use a kebab-case slug.",
            )
    elif op in ("update", "delete") and not str(payload.get("id", "")).strip():
        return Reject(
            rule="rule-required-fields",
            file=None, anchor=None, field="id",
            expected="payload.id",
            actual="missing",
            suggested_fix="Name the rule id to mutate.",
        )
    return None


def rule_rule_origin_reserved(pkg, op, target, payload) -> Reject | None:
    """Export-owned origins are created only by their exporters, never by manual inserts."""
    if target != "rule" or op != "insert":
        return None
    origin = payload.get("origin", "user")
    if origin not in RULE_RESERVED_INSERT_ORIGINS:
        return None
    return Reject(
        rule="rule-origin-reserved",
        file=None, anchor=None, field="origin",
        expected="origin omitted or origin=user on the package write path",
        actual=f"origin={origin}",
        suggested_fix="Do not set origin=mirror/selfevolve; those rows are exporter-owned.",
    )


def rule_rule_text_plain(pkg, op, target, payload) -> Reject | None:
    """Rules are data rows with plain prose text; HTML belongs only in renderers."""
    if target != "rule" or op not in ("insert", "update"):
        return None
    if "text" not in payload or not RULE_HTML_TAG_RE.search(str(payload.get("text", ""))):
        return None
    return Reject(
        rule="rule-text-plain",
        file=None, anchor=None, field="text",
        expected="plain natural-language prose with no HTML tags",
        actual="HTML-like tag found",
        suggested_fix="Remove markup from payload.text; renderers escape rule text.",
    )


def rule_rule_lesson_needs_result(pkg, op, target, payload) -> Reject | None:
    """A lesson generalizes a finalized result — require ≥1 verdict chip in results.html (inherits I8)."""
    if target != "rule" or op != "insert" or payload.get("kind") != "lesson":
        return None
    results = Path(f"research_html/packages/{pkg}/results.html")
    text = results.read_text() if results.exists() else ""
    if FINALIZED_VERDICT_CELL_RE.search(text):
        return None
    return Reject(
        rule="rule-lesson-needs-result",
        file=str(results), anchor=None, field=None,
        expected=">=1 finalized result-gate row in results.html",
        actual="no verdict found",
        suggested_fix="Finalize a result first; lessons distill verdicts, not plans.",
    )


def rule_rule_lifecycle_fields(pkg, op, target, payload) -> Reject | None:
    """Lifecycle moves carry their evidence: RETIRED→retireReason, PROMOTED→promotedTo."""
    if target != "rule" or op != "update":
        return None
    if payload.get("status") == "RETIRED" and not str(payload.get("retireReason", "")).strip():
        return Reject(
            rule="rule-lifecycle-fields",
            file=None, anchor=None, field="retireReason",
            expected="retireReason with RETIRED",
            actual="missing",
            suggested_fix="State why the rule is retired.",
        )
    if payload.get("status") == "PROMOTED" and not str(payload.get("promotedTo", "")).strip():
        return Reject(
            rule="rule-lifecycle-fields",
            file=None, anchor=None, field="promotedTo",
            expected="promotedTo with PROMOTED",
            actual="missing",
            suggested_fix="Name the project rule id this promoted to.",
        )
    return None


def rule_rule_origin_immutable(pkg, op, target, payload) -> Reject | None:
    """Hand edits to export-owned rows (mirror/selfevolve) are rejected; the package
    path may only mutate package-level rows."""
    if target != "rule" or op not in ("update", "delete"):
        return None
    rules_js = Path("research_html/data/rules.js")
    if not rules_js.exists():
        return None
    text = rules_js.read_text(encoding="utf-8").strip()
    prefix = "window.RESEARCH_RULES = "
    if not text.startswith(prefix):
        return None
    rows = json.loads(text[len(prefix):].rstrip(";"))
    row = next((r for r in rows if r.get("id") == payload.get("id")), None)
    if row is None:
        return None
    if row.get("origin") in ("mirror", "selfevolve"):
        return Reject(
            rule="rule-origin-immutable",
            file=str(rules_js), anchor=None, field="origin",
            expected="origin in {user, apply, migration}",
            actual=f"origin={row.get('origin')}",
            suggested_fix="Mirror/selfevolve rows are regenerated by their exporters.",
        )
    if row.get("level") != "package":
        return Reject(
            rule="rule-level-routable",
            file=str(rules_js), anchor=None, field="level",
            expected="a package-level rule id on the package path",
            actual=f"level={row.get('level')}",
            suggested_fix="Project-level rule ops use --pkg _project.",
        )
    return None


def rule_methodstried_six_fields(pkg, op, target, payload) -> Reject | None:
    if target != "methodsTried" or op != "insert":
        return None
    if payload.get("source_ref"):
        missing = _METHODSTRIED_SOURCE_REF_FIELDS - set(payload.keys())
        if missing:
            return Reject(
                rule="methodstried-source-ref-fields",
                file=None, anchor=None, field="payload",
                expected=f"keys include {sorted(_METHODSTRIED_SOURCE_REF_FIELDS)} when source_ref is present",
                actual=f"missing={sorted(missing)}",
                suggested_fix="Set source_ref plus method, hypothesis, and gate; measured/verdict/evidencePath come from the source row.",
            )
        return None
    keys = set(payload.keys())
    missing = _METHODSTRIED_FIELDS - keys
    extra   = keys - _METHODSTRIED_FIELDS
    if missing or extra:
        return Reject(
            rule="methodstried-six-fields",
            file=None, anchor=None, field="payload",
            expected=f"keys exactly = {sorted(_METHODSTRIED_FIELDS)}",
            actual=f"missing={sorted(missing)}; extra={sorted(extra)}",
            suggested_fix="Set the payload to exactly the six canonical fields; remove extras, fill missing.",
        )
    return None


def rule_methodstried_verdict_enum(pkg, op, target, payload) -> Reject | None:
    if target != "methodsTried" or op != "insert":
        return None
    if payload.get("source_ref") and "verdict" not in payload:
        return None
    v = payload.get("verdict")
    if v not in _VERDICT_ALLOWED:
        return Reject(
            rule="methodstried-verdict-enum",
            file=None, anchor=None, field="verdict",
            expected=f"one of {sorted(_VERDICT_ALLOWED)}",
            actual=repr(v),
            suggested_fix="Set verdict to PASS / FAIL / INCONCLUSIVE. Single-seed PASS is INCONCLUSIVE until multi-seed gate is met.",
        )
    return None


def rule_methodstried_fact_backed_requires_source_ref(pkg, op, target, payload) -> Reject | None:
    if target != "methodsTried" or op != "insert":
        return None
    if payload.get("source_ref") or not _is_fact_backed(pkg):
        return None
    return Reject(
        rule="fact-backed-methodstried-requires-source-ref",
        file=f"research_html/data/packages/{pkg}/tables/methods_tried.csv",
        anchor=None,
        field="source_ref",
        expected="source_ref pointing at a fact CSV row",
        actual="manual methodsTried row for a fact-backed package",
        suggested_fix="Insert the witnessing result row first, then append methodsTried with source_ref.",
    )


def rule_methodstried_evidence_resolves(pkg, op, target, payload) -> Reject | None:
    if target != "methodsTried" or op != "insert":
        return None
    if payload.get("source_ref"):
        return None
    ep = payload.get("evidencePath", "")
    if "#" in ep:  # HTML anchor
        page, anchor = ep.split("#", 1)
        path = Path("research_html") / "packages" / pkg / page
        if not path.exists():
            return Reject(
                rule="methodstried-evidence-resolves",
                file=str(path), anchor=anchor, field="evidencePath",
                expected="page file exists",
                actual="page file not on disk",
                suggested_fix=f"Create {path} first, or correct the evidencePath.",
            )
        text = path.read_text()
        if f'id="{anchor}"' not in text and f"id='{anchor}'" not in text:
            return Reject(
                rule="methodstried-evidence-resolves",
                file=str(path), anchor=anchor, field="evidencePath",
                expected=f"#{anchor} anchor exists in page",
                actual=f"#{anchor} not found in {path.name}",
                suggested_fix=f"Add the anchor to {page} or correct the evidencePath slug.",
            )
        return None
    # File path
    if not Path(ep).exists():
        return Reject(
            rule="methodstried-evidence-resolves",
            file=ep, anchor=None, field="evidencePath",
            expected="file exists on disk",
            actual=f"{ep} not found",
            suggested_fix="Verify the file path is correct and the artifact landed before recording the row.",
        )
    return None


def rule_methodstried_manual_pass_forbidden(pkg, op, target, payload) -> Reject | None:
    if target != "methodsTried" or op != "insert":
        return None
    if payload.get("source_ref"):
        return None
    if _is_fact_backed(pkg) and payload.get("verdict") == "PASS":
        return Reject(
            rule="manual-pass-forbidden",
            file=None, anchor=None, field="verdict",
            expected="source_ref-backed PASS for fact-backed packages",
            actual="manual methodsTried verdict=PASS",
            suggested_fix="Provide source_ref to a result CSV row or record the manual row as INCONCLUSIVE.",
        )
    return None




# ---- Result-gate row rules ----

_RESULT_GATE_FIELDS = {
    "exp_id", "validity", "baseline", "plan_gate", "observed_metric",
    "budget_use", "seed_status", "artifact_completeness", "verdict", "reason",
}
_VALIDITY_ALLOWED = package_facts.VALID_RESULT_VALIDITY
_OBJECTIVE_CONTRACT_FIELDS = {"hypothesisOneLine", "metric", "baseline", "budget", "successPredicate"}
_RESULT_GATE_UPDATE_FIELDS = {
    "validity", "baseline", "plan-gate", "observed-metric", "budget-use",
    "seed-status", "artifact-completeness", "verdict", "reason",
}


def rule_result_gate_ten_cols(pkg, op, target, payload) -> Reject | None:
    """All 10 result-gate columns must be present."""
    if target != "results-gate-row" or op != "insert":
        return None
    missing = _RESULT_GATE_FIELDS - set(payload.keys())
    if missing:
        return Reject(
            rule="result-gate-ten-cols",
            file=None, anchor=None, field="payload",
            expected=f"keys include {sorted(_RESULT_GATE_FIELDS)}",
            actual=f"missing={sorted(missing)}",
            suggested_fix="Add the missing column(s) to the payload.",
        )
    return None


def rule_result_gate_validity_enum(pkg, op, target, payload) -> Reject | None:
    """validity must use the canonical fact-layer RESULT_VALIDITY enum."""
    if target != "results-gate-row" or op != "insert":
        return None
    v = payload.get("validity")
    if v not in _VALIDITY_ALLOWED:
        return Reject(
            rule="result-gate-validity-enum",
            file=None, anchor=None, field="validity",
            expected=f"one of {sorted(_VALIDITY_ALLOWED)}",
            actual=repr(v),
            suggested_fix=f"Set validity to one of {sorted(_VALIDITY_ALLOWED)}.",
        )
    return None


def rule_fact_backed_projection_write(pkg, op, target, payload) -> Reject | None:
    if not _is_fact_backed(pkg):
        return None
    if (op, target) not in {
        ("insert", "results-block"),
        ("update", "results-gate-row"),
        ("update", "results-verdict"),
        ("update", "results-block"),
    }:
        return None
    return Reject(
        rule="fact-backed-projection-write",
        file=None,
        anchor=None,
        field="target",
        expected="CSV/JS fact write followed by projection renderer",
        actual=f"{op}:{target}",
        suggested_fix="Update package facts and re-render the projection instead of mutating results.html directly.",
    )


def rule_experiments_update_payload(pkg, op, target, payload) -> Reject | None:
    """Updating an experiments[] row requires an id plus a full replacement row with the same id."""
    if target != "experiments-row" or op != "update":
        return None
    exp_id = payload.get("id")
    row = payload.get("row")
    if not exp_id or not isinstance(row, dict):
        return Reject(
            rule="experiments-update-payload",
            file=None, anchor=None, field="payload",
            expected="payload has non-empty id and row object",
            actual=f"id={exp_id!r}, row_type={type(row).__name__}",
            suggested_fix='Use {"id":"P0","row":{"id":"P0", ...}}.',
        )
    if row.get("id") != exp_id:
        return Reject(
            rule="experiments-update-id-match",
            file=None, anchor=None, field="row.id",
            expected=f"row.id matches id={exp_id!r}",
            actual=repr(row.get("id")),
            suggested_fix="Set payload.row.id to the same experiment id being replaced.",
        )
    return None


def rule_objective_contract_update_payload(pkg, op, target, payload) -> Reject | None:
    """objectiveContract can be replaced as a whole or one known field at a time."""
    if target != "objectiveContract" or op != "update":
        return None
    if "field" not in payload:
        if isinstance(payload.get("to"), dict):
            return None
        return Reject(
            rule="objective-contract-update-payload",
            file=None, anchor=None, field="payload",
            expected="either {field,to} for one field or {to:{...}} for whole object",
            actual=f"keys={sorted(payload.keys())}",
            suggested_fix='Use {"field":"baseline","to":"..."} or {"to":{"metric":"..."}}.',
        )
    field = payload.get("field")
    if field not in _OBJECTIVE_CONTRACT_FIELDS:
        return Reject(
            rule="objective-contract-field-known",
            file=None, anchor=None, field="field",
            expected=f"one of {sorted(_OBJECTIVE_CONTRACT_FIELDS)}",
            actual=repr(field),
            suggested_fix="Pick a known objectiveContract field.",
        )
    if "to" not in payload:
        return Reject(
            rule="objective-contract-update-payload",
            file=None, anchor=None, field="to",
            expected="replacement value in payload.to",
            actual="missing",
            suggested_fix='Add the new value as payload.to.',
        )
    return None


def rule_results_gate_update_payload(pkg, op, target, payload) -> Reject | None:
    """Updating a result-gate row requires an exp id and known cell names."""
    if target != "results-gate-row" or op != "update":
        return None
    exp_id = payload.get("exp_id")
    cells = payload.get("cells")
    if not exp_id or not isinstance(cells, dict) or not cells:
        return Reject(
            rule="results-gate-update-payload",
            file=None, anchor=None, field="payload",
            expected="payload has exp_id and non-empty cells object",
            actual=f"exp_id={exp_id!r}, cells_type={type(cells).__name__}, cells={cells!r}",
            suggested_fix='Use {"exp_id":"P0","cells":{"plan-gate":"..."}}.',
        )
    unknown = set(cells) - _RESULT_GATE_UPDATE_FIELDS
    if unknown:
        return Reject(
            rule="results-gate-update-fields-known",
            file=None, anchor=None, field="cells",
            expected=f"keys subset of {sorted(_RESULT_GATE_UPDATE_FIELDS)}",
            actual=f"unknown={sorted(unknown)}",
            suggested_fix="Use the data-field names from the result-gate table.",
        )
    return None


# ---- Result-block rules ----

_RESULT_BLOCK_ANCHORS = [
    'data-block="title"',
    'data-block="summary"',
    'data-block="detail"',
    'data-block="main-table"',
    'data-block="insight"',
    'data-block="ablation"',
]
_DETAILS_OPEN_RE = re.compile(r"<details\s[^>]*open", re.IGNORECASE)


def rule_result_block_six_parts(pkg, op, target, payload) -> Reject | None:
    """HTML must contain all 6 data-block anchors (or <!-- no ablation --> for ablation)."""
    if target != "results-block" or op not in {"insert", "update"}:
        return None
    html = payload.get("html", "")
    missing = []
    for anchor in _RESULT_BLOCK_ANCHORS:
        if anchor == 'data-block="ablation"':
            if anchor not in html and "<!-- no ablation -->" not in html:
                missing.append(anchor)
        elif anchor not in html:
            missing.append(anchor)
    if missing:
        return Reject(
            rule="result-block-six-parts",
            file=None, anchor=None, field="html",
            expected="all 6 data-block anchors present",
            actual=f"missing={missing}",
            suggested_fix='Add the missing data-block="..." anchors (or <!-- no ablation --> for ablation).',
        )
    return None


def rule_result_block_update_payload(pkg, op, target, payload) -> Reject | None:
    """Updating a result block requires a phase id and replacement HTML."""
    if target != "results-block" or op != "update":
        return None
    phase_id = payload.get("phase_id")
    html = payload.get("html")
    if not phase_id or not isinstance(html, str) or not html.strip():
        return Reject(
            rule="result-block-update-payload",
            file=None, anchor=None, field="payload",
            expected='payload has non-empty "phase_id" and replacement "html"',
            actual=f"phase_id={phase_id!r}, html_type={type(html).__name__}",
            suggested_fix='Use {"phase_id":"unmeasured","html":"<article ...>...</article>"}',
        )
    return None


def rule_result_block_details_closed(pkg, op, target, payload) -> Reject | None:
    """No <details open> allowed — every <details> must be closed by default."""
    if target != "results-block" or op != "insert":
        return None
    html = payload.get("html", "")
    if _DETAILS_OPEN_RE.search(html):
        return Reject(
            rule="result-block-details-closed",
            file=None, anchor=None, field="html",
            expected="no <details open> in block",
            actual="found <details open>",
            suggested_fix="Remove the 'open' attribute from all <details> elements.",
        )
    return None


# ---- Tracker live-check row rules ----

_LIVE_CHECK_FIELDS = {
    "time", "exp_id", "agent", "run_state", "last_log", "progress",
    "metrics", "resource", "artifacts", "eta", "action", "next_check",
}


def rule_live_check_twelve_cols(pkg, op, target, payload) -> Reject | None:
    """All 12 live-check columns must be present."""
    if target != "tracker-live-check-row" or op != "insert":
        return None
    missing = _LIVE_CHECK_FIELDS - set(payload.keys())
    if missing:
        return Reject(
            rule="live-check-twelve-cols",
            file=None, anchor=None, field="payload",
            expected=f"keys include {sorted(_LIVE_CHECK_FIELDS)}",
            actual=f"missing={sorted(missing)}",
            suggested_fix="Add the missing column(s) to the live-check row payload.",
        )
    return None


def rule_live_check_time_local(pkg, op, target, payload) -> Reject | None:
    """time field must be local wall-clock: no trailing Z, no +00:00 offset."""
    if target != "tracker-live-check-row" or op != "insert":
        return None
    t = payload.get("time", "")
    if t.endswith("Z") or "+00:00" in t:
        return Reject(
            rule="live-check-time-local",
            file=None, anchor=None, field="time",
            expected="local wall-clock time (no Z, no +00:00)",
            actual=repr(t),
            suggested_fix="Use local time without UTC suffix, e.g. '2026-05-24T10:30:00+10:00'.",
        )
    return None


# ---- Status / lane-crossing rules ----

_SUCCESS_REQUIRED = {"terminationMessage", "adoptionPath"}
_FAIL_REQUIRED    = {"terminationMessage"}


def rule_lane_t1_ack_present(pkg, op, target, payload, state) -> Reject | None:
    """Lane-crossing status updates require a T1 ack token."""
    if target != "status" or op != "update":
        return None
    to_cat = payload.get("to_category")
    if to_cat is None or to_cat == state.get("category"):
        return None  # not a lane crossing
    ack = payload.get("ack_token", "")
    if not ack or not str(ack).strip():
        return Reject(
            rule="lane-t1-ack-present",
            file=None, anchor=None, field="ack_token",
            expected="non-empty ack_token string for lane crossing",
            actual=repr(ack),
            suggested_fix="Add ack_token to the payload with the T1 acknowledgement value.",
        )
    return None


def rule_lane_required_fields(pkg, op, target, payload, state) -> Reject | None:
    """Lane-crossing updates must include required fields for the destination lane."""
    if target != "status" or op != "update":
        return None
    to_cat = payload.get("to_category")
    if to_cat is None or to_cat == state.get("category"):
        return None  # not a lane crossing
    if to_cat == "success":
        required = _SUCCESS_REQUIRED
    elif to_cat == "fail":
        required = _FAIL_REQUIRED
    else:
        return None
    missing = required - set(payload.keys())
    if missing:
        return Reject(
            rule="lane-required-fields",
            file=None, anchor=None, field="payload",
            expected=f"fields {sorted(required)} for destination lane={to_cat!r}",
            actual=f"missing={sorted(missing)}",
            suggested_fix=f"Add {sorted(missing)} to the payload before crossing to {to_cat!r}.",
        )
    return None


def rule_acquit_needs_verdict(pkg, op, target, payload, state) -> Reject | None:
    """Acquit — crossing into the success lane — must carry a verdict record (the verifier seam)."""
    if target != "status" or op != "update":
        return None
    if payload.get("to_category") != "success":
        return None
    if not payload.get("verdict"):
        return Reject(
            rule="acquit-needs-verdict",
            file=None, anchor=None, field="verdict",
            expected="a verdict record attached to any acquit into the success lane",
            actual="no verdict in payload",
            suggested_fix="Attach a verdict record (judge, verdict, evidence) before acquitting to success.",
        )
    return None


def rule_acquit_judge_independent(pkg, op, target, payload, state) -> Reject | None:
    """L2 (Stage 2a): the acquit verdict must be independent enough for the Task's control mode."""
    if target != "status" or op != "update":
        return None
    if payload.get("to_category") != "success":
        return None
    verdict = payload.get("verdict")
    if not verdict:
        return None  # presence is handled by rule_acquit_needs_verdict
    mode = payload.get("control_mode", "SUPERVISED")
    reason = verifier.assess_acquit(verdict, mode)
    if reason:
        return Reject(
            rule="acquit-judge-independent",
            file=None, anchor=None, field="verdict",
            expected=f"a verdict whose independence satisfies control_mode={mode!r} and that acquits",
            actual=reason,
            suggested_fix="Use a fresh judge distinct from the producer (cross-family at Autonomous) "
                          "and acquit only on a 'sound' verdict.",
        )
    return None


def _entering_launch(op, target, payload, state) -> bool:
    """True iff this op moves status INTO READY_TO_LAUNCH (within-lane; keyed on to_status, not to_category)."""
    return (
        target == "status" and op == "update"
        and payload.get("to_status") == "READY_TO_LAUNCH"
        and state.get("status") != "READY_TO_LAUNCH"  # ignore no-op self-transition
    )


def rule_launch_needs_verdict(pkg, op, target, payload, state) -> Reject | None:
    """Entering READY_TO_LAUNCH must carry a reviewer verdict on the implementation (any source status)."""
    if not _entering_launch(op, target, payload, state):
        return None
    if not payload.get("reviewer_verdict"):
        return Reject(
            rule="launch-needs-verdict",
            file=None, anchor=None, field="reviewer_verdict",
            expected="a reviewer verdict on the implementation before entering READY_TO_LAUNCH",
            actual="no reviewer_verdict in payload",
            suggested_fix="Have a separate reviewer sub-agent review the implementation diff and attach "
                          "reviewer_verdict (producer, judge, result, scope_version, artifact_id) "
                          "before moving to READY_TO_LAUNCH. At supervised the human may attest it "
                          "(judge='human').",
        )
    return None


def rule_launch_acquits(pkg, op, target, payload, state) -> Reject | None:
    """The reviewer must be a distinct judge and the verdict must acquit (sound) — autonomy-independent."""
    if not _entering_launch(op, target, payload, state):
        return None
    verdict = payload.get("reviewer_verdict")
    if not verdict:
        return None  # presence is handled by rule_launch_needs_verdict
    producer, judge = verdict.get("producer"), verdict.get("judge")
    if not producer or not judge:
        return Reject(
            rule="launch-acquits",
            file=None, anchor=None, field="reviewer_verdict",
            expected="both producer and judge identities set on the reviewer verdict",
            actual=f"producer={producer!r} judge={judge!r}",
            suggested_fix="Record both the implementer (producer) and the reviewer (judge) identities.",
        )
    if producer == judge:
        return Reject(
            rule="launch-acquits",
            file=None, anchor=None, field="reviewer_verdict",
            expected="a verdict whose judge is distinct from the implementer (producer != judge)",
            actual=f"producer={producer!r} judge={judge!r}",
            suggested_fix="Use a separate reviewer (cross-family preferred for the faithfulness check) "
                          "distinct from the coding agent.",
        )
    if verdict.get("result") not in verifier.ACQUIT_STATES:
        return Reject(
            rule="launch-acquits",
            file=None, anchor=None, field="reviewer_verdict",
            expected=f"an acquitting result in {sorted(verifier.ACQUIT_STATES)}",
            actual=f"result={verdict.get('result')!r}",
            suggested_fix="Proceed to launch only on a 'sound' verdict; fix the implementation otherwise.",
        )
    return None


# ---- Doc-file / doc-card rules ----

_DOC_PATH_RE = re.compile(r"^research_html/packages/[^/]+/docs/[^/]+\.html$")
_DOC_CARD_ATTRS = [
    "data-doc-slug",
    "data-doc-purpose",
    "data-doc-audience",
    "data-doc-status",
    "data-doc-anchor",
]


def rule_doc_file_path_under_package(pkg, op, target, payload) -> Reject | None:
    """doc-file path must be under research_html/packages/<pkg>/docs/."""
    if target != "doc-file" or op != "insert":
        return None
    path = payload.get("path", "")
    if not _DOC_PATH_RE.match(path):
        return Reject(
            rule="doc-file-path-under-package",
            file=path, anchor=None, field="path",
            expected=r"research_html/packages/<pkg>/docs/<slug>.html",
            actual=repr(path),
            suggested_fix="Place doc files under research_html/packages/<pkg>/docs/<slug>.html.",
        )
    return None


def rule_doc_card_six_parts(pkg, op, target, payload) -> Reject | None:
    """doc-card HTML must include data-doc-slug and 4 other data-doc-* attrs."""
    if target != "doc-card" or op != "insert":
        return None
    html = payload.get("html", "")
    missing = [attr for attr in _DOC_CARD_ATTRS if attr not in html]
    if missing:
        return Reject(
            rule="doc-card-six-parts",
            file=None, anchor=None, field="html",
            expected=f"all doc-card attrs present: {_DOC_CARD_ATTRS}",
            actual=f"missing={missing}",
            suggested_fix="Add the missing data-doc-* attributes to the doc-card HTML.",
        )
    return None


def rule_doc_group_rationale_present(pkg, op, target, payload) -> Reject | None:
    """parent_section_html must contain data-doc-group-rationale= attribute."""
    if target != "doc-card" or op != "insert":
        return None
    section_html = payload.get("parent_section_html", "")
    if "data-doc-group-rationale=" not in section_html:
        return Reject(
            rule="doc-group-rationale-present",
            file=None, anchor=None, field="parent_section_html",
            expected="data-doc-group-rationale= present in parent section",
            actual="attribute not found",
            suggested_fix="Add data-doc-group-rationale='...' to the parent <section> element.",
        )
    return None


# ---- Delete rules ----

_TERMINAL_CATEGORIES = {"success", "fail"}
_BLOCKING_STATUSES   = {"RUNNING", "COMPLETED", "RUN_FAILED"}


def rule_experiments_pre_launch_only(pkg, op, target, payload, state) -> Reject | None:
    """Refuse to delete experiments-row if any experiment is running/completed/failed."""
    if target != "experiments-row" or op != "delete":
        return None
    statuses = payload.get("existing_experiments_status_list", [])
    blocking = [s for s in statuses if s in _BLOCKING_STATUSES]
    if blocking:
        return Reject(
            rule="experiments-pre-launch-only",
            file=None, anchor=None, field="existing_experiments_status_list",
            expected="all experiments in pre-launch state (QUEUED/STALE/RUN_HALTED)",
            actual=f"blocking statuses found: {blocking}",
            suggested_fix="Cannot delete experiments-row while runs are RUNNING, COMPLETED, or RUN_FAILED.",
        )
    return None


def rule_experiments_delete_no_authored_blocks(pkg, op, target, payload, state) -> Reject | None:
    """Refuse to delete an experiments[] row after derived task blocks are authored."""
    if target != "experiments-row" or op != "delete":
        return None
    exp_id = payload.get("id")
    if not exp_id:
        return None
    hits = task_spine.has_authored_content_for_exp(Path(f"research_html/packages/{pkg}"), str(exp_id))
    if hits:
        return Reject(
            rule="experiments-delete-bound-content",
            file=", ".join(hits), anchor=str(exp_id), field="id",
            expected="no authored content in blocks bound to this experiment",
            actual=f"authored blocks found in {hits}",
            suggested_fix="Clear or archive the authored task thread before deleting the experiments[] row.",
        )
    return None


def rule_methodstried_terminal_frozen(pkg, op, target, payload, state) -> Reject | None:
    """Refuse to delete methodsTried rows when package is in a terminal lane."""
    if target != "methodsTried" or op != "delete":
        return None
    if state.get("category") in _TERMINAL_CATEGORIES:
        return Reject(
            rule="methodstried-terminal-frozen",
            file=None, anchor=None, field="category",
            expected="non-terminal category (not success or fail)",
            actual=state["category"],
            suggested_fix="methodsTried rows are frozen in success/fail packages; do not delete.",
        )
    return None


def rule_target_known(pkg, op, target, payload, known_targets) -> Reject | None:
    """target must be in transitions.TARGETS (only for non-check ops)."""
    if op == "check" or target is None:
        return None
    if target not in known_targets:
        return Reject(
            rule="target-known",
            file=None, anchor=None, field="target",
            expected=f"one of {sorted(known_targets)[:8]}... (see references/matrix.md)",
            actual=repr(target),
            suggested_fix="Pick a target listed in references/matrix.md or transitions.TARGETS.",
        )
    return None


def rule_verdict_mechanical(pkg, op, target, payload, state) -> Reject | None:
    """If we're writing a verdict, the verdict must match success.predicate(measured)."""
    if target != "results-verdict" or op != "update":
        return None
    measured = payload.get("measured")
    verdict  = payload.get("verdict")
    if measured is None or verdict is None:
        return Reject(
            rule="verdict-mechanical",
            file=None, anchor=None, field="payload",
            expected="payload has both `measured` and `verdict`",
            actual=f"measured={measured!r}, verdict={verdict!r}",
            suggested_fix="Provide both fields; the rule needs the measured value to compute the expected verdict.",
        )
    # Read frozen success.predicate from plan.html
    plan = Path(f"research_html/packages/{pkg}/plan.html").read_text()
    m = re.search(r'data-objective-field="success\.predicate"[^>]*>([^<]+)<', plan)
    if not m:
        return Reject(
            rule="verdict-mechanical",
            file=f"research_html/packages/{pkg}/plan.html", anchor=None,
            field="success.predicate",
            expected="plan.html has data-objective-field=\"success.predicate\" with a value",
            actual="no success.predicate slot found",
            suggested_fix="Define success.predicate on plan.html before recording any verdict.",
        )
    predicate = m.group(1).strip()
    # Evaluate the predicate mechanically. Supported forms: `measured >= 0.85`,
    # `measured > baseline + 0.02`, etc. For MVP, only `measured >= <float>` is supported;
    # any other shape downgrades to inconclusive instead of refusing.
    pm = re.match(r"measured\s*>=\s*([0-9.]+)", predicate)
    if not pm:
        # Predicate too complex for mechanical eval — skip this rule, let Stop-Gate handle.
        return None
    threshold = float(pm.group(1))
    try:
        m_val = float(measured)
    except (TypeError, ValueError):
        return Reject(
            rule="verdict-mechanical",
            file=None, anchor=None, field="measured",
            expected="numeric measured value",
            actual=repr(measured),
            suggested_fix="Coerce measured to a number before recording the verdict.",
        )
    expected_verdict = "PASS" if m_val >= threshold else "FAIL"
    if verdict != expected_verdict:
        return Reject(
            rule="verdict-mechanical",
            file=f"research_html/packages/{pkg}/plan.html", anchor=None,
            field="verdict",
            expected=f"verdict={expected_verdict} (predicate {predicate} with measured={m_val})",
            actual=f"verdict={verdict}",
            suggested_fix=f"Set verdict={expected_verdict}; the measured value {'meets' if expected_verdict == 'PASS' else 'does not meet'} the gate.",
        )
    return None


# Add more rules as they are needed; the spec § 6.2 catalogue grows here.


# ---- Dispatcher ----

# Each entry: (rule_fn, needs_state_arg).
_RULES: list[tuple[Callable, bool]] = [
    (rule_fact_backed_projection_write,      False),
    (rule_rule_universal_writelock,          False),
    (rule_rule_level_routable,               False),
    (rule_rule_store_parseable,              False),
    (rule_rule_required_fields,              False),
    (rule_rule_origin_reserved,              False),
    (rule_rule_text_plain,                   False),
    (rule_rule_lesson_needs_result,          False),
    (rule_rule_lifecycle_fields,             False),
    (rule_rule_origin_immutable,             False),
    (rule_methodstried_six_fields,           False),
    (rule_methodstried_verdict_enum,         False),
    (rule_methodstried_fact_backed_requires_source_ref, False),
    (rule_methodstried_manual_pass_forbidden, False),
    (rule_methodstried_evidence_resolves,    False),
    (rule_result_gate_ten_cols,              False),
    (rule_result_gate_validity_enum,         False),
    (rule_experiments_update_payload,        False),
    (rule_objective_contract_update_payload, False),
    (rule_results_gate_update_payload,       False),
    (rule_result_block_six_parts,            False),
    (rule_result_block_update_payload,       False),
    (rule_result_block_details_closed,       False),
    (rule_live_check_twelve_cols,            False),
    (rule_live_check_time_local,             False),
    (rule_lane_t1_ack_present,               True),
    (rule_lane_required_fields,              True),
    (rule_acquit_needs_verdict,              True),
    (rule_acquit_judge_independent,          True),
    (rule_launch_needs_verdict,              True),
    (rule_launch_acquits,                    True),
    (rule_doc_file_path_under_package,       False),
    (rule_doc_card_six_parts,                False),
    (rule_doc_group_rationale_present,       False),
    (rule_experiments_pre_launch_only,       True),
    (rule_experiments_delete_no_authored_blocks, True),
    (rule_methodstried_terminal_frozen,      True),
    (rule_verdict_mechanical,                True),
]


def validate(pkg: str, op: str, target: str | None, payload: dict, state: dict) -> Reject | None:
    """Run every applicable rule. Return first rejection, or None on all-pass."""
    for fn, needs_state in _RULES:
        rej = fn(pkg, op, target, payload, state) if needs_state else fn(pkg, op, target, payload)
        if rej:
            return rej
    return None
