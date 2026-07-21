#!/usr/bin/env python3
"""Event-backed pre-package brainstorms and Direction proposal shaping.

Brainstorms are management records.  This module never reads or writes the
generated interface; ``lib.interface`` owns the HTML/JS projection.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PIPELINE_ROOT = Path(__file__).resolve().parents[3]
if str(PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(PIPELINE_ROOT))
if str(PIPELINE_ROOT / "lib") not in sys.path:
    sys.path.insert(0, str(PIPELINE_ROOT / "lib"))
RESEARCH_OP_SCRIPTS = PIPELINE_ROOT / "skills" / "research-op" / "scripts"
if str(RESEARCH_OP_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(RESEARCH_OP_SCRIPTS))

from lib.interface.project import validate_brainstorm_document_fragment  # noqa: E402
from lib.research_state import ResearchPaths, StateQuery  # noqa: E402
from lib.research_state.io import canonical_json  # noqa: E402
import management  # noqa: E402
import scope_ssot  # noqa: E402


DIRECTION_FIELDS = ("hypothesis", "metric", "baselines", "success_gate")


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "idea"


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _created_date(entry: dict[str, Any]) -> str:
    created_at = str(entry.get("created_at") or "")
    if re.match(r"^\d{4}-\d{2}-\d{2}", created_at):
        return created_at[:10]
    return datetime.now(timezone.utc).date().isoformat()


def brainstorm_detail_path(entry: dict[str, Any]) -> str:
    """Return the stable interface-relative detail path rendered later."""
    return f"brainstorm/{_created_date(entry)}-{entry['id']}.html"


def _coerce_paths(
    value: ResearchPaths | str | Path | None = None,
    *,
    workspace: str | Path = ".",
    research_root: str | Path | None = None,
) -> ResearchPaths:
    if isinstance(value, ResearchPaths):
        return value
    if value is not None:
        workspace = Path(value).expanduser()
    return ResearchPaths.resolve(workspace=workspace, research_root=research_root)


def read_brainstorms(
    root: ResearchPaths | str | Path | None = None,
    *,
    include_archived: bool = False,
    workspace: str | Path = ".",
    research_root: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Read brainstorm aggregates; generated interface files are never consulted."""
    paths = _coerce_paths(
        root,
        workspace=workspace,
        research_root=research_root,
    )
    return StateQuery(paths).brainstorms(
        include_archived=include_archived,
    )["data"]["items"]


def _materialize_document_note(
    paths: ResearchPaths,
    record: dict[str, Any],
    *,
    idea_id: str,
) -> None:
    """Replace transient document_html input with one verified NoteRef."""
    if "document_html" not in record:
        return
    raw = record.pop("document_html")
    if not isinstance(raw, str):
        raise ValueError("document_html must be a string")
    body = validate_brainstorm_document_fragment(raw)
    record["document_note"] = management.write_note(
        paths,
        body,
        mime="text/html;profile=brainstorm-fragment",
        title=f"Brainstorm body: {idea_id}",
    )


def add_brainstorm(
    root: ResearchPaths | str | Path | None,
    record: dict[str, Any],
    *,
    actor: dict[str, str] | None = None,
) -> str:
    """Commit ``BrainstormCreated`` and return its stable id."""
    paths = _coerce_paths(root)
    management.initialize(paths)
    view = StateQuery(paths).brainstorms(include_archived=True)["data"]
    existing = {str(row["id"]) for row in view["items"]}
    idea_id = str(record.get("id") or _slug(str(record.get("title") or "idea")))
    if idea_id in existing:
        base = idea_id
        suffix = 2
        while f"{base}-{suffix}" in existing:
            suffix += 1
        idea_id = f"{base}-{suffix}"
    entry = copy.deepcopy(record)
    entry["id"] = idea_id
    entry.setdefault("created_at", datetime.now(timezone.utc).isoformat())
    entry.setdefault("updated_at", entry["created_at"])
    entry.setdefault("page_language", "en")
    entry.setdefault("status", "ACTIVE")
    entry.setdefault("detailPath", brainstorm_detail_path(entry))
    _materialize_document_note(paths, entry, idea_id=idea_id)
    management.create_brainstorm(
        paths,
        idea_id,
        entry,
        actor=actor or {"type": "agent", "id": "research-brainstorm"},
        idempotency_key=f"brainstorm:create:{idea_id}:{_digest(entry)}",
    )
    return idea_id


