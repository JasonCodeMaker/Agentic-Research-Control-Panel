"""Allocation decision support — filter + rank servers, write the ledger.

The harness recommends and records; the agent decides and launches.
"""

from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lib import resource_alloc as ra  # noqa: E402
from lib.resource_alloc import probe  # noqa: E402

_AVAILABILITY_RANK = {"confirmed-free": 0, "unknown": 1, "busy-now": 2}


def _validate_requirement(req):
    if not req.get("pkg") or not req.get("exp_id"):
        raise ra.RuleViolation("requirement needs pkg and exp_id")
    count = req.get("gpu_count", 1)
    if not isinstance(count, int) or count < 0:
        raise ra.RuleViolation("gpu_count must be an integer >= 0")
    return {**req, "gpu_count": count}


def _eligible_blocks(server, req):
    blocks = []
    for block in server.get("gpus", []):
        if req.get("gpu_type") and block["type"] != req["gpu_type"]:
            continue
        if req.get("min_mem_gb") and block.get("mem_gb", 0) < req["min_mem_gb"]:
            continue
        blocks.append(block)
    return blocks


def _open_count(server_name, eligible_types, open_allocs):
    count = 0
    for alloc in open_allocs:
        if alloc.get("server") != server_name:
            continue
        if alloc.get("gpu_type") and alloc["gpu_type"] not in eligible_types:
            continue
        count += alloc.get("gpu_count", 1)
    return count


def _evaluate(server, req, open_allocs):
    """Hard filters; returns (ok, reasons, fit_mem_gb, free_declared)."""
    reasons = []
    if server.get("status") != "ACTIVE":
        reasons.append(f"server status is {server.get('status')} (DISABLED servers are never allocated)")
    missing_tags = set(req.get("tags", [])) - set(server.get("tags", []))
    if missing_tags:
        reasons.append(f"missing required tag(s): {sorted(missing_tags)}")
    max_hours = (server.get("slurm") or {}).get("max_hours")
    if req.get("min_hours") and max_hours and req["min_hours"] > max_hours:
        reasons.append(f"needs {req['min_hours']}h but server max_hours is {max_hours}")

    fit_mem = None
    free_declared = 0
    if req["gpu_count"] > 0:
        blocks = _eligible_blocks(server, req)
        if not blocks:
            reasons.append("no GPU block matches gpu_type/min_mem_gb requirement")
        else:
            eligible_types = {b["type"] for b in blocks}
            declared = sum(b["count"] for b in blocks)
            free_declared = declared - _open_count(server["name"], eligible_types, open_allocs)
            if free_declared < req["gpu_count"]:
                reasons.append(
                    f"capacity: {free_declared}/{declared} {sorted(eligible_types)} free after open allocations,"
                    f" need {req['gpu_count']}"
                )
            with_mem = [b.get("mem_gb") for b in blocks if b.get("mem_gb")]
            fit_mem = min(with_mem) if with_mem else None
    return (not reasons, reasons, fit_mem, free_declared)


def _availability(outputs_root, server, req, now):
    snapshot = probe.load_snapshot(outputs_root, server["name"], now=now)
    if snapshot is None or not snapshot["fresh"]:
        return "unknown", "no fresh snapshot — availability unknown"
    if snapshot["free_count"] >= max(req["gpu_count"], 1):
        return "confirmed-free", f"fresh snapshot shows {snapshot['free_count']} idle GPU(s)"
    return "busy-now", f"fresh snapshot shows only {snapshot['free_count']} idle GPU(s)"


