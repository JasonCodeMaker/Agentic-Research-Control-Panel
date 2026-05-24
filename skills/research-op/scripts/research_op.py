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
import validate


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


def main() -> int:
    p = argparse.ArgumentParser(prog="research-op")
    p.add_argument("--pkg", required=True, help="package id under research_html/packages/")
    p.add_argument("--op", choices=["check", "insert", "update", "delete"],
                   help="primitive op (one of --op or --event required)")
    p.add_argument("--event", help="composite event (chain-done, checkpoint-saved, ...) "
                   "(one of --op or --event required)")
    p.add_argument("--target", help="target name from references/matrix.md (required for insert/update/delete)")
    p.add_argument("--scope", default="package", help="check scope: package | all")
    p.add_argument("--payload", default="{}", help="JSON payload for insert/update/delete")
    args = p.parse_args()

    t0 = time.monotonic()
    state = _read_inventory(args.pkg)

    if not args.op and not args.event:
        print("error: one of --op or --event is required", file=sys.stderr)
        return 1
    if args.op and args.event:
        print("error: cannot use --op and --event together", file=sys.stderr)
        return 1

    # Composite event path
    if args.event:
        import events  # noqa: E402
        import router as _router  # noqa: E402
        payload_obj = json.loads(args.payload)
        validation, files = events.fanout(args.event, args.pkg, payload_obj,
                                          dispatch_fn=lambda o, p, t, pl: _router.dispatch(o, p, t, pl, state))
        audit.append(args.pkg, op="event", target=None, event=args.event,
                     state_before=state, state_after=state,
                     validation=validation, rule=None,
                     files_touched=files, payload=payload_obj,
                     user_intent=None, duration_ms=int((time.monotonic() - t0) * 1000))
        print(f"event={args.event} OK files={files}")
        return 0 if validation == "passed" else 2

    # Universal pre-checks (must run before state-gate so malformed inputs produce envelopes).
    rej_json = validate.rule_payload_json_valid(args.pkg, args.op, args.target, args.payload)
    if rej_json:
        audit.append(args.pkg, op=args.op, target=args.target, event=None,
                     state_before=state, state_after=state,
                     validation="rejected", rule=rej_json.rule,
                     files_touched=[], payload={"_raw": args.payload},
                     user_intent=None, duration_ms=int((time.monotonic() - t0) * 1000))
        print(json.dumps(rej_json.envelope(op=args.op, target=args.target, phase="universal-check"), indent=2))
        return 2
    target = args.target if args.op != "check" else None
    rej_tgt = validate.rule_target_known(args.pkg, args.op, target, json.loads(args.payload), transitions.TARGETS)
    if rej_tgt:
        audit.append(args.pkg, op=args.op, target=target, event=None,
                     state_before=state, state_after=state,
                     validation="rejected", rule=rej_tgt.rule,
                     files_touched=[], payload=json.loads(args.payload),
                     user_intent=None, duration_ms=int((time.monotonic() - t0) * 1000))
        print(json.dumps(rej_tgt.envelope(op=args.op, target=target, phase="universal-check"), indent=2))
        return 2

    # Phase 1 state-gate.
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

    payload = json.loads(args.payload)

    # For check op, inject scope into payload so the handler can access it.
    if args.op == "check":
        payload["scope"] = args.scope

    # Phase 2 invariant check — SKIP for check op (no payload to validate).
    if args.op != "check":
        rej = validate.validate(args.pkg, args.op, target, payload, state)
        if rej:
            audit.append(args.pkg, op=args.op, target=target, event=None,
                         state_before=state, state_after=state,
                         validation="rejected", rule=rej.rule,
                         files_touched=[], payload=payload,
                         user_intent=None, duration_ms=int((time.monotonic() - t0) * 1000))
            print(json.dumps(rej.envelope(op=args.op, target=target), indent=2))
            return 2

    # Phase 3 dispatch — router calls into ops/<op>.py.
    import router  # noqa: E402
    validation, files = router.dispatch(args.op, args.pkg, target, payload, state)
    audit.append(args.pkg, op=args.op, target=target, event=None,
                 state_before=state, state_after=state,
                 validation=validation, rule=None,
                 files_touched=files, payload=payload,
                 user_intent=None, duration_ms=int((time.monotonic() - t0) * 1000))
    print(f"{args.op} OK pkg={args.pkg} target={target} files={files}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
