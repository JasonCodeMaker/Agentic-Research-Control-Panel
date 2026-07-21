"""Availability snapshots — parse nvidia-smi text into typed per-server GPU state."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lib import resource_alloc as ra  # noqa: E402
from lib.research_state.io import canonical_json, read_json, write_json_atomic  # noqa: E402

SNAPSHOT_MAX_AGE = 600  # seconds; older snapshots count as unknown availability
FREE_UTIL_MAX = 10      # percent
FREE_MEM_FRAC_MAX = 0.1

NVSMI_QUERY = [
    "nvidia-smi",
    "--query-gpu=index,memory.used,memory.total,utilization.gpu",
    "--format=csv,noheader,nounits",
]


def parse_nvidia_smi(text):
    """Parse `nvidia-smi --query-gpu=index,memory.used,memory.total,utilization.gpu` CSV output."""
    gpus = []
    for line in text.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 4:
            continue
        try:
            index, mem_used_mib, mem_total_mib, util = (int(parts[0]), float(parts[1]), float(parts[2]), int(parts[3]))
        except ValueError:
            continue
        gpu = {
            "index": index,
            "mem_used_gb": round(mem_used_mib / 1024, 1),
            "mem_total_gb": round(mem_total_mib / 1024, 1),
            "util": util,
        }
        gpu["free"] = util <= FREE_UTIL_MAX and mem_used_mib <= FREE_MEM_FRAC_MAX * mem_total_mib
        gpus.append(gpu)
    return gpus


def probe_local():
    """Run nvidia-smi on this machine and return parsed GPU state."""
    result = subprocess.run(NVSMI_QUERY, capture_output=True, text=True)
    if result.returncode != 0:
        raise ra.RuleViolation(f"nvidia-smi failed: {result.stderr.strip()}")
    return parse_nvidia_smi(result.stdout)


def _snapshot_path(research_root, server) -> Path:
    return ra.resources_root(research_root) / f"{server}.json"


def _validate_snapshot_gpus(server_record, gpus):
    if not isinstance(gpus, list):
        raise ra.RuleViolation(
            "probe GPUs must be a list",
            rule="resource-probe-invalid",
        )
    try:
        canonical_json(gpus)
    except (TypeError, ValueError) as exc:
        raise ra.RuleViolation(
            "probe GPUs must contain only JSON-compatible values",
            rule="resource-probe-invalid",
        ) from exc
    physical_ids = []
    for gpu in gpus:
        if not isinstance(gpu, dict):
            raise ra.RuleViolation(
                "each probe GPU must be an object",
                rule="resource-probe-invalid",
            )
        index = gpu.get("index")
        if (
            isinstance(index, bool)
            or not isinstance(index, (int, str))
            or not str(index).strip()
        ):
            raise ra.RuleViolation(
                "each probe GPU needs a physical index",
                rule="resource-probe-id-invalid",
            )
        physical_ids.append(str(index).strip())
    if len(physical_ids) != len(set(physical_ids)):
        raise ra.RuleViolation(
            "probe GPU physical indices must be unique",
            rule="resource-probe-id-duplicate",
        )
    if server_record.get("gpus") and not physical_ids:
        raise ra.RuleViolation(
            "probe returned no physical GPU ids for a GPU resource",
            rule="resource-probe-empty",
        )


def _write_snapshot(research_root, server, gpus, t=None) -> Path:
    """Atomically cache a short-lived probe outside persistent research data."""
    server_record = ra.get_server(research_root, server)
    _validate_snapshot_gpus(server_record, gpus)
    path = _snapshot_path(research_root, server)
    snapshot = {"server": server, "t": time.time() if t is None else t, "gpus": gpus}
    write_json_atomic(path, snapshot)
    return path


def write_snapshot(research_root, server, gpus, t=None) -> Path:
    """Validate and audit a probe observation before caching it."""
    summary = {
        "server": server,
        "gpu_observation_count": len(gpus) if isinstance(gpus, list) else None,
        "gpu_ids": (
            [gpu.get("index") for gpu in gpus if isinstance(gpu, dict)]
            if isinstance(gpus, list)
            else None
        ),
    }
    try:
        return _write_snapshot(research_root, server, gpus, t=t)
    except ra.RuleViolation as exc:
        ra.audit_rejection(
            research_root,
            command="resource-probe",
            payload=summary,
            error=exc,
            actor={"type": "agent", "id": "resource-probe"},
        )
        raise


def load_snapshot(research_root, server, now=None, max_age=SNAPSHOT_MAX_AGE):
    """Return the snapshot with age/freshness/free_count derived, or None when absent."""
    path = _snapshot_path(research_root, server)
    if not path.exists():
        return None
    snapshot = read_json(path)
    age = (time.time() if now is None else now) - snapshot["t"]
    snapshot["age"] = age
    snapshot["fresh"] = age <= max_age
    snapshot["free_count"] = sum(1 for g in snapshot["gpus"] if g.get("free"))
    return snapshot