def recommend(outputs_root, requirement, now=None):
    """Rank ACTIVE servers for a requirement; every candidate/rejection carries reasons."""
    req = _validate_requirement(requirement)
    now = time.time() if now is None else now
    open_allocs = ra.open_allocations(outputs_root)
    candidates, blocked = [], []
    for idx, server in enumerate(ra.load_registry(outputs_root)):
        ok, reasons, fit_mem, free_declared = _evaluate(server, req, open_allocs)
        if not ok:
            blocked.append({"server": server["name"], "reasons": reasons})
            continue
        availability, why = _availability(outputs_root, server, req, now)
        candidates.append({
            "server": server["name"],
            "availability": availability,
            "start_latency": server["start_latency"],
            "fit_mem_gb": fit_mem,
            "free_declared": free_declared,
            "reasons": [
                why,
                f"start_latency={server['start_latency']}",
                f"{free_declared} declared GPU(s) free of open allocations",
            ],
            "_order": idx,
        })
    candidates.sort(key=lambda c: (
        _AVAILABILITY_RANK[c["availability"]],
        c["start_latency"],
        c["fit_mem_gb"] if c["fit_mem_gb"] is not None else float("inf"),
        c["_order"],
    ))
    for c in candidates:
        c.pop("_order")
    return {"candidates": candidates, "blocked": blocked}


def allocate(outputs_root, server_name, requirement, reason="", gpu_ids=None, now=None):
    """Reject-before-write: re-check the hard filters, then append one allocate line."""
    req = _validate_requirement(requirement)
    now = time.time() if now is None else now
    server = ra.get_server(outputs_root, server_name)
    ok, reasons, _, _ = _evaluate(server, req, ra.open_allocations(outputs_root))
    if not ok:
        raise ra.RuleViolation(f"cannot allocate on {server_name!r}: " + "; ".join(reasons))
    entry = {
        "op": "allocate",
        "alloc_id": f"a-{uuid.uuid4().hex[:8]}",
        "server": server_name,
        "pkg": req["pkg"],
        "exp_id": req["exp_id"],
        "gpu_count": req["gpu_count"],
        "gpu_type": req.get("gpu_type"),
        "gpu_ids": gpu_ids,
        "reason": reason,
        "t": now,
    }
    ra.append_ledger(outputs_root, entry)
    return entry


def _open_by_id(outputs_root, alloc_id):
    for alloc in ra.open_allocations(outputs_root):
        if alloc["alloc_id"] == alloc_id:
            return alloc
    raise ra.RuleViolation(f"no open allocation with alloc_id {alloc_id!r}")


def link(outputs_root, alloc_id, run_id=None, job_id=None, now=None):
    """Bind a launched run/job to an open allocation."""
    _open_by_id(outputs_root, alloc_id)
    entry = {"op": "link", "alloc_id": alloc_id, "t": time.time() if now is None else now}
    if run_id:
        entry["run_id"] = run_id
    if job_id:
        entry["job_id"] = job_id
    ra.append_ledger(outputs_root, entry)
    return entry


def release(outputs_root, alloc_id, outcome, now=None):
    """Close an open allocation; double release and unknown ids reject."""
    _open_by_id(outputs_root, alloc_id)
    entry = {"op": "release", "alloc_id": alloc_id, "outcome": outcome,
             "t": time.time() if now is None else now}
    ra.append_ledger(outputs_root, entry)
    return entry


def _terminal_run_ids(outputs_root):
    path = Path(outputs_root) / "_live" / "runs.jsonl"
    if not path.exists():
        return set()
    terminal = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("op") == "terminal":
            terminal.add(record.get("run_id"))
    return terminal


def status(outputs_root, now=None):
    """Per-server occupancy + snapshot age, open allocations, and leak detection."""
    now = time.time() if now is None else now
    open_allocs = ra.open_allocations(outputs_root)
    terminal = _terminal_run_ids(outputs_root)
    servers = []
    for server in ra.load_registry(outputs_root):
        snapshot = probe.load_snapshot(outputs_root, server["name"], now=now)
        servers.append({
            "name": server["name"],
            "kind": server["kind"],
            "status": server["status"],
            "open_allocations": sum(1 for a in open_allocs if a["server"] == server["name"]),
            "snapshot_age": None if snapshot is None else round(snapshot["age"], 1),
            "snapshot_fresh": None if snapshot is None else snapshot["fresh"],
        })
    leaks = [a for a in open_allocs if a.get("run_id") in terminal]
    return {"servers": servers, "open": open_allocs, "leaks": leaks}
