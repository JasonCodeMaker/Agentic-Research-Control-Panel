"""Verifier — the layered trust gate. Deterministic independence rules + a Codex jury adapter.

The substantive judgment is made by a fresh, cross-family model (via mcp__codex__codex, called
by the research-run / research-op skill with file paths only). This lib owns the *deterministic*
half: which independence a Task's autonomy level requires, and whether a verdict is allowed to acquit.
A judge may DRIVE review but may never ACQUIT its own work.
"""

import json
import uuid
from pathlib import Path

# Model id prefix -> family. Cross-family independence is decided here.
_FAMILY_PREFIXES = {
    "claude": "anthropic", "gpt": "openai", "o1": "openai", "o3": "openai",
    "codex": "openai", "gemini": "google", "llama": "meta", "mistral": "mistral",
}

# Autonomy dial canonical values (SSOT for this concept).
AUTONOMY_LEVELS = ("SUPERVISED", "CHECKPOINTED", "DEFERRED", "AUTONOMOUS")

# Autonomy level -> required judge independence. The dial escalates this.
INDEPENDENCE_TABLE = {
    "SUPERVISED":   "HUMAN_BACKSTOP",   # human is the backstop; L2 is a deferring placeholder
    "CHECKPOINTED": "CROSS_MODEL",
    "DEFERRED":     "CROSS_MODEL",
    "AUTONOMOUS":   "CROSS_FAMILY",
}

# Gate kind canonical values.
GATE_KIND = ("TERMINAL", "INTERMEDIATE")

# Autonomy level -> pause cadence + whether the loop blocks waiting on a human.
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


class VerifierError(Exception):
    """Raised when the verifier configuration is invalid (e.g. an unknown autonomy level)."""


def family_of(model_id):
    """Map a model id to its family ('unknown' if unrecognized)."""
    mid = (model_id or "").lower()
    for prefix, fam in _FAMILY_PREFIXES.items():
        if mid.startswith(prefix):
            return fam
    return "unknown"


def assess_acquit(verdict, autonomy_level):
    """Return a violation reason if this verdict may not acquit at this autonomy level, else None."""
    required = INDEPENDENCE_TABLE.get(autonomy_level)
    if required is None:
        raise VerifierError(f"unknown autonomy level: {autonomy_level!r}")
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
        return f"autonomy {autonomy_level!r} requires a cross-family judge"
    return None


def pauses_at(autonomy_level, gate_kind):
    """Whether the loop pauses for a human at a gate of this kind at this autonomy level."""
    behavior = DIAL_BEHAVIOR.get(autonomy_level)
    if behavior is None:
        raise VerifierError(f"unknown autonomy level: {autonomy_level!r}")
    return gate_kind in behavior["pauses"]


def blocks(autonomy_level):
    """Whether the loop blocks waiting on a human at this autonomy level (DEFERRED/AUTONOMOUS never do)."""
    behavior = DIAL_BEHAVIOR.get(autonomy_level)
    if behavior is None:
        raise VerifierError(f"unknown autonomy level: {autonomy_level!r}")
    return behavior["blocks"]


def jury_request(artifact_paths, question, *, judge_model):
    """Build the file-paths-only request an agent passes to mcp__codex__codex (fresh thread)."""
    return {
        "judge_model": judge_model,
        "question": question,
        "artifact_paths": list(artifact_paths),  # paths only — never inlined content
        "instruction": "Judge soundness from the artifacts. Reply with one of: " + ", ".join(VERDICT_STATES),
    }


def interpret(raw_text):
    """Map a judge's free-text reply to one of the 6 verdict states (ABSTAIN if unrecognized).

    Checks longer states first to avoid substring collisions (e.g. 'sound' inside 'unsound').
    """
    text = (raw_text or "").strip().lower()
    # Sort by descending length so longer tokens don't get shadowed by shorter substrings.
    for state in sorted(VERDICT_STATES, key=len, reverse=True):
        slug = state.lower()
        prose = slug.replace("_", " ")
        if slug in text or prose in text:
            return state
    return "ABSTAIN"


# A persisted verdict record must carry these — the verifier's structured output the acquit gate reads.
_VERDICT_REQUIRED = ("producer", "judge", "scope_version", "artifact_id", "result")


def write_verdict(verdicts_dir, verdict):
    """Persist a structured verdict record; reject (raise) before write if incomplete or self-judged."""
    missing = [f for f in _VERDICT_REQUIRED if not str(verdict.get(f, "")).strip()]
    if missing:
        raise VerifierError(f"verdict missing required fields: {missing}")
    if verdict["producer"] == verdict["judge"]:
        raise VerifierError("producer == judge (may DRIVE review but never ACQUIT)")
    record = dict(verdict)
    record.setdefault("verdict_id", uuid.uuid4().hex[:12])
    path = Path(verdicts_dir) / f"{record['verdict_id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return record


def read_verdict(verdicts_dir, verdict_id):
    """Read a persisted verdict record by id."""
    return json.loads((Path(verdicts_dir) / f"{verdict_id}.json").read_text(encoding="utf-8"))
