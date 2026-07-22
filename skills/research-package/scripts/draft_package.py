#!/usr/bin/env python3
"""Convert an approved Brainstorm into a refinable Draft Package."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
PIPELINE_ROOT = Path(__file__).resolve().parents[3]
for candidate in (
    SCRIPT_DIR,
    PIPELINE_ROOT,
    PIPELINE_ROOT / "lib",
    PIPELINE_ROOT / "skills" / "research-op" / "scripts",
):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from lib.interface.project import validate_brainstorm_document_fragment  # noqa: E402
from lib.research_state import ResearchPaths, StateQuery  # noqa: E402
from lib.research_state.io import canonical_json  # noqa: E402
import create_research_package  # noqa: E402
import management  # noqa: E402
import scope_ssot  # noqa: E402


SOURCE_FIELDS = (
    "title",
    "abstract",
    "idea",
    "idea_snapshot",
    "page_language",
    "created_at",
    "updated_at",
    "revision",
)


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _paths(workspace: str, research_root: str | None) -> ResearchPaths:
    return ResearchPaths.resolve(workspace=workspace, research_root=research_root)


def _draft_binding(package: dict[str, Any]) -> dict[str, Any]:
    note = package.get("document_note")
    if not isinstance(note, dict) or not note.get("sha256"):
        raise ValueError("Draft Package has no governed proposal document")
    return {
        "id": str(package["id"]),
        "draft_revision": int(package["draftRevision"]),
        "document_sha256": str(note["sha256"]),
    }


def _source_descriptor(
    package_id: str,
    brainstorm_id: str,
    brainstorm: dict[str, Any],
    brainstorm_version: int,
) -> dict[str, Any]:
    note = brainstorm.get("document_note")
    if not isinstance(note, dict):
        raise ValueError(f"Brainstorm has no governed document: {brainstorm_id}")
    descriptor: dict[str, Any] = {
        "id": brainstorm_id,
        "sourceKind": "brainstorm-proposal",
        "ownership": "package",
        "sourceVersion": brainstorm_version,
        "documentPath": "docs/proposal.html",
        "document_note": copy.deepcopy(note),
        "convertedInto": package_id,
    }
    for field in SOURCE_FIELDS:
        if brainstorm.get(field) is not None:
            descriptor[field] = copy.deepcopy(brainstorm[field])
    return descriptor


def convert(
    paths: ResearchPaths,
    *,
    brainstorm_id: str,
    package_id: str | None,
    actor_id: str,
) -> dict[str, Any]:
    """Consume one exact Brainstorm revision into a same-document Draft Package."""
    view = StateQuery(paths).brainstorms(
        idea_id=brainstorm_id,
        include_archived=True,
    )["data"]
    brainstorm = view["items"][0] if view["items"] else None
    if not isinstance(brainstorm, dict) or brainstorm.get("status") != "ACTIVE":
        raise ValueError(f"ACTIVE Brainstorm required: {brainstorm_id}")
    resolved_id = package_id or brainstorm_id
    try:
        StateQuery(paths).show("package", resolved_id)
    except KeyError:
        pass
    else:
        raise ValueError(f"Package already exists: {resolved_id}")
    brainstorm_version = int(view["versions"].get(brainstorm_id, 0))
    if brainstorm_version < 1:
        raise ValueError(f"Brainstorm has no committed revision: {brainstorm_id}")
    note = copy.deepcopy(brainstorm.get("document_note"))
    if not isinstance(note, dict):
        raise ValueError(f"Brainstorm has no governed document: {brainstorm_id}")
    converted_at = str(
        brainstorm.get("updated_at")
        or brainstorm.get("created_at")
        or datetime.now(timezone.utc).isoformat()
    )
    descriptor = _source_descriptor(
        resolved_id,
        brainstorm_id,
        brainstorm,
        brainstorm_version,
    )
    title = str(brainstorm.get("title") or resolved_id)
    record: dict[str, Any] = copy.deepcopy(brainstorm)
    record.update(
        {
            "id": resolved_id,
            "slug": resolved_id,
            "name": title,
            "lifecycle": "DRAFT",
            "phase": None,
            "blocker": None,
            "draftStatus": "REFINING",
            "draftRevision": 1,
            "executionAuthorized": False,
            "direction_id": None,
            "sourceVersion": None,
            "sourceChange": None,
            "sourceExperiments": [],
            "scopeBinding": None,
            "documentPath": "docs/proposal.html",
            "document_note": note,
            "sourceBrainstorms": [descriptor],
            "interface_notes": {"docs/proposal.html": note},
            "pages": ["index", "tracker", "docs", "_agent"],
            "docsGroups": [],
            "methodsTried": [],
            "resultGateRows": [],
            "resultBlocks": [],
            "analysisInsights": [],
            "updated_at": converted_at,
            "lastUpdated": converted_at[:10],
            "nextAction": "Refine the Draft Package, then review its full Scope bundle",
        }
    )
    record.pop("status", None)
    record.pop("detailPath", None)
    record.pop("_aggregate_type", None)
    consumption = {
        "aggregate_id": brainstorm_id,
        "expected_version": brainstorm_version,
        "document_path": "docs/proposal.html",
        "document_note": note,
    }
    event = management.create_draft_package(
        paths,
        resolved_id,
        record,
        [consumption],
        actor={"type": "user", "id": actor_id},
        idempotency_key=(
            f"brainstorm-convert:{brainstorm_id}:v{brainstorm_version}:"
            f"{resolved_id}:{_digest(note)}"
        ),
    )
    return {
        "status": "converted",
        "brainstorm_id": brainstorm_id,
        "package_id": resolved_id,
        "draft_revision": 1,
        "event_id": event["event_id"],
    }


def revise(
    paths: ResearchPaths,
    *,
    package_id: str,
    patch: dict[str, Any],
    actor_id: str,
    document_html: str | None = None,
) -> dict[str, Any]:
    """Refine one Draft Package and invalidate any older review binding."""
    current = StateQuery(paths).show("package", package_id)["data"]
    if current.get("lifecycle") != "DRAFT":
        raise ValueError(f"Draft Package required: {package_id}")
    candidate = copy.deepcopy(patch)
    if candidate.get("draftStatus") not in {None, "REFINING"}:
        raise ValueError(
            "Draft refinement cannot set SCOPE_READY; final approval owns that transition"
        )
    candidate["draftStatus"] = "REFINING"
    candidate["draftRevision"] = int(current["draftRevision"]) + 1
    candidate["updated_at"] = datetime.now(timezone.utc).isoformat()
    candidate["lastUpdated"] = candidate["updated_at"][:10]
    if document_html is not None:
        body = validate_brainstorm_document_fragment(document_html)
        note = management.write_note(
            paths,
            body,
            mime="text/html;profile=brainstorm-fragment",
            title=f"Draft Package proposal: {package_id}",
        )
        candidate["document_note"] = note
        notes = copy.deepcopy(current.get("interface_notes") or {})
        notes["docs/proposal.html"] = note
        candidate["interface_notes"] = notes
    history = StateQuery(paths).history("package", package_id)["data"]
    version = int(history[-1]["aggregate_version"]) if history else 0
    event = management.revise_draft_package(
        paths,
        package_id,
        candidate,
        expected_version=version,
        actor={"type": "agent", "id": actor_id},
        idempotency_key=(
            f"draft-package:revise:{package_id}:v{candidate['draftRevision']}:"
            f"{_digest(candidate)}"
        ),
    )
    return {
        "status": "revised",
        "package_id": package_id,
        "draft_revision": candidate["draftRevision"],
        "event_id": event["event_id"],
    }


def build_finalization_proposal(
    paths: ResearchPaths,
    *,
    package_id: str,
    direction: dict[str, Any],
    experiments: list[dict[str, Any]],
    proposal_id: str | None = None,
) -> dict[str, Any]:
    """Build one user-visible proposal for Scope commit plus Package activation."""
    package = StateQuery(paths).show("package", package_id)["data"]
    if package.get("lifecycle") != "DRAFT" or package.get("draftStatus") != "REFINING":
        raise ValueError(f"REFINING Draft Package required: {package_id}")
    scope_ssot.validate_node(direction)
    if direction.get("level") != "direction" or direction.get("version") != 1:
        raise ValueError("finalization requires a new Direction at version 1")
    if not isinstance(experiments, list) or not experiments:
        raise ValueError("finalization requires at least one Experiment")
    seen: set[str] = set()
    for experiment in experiments:
        scope_ssot.validate_node(experiment)
        experiment_id = str(experiment.get("id") or "")
        if (
            experiment.get("level") != "experiment"
            or experiment.get("parents") != [direction["id"]]
            or experiment.get("version") != 1
            or not experiment_id
            or experiment_id in seen
        ):
            raise ValueError(
                "every finalization Experiment must be unique, version 1, and parented by the Direction"
            )
        seen.add(experiment_id)
    return {
        "id": proposal_id
        or f"finalize-{create_research_package.slugify(package_id)}-v{package['draftRevision']}",
        "proposal_kind": "package_finalization",
        "level": "direction",
        "node_id": direction["id"],
        "op": "create",
        "gate": scope_ssot.REQUIRED_GATE["direction"],
        "change": f"Finalize Draft Package {package_id} and activate its Scope",
        "rationale": (
            "The reviewed Draft, Direction, and Experiments form one executable authority boundary."
        ),
        "proposed_spec": copy.deepcopy(direction["spec"]),
        "proposed_node": copy.deepcopy(direction),
        "proposed_experiments": copy.deepcopy(experiments),
        "source_package": _draft_binding(package),
        "source_brainstorms": [
            str(row["id"])
            for row in package.get("sourceBrainstorms", [])
            if isinstance(row, dict) and row.get("id")
        ],
        "post_accept_actions": [
            "Commit Direction and Experiments",
            "Activate the same Package at ACTIVE/CONTEXT_LOADED",
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--research-root")
    sub = parser.add_subparsers(dest="command", required=True)

    convert_parser = sub.add_parser("convert")
    convert_parser.add_argument("--brainstorm-id", required=True)
    convert_parser.add_argument("--package-id")
    convert_parser.add_argument("--actor-id", required=True)

    revise_parser = sub.add_parser("revise")
    revise_parser.add_argument("--package-id", required=True)
    revise_parser.add_argument("--patch", default="{}")
    revise_parser.add_argument("--body-file")
    revise_parser.add_argument("--actor-id", default="research-package")

    proposal_parser = sub.add_parser("build-proposal")
    proposal_parser.add_argument("--package-id", required=True)
    proposal_parser.add_argument("--direction", required=True)
    proposal_parser.add_argument("--experiments", required=True)
    proposal_parser.add_argument("--proposal-id")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = _paths(args.workspace, args.research_root)
    if args.command == "convert":
        result = convert(
            paths,
            brainstorm_id=args.brainstorm_id,
            package_id=args.package_id,
            actor_id=args.actor_id,
        )
    elif args.command == "revise":
        patch = json.loads(args.patch)
        if not isinstance(patch, dict):
            raise ValueError("--patch must be a JSON object")
        document_html = (
            Path(args.body_file).read_text(encoding="utf-8")
            if args.body_file
            else None
        )
        result = revise(
            paths,
            package_id=args.package_id,
            patch=patch,
            actor_id=args.actor_id,
            document_html=document_html,
        )
    else:
        experiments = json.loads(args.experiments)
        if not isinstance(experiments, list):
            raise ValueError("--experiments must be a JSON list")
        result = build_finalization_proposal(
            paths,
            package_id=args.package_id,
            direction=json.loads(args.direction),
            experiments=experiments,
            proposal_id=args.proposal_id,
        )
    print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
