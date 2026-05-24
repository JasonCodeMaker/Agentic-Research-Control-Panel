"""Pattern B reject-before-write checks.

Each rule is a function `rule_<id>(pkg, op, target, payload) -> Reject | None`.
The dispatcher calls all rules applicable to (op, target) and returns the first
rejection, or None if all pass.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


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


def rule_brainstorm_category_only(pkg, op, target, payload, state) -> Reject | None:
    if target != "brainstorm-section" or op != "insert":
        return None
    if state["category"] != "brainstorm":
        return Reject(
            rule="brainstorm-category-only",
            file=None, anchor=None, field="category",
            expected="brainstorm",
            actual=state["category"],
            suggested_fix="brainstorm sections only exist on brainstorm-category packages.",
        )
    return None


# Add more rules as they are needed; the spec § 6.2 catalogue grows here.


# ---- Dispatcher ----

# Each entry: (rule_fn, needs_state_arg).
_RULES: list[tuple[Callable, bool]] = [
    (rule_methodstried_six_fields,      False),
    (rule_methodstried_verdict_enum,    False),
    (rule_methodstried_evidence_resolves, False),
    (rule_brainstorm_category_only,     True),
]


def validate(pkg: str, op: str, target: str | None, payload: dict, state: dict) -> Reject | None:
    """Run every applicable rule. Return first rejection, or None on all-pass."""
    for fn, needs_state in _RULES:
        rej = fn(pkg, op, target, payload, state) if needs_state else fn(pkg, op, target, payload)
        if rej:
            return rej
    return None
