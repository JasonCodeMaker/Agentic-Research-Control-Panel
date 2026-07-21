"""Allocation decision support — filter + rank servers, write the ledger.

The harness recommends and records; the agent decides and launches.
"""

from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lib import resource_alloc as ra  # noqa: E402
from lib.resource_alloc import probe  # noqa: E402
from lib.research_state import resolve_bound_experiment  # noqa: E402
from lib.research_state.store import CommandRejected  # noqa: E402

_AVAILABILITY_RANK = {"confirmed-free": 0, "unknown": 1, "busy-now": 2}


def _validate_requirement(req):
    if not isinstance(req, dict):
        raise ra.RuleViolation("requirement must be an object")
    if (
        not isinstance(req.get("pkg"), str)
        or not req["pkg"].strip()
        or not isinstance(req.get("exp_id"), str)
        or not req["exp_id"].strip()
    ):
        raise ra.RuleViolation("requirement needs pkg and exp_id")
    count = req.get("gpu_count", 1)
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ra.RuleViolation("gpu_count must be an integer >= 0")
    gpu_type = req.get("gpu_type")
    if gpu_type is not None and (
        not isinstance(gpu_type, str) or not gpu_type.strip()
    ):
        raise ra.RuleViolation("gpu_type must be a non-empty string")
    for field in ("min_mem_gb", "min_hours"):
        value = req.get(field)
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or value <= 0
        ):
            raise ra.RuleViolation(f"{field} must be a number > 0")
    tags = req.get("tags", [])
    if (
        not isinstance(tags, list)
        or any(not isinstance(tag, str) or not tag.strip() for tag in tags)
    ):
        raise ra.RuleViolation("tags must be a list of non-empty strings")
    return {
        **req,
        "pkg": req["pkg"].strip(),
        "exp_id": req["exp_id"].strip(),
        "gpu_count": count,
        **({"gpu_type": gpu_type.strip()} if gpu_type is not None else {}),
        "tags": [tag.strip() for tag in tags],
    }


def _normalize_gpu_ids(gpu_ids, gpu_count):
    if gpu_ids is None:
        return None
    if not isinstance(gpu_ids, (list, tuple)):
        raise ra.RuleViolation("gpu_ids must be a list of GPU identifiers")
    normalized = []
    for gpu_id in gpu_ids:
        if not isinstance(gpu_id, str) or not gpu_id.strip():
            raise ra.RuleViolation("gpu_ids must contain non-empty strings")
        normalized.append(gpu_id.strip())
    if len(normalized) != len(set(normalized)):
        raise ra.RuleViolation("gpu_ids must be unique")
    if len(normalized) != gpu_count:
        raise ra.RuleViolation(
            f"gpu_ids must contain exactly gpu_count={gpu_count} identifier(s)"
        )
    return normalized


def _eligible_blocks(server, req):
    blocks = []
    for block in server.get("gpus", []):
        if req.get("gpu_type") and block["type"] != req["gpu_type"]:
            continue
        if req.get("min_mem_gb") and block.get("mem_gb", 0) < req["min_mem_gb"]:
            continue
        blocks.append(block)
    return blocks


def _gpu_inventory(server):
    """Return deterministic physical identifiers grouped by declared type."""
    explicitly_declared = {}
    for block in server.get("gpus", []):
        gpu_type = block["type"]
        explicitly_declared.setdefault(gpu_type, set()).update(block.get("ids") or [])

    used = {gpu_type: set(ids) for gpu_type, ids in explicitly_declared.items()}
    inventory = {}
    for block_index, block in enumerate(server.get("gpus", [])):
        gpu_type = block["type"]
        block_ids = block.get("ids")
        if block_ids is None:
            block_ids = []
            candidate = 0
            while len(block_ids) < block["count"]:
                gpu_id = str(candidate)
                candidate += 1
                if gpu_id in used.setdefault(gpu_type, set()):
                    continue
                used[gpu_type].add(gpu_id)
                block_ids.append(gpu_id)
        for gpu_id in block_ids:
            inventory.setdefault(gpu_type, []).append(
                {
                    "id": gpu_id,
                    "mem_gb": block.get("mem_gb"),
                    "block_index": block_index,
                }
            )
    return inventory


