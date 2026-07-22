"""Load v1 JSONL exports only when bootstrapping the SQLite authority."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..io import read_jsonl


def load_v1_exports(
    events_path: Path,
    audit_path: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return read_jsonl(events_path), read_jsonl(audit_path)