def revise_brainstorm(
    root: ResearchPaths | str | Path | None,
    idea_id: str,
    patch: dict[str, Any],
    *,
    actor: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Commit a bounded ``BrainstormRevised`` patch."""
    if not isinstance(patch, dict) or not patch:
        raise ValueError("brainstorm revision requires a non-empty patch object")
    forbidden = {"id", "status", "archived_at"}
    illegal = sorted(forbidden.intersection(patch))
    if illegal:
        raise ValueError(f"brainstorm revision cannot change {illegal}")
    paths = _coerce_paths(root)
    view = StateQuery(paths).brainstorms(
        idea_id=idea_id,
        include_archived=True,
    )["data"]
    current = view["items"][0] if view["items"] else None
    if not isinstance(current, dict):
        raise KeyError(f"unknown brainstorm: {idea_id}")
    if current.get("status") == "ARCHIVED":
        raise ValueError(f"cannot revise archived brainstorm: {idea_id}")
    revision = copy.deepcopy(patch)
    revision.setdefault("updated_at", datetime.now(timezone.utc).isoformat())
    _materialize_document_note(paths, revision, idea_id=idea_id)
    version = int(view["versions"].get(idea_id, 0))
    event = management.revise_brainstorm(
        paths,
        idea_id,
        revision,
        expected_version=version,
        actor=actor or {"type": "agent", "id": "research-brainstorm"},
        idempotency_key=(
            f"brainstorm:revise:{idea_id}:v{version + 1}:{_digest(revision)}"
        ),
    )
    return event


def remove_brainstorm(
    root: ResearchPaths | str | Path | None,
    idea_id: str,
    *,
    reason: str = "removed from active brainstorm lane",
    merged_into: str | None = None,
    actor: dict[str, str] | None = None,
) -> bool:
    """Archive one idea semantically; never delete history or interface files."""
    paths = _coerce_paths(root)
    view = StateQuery(paths).brainstorms(
        idea_id=idea_id,
        include_archived=True,
    )["data"]
    current = view["items"][0] if view["items"] else None
    if not isinstance(current, dict) or current.get("status") == "ARCHIVED":
        return False
    version = int(view["versions"].get(idea_id, 0))
    patch = {
        "archived_at": datetime.now(timezone.utc).isoformat(),
        "archive_reason": reason,
    }
    if merged_into:
        if merged_into == idea_id:
            raise ValueError("a Brainstorm cannot be merged into itself")
        target_view = StateQuery(paths).brainstorms(
            idea_id=merged_into,
            include_archived=True,
        )["data"]
        target = target_view["items"][0] if target_view["items"] else None
        if not isinstance(target, dict) or target.get("status") == "ARCHIVED":
            raise ValueError(f"merged-into Brainstorm must be ACTIVE: {merged_into}")
        patch["merged_into"] = merged_into
        patch["merged_detail_path"] = target.get("detailPath") or brainstorm_detail_path(
            target
        )
    management.archive_brainstorm(
        paths,
        idea_id,
        patch,
        expected_version=version,
        actor=actor or {"type": "agent", "id": "research-brainstorm"},
        idempotency_key=f"brainstorm:archive:{idea_id}",
    )
    return True


def discard_brainstorm(
    root: ResearchPaths | str | Path | None,
    idea_id: str,
    *,
    reason: str,
    actor: dict[str, str],
) -> bool:
    """Remove one archived duplicate from current state, preserving event history."""
    paths = _coerce_paths(root)
    view = StateQuery(paths).brainstorms(
        idea_id=idea_id,
        include_archived=True,
    )["data"]
    current = view["items"][0] if view["items"] else None
    if not isinstance(current, dict):
        return False
    version = int(view["versions"].get(idea_id, 0))
    management.discard_brainstorm(
        paths,
        idea_id,
        reason=reason,
        expected_version=version,
        actor=actor,
        idempotency_key=f"brainstorm:discard:{idea_id}:v{version + 1}",
    )
    return True


def consume_brainstorms(
    root: ResearchPaths | str | Path | None,
    idea_ids: list[str],
    *,
    package_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return active source records and archive them as package provenance."""
    paths = _coerce_paths(root)
    active = {row["id"]: row for row in read_brainstorms(paths)}
    taken = [
        copy.deepcopy(active[idea_id])
        for idea_id in idea_ids
        if idea_id in active
    ]
    reason = (
        f"materialized into package {package_id}"
        if package_id
        else "materialized from brainstorm"
    )
    for row in taken:
        remove_brainstorm(paths, str(row["id"]), reason=reason)
    return taken


def active_project_context(
    root: ResearchPaths | str | Path | None = None,
) -> list[dict[str, Any]]:
    """Return active Project records from management state."""
    paths = _coerce_paths(root)
    return StateQuery(paths).project_boundary()["data"]


def active_project_ids(
    root: ResearchPaths | str | Path | None = None,
) -> list[str]:
    return [row["id"] for row in active_project_context(root)]


def direction_ready(spec: dict[str, Any]) -> bool:
    """True when the Direction conversion contract is complete."""
    return all(spec.get(field) not in (None, "", [], {}) for field in DIRECTION_FIELDS)


def build_direction_proposal(
    node_id: str,
    spec: dict[str, Any],
    *,
    parent_project_id: str,
    source: str,
    source_brainstorms: list[str] | None = None,
    item_id: str | None = None,
    change: str | None = None,
    rationale: str | None = None,
) -> dict[str, Any]:
    """Build a validated Direction proposal; submission remains Triage-owned."""
    node = {
        "id": node_id,
        "level": "direction",
        "parents": [parent_project_id],
        "version": 1,
        "status": "ACTIVE",
        "spec": spec,
        "source": source,
    }
    scope_ssot.validate_node(node)
    return {
        "id": item_id or f"direction-{_slug(node_id.rsplit('/', 1)[-1])}",
        "level": "direction",
        "node_id": node_id,
        "op": "create",
        "gate": scope_ssot.REQUIRED_GATE["direction"],
        "change": change or f"Create direction {node_id} from brainstormed idea(s)",
        "rationale": rationale
        or "Brainstormed idea(s) converged into a testable direction; PM must ratify.",
        "proposed_spec": spec,
        "proposed_node": node,
        "source_brainstorms": list(source_brainstorms or []),
        "post_accept_actions": [],
    }


def _add_location_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--research-root")


def _paths_from_args(args: argparse.Namespace) -> ResearchPaths:
    return ResearchPaths.resolve(
        workspace=args.workspace,
        research_root=args.research_root,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    add = sub.add_parser("add")
    _add_location_arguments(add)
    add.add_argument("--title", required=True)
    add.add_argument("--idea", required=True)
    add.add_argument("--abstract")
    add.add_argument("--snapshot", help="JSON string, object, or list")
    add.add_argument("--body-file", help="HTML fragment for the free-form document body")
    add.add_argument("--id")
    add.add_argument("--rough-metric")
    add.add_argument("--lit-refs", help="JSON list of source refs")
    add.add_argument("--page-language", default="en")

    list_cmd = sub.add_parser("list")
    _add_location_arguments(list_cmd)
    list_cmd.add_argument("--include-archived", action="store_true")

    revise = sub.add_parser("revise")
    _add_location_arguments(revise)
    revise.add_argument("--id", required=True)
    revise.add_argument("--patch", default="{}", help="JSON object")
    revise.add_argument("--abstract")
    revise.add_argument("--snapshot", help="JSON string, object, or list")
    revise.add_argument("--body-file", help="HTML fragment for the free-form document body")

    remove = sub.add_parser("remove")
    _add_location_arguments(remove)
    remove.add_argument("--id", required=True)
    remove.add_argument("--reason", default="removed from active brainstorm lane")
    remove.add_argument("--merged-into")

    delete = sub.add_parser("delete")
    _add_location_arguments(delete)
    delete.add_argument("--id", required=True)
    delete.add_argument("--reason", required=True)
    delete.add_argument("--actor-id", required=True)

    project = sub.add_parser("check-project")
    _add_location_arguments(project)

    ready = sub.add_parser("direction-ready")
    ready.add_argument("--spec", required=True)

    proposal = sub.add_parser("build-proposal")
    proposal.add_argument("--node-id", required=True)
    proposal.add_argument("--parent-project-id", required=True)
    proposal.add_argument("--spec", required=True)
    proposal.add_argument("--source", required=True)
    proposal.add_argument("--source-brainstorms", default="[]")
    proposal.add_argument("--item-id")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "add":
        paths = _paths_from_args(args)
        record: dict[str, Any] = {"title": args.title, "idea": args.idea}
        if args.abstract:
            record["abstract"] = args.abstract
        if args.snapshot:
            record["idea_snapshot"] = json.loads(args.snapshot)
        if args.body_file:
            record["document_html"] = Path(args.body_file).read_text(encoding="utf-8")
        if args.id:
            record["id"] = args.id
        if args.rough_metric:
            record["rough_metric"] = args.rough_metric
        if args.lit_refs:
            refs = json.loads(args.lit_refs)
            if not isinstance(refs, list):
                raise ValueError("--lit-refs must be a JSON list")
            record["lit_refs"] = refs
        record["page_language"] = args.page_language
        idea_id = add_brainstorm(paths, record)
        item = next(row for row in read_brainstorms(paths) if row["id"] == idea_id)
        print(
            json.dumps(
                {"id": idea_id, "detailPath": item.get("detailPath")},
                ensure_ascii=False,
            )
        )
    elif args.cmd == "list":
        print(
            json.dumps(
                read_brainstorms(
                    _paths_from_args(args),
                    include_archived=args.include_archived,
                ),
                ensure_ascii=False,
            )
        )
    elif args.cmd == "revise":
        patch = json.loads(args.patch)
        if not isinstance(patch, dict):
            raise ValueError("--patch must be a JSON object")
        if args.abstract:
            patch["abstract"] = args.abstract
        if args.snapshot:
            patch["idea_snapshot"] = json.loads(args.snapshot)
        if args.body_file:
            patch["document_html"] = Path(args.body_file).read_text(encoding="utf-8")
        event = revise_brainstorm(
            _paths_from_args(args),
            args.id,
            patch,
        )
        print(json.dumps({"revised": True, "event_id": event["event_id"]}))
    elif args.cmd == "remove":
        print(
            json.dumps(
                {
                    "archived": remove_brainstorm(
                        _paths_from_args(args),
                        args.id,
                        reason=args.reason,
                        merged_into=args.merged_into,
                    )
                }
            )
        )
    elif args.cmd == "delete":
        print(
            json.dumps(
                {
                    "deleted": discard_brainstorm(
                        _paths_from_args(args),
                        args.id,
                        reason=args.reason,
                        actor={"type": "user", "id": args.actor_id},
                    )
                }
            )
        )
    elif args.cmd == "check-project":
        projects = active_project_context(_paths_from_args(args))
        print(
            json.dumps(
                {
                    "active_project_ids": [row["id"] for row in projects],
                    "active_projects": projects,
                },
                ensure_ascii=False,
            )
        )
    elif args.cmd == "direction-ready":
        print(json.dumps({"ready": direction_ready(json.loads(args.spec))}))
    else:
        item = build_direction_proposal(
            args.node_id,
            json.loads(args.spec),
            parent_project_id=args.parent_project_id,
            source=args.source,
            source_brainstorms=json.loads(args.source_brainstorms),
            item_id=args.item_id,
        )
        print(json.dumps(item, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