def _candidate_gpu_types(server, req):
    selected = req.get("gpu_type")
    if selected:
        return [selected]
    ordered = []
    for block in _eligible_blocks(server, req):
        if block["type"] not in ordered:
            ordered.append(block["type"])
    return ordered


def _allocation_uses_type(allocation, server, gpu_type):
    allocated_type = allocation.get("gpu_type")
    if allocated_type:
        return allocated_type == gpu_type
    declared_types = {
        block["type"]
        for block in server.get("gpus", [])
    }
    # Legacy rows without a type are unambiguous only on homogeneous servers.
    # On mixed servers, conservatively treat them as occupying every type.
    return len(declared_types) != 1 or gpu_type in declared_types


def _available_gpu_ids(server, gpu_type, eligible_ids, open_allocs):
    occupied = set()
    for allocation in open_allocs:
        if allocation.get("server") != server["name"]:
            continue
        if not _allocation_uses_type(allocation, server, gpu_type):
            continue
        count = allocation.get("gpu_count", 1)
        if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
            continue
        allocation_ids = allocation.get("gpu_ids")
        if (
            not isinstance(allocation_ids, list)
            or len(allocation_ids) != count
            or any(not isinstance(gpu_id, str) or not gpu_id for gpu_id in allocation_ids)
        ):
            return [], (
                f"open allocation {allocation.get('alloc_id')!r} has no "
                f"deterministic physical GPU ids for {gpu_type}"
            )
        occupied.update(allocation_ids)
    return [gpu_id for gpu_id in eligible_ids if gpu_id not in occupied], None


def _gpu_placement(server, req, open_allocs, requested_ids):
    count = req["gpu_count"]
    if count == 0:
        return None, [], 0, None, []

    inventory = _gpu_inventory(server)
    failures = []
    for gpu_type in _candidate_gpu_types(server, req):
        eligible_records = [
            record
            for record in inventory.get(gpu_type, [])
            if (
                not req.get("min_mem_gb")
                or (
                    server["gpus"][record["block_index"]].get("mem_gb", 0)
                    >= req["min_mem_gb"]
                )
            )
        ]
        eligible_ids = [record["id"] for record in eligible_records]
        eligible_mem = {
            record["id"]: record["mem_gb"]
            for record in eligible_records
        }
        if not eligible_ids:
            failures.append(f"{gpu_type}: no physical ids match memory requirement")
            continue
        available, occupancy_error = _available_gpu_ids(
            server,
            gpu_type,
            eligible_ids,
            open_allocs,
        )
        if occupancy_error:
            failures.append(f"{gpu_type}: {occupancy_error}")
            continue
        if requested_ids is not None:
            undeclared = [gpu_id for gpu_id in requested_ids if gpu_id not in eligible_ids]
            overlap = [gpu_id for gpu_id in requested_ids if gpu_id not in available]
            if undeclared:
                failures.append(
                    f"{gpu_type}: physical GPU ids are not declared/eligible: "
                    f"{undeclared}"
                )
                continue
            if overlap:
                failures.append(
                    f"{gpu_type}: physical GPU ids already allocated: {overlap}"
                )
                continue
            selected_ids = list(requested_ids)
        else:
            if len(available) < count:
                failures.append(
                    f"{gpu_type}: only {len(available)}/{len(eligible_ids)} "
                    f"physical GPU ids are free, need {count}"
                )
                continue
            selected_ids = available[:count]
        fit_values = [
            eligible_mem[gpu_id]
            for gpu_id in selected_ids
            if eligible_mem.get(gpu_id)
        ]
        fit_mem = min(fit_values) if fit_values else None
        return gpu_type, selected_ids, len(available), fit_mem, failures
    return None, None, 0, None, failures


def _evaluate(server, req, open_allocs, requested_ids=None):
    """Hard filters plus deterministic physical placement."""
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
    selected_type = None
    selected_ids = []
    if req["gpu_count"] > 0:
        blocks = _eligible_blocks(server, req)
        if not blocks:
            reasons.append("no GPU block matches gpu_type/min_mem_gb requirement")
        else:
            (
                selected_type,
                selected_ids,
                free_declared,
                fit_mem,
                placement_reasons,
            ) = _gpu_placement(server, req, open_allocs, requested_ids)
            if selected_type is None:
                reasons.append(
                    "capacity/physical ids: " + "; ".join(placement_reasons)
                )
    return (
        not reasons,
        reasons,
        fit_mem,
        free_declared,
        selected_type,
        selected_ids,
    )


