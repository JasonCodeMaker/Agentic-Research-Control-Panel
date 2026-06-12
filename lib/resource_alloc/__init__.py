"""Resource allocation — typed server registry + allocation ledger.

Structured memory of the user's predefined servers (the connection knowledge)
and an append-only allocate/link/release ledger that makes occupancy a fold,
not a recollection. Passive and stdlib-only: this library recommends and
records; it never launches work or drives a remote. See
plan/2026-06-12-resource-allocation.md.
"""

import json
import os
import re
from pathlib import Path

SERVER_KINDS = ("local", "ssh", "slurm")
SERVER_STATUS = frozenset({"ACTIVE", "DISABLED"})
CONTROL_PATHS = ("direct", "tmux")
DEFAULT_START_LATENCY = {"local": 0, "ssh": 1, "slurm": 2}

SERVER_FIELDS = frozenset({
    "name", "kind", "status", "control", "gpus", "slurm", "env",
    "tags", "skill", "start_latency", "notes",
})

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class RuleViolation(Exception):
    """Raised when a server or ledger op breaks an invariant (reject-before-write)."""


def resources_root(outputs_root) -> Path:
    return Path(outputs_root) / "_resources"


def _registry_path(outputs_root) -> Path:
    return resources_root(outputs_root) / "servers.json"


def _ledger_path(outputs_root) -> Path:
    return resources_root(outputs_root) / "allocations.jsonl"


def validate_server(server):
    """Reject a server dict with unknown fields, bad enums, or an unusable control/gpu block."""
    if not isinstance(server, dict):
        raise RuleViolation("server must be a JSON object")
    unknown = set(server) - SERVER_FIELDS
    if unknown:
        raise RuleViolation(f"unknown server fields: {sorted(unknown)}")
    name = server.get("name")
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise RuleViolation(f"server name must be a non-empty token, got {name!r}")
    if server.get("kind") not in SERVER_KINDS:
        raise RuleViolation(f"kind must be one of {SERVER_KINDS}, got {server.get('kind')!r}")
    if server.get("status", "ACTIVE") not in SERVER_STATUS:
        raise RuleViolation(f"status must be one of {sorted(SERVER_STATUS)}")
    control = server.get("control", {"path": "direct"})
    if not isinstance(control, dict) or control.get("path") not in CONTROL_PATHS:
        raise RuleViolation(f"control.path must be one of {CONTROL_PATHS}")
    if control.get("path") == "tmux" and not control.get("tmux_session"):
        raise RuleViolation("control.path=tmux requires control.tmux_session")
    for gpu in server.get("gpus", []):
        if not isinstance(gpu, dict) or not gpu.get("type"):
            raise RuleViolation(f"gpu block needs a type: {gpu!r}")
        count = gpu.get("count")
        if not isinstance(count, int) or count < 1:
            raise RuleViolation(f"gpu block needs an integer count >= 1: {gpu!r}")
    tags = server.get("tags", [])
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        raise RuleViolation("tags must be a list of strings")
    latency = server.get("start_latency")
    if latency is not None and (not isinstance(latency, int) or latency < 0):
        raise RuleViolation("start_latency must be an integer >= 0")


def _normalize_server(server):
    out = {k: v for k, v in server.items() if v is not None}
    out.setdefault("status", "ACTIVE")
    out.setdefault("control", {"path": "direct"})
    out.setdefault("gpus", [])
    out.setdefault("tags", [])
    out.setdefault("start_latency", DEFAULT_START_LATENCY[out["kind"]])
    return out


def load_registry(outputs_root):
    path = _registry_path(outputs_root)
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def register_server(outputs_root, server):
    """Validate then upsert one server by name (atomic rename), preserving registry order."""
    validate_server(server)
    normalized = _normalize_server(server)
    registry = load_registry(outputs_root)
    names = [s["name"] for s in registry]
    if normalized["name"] in names:
        registry[names.index(normalized["name"])] = normalized
    else:
        registry.append(normalized)
    path = _registry_path(outputs_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.rename(tmp, path)
    return normalized


def get_server(outputs_root, name):
    for server in load_registry(outputs_root):
        if server["name"] == name:
            return server
    raise RuleViolation(f"server not registered: {name!r}")


def append_ledger(outputs_root, entry):
    path = _ledger_path(outputs_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")


def load_ledger(outputs_root):
    path = _ledger_path(outputs_root)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def open_allocations(outputs_root):
    """Fold the ledger: allocate entries (with later link fields merged) lacking a release."""
    folded = {}
    for entry in load_ledger(outputs_root):
        alloc_id = entry.get("alloc_id")
        op = entry.get("op")
        if op == "allocate":
            folded[alloc_id] = dict(entry)
        elif op == "link" and alloc_id in folded:
            folded[alloc_id].update({k: v for k, v in entry.items() if k not in {"op", "t"}})
        elif op == "release":
            folded.pop(alloc_id, None)
    return list(folded.values())
