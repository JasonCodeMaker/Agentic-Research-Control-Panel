"""Verifier — the layered trust gate. Deterministic independence rules + a Codex jury adapter.

The substantive judgment is made by a fresh, cross-family model (via mcp__codex__codex, called
by the research-run / research-op skill with file paths only). This lib owns the *deterministic*
half: which independence an Experiment spec's control mode requires, and whether a verdict is allowed to acquit.
A judge may DRIVE review but may never ACQUIT its own work.
"""

import json
import operator
import re
from pathlib import Path

from lib.research_state.schema import enum

# Model id prefix -> family. Cross-family independence is decided here.
_FAMILY_PREFIXES = {
    "claude": "anthropic", "gpt": "openai", "o1": "openai", "o3": "openai",
    "codex": "openai", "gemini": "google", "llama": "meta", "mistral": "mistral",
}

# Control modes are owned by the central research-state schema.
CONTROL_MODES = tuple(enum("control_mode"))

# Control mode -> required judge independence. The mode escalates this.
INDEPENDENCE_TABLE = {
    "SUPERVISED":   "HUMAN_BACKSTOP",   # human is the backstop; L2 is a deferring placeholder
    "CHECKPOINTED": "CROSS_MODEL",
    "DEFERRED":     "CROSS_MODEL",
    "AUTONOMOUS":   "CROSS_FAMILY",
}

# Gate kind canonical values.
GATE_KIND = ("TERMINAL", "INTERMEDIATE")

# Control mode -> pause cadence + whether the loop blocks waiting on a human.
# SUPERVISED pauses at every gate; CHECKPOINTED only at terminal gates; DEFERRED/AUTONOMOUS never block.
DIAL_BEHAVIOR = {
    "SUPERVISED":   {"pauses": ("TERMINAL", "INTERMEDIATE"), "blocks": True},
    "CHECKPOINTED": {"pauses": ("TERMINAL",),                "blocks": True},
    "DEFERRED":     {"pauses": (),                           "blocks": False},
    "AUTONOMOUS":   {"pauses": (),                           "blocks": False},
}

# The 6-state verdict taxonomy a jury may return; only SOUND acquits.
VERDICT_STATES = ("SOUND", "UNSOUND", "INCONCLUSIVE", "NEEDS_REVISION",
                  "INSUFFICIENT_EVIDENCE", "ABSTAIN")
ACQUIT_STATES = {"SOUND"}

_NUMERIC_GATE = re.compile(
    r"^\s*(?P<metric>.+?)\s*(?P<operator>>=|<=|==|>|<)\s*"
    r"(?P<threshold>-?(?:\d+(?:\.\d*)?|\.\d+))\s*$"
)
_COMPARATORS = {
    ">=": operator.ge,
    "<=": operator.le,
    "==": operator.eq,
    ">": operator.gt,
    "<": operator.lt,
}


class VerifierError(Exception):
    """Raised when the verifier configuration is invalid, e.g. an unknown control mode."""


def family_of(model_id):
    """Map a model id to its family ('unknown' if unrecognized)."""
    mid = (model_id or "").lower()
    for prefix, fam in _FAMILY_PREFIXES.items():
        if mid.startswith(prefix):
            return fam
    return "unknown"


def assess_acquit(verdict, control_mode):
    """Return a violation reason if this verdict may not acquit at this control mode, else None."""
    required = INDEPENDENCE_TABLE.get(control_mode)
    if required is None:
        raise VerifierError(f"unknown control mode: {control_mode!r}")
    if required == "HUMAN_BACKSTOP":
        return None  # Supervised: presence + L1 metric gate already enforced upstream
    if verdict.get("result") not in ACQUIT_STATES:
        return f"L2 verdict {verdict.get('result')!r} does not acquit"
    producer, judge = verdict.get("producer"), verdict.get("judge")
    if not producer or not judge:
        return "L2 verdict needs both producer and judge identities"
    if producer == judge:
        return "producer == judge (may DRIVE review but never ACQUIT)"
    if required == "CROSS_FAMILY" and family_of(producer) == family_of(judge):
        return f"control mode {control_mode!r} requires a cross-family judge"
    return None


def assess_metric_verdict(measured, gate, verdict):
    """Reject a PASS/FAIL claim that contradicts a simple numeric gate.

    Natural-language and compound gates remain verifier work.  Returning
    ``None`` for those shapes is deliberate: the later governed verifier
    Decision binds its judgment to the exact Experiment gate and Result.
    """
    match = _NUMERIC_GATE.fullmatch(str(gate or ""))
    if match is None or verdict not in {"PASS", "FAIL"}:
        return None
    try:
        measured_value = float(measured)
    except (TypeError, ValueError):
        return (
            "numeric gate requires a numeric measured value, "
            f"got {measured!r}"
        )
    threshold = float(match.group("threshold"))
    passed = _COMPARATORS[match.group("operator")](
        measured_value,
        threshold,
    )
    expected = "PASS" if passed else "FAIL"
    if verdict != expected:
        return (
            f"verdict {verdict!r} contradicts gate {gate!r} with "
            f"measured={measured_value}; expected {expected}"
        )
    return None


def assess_measurements_verdict(measurements, gate, verdict):
    """Apply a simple numeric gate to the matching measured result."""
    match = _NUMERIC_GATE.fullmatch(str(gate or ""))
    if match is None or verdict not in {"PASS", "FAIL"}:
        return None
    if not isinstance(measurements, dict) or not measurements:
        return "numeric gate requires a non-empty measurements object"
    metric = match.group("metric").strip()
    if metric in measurements:
        measured = measurements[metric]
    elif len(measurements) == 1:
        measured = next(iter(measurements.values()))
    else:
        return (
            f"numeric gate metric {metric!r} is absent from measurements "
            f"{sorted(measurements)}"
        )
    return assess_metric_verdict(measured, gate, verdict)


def pauses_at(control_mode, gate_kind):
    """Whether the loop pauses for a human at a gate of this kind at this control mode."""
    behavior = DIAL_BEHAVIOR.get(control_mode)
    if behavior is None:
        raise VerifierError(f"unknown control mode: {control_mode!r}")
    return gate_kind in behavior["pauses"]


def blocks(control_mode):
    """Whether the loop blocks waiting on a human at this control mode. DEFERRED/AUTONOMOUS never do."""
    behavior = DIAL_BEHAVIOR.get(control_mode)
    if behavior is None:
        raise VerifierError(f"unknown control mode: {control_mode!r}")
    return behavior["blocks"]


def read_verdict(verdicts_dir, verdict_id):
    """Read a persisted verdict record by id."""
    return json.loads((Path(verdicts_dir) / f"{verdict_id}.json").read_text(encoding="utf-8"))
