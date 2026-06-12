"""Availability snapshots — parse nvidia-smi text into typed per-server GPU state."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lib import resource_alloc as ra  # noqa: E402

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


def _snapshot_path(outputs_root, server) -> Path:
    return ra.resources_root(outputs_root) / "snapshots" / f"{server}.json"


def write_snapshot(outputs_root, server, gpus, t=None) -> Path:
    path = _snapshot_path(outputs_root, server)
    path.parent.mkdir(parents=True, exist_ok=True)
    snapshot = {"server": server, "t": time.time() if t is None else t, "gpus": gpus}
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(snapshot, sort_keys=True) + "\n", encoding="utf-8")
    os.rename(tmp, path)
    return path


def load_snapshot(outputs_root, server, now=None, max_age=SNAPSHOT_MAX_AGE):
    """Return the snapshot with age/freshness/free_count derived, or None when absent."""
    path = _snapshot_path(outputs_root, server)
    if not path.exists():
        return None
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    age = (time.time() if now is None else now) - snapshot["t"]
    snapshot["age"] = age
    snapshot["fresh"] = age <= max_age
    snapshot["free_count"] = sum(1 for g in snapshot["gpus"] if g.get("free"))
    return snapshot
