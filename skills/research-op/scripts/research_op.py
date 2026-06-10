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
    p.add_argument("--pkg", help="package id under research_html/packages/ (required unless --nl)")
    p.add_argument("--op", choices=["check", "insert", "update", "delete", "scan-events",
                                    "scope-transition", "registry-add",
                                    "evolution-observe", "evolution-create",
                                    "evolution-evidence-add", "evolution-transition",
                                    "evolution-project", "evolution-check",
                                    "evolution-approve", "evolution-install-skill",
                                    "evolution-suspend-skill", "evolution-rollback-skill"],
                   help="primitive op (one of --op or --event required)")
    p.add_argument("--event", help="composite event (chain-done, checkpoint-saved, ...) "
                   "(one of --op or --event required)")
    p.add_argument("--target", help="target name from references/matrix.md (required for insert/update/delete)")
    p.add_argument("--scope", default="package", help="check scope: package | all")
    p.add_argument("--payload", default="{}", help="JSON payload for insert/update/delete")
    p.add_argument("--nl", help="natural-language form: e.g. 'update: set status of <pkg> to BLOCKED'")
    args = p.parse_args()

    # NL escape hatch — real parsing lives in the SKILL.md body (the agent reads the prose,
    # produces the structured form, and calls the CLI again with explicit --pkg/--op/--target/--payload).
    if args.nl:
        print("Natural-language parsing is best done from the SKILL.md body. "
              "Re-invoke with explicit --pkg / --op / --target / --payload.", file=sys.stderr)
        return 4

    if not args.pkg:
        print("error: --pkg is required (unless --nl)", file=sys.stderr)
        return 1

    t0 = time.monotonic()

    # Self-evolve path — project-level Rule Store ops. Like scope-transition/registry-add
    # these are cross-package, so they bypass the package (category, status) state machine.
    # `--pkg _selfevolve` is a synthetic project-level context with no inventory entry, so
    # this branch runs BEFORE _read_inventory (which would raise on a non-package pkg).
    if args.op and args.op.startswith("evolution-"):
        sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
        from ops import evolution  # noqa: E402
        try:
            payload = json.loads(args.payload)
        except json.JSONDecodeError as e:
            print(json.dumps({"rejected": True, "phase": "evolution-validate",
                              "rule": "payload-json-valid", "pkg": args.pkg, "op": args.op,
                              "detail": str(e)}, indent=2))
            return 2
        root = audit.runtime_root("_selfevolve")
        try:
            status_, files, message = evolution.run(args.op, payload, root)
        except evolution.EvolutionReject as e:
            audit.append("_selfevolve", op=args.op, target=None, event=None,
                         state_before={}, state_after={}, validation="OP_REJECTED", rule=e.rule,
                         files_touched=[], payload=payload, user_intent=None,
                         duration_ms=int((time.monotonic() - t0) * 1000))
            print(json.dumps({"rejected": True, "phase": "evolution-validate", "rule": e.rule,
                              "pkg": args.pkg, "op": args.op, "detail": e.detail}, indent=2))
            return 2
        audit.append("_selfevolve", op=args.op, target=None, event=None,
                     state_before={}, state_after={}, validation="PASSED", rule=None,
                     files_touched=files, payload=payload, user_intent=None,
                     duration_ms=int((time.monotonic() - t0) * 1000))
        print(f"{args.op} {status_}: {message}")
        return 0

    state = _read_inventory(args.pkg)

    # Scan-events path (read-only, no state-gate, no validation).
    if args.op == "scan-events":
        import scan_events  # noqa: E402
        found = scan_events.scan(args.pkg)
        for ev in found:
            print(json.dumps(ev))
        # Caller is expected to invoke --event for each; bump only after the agent confirms.
        return 0

    # Scope-transition path — the one gated writer for the Scope SSOT. Gated by node level
    # (not the package (category, status) state machine), so it bypasses the state-gate.
    if args.op == "scope-transition":
        sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
        import scope_ssot  # noqa: E402
        payload = json.loads(args.payload)
        node = {k: payload[k] for k in ("id", "level", "parents", "version", "status",
                                        "yardstick", "provenance") if k in payload}
        log_path = audit.runtime_root("_scope") / "transitions.jsonl"
        try:
            record = scope_ssot.propose_transition(
                node, op=payload.get("op"), gate=payload.get("gate"), log_path=log_path,
                trigger=payload.get("trigger"), cause=payload.get("cause"),
                invalidates=payload.get("invalidates"), reopens=payload.get("reopens"),
                dial_revert=payload.get("dial_revert"))
        except scope_ssot.RuleViolation as e:
            audit.append(args.pkg, op="scope-transition", target=node.get("id"), event=None,
                         state_before=state, state_after=state,
                         validation="OP_REJECTED", rule="scope-gate",
                         files_touched=[], payload=payload,
                         user_intent=None, duration_ms=int((time.monotonic() - t0) * 1000))
            print(json.dumps({
                "rejected": True, "phase": "scope-gate", "rule": "scope-gate",
                "pkg": args.pkg, "op": "scope-transition", "node_id": node.get("id"),
                "detail": str(e),
            }, indent=2))
            return 2
        audit.append(args.pkg, op="scope-transition", target=node.get("id"), event=None,
                     state_before=state, state_after=state,
                     validation="PASSED", rule=None,
                     files_touched=[str(log_path)], payload=payload,
                     user_intent=None, duration_ms=int((time.monotonic() - t0) * 1000))
        print(f"scope-transition OK node={node.get('id')} txn={record['transaction_id']}")
        return 0

    # Registry-add path — project-level knowledge stores (papers / edges / gaps). Like
    # scope-transition these are cross-package, so they bypass the package (category, status)
    # state-gate; reject-before-write validators live in registry.py.
    if args.op == "registry-add":
        import registry  # noqa: E402
        try:
            payload = json.loads(args.payload)
        except json.JSONDecodeError as e:
            print(json.dumps({"rejected": True, "phase": "registry-validate", "rule": "payload-json-valid",
                              "pkg": args.pkg, "op": "registry-add", "target": args.target,
                              "detail": str(e)}, indent=2))
            return 2
        try:
            status_, record, path = registry.add(args.target, payload)
        except registry.RegistryReject as e:
            audit.append(args.pkg, op="registry-add", target=args.target, event=None,
                         state_before=state, state_after=state, validation="OP_REJECTED", rule=e.rule,
                         files_touched=[], payload=payload, user_intent=None,
                         duration_ms=int((time.monotonic() - t0) * 1000))
            print(json.dumps({"rejected": True, "phase": "registry-validate", "rule": e.rule,
                              "pkg": args.pkg, "op": "registry-add", "target": args.target,
                              "detail": e.detail}, indent=2))
            return 2
        audit.append(args.pkg, op="registry-add", target=args.target, event=None,
                     state_before=state, state_after=state, validation="PASSED", rule=None,
                     files_touched=[str(path)] if status_ == "added" else [], payload=payload,
                     user_intent=None, duration_ms=int((time.monotonic() - t0) * 1000))
        print(f"registry-add {status_} target={args.target} store={path}")
        return 0

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
        return 0 if validation == "PASSED" else 2

    # Universal pre-checks (must run before state-gate so malformed inputs produce envelopes).
    rej_json = validate.rule_payload_json_valid(args.pkg, args.op, args.target, args.payload)
    if rej_json:
        audit.append(args.pkg, op=args.op, target=args.target, event=None,
                     state_before=state, state_after=state,
                     validation="OP_REJECTED", rule=rej_json.rule,
                     files_touched=[], payload={"_raw": args.payload},
                     user_intent=None, duration_ms=int((time.monotonic() - t0) * 1000))
        print(json.dumps(rej_json.envelope(op=args.op, target=args.target, phase="universal-check"), indent=2))
        return 2
    target = args.target if args.op != "check" else None
    rej_tgt = validate.rule_target_known(args.pkg, args.op, target, json.loads(args.payload), transitions.TARGETS)
    if rej_tgt:
        audit.append(args.pkg, op=args.op, target=target, event=None,
                     state_before=state, state_after=state,
                     validation="OP_REJECTED", rule=rej_tgt.rule,
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
                     validation="OP_REJECTED", rule="illegal-transition",
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
                         validation="OP_REJECTED", rule=rej.rule,
                         files_touched=[], payload=payload,
                         user_intent=None, duration_ms=int((time.monotonic() - t0) * 1000))
            print(json.dumps(rej.envelope(op=args.op, target=target), indent=2))
            return 2

    # Phase 3 dispatch — router calls into ops/<op>.py.
    import router  # noqa: E402
    validation, files = router.dispatch(args.op, args.pkg, target, payload, state)
    audit.append(args.pkg, op=args.op, target=target, event=None,
                 state_before=state, state_after=state,
                 validation="PASSED", rule=None,
                 files_touched=files, payload=payload,
                 user_intent=None, duration_ms=int((time.monotonic() - t0) * 1000))
    print(f"{args.op} OK pkg={args.pkg} target={target} files={files}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
