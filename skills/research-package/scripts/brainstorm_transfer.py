#!/usr/bin/env python3
"""Transfer one Brainstorm document into Package-owned documentation."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any


PIPELINE_ROOT = Path(__file__).resolve().parents[3]
for candidate in (
    PIPELINE_ROOT,
    PIPELINE_ROOT / "skills" / "research-op" / "scripts",
):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from lib.research_state import EventStore, ResearchPaths  # noqa: E402
import create_from_scope  # noqa: E402
import management  # noqa: E402


SOURCE_GROUP_ID = "source-proposal"


def merge_transfer_fields(
    package: dict[str, Any],
    incoming: dict[str, Any],
) -> dict[str, Any]:
    """Merge source-proposal metadata without replacing unrelated Package docs."""
    source_ids = {
        str(row.get("id"))
        for row in incoming.get("sourceBrainstorms", [])
        if isinstance(row, dict)
    }
    sources = [
        copy.deepcopy(row)
        for row in package.get("sourceBrainstorms", [])
        if isinstance(row, dict) and str(row.get("id")) not in source_ids
    ]
    sources.extend(copy.deepcopy(incoming.get("sourceBrainstorms", [])))

    groups = [
        copy.deepcopy(row)
        for row in package.get("docsGroups", [])
        if isinstance(row, dict) and row.get("id") != SOURCE_GROUP_ID
    ]
    existing_source_group = next(
        (
            copy.deepcopy(row)
            for row in package.get("docsGroups", [])
            if isinstance(row, dict) and row.get("id") == SOURCE_GROUP_ID
        ),
        None,
    )
    incoming_source_group = next(
        (
            copy.deepcopy(row)
            for row in incoming.get("docsGroups", [])
            if isinstance(row, dict) and row.get("id") == SOURCE_GROUP_ID
        ),
        None,
    )
    if incoming_source_group is not None:
        prior_docs = (
            existing_source_group.get("docs", [])
            if isinstance(existing_source_group, dict)
            else []
        )
        incoming_doc_ids = {
            str(row.get("id"))
            for row in incoming_source_group.get("docs", [])
            if isinstance(row, dict)
        }
        merged_docs = [
            copy.deepcopy(row)
            for row in prior_docs
            if isinstance(row, dict) and str(row.get("id")) not in incoming_doc_ids
        ]
        merged_docs.extend(copy.deepcopy(incoming_source_group.get("docs", [])))
        incoming_source_group["docs"] = merged_docs
        groups.append(incoming_source_group)
    elif existing_source_group is not None:
        groups.append(existing_source_group)

    notes = (
        copy.deepcopy(package.get("interface_notes"))
        if isinstance(package.get("interface_notes"), dict)
        else {}
    )
    notes.update(copy.deepcopy(incoming.get("interface_notes", {})))
    return {
        "sourceBrainstorms": sources,
        "docsGroups": groups,
        "interface_notes": notes,
    }


def transfer_existing(
    paths: ResearchPaths,
    *,
    package_id: str,
    brainstorm_ids: list[str],
    actor: dict[str, str],
) -> dict[str, Any]:
    """Atomically attach source docs and remove the standalone Brainstorms."""
    state = EventStore(paths).state()
    package = state["aggregates"]["package"].get(package_id)
    if not isinstance(package, dict):
        raise ValueError(f"unknown Package: {package_id}")
    records_by_id = state["aggregates"]["brainstorm"]
    package_owned = {
        str(row.get("id"))
        for row in package.get("sourceBrainstorms", [])
        if isinstance(row, dict) and row.get("ownership") == "package"
    }
    missing = [idea_id for idea_id in brainstorm_ids if idea_id not in records_by_id]
    unknown = [idea_id for idea_id in missing if idea_id not in package_owned]
    if unknown:
        raise ValueError("unknown Brainstorm(s): " + ", ".join(unknown))
    active_ids = [idea_id for idea_id in brainstorm_ids if idea_id in records_by_id]
    if not active_ids:
        return {
            "package_event_id": None,
            "removed_brainstorms": [],
            "already_converted": brainstorm_ids,
        }
    experiments = [
        str(row.get("id"))
        for row in package.get("sourceExperiments", [])
        if isinstance(row, dict) and row.get("id")
    ]
    source_rows = [
        {
            "aggregate_id": idea_id,
            "aggregate_version": int(
                state["aggregate_versions"].get(f"brainstorm/{idea_id}", 0)
            ),
            "record": copy.deepcopy(records_by_id[idea_id]),
        }
        for idea_id in active_ids
    ]
    sources, groups, notes, consumptions = (
        create_from_scope._build_brainstorm_transfer(
            package_id,
            source_rows,
            experiments,
        )
    )
    incoming = {
        "sourceBrainstorms": sources,
        "docsGroups": groups,
        "interface_notes": notes,
    }
    merged = merge_transfer_fields(package, incoming)
    package_event = management.commit_package_brainstorm_transfer(
        paths,
        package_id,
        source_brainstorms=merged["sourceBrainstorms"],
        docs_groups=merged["docsGroups"],
        interface_notes=merged["interface_notes"],
        brainstorm_consumptions=consumptions,
        expected_version=int(
            state["aggregate_versions"].get(f"package/{package_id}", 0)
        ),
        actor=actor,
        idempotency_key=(
            f"package:{package_id}:absorb-brainstorms:"
            + ",".join(active_ids)
        ),
    )
    return {
        "package_event_id": package_event["event_id"],
        "removed_brainstorms": active_ids,
        "already_converted": missing,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--research-root")
    parser.add_argument("--package-id", required=True)
    parser.add_argument("--brainstorm-id", action="append", required=True)
    parser.add_argument("--actor-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = ResearchPaths.resolve(
        workspace=args.workspace,
        research_root=args.research_root,
    )
    result = transfer_existing(
        paths,
        package_id=args.package_id,
        brainstorm_ids=list(dict.fromkeys(args.brainstorm_id)),
        actor={"type": "user", "id": args.actor_id},
    )
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
