"""PACK — the typed continuity bundle an Async/Autonomous tick writes for the absent reader.

A tick that does not produce a complete bundle (attempted / found / hypothesis-state / next-action /
blocking-decision) is rejected before write, so there is never a silent gap when the human is away.
Append-only history; the dashboard shows the latest (tail) for UNPACK.
"""

import json
from pathlib import Path

PACK_FIELDS = ("attempted", "found", "hypothesis_state", "next_action", "blocking_decision")


def missing_fields(bundle):
    """Return the required PACK fields absent (or blank) in this bundle."""
    return [f for f in PACK_FIELDS if not str(bundle.get(f, "")).strip()]


def write_pack(pack_log, bundle):
    """Append a complete PACK bundle to the history; reject (raise) before write if any field is missing."""
    missing = missing_fields(bundle)
    if missing:
        raise ValueError(f"PACK bundle missing required fields: {missing}")
    pack_log = Path(pack_log)
    pack_log.parent.mkdir(parents=True, exist_ok=True)
    with pack_log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(bundle, ensure_ascii=False) + "\n")
    return bundle


def latest(pack_log):
    """The most recent PACK bundle (the dashboard's latest-PACK strip), or None if empty."""
    pack_log = Path(pack_log)
    if not pack_log.exists():
        return None
    lines = [line for line in pack_log.read_text(encoding="utf-8").splitlines() if line.strip()]
    return json.loads(lines[-1]) if lines else None
