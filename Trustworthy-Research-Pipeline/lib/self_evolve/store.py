"""Append-only Rule transition log: deterministic fold + optimistic concurrency (plan §9.2-§9.3).

The log is the store. Authoritative state is the fold of the append-only transitions;
a fresh (entity_id, version) reads as the pre-creation state "observed". Writes are
serialized by compare-and-append on (expected_from_state, entity_version).
"""

import json
from pathlib import Path

FRESH_STATE = "observed"  # implicit state of an (entity_id, version) with no transition yet


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


def active_version(records, entity_id):
    """The version of an entity currently in the 'active' state, if any."""
    for (eid, ver), st in fold(records).items():
        if eid == entity_id and st == "active":
            return ver
    return None


def active_transitions(records):
    """The last transition per (entity_id, version) whose folded state is 'active'."""
    last = {}
    for r in _dedup(records):
        last[(r["entity_id"], r["entity_version"])] = r
    return {k: t for k, t in last.items() if t["to_state"] == "active"}


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
