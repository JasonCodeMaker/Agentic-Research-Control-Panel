"""Legacy append-only transition helper for generated Skill bundles only.

Project Learning, Decision, and Rule memory must use ``self_evolve.state`` and
the shared management ``EventStore``.  This small fold remains because Skill
bundle/install state intentionally lives in the user's tool directory, outside
workspace ``.research``.
"""

import json
from pathlib import Path

FRESH_STATE = "OBSERVED"  # implicit state of an (entity_id, version) with no transition yet


class ConcurrencyConflict(Exception):
    """Raised when expected_from_state does not match the folded current state."""


def read_log(path):
    """Read the append-only transition log into a list of records (empty if absent)."""
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _dedup(records):
    """Collapse duplicate delivery: keep first occurrence per transition_id, preserve order."""
    seen, out = set(), []
    for r in records:
        tid = r.get("transition_id")
        if tid in seen:
            continue
        seen.add(tid)
        out.append(r)
    return out


def fold(records):
    """Current state per (entity_id, entity_version): last to_state in log order, deduped."""
    state = {}
    for r in _dedup(records):
        state[(r["entity_id"], r["entity_version"])] = r["to_state"]
    return state


def current_state(records, entity_id, entity_version):
    """Folded state for one version; FRESH_STATE if the version has no transition yet."""
    return fold(records).get((entity_id, entity_version), FRESH_STATE)


def append_transition(path, transition):
    """The single gated writer. Returns (record, skipped).

    Idempotent: a duplicate idempotency_key returns the prior record with skipped=True.
    Concurrency-safe: rejects before write when expected_from_state != folded current state.
    """
    path = Path(path)
    records = read_log(path)
    key = transition["idempotency_key"]
    for r in records:
        if r.get("idempotency_key") == key:
            return r, True  # idempotent skip — no second append
    cur = current_state(records, transition["entity_id"], transition["entity_version"])
    if cur != transition["expected_from_state"]:
        raise ConcurrencyConflict(
            f"{transition['entity_id']}@{transition['entity_version']}: "
            f"expected_from_state={transition['expected_from_state']!r} but current={cur!r}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(transition, ensure_ascii=False) + "\n")
    return transition, False