def _availability(research_root, server, req, now):
    snapshot = probe.load_snapshot(research_root, server["name"], now=now)
    if snapshot is None or not snapshot["fresh"]:
        return "unknown", "no fresh snapshot — availability unknown"
    if snapshot["free_count"] >= max(req["gpu_count"], 1):
        return "confirmed-free", f"fresh snapshot shows {snapshot['free_count']} idle GPU(s)"
    return "busy-now", f"fresh snapshot shows only {snapshot['free_count']} idle GPU(s)"


def recommend(research_root, requirement, now=None):
    """Rank ACTIVE servers for a requirement; every candidate/rejection carries reasons."""
    req = _validate_requirement(requirement)
    now = time.time() if now is None else now
    open_allocs = ra.open_allocations(research_root)
    candidates, blocked = [], []
    for idx, server in enumerate(ra.load_registry(research_root)):
        (
            ok,
            reasons,
            fit_mem,
            free_declared,
            selected_type,
            selected_ids,
        ) = _evaluate(server, req, open_allocs)
        if not ok:
            blocked.append({"server": server["name"], "reasons": reasons})
            continue
        availability, why = _availability(research_root, server, req, now)
        candidates.append({
            "server": server["name"],
            "availability": availability,
            "start_latency": server["start_latency"],
            "fit_mem_gb": fit_mem,
            "free_declared": free_declared,
            "gpu_type": selected_type,
            "gpu_ids": selected_ids,
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


def _allocate(research_root, server_name, requirement, reason="", gpu_ids=None, now=None):
    """Reject-before-write: re-check the hard filters, then append one allocate line."""
    if not isinstance(server_name, str) or not server_name.strip():
        raise ra.RuleViolation("server_name must be a non-empty string")
    if not isinstance(reason, str):
        raise ra.RuleViolation("allocation reason must be a string")
    if now is not None and (
        isinstance(now, bool) or not isinstance(now, (int, float))
    ):
        raise ra.RuleViolation("allocation timestamp must be numeric")
    server_name = server_name.strip()
    req = _validate_requirement(requirement)
    requested_gpu_ids = _normalize_gpu_ids(gpu_ids, req["gpu_count"])
    now = time.time() if now is None else now
    state = ra._store(research_root).state()
    try:
        experiment_id, experiment = resolve_bound_experiment(
            state["aggregates"]["experiment"],
            str(req["pkg"]),
            req["exp_id"],
        )
    except ValueError as exc:
        raise ra.RuleViolation(
            str(exc),
            rule="resource-experiment-invalid",
        ) from exc
    experiment_local_id = str(
        experiment.get("local_id") or experiment.get("localId") or req["exp_id"]
    )
    server = ra.get_server(research_root, server_name)
    (
        ok,
        reasons,
        _,
        _,
        selected_gpu_type,
        selected_gpu_ids,
    ) = _evaluate(
        server,
        req,
        ra.open_allocations(research_root),
        requested_gpu_ids,
    )
    if not ok:
        raise ra.RuleViolation(
            f"cannot allocate on {server_name!r}: " + "; ".join(reasons),
            rule="resource-gpu-placement",
        )
    entry = {
        "op": "allocate",
        "alloc_id": f"a-{uuid.uuid4().hex[:8]}",
        "server": server_name,
        "package_id": req["pkg"],
        "experiment_id": experiment_id,
        "experiment_local_id": experiment_local_id,
        # One-version compatibility aliases for older resource consumers.
        "pkg": req["pkg"],
        "exp_id": req["exp_id"],
        "gpu_count": req["gpu_count"],
        "gpu_type": selected_gpu_type,
        "gpu_ids": selected_gpu_ids,
        "reason": reason,
        "t": now,
    }

    def _capacity_policy(state, _command):
        try:
            live_experiment_id, _ = resolve_bound_experiment(
                state["aggregates"]["experiment"],
                str(req["pkg"]),
                req["exp_id"],
            )
        except ValueError as exc:
            raise CommandRejected("resource-experiment-invalid", str(exc)) from exc
        if live_experiment_id != experiment_id:
            raise CommandRejected(
                "resource-experiment-changed",
                "Experiment identity changed while creating the allocation",
            )
        current_server = state["aggregates"]["resource"].get(server_name)
        if not current_server:
            raise CommandRejected(
                "resource-not-registered", f"server not registered: {server_name!r}"
            )
        current_open = [
            allocation
            for allocation in state["aggregates"]["resource_allocation"].values()
            if allocation.get("status") == "OPEN"
        ]
        live_requirement = {**req, "gpu_type": selected_gpu_type}
        (
            allowed,
            current_reasons,
            _,
            _,
            current_gpu_type,
            current_gpu_ids,
        ) = _evaluate(
            current_server,
            live_requirement,
            current_open,
            selected_gpu_ids,
        )
        if (
            not allowed
            or current_gpu_type != selected_gpu_type
            or current_gpu_ids != selected_gpu_ids
        ):
            raise CommandRejected(
                "resource-capacity",
                f"cannot allocate on {server_name!r}: " + "; ".join(current_reasons),
            )

    ra.append_ledger(research_root, entry, policy=_capacity_policy)
    return entry


def allocate(research_root, server_name, requirement, reason="", gpu_ids=None, now=None):
    """Allocate deterministic physical GPU ids and audit every rejection."""
    summary = {
        "server": server_name,
        "package_id": (
            requirement.get("pkg") if isinstance(requirement, dict) else None
        ),
        "experiment_local_id": (
            requirement.get("exp_id") if isinstance(requirement, dict) else None
        ),
        "gpu_count": (
            requirement.get("gpu_count", 1)
            if isinstance(requirement, dict)
            else None
        ),
        "gpu_type": (
            requirement.get("gpu_type")
            if isinstance(requirement, dict)
            else None
        ),
        "gpu_ids": gpu_ids,
    }
    try:
        return _allocate(
            research_root,
            server_name,
            requirement,
            reason=reason,
            gpu_ids=gpu_ids,
            now=now,
        )
    except ra.RuleViolation as exc:
        ra.audit_rejection(
            research_root,
            command="resource-allocate",
            payload=summary,
            error=exc,
        )
        raise


def _open_by_id(research_root, alloc_id):
    for alloc in ra.open_allocations(research_root):
        if alloc["alloc_id"] == alloc_id:
            return alloc
    raise ra.RuleViolation(f"no open allocation with alloc_id {alloc_id!r}")


def link(research_root, alloc_id, run_id=None, job_id=None, now=None):
    """Bind a launched run/job to an open allocation."""
    entry = {"op": "link", "alloc_id": alloc_id, "t": time.time() if now is None else now}
    if run_id:
        entry["run_id"] = run_id
    if job_id:
        entry["job_id"] = job_id
    ra.append_ledger(research_root, entry)
    return entry


def _release(research_root, alloc_id, outcome, now=None):
    """Close an open allocation; double release and unknown ids reject."""
    _open_by_id(research_root, alloc_id)
    entry = {"op": "release", "alloc_id": alloc_id, "outcome": outcome,
             "t": time.time() if now is None else now}
    ra.append_ledger(research_root, entry)
    return entry


def release(research_root, alloc_id, outcome, now=None):
    try:
        return _release(research_root, alloc_id, outcome, now=now)
    except ra.RuleViolation as exc:
        ra.audit_rejection(
            research_root,
            command="resource-release",
            payload={"alloc_id": alloc_id, "outcome": outcome},
            error=exc,
        )
        raise


def _terminal_run_ids(research_root):
    state = ra._store(research_root).state()
    return {
        run_id
        for run_id, record in state["aggregates"]["run"].items()
        if record.get("status") in {"COMPLETED", "FAILED", "HALTED", "SKIPPED"}
    }


def status(research_root, now=None):
    """Per-server occupancy + snapshot age, open allocations, and leak detection."""
    now = time.time() if now is None else now
    open_allocs = ra.open_allocations(research_root)
    terminal = _terminal_run_ids(research_root)
    servers = []
    for server in ra.load_registry(research_root):
        snapshot = probe.load_snapshot(research_root, server["name"], now=now)
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
