#!/usr/bin/env python3
"""The state-backed mutation and bounded-query facade for research work."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
PIPELINE_ROOT = Path(__file__).resolve().parents[3]
for candidate in (SCRIPT_DIR, PIPELINE_ROOT, PIPELINE_ROOT / "lib"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import management  # noqa: E402


def _interface_fields(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Expose the projection receipt from the last committed domain event."""
    projection = (
        events[-1].get("_interface_projection")
        if events and isinstance(events[-1], dict)
        else None
    )
    if not isinstance(projection, dict):
        return {"interface_written": False}
    fields: dict[str, Any] = {
        "interface_written": bool(projection.get("written")),
        "interface_root": projection.get("root"),
    }
    if "files_written" in projection:
        fields["interface_files_written"] = projection["files_written"]
    if "source_seq" in projection:
        fields["interface_source_seq"] = projection["source_seq"]
    if projection.get("error"):
        fields["interface_error"] = projection["error"]
    return fields


def _error(
    exc: Exception,
    *,
    phase: str,
    package_id: str | None = None,
    operation: str | None = None,
    target: str | None = None,
    paths=None,
    payload: dict[str, Any] | None = None,
    actor: dict[str, str] | None = None,
    idempotency_key: str | None = None,
) -> int:
    audit_error: str | None = None
    if paths is not None and not bool(getattr(exc, "audited", False)):
        try:
            management.record_rejected_attempt(
                paths,
                command_name="research-op-cli",
                actor=actor or {"type": "agent", "id": "main"},
                payload={
                    "package_id": package_id,
                    "operation": operation,
                    "target": target,
                    "input": copy.deepcopy(payload or {}),
                },
                rule=str(getattr(exc, "rule", type(exc).__name__)),
                detail=str(exc),
                entry_skill="research-op/cli",
                idempotency_key=idempotency_key,
            )
            if hasattr(exc, "audited"):
                exc.audited = True
        except Exception as audit_exc:  # preserve the original rejection
            audit_error = str(audit_exc)
    print(
        json.dumps(
            {
                "rejected": True,
                "phase": phase,
                "rule": getattr(exc, "rule", type(exc).__name__),
                "pkg": package_id,
                "op": operation,
                "target": target,
                "detail": str(exc),
                **({"audit_error": audit_error} if audit_error else {}),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 2


def _management_query(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog=f"research-op {argv[0]}")
    parser.add_argument("command", choices=("show", "context", "history", "audit"))
    parser.add_argument("subject")
    parser.add_argument("aggregate_id", nargs="?")
    parser.add_argument("--phase")
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--research-root")
    args = parser.parse_args(argv)
    from lib.research_state import ResearchPaths, StateQuery

    paths = ResearchPaths.resolve(
        workspace=args.workspace,
        research_root=args.research_root,
    )
    query = StateQuery(paths)
    try:
        if args.command == "show":
            result = query.show(args.subject, args.aggregate_id)
        elif args.command == "context":
            if args.aggregate_id is not None:
                parser.error("context accepts one package id")
            result = query.context(args.subject, phase=args.phase)
        elif args.command == "history":
            if args.aggregate_id is not None or "/" not in args.subject:
                parser.error("history requires <type>/<id>")
            aggregate_type, aggregate_id = args.subject.split("/", 1)
            result = query.history(aggregate_type, aggregate_id)
        else:
            if args.aggregate_id is not None:
                parser.error("audit accepts one command id")
            result = query.audit(args.subject)
    except Exception as exc:
        return _error(exc, phase="query")
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="research-op")
    parser.add_argument("--pkg")
    parser.add_argument(
        "--op",
        choices=[
            "check",
            "insert",
            "update",
            "delete",
            "scan-events",
            "scope-accept",
            "scope-transition",
            "package-finalize",
            "registry-add",
            "evolution-observe",
            "evolution-create",
            "evolution-evidence-add",
            "evolution-transition",
            "evolution-project",
            "evolution-check",
            "evolution-approve",
            "evolution-install-skill",
            "evolution-suspend-skill",
            "evolution-rollback-skill",
        ],
    )
    parser.add_argument("--event")
    parser.add_argument("--target")
    parser.add_argument("--scope", default="package")
    parser.add_argument("--payload", default="{}")
    parser.add_argument("--from-triage")
    parser.add_argument("--proposal-hash")
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--research-root")
    parser.add_argument("--idempotency-key")
    parser.add_argument("--expected-version", type=int)
    parser.add_argument(
        "--actor-type",
        choices=("user", "agent", "system"),
        default="agent",
    )
    parser.add_argument("--actor-id", default="main")
    parser.add_argument("--nl")
    return parser


def _payload(raw: str) -> dict[str, Any]:
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("--payload must be a JSON object")
    return value


def _evolution(args: argparse.Namespace, payload: dict[str, Any], paths) -> int:
    """Route project memory to state; keep only skill bundles outside it."""
    from ops import evolution

    try:
        status, files, message = evolution.run(
            args.op,
            payload,
            paths,
            project_root=paths.workspace,
        )
    except evolution.EvolutionReject as exc:
        return _error(
            exc,
            phase="evolution-validate",
            package_id=args.pkg,
            operation=args.op,
            paths=paths,
            payload=payload,
            actor={"type": args.actor_type, "id": args.actor_id},
            idempotency_key=args.idempotency_key,
        )
    print(
        json.dumps(
            {
                "ok": True,
                "op": args.op,
                "status": status,
                "message": message,
                "files": files,
            },
            ensure_ascii=False,
        )
    )
    return 0


def _scope_transition(args: argparse.Namespace, paths, payload) -> int:
    if args.pkg != "_scope":
        return _error(
            ValueError("scope-transition requires --pkg _scope"),
            phase="scope-gate",
            package_id=args.pkg,
            operation=args.op,
            paths=paths,
            payload=payload,
            actor={"type": args.actor_type, "id": args.actor_id},
            idempotency_key=args.idempotency_key,
        )
    try:
        if not args.from_triage:
            raise ValueError(
                "scope-transition requires --from-triage <accepted-proposal-id>"
            )
        payload, causation_id = management.accepted_scope_payload(
            paths,
            args.from_triage,
        )
        event, record, idempotent = management.commit_scope_transition(
            paths,
            payload,
            actor={"type": args.actor_type, "id": args.actor_id},
            idempotency_key=args.idempotency_key,
            expected_version=args.expected_version,
            causation_id=causation_id,
        )
    except Exception as exc:
        return _error(
            exc,
            phase="scope-gate",
            package_id=args.pkg,
            operation=args.op,
            paths=paths,
            payload=payload,
            actor={"type": args.actor_type, "id": args.actor_id},
            idempotency_key=args.idempotency_key,
        )
    print(
        json.dumps(
            {
                "ok": True,
                "op": "scope-transition",
                "aggregate": f"{event['aggregate_type']}/{event['aggregate_id']}",
                "event_id": event["event_id"],
                "aggregate_version": event["aggregate_version"],
                "idempotent": idempotent,
                "record": record,
                **_interface_fields([event]),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def _scope_accept(args: argparse.Namespace, paths, payload) -> int:
    """Accept one visible proposal and commit its bound Scope snapshot."""
    actor = {"type": args.actor_type, "id": args.actor_id}
    if args.pkg != "_scope":
        return _error(
            ValueError("scope-accept requires --pkg _scope"),
            phase="scope-accept",
            package_id=args.pkg,
            operation=args.op,
            paths=paths,
            payload=payload,
            actor=actor,
            idempotency_key=args.idempotency_key,
        )
    try:
        if not args.from_triage:
            raise ValueError(
                "scope-accept requires --from-triage <pending-proposal-id>"
            )
        if not args.proposal_hash:
            raise ValueError(
                "scope-accept requires --proposal-hash <visible-proposal-hash>"
            )
        disposition, _accepted_event = management.dispose_proposal(
            paths,
            args.from_triage,
            "ACCEPTED",
            args.proposal_hash,
            actor=actor,
        )
        accepted_payload, causation_id = management.accepted_scope_payload(
            paths,
            args.from_triage,
        )
        event, record, idempotent = management.commit_scope_transition(
            paths,
            accepted_payload,
            actor=actor,
            idempotency_key=args.idempotency_key,
            expected_version=args.expected_version,
            causation_id=causation_id,
        )
    except Exception as exc:
        return _error(
            exc,
            phase="scope-accept",
            package_id=args.pkg,
            operation=args.op,
            paths=paths,
            payload={
                "proposal_id": args.from_triage,
                "proposal_hash": args.proposal_hash,
            },
            actor=actor,
            idempotency_key=args.idempotency_key,
        )
    print(
        json.dumps(
            {
                "ok": True,
                "op": "scope-accept",
                "disposition": disposition,
                "proposal_id": args.from_triage,
                "scope_id": record.get("id"),
                "level": record.get("level"),
                "event_id": event["event_id"],
                "aggregate_version": event["aggregate_version"],
                "idempotent": idempotent,
                **_interface_fields([event]),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def _package_finalize(args: argparse.Namespace, paths, payload) -> int:
    """Approve one full proposal and commit Scope plus Package activation."""
    actor = {"type": args.actor_type, "id": args.actor_id}
    try:
        if not args.from_triage:
            raise ValueError(
                "package-finalize requires --from-triage <pending-proposal-id>"
            )
        if not args.proposal_hash:
            raise ValueError(
                "package-finalize requires --proposal-hash <visible-proposal-hash>"
            )
        event = management.finalize_draft_package(
            paths,
            str(args.pkg),
            args.from_triage,
            args.proposal_hash,
            actor=actor,
            idempotency_key=args.idempotency_key,
        )
    except Exception as exc:
        return _error(
            exc,
            phase="package-finalize",
            package_id=args.pkg,
            operation=args.op,
            paths=paths,
            payload={
                "proposal_id": args.from_triage,
                "proposal_hash": args.proposal_hash,
            },
            actor=actor,
            idempotency_key=args.idempotency_key,
        )
    finalization = event["payload"]["scope_finalization"]
    print(
        json.dumps(
            {
                "ok": True,
                "op": "package-finalize",
                "package_id": args.pkg,
                "proposal_id": args.from_triage,
                "direction_id": finalization["direction"]["aggregate_id"],
                "experiment_ids": [
                    row["aggregate_id"]
                    for row in finalization["experiments"]
                ],
                "event_id": event["event_id"],
                "lifecycle": event["payload"]["record"]["lifecycle"],
                "phase": event["payload"]["record"]["phase"],
                **_interface_fields([event]),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def _registry_add(args: argparse.Namespace, paths, payload) -> int:
    try:
        status, record, event = management.commit_registry_add(
            paths,
            args.target or "",
            payload,
            package_id=str(args.pkg),
            actor={"type": args.actor_type, "id": args.actor_id},
            idempotency_key=args.idempotency_key,
        )
    except Exception as exc:
        return _error(
            exc,
            phase="registry-validate",
            package_id=args.pkg,
            operation=args.op,
            target=args.target,
            paths=paths,
            payload=payload,
            actor={"type": args.actor_type, "id": args.actor_id},
            idempotency_key=args.idempotency_key,
        )
    print(
        json.dumps(
            {
                "ok": True,
                "op": args.op,
                "status": status,
                "aggregate": f"{event['aggregate_type']}/{event['aggregate_id']}",
                "event_id": event["event_id"],
                "record": record,
                **_interface_fields([event]),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def _check(args: argparse.Namespace, paths) -> int:
    from lib.research_state import StateQuery

    try:
        if args.pkg == "_project":
            result = StateQuery(paths).show("rule")
        else:
            result = StateQuery(paths).context(str(args.pkg))
    except Exception as exc:
        return _error(
            exc,
            phase="state-check",
            package_id=args.pkg,
            operation="check",
            target=args.target,
            paths=paths,
            payload={},
            actor={"type": args.actor_type, "id": args.actor_id},
            idempotency_key=args.idempotency_key,
        )
    print(
        json.dumps(
            {
                "ok": True,
                "scope": args.scope,
                **result,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def _scan_events(args: argparse.Namespace, paths) -> int:
    from lib.experiments.reconcile import reconcile_runs

    try:
        result = reconcile_runs(paths)
    except Exception as exc:
        return _error(
            exc,
            phase="run-reconcile",
            package_id=args.pkg,
            operation="scan-events",
            paths=paths,
            payload={},
            actor={"type": args.actor_type, "id": args.actor_id},
            idempotency_key=args.idempotency_key,
        )
    actions = [
        {
            "run_id": action.run_id,
            "event_type": action.event_type,
            "event_id": action.event_id,
        }
        for action in result.actions
    ]
    print(
        json.dumps(
            {
                "ok": not result.errors,
                "scanned": result.scanned,
                "actions": actions,
                "errors": list(result.errors),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 2 if result.errors else 0


def _chosen_route(args: argparse.Namespace, paths, payload) -> list[dict[str, Any]]:
    decision = management.commit_decision(
        paths,
        str(args.pkg),
        payload,
        actor={"type": args.actor_type, "id": args.actor_id},
        idempotency_key=(
            f"{args.idempotency_key}:decision"
            if args.idempotency_key
            else None
        ),
    )
    return [decision]


def _doc_payload(paths, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
    if operation == "delete":
        return payload
    content = payload.get("content")
    if content is None:
        content = payload.get("html")
    if not isinstance(content, str):
        raise ValueError("doc-file requires string content")
    slug = str(payload.get("slug") or "")
    if not slug:
        raise ValueError("doc-file requires slug")
    path = str(payload.get("path") or f"docs/{slug}.html")
    if not path.startswith("docs/") or ".." in Path(path).parts:
        raise ValueError("doc-file path must stay below docs/")
    note_ref = management.write_note(
        paths,
        content,
        mime="text/html" if path.endswith(".html") else "text/markdown",
        title=str(payload.get("title") or slug),
    )
    return {
        **copy.deepcopy(payload),
        "path": path,
        "_note_ref": note_ref,
    }


def _event(args: argparse.Namespace, paths, payload) -> int:
    event_name = str(args.event or "").upper().replace("-", "_")
    try:
        if event_name == "RUN_RESULT_FINALIZED":
            events = management.propagate_run_result(
                paths,
                str(args.pkg),
                str(payload.get("run_id") or ""),
                actor={"type": args.actor_type, "id": args.actor_id},
            )
        elif event_name == "CHAIN_DONE":
            run_id = str(payload.get("run_id") or "")
            state = __import__(
                "lib.research_state",
                fromlist=["EventStore"],
            ).EventStore(paths).state()
            run = state["aggregates"]["run"].get(run_id)
            if not isinstance(run, dict) or run.get("package_id") != args.pkg:
                raise ValueError("CHAIN_DONE requires a package-owned run_id")
            if run.get("status") not in {"COMPLETED", "FAILED", "HALTED", "SKIPPED"}:
                raise ValueError("CHAIN_DONE requires a terminal run")
            events = management.apply_package_operation(
                paths,
                str(args.pkg),
                operation="update",
                target="lastAction",
                payload={"to": f"run {run_id} terminal: {run.get('status')}"},
                actor={"type": args.actor_type, "id": args.actor_id},
                idempotency_key=args.idempotency_key,
            )
        elif event_name in {
            "CHECKPOINT_SAVED",
            "CANDIDATE_SUBMITTED",
            "SENTINEL_WRITE",
            "PHASE_MARKER",
        }:
            # These are evidence observations, never scientific verdicts.
            events = management.apply_package_operation(
                paths,
                str(args.pkg),
                operation="update",
                target="lastAction",
                payload={
                    "to": f"{event_name}: {payload.get('artifact') or payload.get('run_id') or 'recorded'}"
                },
                actor={"type": args.actor_type, "id": args.actor_id},
                idempotency_key=args.idempotency_key,
            )
        else:
            raise ValueError(f"unknown composite event: {args.event}")
    except Exception as exc:
        return _error(
            exc,
            phase="event-fanout",
            package_id=args.pkg,
            operation="event",
            target=args.event,
            paths=paths,
            payload=payload,
            actor={"type": args.actor_type, "id": args.actor_id},
            idempotency_key=args.idempotency_key,
        )
    print(
        json.dumps(
            {
                "ok": True,
                "event": event_name,
                "events": [
                    {
                        "event_id": event["event_id"],
                        "event_type": event["event_type"],
                        "aggregate": (
                            f"{event['aggregate_type']}/{event['aggregate_id']}"
                        ),
                    }
                    for event in events
                ],
                **_interface_fields(events),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in {"show", "context", "history", "audit"}:
        return _management_query(argv)
    parser = _parser()
    args = parser.parse_args(argv)
    if args.nl:
        print(
            "Translate the request into explicit --pkg/--op/--target/--payload "
            "using the research-op contract.",
            file=sys.stderr,
        )
        return 4
    if not args.pkg:
        parser.error("--pkg is required")
    if bool(args.op) == bool(args.event):
        parser.error("choose exactly one of --op or --event")
    from lib.research_state import ResearchPaths

    paths = ResearchPaths.resolve(
        workspace=args.workspace,
        research_root=args.research_root,
    )
    try:
        payload = _payload(args.payload)
    except (ValueError, json.JSONDecodeError) as exc:
        raw = args.payload.encode("utf-8")
        return _error(
            exc,
            phase="payload-validate",
            package_id=args.pkg,
            operation=args.op or "event",
            target=args.target or args.event,
            paths=paths,
            payload={
                "raw_payload_sha256": hashlib.sha256(raw).hexdigest(),
                "size_bytes": len(raw),
            },
            actor={"type": args.actor_type, "id": args.actor_id},
            idempotency_key=args.idempotency_key,
        )
    if args.op and args.op.startswith("evolution-"):
        return _evolution(args, payload, paths)
    if args.op == "scope-accept":
        return _scope_accept(args, paths, payload)
    if args.op == "scope-transition":
        return _scope_transition(args, paths, payload)
    if args.op == "package-finalize":
        return _package_finalize(args, paths, payload)
    if args.op == "registry-add":
        return _registry_add(args, paths, payload)
    if args.op == "check":
        return _check(args, paths)
    if args.op == "scan-events":
        return _scan_events(args, paths)
    if args.event:
        return _event(args, paths, payload)
    if not args.target:
        parser.error("--target is required for insert/update/delete")

    try:
        if args.target == "rule":
            events = [
                management.commit_rule_operation(
                    paths,
                    str(args.pkg),
                    str(args.op),
                    payload,
                    actor={"type": args.actor_type, "id": args.actor_id},
                    idempotency_key=args.idempotency_key,
                )
            ]
        elif args.target == "tracker-chosen-route":
            if args.op != "insert":
                raise ValueError("tracker-chosen-route is insert-only")
            events = _chosen_route(args, paths, payload)
        elif args.target == "analysis-insight":
            learning = management.commit_learning_operation(
                paths,
                str(args.pkg),
                str(args.op),
                payload,
                actor={"type": args.actor_type, "id": args.actor_id},
                idempotency_key=(
                    f"{args.idempotency_key}:learning"
                    if args.idempotency_key
                    else None
                ),
            )
            events = [learning]
        elif args.target == "tracker-impl-review-row":
            change = management.commit_change_operation(
                paths,
                str(args.pkg),
                str(args.op),
                payload,
                actor={"type": args.actor_type, "id": args.actor_id},
                idempotency_key=(
                    f"{args.idempotency_key}:change"
                    if args.idempotency_key
                    else None
                ),
            )
            events = [change]
        elif args.target == "results-verdict":
            if args.op != "update":
                raise ValueError(
                    "results-verdict is an immutable Decision and requires --op update"
                )
            verdict = management.commit_verifier_decision(
                paths,
                str(args.pkg),
                payload,
                actor={"type": args.actor_type, "id": args.actor_id},
                idempotency_key=(
                    f"{args.idempotency_key}:verifier"
                    if args.idempotency_key
                    else None
                ),
            )
            events = [verdict]
        elif args.target == "approval-ack-slot":
            if args.op == "delete":
                raise ValueError(
                    "acknowledgements are immutable decisions and cannot be deleted"
                )
            acknowledgement = management.commit_acknowledgement(
                paths,
                str(args.pkg),
                payload,
                actor={"type": args.actor_type, "id": args.actor_id},
                idempotency_key=(
                    f"{args.idempotency_key}:decision"
                    if args.idempotency_key
                    else None
                ),
            )
            events = [acknowledgement]
        else:
            if args.target == "doc-file":
                payload = _doc_payload(paths, str(args.op), payload)
            events = management.apply_package_operation(
                paths,
                str(args.pkg),
                operation=str(args.op),
                target=str(args.target),
                payload=payload,
                actor={"type": args.actor_type, "id": args.actor_id},
                idempotency_key=args.idempotency_key,
                expected_version=args.expected_version,
            )
    except Exception as exc:
        return _error(
            exc,
            phase="package-gate",
            package_id=args.pkg,
            operation=args.op,
            target=args.target,
            paths=paths,
            payload=payload,
            actor={"type": args.actor_type, "id": args.actor_id},
            idempotency_key=args.idempotency_key,
        )

    print(
        json.dumps(
            {
                "ok": True,
                "op": args.op,
                "pkg": args.pkg,
                "target": args.target,
                "events": [
                    {
                        "event_id": event["event_id"],
                        "event_type": event["event_type"],
                        "aggregate": (
                            f"{event['aggregate_type']}/{event['aggregate_id']}"
                        ),
                    }
                    for event in events
                ],
                **_interface_fields(events),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
