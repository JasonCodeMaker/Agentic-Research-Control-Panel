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

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import verifier  # noqa: E402


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
_VERDICT_ALLOWED    = {"pass", "fail", "inconclusive"}


def rule_methodstried_six_fields(pkg, op, target, payload) -> Reject | None:
    if target != "methodsTried" or op != "insert":
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
    v = payload.get("verdict")
    if v not in _VERDICT_ALLOWED:
        return Reject(
            rule="methodstried-verdict-enum",
            file=None, anchor=None, field="verdict",
            expected=f"one of {sorted(_VERDICT_ALLOWED)}",
            actual=repr(v),
            suggested_fix="Set verdict to pass / fail / inconclusive. Single-seed pass is inconclusive until multi-seed gate is met.",
        )
    return None


def rule_methodstried_evidence_resolves(pkg, op, target, payload) -> Reject | None:
    if target != "methodsTried" or op != "insert":
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




# ---- Result-gate row rules ----

_RESULT_GATE_FIELDS = {
    "exp_id", "validity", "baseline", "plan_gate", "observed_metric",
    "budget_use", "seed_status", "artifact_completeness", "verdict", "reason",
}
_VALIDITY_ALLOWED = {"ok", "partial", "fail", "unmeasured"}


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
    """validity must be one of {ok, partial, fail, unmeasured}."""
    if target != "results-gate-row" or op != "insert":
        return None
    v = payload.get("validity")
    if v not in _VALIDITY_ALLOWED:
        return Reject(
            rule="result-gate-validity-enum",
            file=None, anchor=None, field="validity",
            expected=f"one of {sorted(_VALIDITY_ALLOWED)}",
            actual=repr(v),
            suggested_fix="Set validity to ok / partial / fail / unmeasured.",
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
    if target != "results-block" or op != "insert":
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
    """L2 (Stage 2a): the acquit verdict must be independent enough for the Task's autonomy level."""
    if target != "status" or op != "update":
        return None
    if payload.get("to_category") != "success":
        return None
    verdict = payload.get("verdict")
    if not verdict:
        return None  # presence is handled by rule_acquit_needs_verdict
    level = payload.get("autonomy_level", "supervised")
    reason = verifier.assess_acquit(verdict, level)
    if reason:
        return Reject(
            rule="acquit-judge-independent",
            file=None, anchor=None, field="verdict",
            expected=f"a verdict whose independence satisfies autonomy={level!r} and that acquits",
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
_BLOCKING_STATUSES   = {"running", "completed", "failed"}


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
            expected="all experiments in pre-launch state (queued/stale/blocked)",
            actual=f"blocking statuses found: {blocking}",
            suggested_fix="Cannot delete experiments-row while runs are running, completed, or failed.",
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
    expected_verdict = "pass" if m_val >= threshold else "fail"
    if verdict != expected_verdict:
        return Reject(
            rule="verdict-mechanical",
            file=f"research_html/packages/{pkg}/plan.html", anchor=None,
            field="verdict",
            expected=f"verdict={expected_verdict} (predicate {predicate} with measured={m_val})",
            actual=f"verdict={verdict}",
            suggested_fix=f"Set verdict={expected_verdict}; the measured value {'meets' if expected_verdict == 'pass' else 'does not meet'} the gate.",
        )
    return None


# Add more rules as they are needed; the spec § 6.2 catalogue grows here.


# ---- Analysis-rule rules ----

def rule_analysis_rule_slug_kebab(pkg, op, target, payload) -> Reject | None:
    if target != "analysis-rule" or op != "insert":
        return None
    slug = payload.get("slug", "")
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", slug):
        return Reject(
            rule="analysis-rule-slug-kebab",
            file=None, anchor=None, field="slug",
            expected="kebab-case slug (lowercase, hyphens, no underscores)",
            actual=repr(slug),
            suggested_fix="Lowercase the slug, replace spaces/underscores with hyphens.",
        )
    return None


def rule_analysis_rule_no_bold(pkg, op, target, payload) -> Reject | None:
    if target != "analysis-rule" or op != "insert":
        return None
    prose = payload.get("prose", "")
    if "<strong>" in prose or "<b>" in prose:
        return Reject(
            rule="analysis-rule-no-bold",
            file=None, anchor=None, field="prose",
            expected="rule prose with no <strong> or <b>",
            actual="bold tag found in prose",
            suggested_fix="Remove the <strong>/<b> wrappers; rules are plain sentences (inline <em> for sub-clauses is fine).",
        )
    return None


# ---- Dispatcher ----

# Each entry: (rule_fn, needs_state_arg).
_RULES: list[tuple[Callable, bool]] = [
    (rule_methodstried_six_fields,           False),
    (rule_methodstried_verdict_enum,         False),
    (rule_methodstried_evidence_resolves,    False),
    (rule_result_gate_ten_cols,              False),
    (rule_result_gate_validity_enum,         False),
    (rule_result_block_six_parts,            False),
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
    (rule_methodstried_terminal_frozen,      True),
    (rule_verdict_mechanical,                True),
    (rule_analysis_rule_slug_kebab,          False),
    (rule_analysis_rule_no_bold,             False),
]


def validate(pkg: str, op: str, target: str | None, payload: dict, state: dict) -> Reject | None:
    """Run every applicable rule. Return first rejection, or None on all-pass."""
    for fn, needs_state in _RULES:
        rej = fn(pkg, op, target, payload, state) if needs_state else fn(pkg, op, target, payload)
        if rej:
            return rej
    return None
