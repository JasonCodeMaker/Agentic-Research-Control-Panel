"""Scope SSOT — the passive, versioned home of intent (Project -> Direction -> Task).

Owns the spec (what to measure / what counts as success), never the reading
(the measured value). Read freely; write only through the one gated writer,
propose_transition. See plan/prototype/scope-ssot-design.html.
"""

import copy
import json
import uuid
from pathlib import Path

LEVELS = ("project", "direction", "task")

# Each level's allowed spec fields: intent only, never a measured value.
SPEC_FIELDS = {
    "project":   frozenset({"goal", "contributions", "out_of_scope"}),
    "direction": frozenset({"hypothesis", "metric", "baselines", "success_gate"}),
    "task":      frozenset({"experiment", "config", "gate", "control_mode"}),
}

# Reading (empirical) fields that must never appear inside a spec.
READING_FIELDS = frozenset({
    "measured", "result", "verdict", "metric_value", "current_best",
    "primaryMetricVsGate", "methodsTried",
})

OPS = ("create", "revise", "supersede", "reopen", "archive")

# Graduated gating: the node's level fixes the change-gate (design §3, Table 1).
# Values are SCREAMING_SNAKE; REQUIRED_GATE is the SSOT for scope_required_gate.
REQUIRED_GATE = {
    "project":   "USER_ONLY",
    "direction": "USER_CROSS_MODEL_AUDIT",
    "task":      "AGENT_DEFERRED_ACK",
}

# Node lifecycle status values — SCREAMING_SNAKE state-machine values.
# Two-tier convention: LANE = lowercase-kebab; STATE = SCREAMING_SNAKE.
# PENDING_TRIAGE = awaiting human Triage disposition (not yet in objective cascade).
NODE_STATUS = frozenset({"ACTIVE", "SUPERSEDED", "ARCHIVED", "PENDING_TRIAGE"})

# Triage decision outcomes (human PM disposition of a proposed scope change).
TRIAGE_DECISION = ("ACCEPTED", "REJECTED")

# Propagate outcome bucket keys (results of a metric-revising memory pass).
PROPAGATE_OUTCOME = ("INVALIDATE", "REOPEN_IDEA", "RETAIN")

# Memory entry kind values.
MEMORY_KIND = frozenset({"RESULT", "IDEA"})


class RuleViolation(Exception):
    """Raised when a node or transition breaks an SSOT invariant (reject-before-write)."""


def validate_node(node):
    """Reject a node with an illegal level, an unknown spec field, or a reading in its spec."""
    level = node.get("level")
    if level not in SPEC_FIELDS:
        raise RuleViolation(f"illegal level: {level!r}")
    if "yardstick" in node:
        raise RuleViolation("old field 'yardstick' is rejected; use 'spec'")
    if "provenance" in node:
        raise RuleViolation("old field 'provenance' is rejected; use 'source'")
    spec = node.get("spec")
    if not isinstance(spec, dict):
        raise RuleViolation("node must carry a spec object")
    allowed = SPEC_FIELDS[level]
    for field in spec:
        if field in READING_FIELDS:
            raise RuleViolation(f"reading field {field!r} cannot live in a spec")
        if field not in allowed:
            raise RuleViolation(f"unknown spec field {field!r} for level {level!r}")


def node_to_json(node):
    """Serialize a node deterministically."""
    return json.dumps(node, sort_keys=True, ensure_ascii=False)


def node_from_json(text):
    """Parse a node from its serialized form."""
    return json.loads(text)


def propose_transition(node, *, op, gate, log_path, trigger=None, cause=None,
                       invalidates=None, reopens=None, dial_revert=None):
    """The single gated writer: validate node + gate, then append one transition. Reject-before-write."""
    validate_node(node)
    if op not in OPS:
        raise RuleViolation(f"illegal op: {op!r}")
    required = REQUIRED_GATE[node["level"]]
    if gate != required:
        raise RuleViolation(f"{node['level']} transition requires gate {required!r}, got {gate!r}")
    record = {
        "transaction_id": uuid.uuid4().hex[:12],
        "scope_version": node["version"],
        "node_id": node["id"],
        "level": node["level"],
        "op": op,
        "gate": gate,
        "trigger": trigger,
        "cause": cause,
        "invalidates": list(invalidates or []),
        "reopens": list(reopens or []),
        "dial_revert": list(dial_revert or []),
        "node": node,  # post-transition snapshot — the log is the store, so it carries the content
    }
    _append(log_path, record)
    return record


def _append(log_path, record):
    """Append one JSON line to the transition log."""
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_log(log_path):
    """Read the append-only transition log into a list of records (empty if absent)."""
    log_path = Path(log_path)
    if not log_path.exists():
        return []
    return [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]


def history(node_id, records):
    """The transition timeline for one node."""
    return [r for r in records if r["node_id"] == node_id]


def fold(records):
    """The current scope: replay the append-only log, last write per node_id wins."""
    projection = {}
    for r in records:
        projection[r["node_id"]] = copy.deepcopy(r["node"])  # detached — never alias the store
    return projection


def intent(node_id, records):
    """Read: the node's current (folded) spec."""
    return fold(records)[node_id]["spec"]


def assert_consistent(projection, records):
    """A projection is only valid if it equals fold(records); a planted drift is rejected."""
    if projection != fold(records):
        raise RuleViolation("projection drift: does not equal fold(transitions)")


def propagate(*, old_metric, new_metric, memory):
    """Carry / invalidate / reopen pass for a metric-revising transition (exact-metric-match v1)."""
    out = {"INVALIDATE": [], "REOPEN_IDEA": [], "RETAIN": []}
    for item in memory:
        if item.get("kind") == "RESULT" and item.get("metric") == old_metric:
            out["INVALIDATE"].append(item["id"])
        elif item.get("kind") == "IDEA" and item.get("failed_on_metric") == old_metric:
            out["REOPEN_IDEA"].append(item["id"])
        else:
            out["RETAIN"].append(item["id"])
    return out


def should_invalidate(node, active_parent_ids):
    """Reference-counted invalidation: a node dies only when none of its parents is still active."""
    return not any(p in active_parent_ids for p in node["parents"])


def append_memory(memory_log, entry):
    """Scope-stamped memory writer: an entry must carry scope_version, else reject before write."""
    if "scope_version" not in entry:
        raise RuleViolation("memory entry must carry scope_version")
    _append(memory_log, entry)
    return entry
