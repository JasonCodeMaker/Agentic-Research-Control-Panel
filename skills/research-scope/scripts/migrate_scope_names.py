#!/usr/bin/env python3
"""Migrate old Scope field names to the current spec/source schema.

Default mode is a dry run. Pass --write to rewrite files in place.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


NODE_FIELD_MAP = {
    "yardstick": "spec",
    "provenance": "source",
}

SPEC_FIELD_MAP = {
    "project": {
        "north_star": "goal",
        "contribution_spine": "contributions",
        "non_goals": "out_of_scope",
    },
    "direction": {
        "success_predicate": "success_gate",
    },
    "task": {
        "config_ref": "config",
        "gate_predicate": "gate",
        "autonomy_level": "control_mode",
    },
}

PACKAGE_FIELD_MAP = {
    "sourceScopeNode": "sourceDirection",
    "sourceScopeVersion": "sourceVersion",
    "sourceScopeTxn": "sourceChange",
    "sourceScopeMilestones": "sourceTasks",
    "parentTask": "sourceTask",
}


class MigrationError(Exception):
    """Raised when an input file is not safely migratable."""


def _reject_mixed(obj: dict, old: str, new: str, label: str) -> None:
    if old in obj and new in obj:
        raise MigrationError(f"mixed old/new {label}: {old!r} and {new!r}")


def _migrate_spec(level: str, spec: dict) -> tuple[dict, int]:
    changed = 0
    out = dict(spec)
    for old, new in SPEC_FIELD_MAP.get(level, {}).items():
        _reject_mixed(out, old, new, f"spec field for level {level!r}")
        if old in out:
            out[new] = out.pop(old)
            changed += 1
    return out, changed


def migrate_node(node: dict) -> tuple[dict, int]:
    out = dict(node)
    changed = 0
    for old, new in NODE_FIELD_MAP.items():
        _reject_mixed(out, old, new, "node field")
        if old in out:
            out[new] = out.pop(old)
            changed += 1
    if isinstance(out.get("spec"), dict):
        out["spec"], spec_changes = _migrate_spec(str(out.get("level")), out["spec"])
        changed += spec_changes
    return out, changed


def migrate_record(record: dict) -> tuple[dict, int]:
    out = dict(record)
    changed = 0
    if isinstance(out.get("node"), dict):
        out["node"], node_changes = migrate_node(out["node"])
        changed += node_changes
    _reject_mixed(out, "proposed_yardstick", "proposed_spec", "proposal field")
    if "proposed_yardstick" in out:
        out["proposed_spec"] = out.pop("proposed_yardstick")
        changed += 1
    if isinstance(out.get("proposed_node"), dict):
        out["proposed_node"], node_changes = migrate_node(out["proposed_node"])
        changed += node_changes
    if isinstance(out.get("proposed_spec"), dict):
        level = str(out.get("level") or (out.get("proposed_node") or {}).get("level") or "")
        out["proposed_spec"], spec_changes = _migrate_spec(level, out["proposed_spec"])
        changed += spec_changes
    return out, changed


def migrate_jsonl(path: Path, *, write: bool) -> dict:
    if not path.exists():
        return {"path": str(path), "exists": False, "records": 0, "changed": 0}
    records = []
    changed = 0
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise MigrationError(f"{path}:{lineno}: invalid JSON: {exc}") from exc
        new_record, record_changes = migrate_record(record)
        records.append(new_record)
        changed += record_changes
    if write and changed:
        text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
        path.write_text(text, encoding="utf-8")
    return {"path": str(path), "exists": True, "records": len(records), "changed": changed}


def migrate_inventory(path: Path, *, write: bool) -> dict:
    if not path.exists():
        return {"path": str(path), "exists": False, "changed": 0}
    text = path.read_text(encoding="utf-8")
    changed = 0
    for old, new in PACKAGE_FIELD_MAP.items():
        old_re = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(old)}(?![A-Za-z0-9_])")
        new_re = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(new)}(?![A-Za-z0-9_])")
        if old_re.search(text) and new_re.search(text):
            raise MigrationError(f"mixed old/new package provenance fields: {old!r} and {new!r}")
        count = len(old_re.findall(text))
        if count:
            text = old_re.sub(new, text)
            changed += count
    if write and changed:
        path.write_text(text, encoding="utf-8")
    return {"path": str(path), "exists": True, "changed": changed}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transitions", default="outputs/_scope/transitions.jsonl")
    parser.add_argument("--triage", default="", help="optional triage.jsonl to migrate")
    parser.add_argument("--inventory", default="", help="optional research-packages.js to migrate")
    parser.add_argument("--write", action="store_true", help="rewrite files in place")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    reports = [migrate_jsonl(Path(args.transitions), write=args.write)]
    if args.triage:
        reports.append(migrate_jsonl(Path(args.triage), write=args.write))
    if args.inventory:
        reports.append(migrate_inventory(Path(args.inventory), write=args.write))
    print(json.dumps({"write": args.write, "reports": reports}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
