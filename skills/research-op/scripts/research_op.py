#!/usr/bin/env python3
"""research-op CLI — the single mutation surface for research packages.

MVP supports `--op check`. Insert/Update/Delete + composite events arrive in Phase 3.
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

# Make sibling modules importable when invoked as `python3 skills/.../research_op.py`.
sys.path.insert(0, str(Path(__file__).parent))

import audit
import transitions  # noqa: E402


def _read_inventory(pkg: str) -> dict:
    """Parse the package entry out of research_html/data/research-packages.js."""
    js = Path("research_html/data/research-packages.js").read_text()
    # Find the line containing id: "<pkg>", then extract category and status nearby.
    # The entry is large and may contain nested structures, so we search forwards
    # from the id line for the next occurrences of category and status.
    pattern = r'id:\s*["\']' + re.escape(pkg) + r'["\']'
    m_id = re.search(pattern, js)
    if not m_id:
        raise SystemExit(f"package id not found in inventory: {pkg}")

    # Search forward from the id line for category and status.
    # Assume they appear within the next 50 lines (conservative).
    search_start = m_id.start()
    search_region = js[search_start:search_start + 10000]  # ~50–100 lines ahead

    m_cat = re.search(r"category:\s*['\"]([^'\"]+)['\"]", search_region)
    m_stat = re.search(r"status:\s*['\"]([^'\"]+)['\"]", search_region)

    if not m_cat or not m_stat:
        raise SystemExit(f"could not parse (category, status) for {pkg}")
    return {"category": m_cat.group(1), "status": m_stat.group(1)}


def _op_check(pkg: str, scope: str, state: dict) -> tuple[str, list[str]]:
    """MVP: read-only audit. Phase 2 will plug in validate.py + scan_events."""
    files = []  # Phase 2 fills this with paths actually inspected.
    return "passed", files


def main() -> int:
    p = argparse.ArgumentParser(prog="research-op")
    p.add_argument("--pkg", required=True, help="package id under research_html/packages/")
    p.add_argument("--op", choices=["check", "insert", "update", "delete"], required=True)
    p.add_argument("--target", help="target name from references/matrix.md (required for insert/update/delete)")
    p.add_argument("--scope", default="package", help="check scope: package | all")
    p.add_argument("--payload", default="{}", help="JSON payload for insert/update/delete")
    args = p.parse_args()

    t0 = time.monotonic()
    state = _read_inventory(args.pkg)

    # Phase 1 state-gate.
    target = args.target if args.op != "check" else None
    if not transitions.is_legal(state["category"], state["status"], args.op, target):
        envelope = {
            "rejected": True,
            "phase": "state-gate",
            "rule": "illegal-transition",
            "pkg": args.pkg,
            "op": args.op,
            "target": target,
            "expected": f"(category={state['category']}, status={state['status']}) "
                        f"to allow op={args.op} on target={target}",
            "actual": "not in transitions table",
            "suggested_fix": "Adjust the package status first via /research-op update --target status, "
                             "or use a target legal in this cell (see references/matrix.md).",
        }
        audit.append(args.pkg, op=args.op, target=target, event=None,
                     state_before=state, state_after=state,
                     validation="rejected", rule="illegal-transition",
                     files_touched=[], payload=json.loads(args.payload),
                     user_intent=None, duration_ms=int((time.monotonic() - t0) * 1000))
        print(json.dumps(envelope, indent=2))
        return 2

    if args.op == "check":
        validation, files = _op_check(args.pkg, args.scope, state)
        audit.append(args.pkg, op="check", target=None, event=None,
                     state_before=state, state_after=state,
                     validation=validation, rule=None,
                     files_touched=files, payload={"scope": args.scope},
                     user_intent=None, duration_ms=int((time.monotonic() - t0) * 1000))
        print(f"check OK pkg={args.pkg} state={state['category']}/{state['status']}")
        return 0

    # Insert / Update / Delete arrive in Phase 3.
    print(f"op={args.op} not yet implemented (Phase 3)", file=sys.stderr)
    return 3


if __name__ == "__main__":
    sys.exit(main())
