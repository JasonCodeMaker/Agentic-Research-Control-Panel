"""Scan artifacts under runtime root; classify into events; advance cursor."""

import os
from pathlib import Path
from time import time


def runtime_root(pkg: str) -> Path:
    env = os.environ.get("RESEARCH_RUNTIME_ROOT")
    return Path(env if env else "outputs") / pkg


def cursor_path(pkg: str) -> Path:
    return runtime_root(pkg) / "manifests" / ".propagation_cursor"


def read_cursor(pkg: str) -> float:
    p = cursor_path(pkg)
    if not p.exists():
        return 0.0
    return float(p.read_text().strip() or 0.0)


def write_cursor(pkg: str, ts: float) -> None:
    p = cursor_path(pkg)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"{ts}")


def scan(pkg: str) -> list[dict]:
    """Return a list of {event, artifact, mtime} dicts newer than cursor."""
    cursor = read_cursor(pkg)
    root = runtime_root(pkg)
    events = []
    if not root.exists():
        return events
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        m = p.stat().st_mtime
        if m <= cursor:
            continue
        name = p.name
        if name.endswith("best_model.pt"):
            events.append({"event": "CHECKPOINT_SAVED", "artifact": str(p), "mtime": m})
        elif p.parent.name == "manifests" and name.endswith(".txt"):
            events.append({"event": "SENTINEL_WRITE", "artifact": str(p), "mtime": m})
        elif "candidates" in p.parts and name.endswith(".json"):
            events.append({"event": "CANDIDATE_SUBMITTED", "artifact": str(p), "mtime": m})
        elif name.endswith(".done"):
            events.append({"event": "CHAIN_DONE", "artifact": str(p), "mtime": m})
    return events


def bump(pkg: str) -> None:
    write_cursor(pkg, time())
