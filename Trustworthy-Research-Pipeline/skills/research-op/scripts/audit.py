"""Append-only jsonl audit log for every research-op invocation."""

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def runtime_root(pkg: str) -> Path:
    """Resolve the runtime root for a package."""
    env = os.environ.get("RESEARCH_RUNTIME_ROOT")
    if env:
        return Path(env) / pkg
    return Path("outputs") / pkg


def log_path(pkg: str) -> Path:
    return runtime_root(pkg) / "_actions.jsonl"


def append(pkg: str, *, op: str, target: str | None, event: str | None,
           state_before: dict, state_after: dict,
           validation: str, rule: str | None,
           files_touched: list[str], payload: dict,
           user_intent: str | None, duration_ms: int) -> None:
    """Append one audit entry. Creates the log file + parent dirs if missing."""
    entry = {
        "ts": datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds"),
        "pkg": pkg,
        "op": op,
        "target": target,
        "event": event,
        "state_before": state_before,
        "state_after": state_after,
        "validation": validation,
        "rule": rule,
        "files_touched": files_touched,
        "agent": os.environ.get("RESEARCH_OP_AGENT", "main"),
        "user_intent": user_intent,
        "duration_ms": duration_ms,
        "payload_sha256": hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()
        ).hexdigest(),
        "payload": payload,
    }
    path = log_path(pkg)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
