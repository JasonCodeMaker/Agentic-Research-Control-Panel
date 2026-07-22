#!/usr/bin/env python3
"""research-onboard: create one Project through one semantic authorization.

Detects whether the workspace is empty or existing, stores prior knowledge as
a content-addressed Project NoteRef, and builds or commits one reviewed Project
transaction.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

PIPELINE_ROOT = Path(__file__).resolve().parents[3]
for candidate in (
    PIPELINE_ROOT,
    PIPELINE_ROOT / "lib",
    PIPELINE_ROOT / "skills" / "research-op" / "scripts",
):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from lib.research_state import (  # noqa: E402
    CommandRejected,
    LockBusy,
    ResearchPaths,
    StateQuery,
    UnsupportedResearchVersion,
    UpgradeRequired,
)
import management  # noqa: E402
import scope_ssot  # noqa: E402

# Entries that never count as "project content" when deciding empty vs existing.
IGNORE = frozenset({
    ".git", ".gitignore", ".gitkeep", ".pytest_cache", "__pycache__", ".DS_Store",
    "AGENTS.md", "CLAUDE.md",
})

def resolve_paths(*, workspace=".", research_root=None) -> ResearchPaths:
    return ResearchPaths.resolve(
        workspace=workspace,
        research_root=research_root,
    )


def _require_safe_workspace(paths: ResearchPaths) -> None:
    """Require setup completion before onboarding reads or writes intent."""
    version = paths.load_version()
    if version is not None:
        return
    markers = paths.legacy_markers()
    if markers:
        raise UpgradeRequired(
            "upgrade-required: legacy research data exists; run the explicit "
            "research migration before onboarding"
        )
    raise UpgradeRequired(
        "setup-required: ARC is not initialized; run research-init before onboarding"
    )


def _is_managed_entry(entry: Path, paths: ResearchPaths) -> bool:
    try:
        return entry.resolve() == paths.root
    except OSError:
        return False


def workspace_state(paths: ResearchPaths) -> str:
    """'empty' if the directory holds nothing but pipeline-managed/noise entries, else 'existing'."""
    _require_safe_workspace(paths)
    for entry in paths.workspace.iterdir():
        if entry.name not in IGNORE and not _is_managed_entry(entry, paths):
            return "existing"
    return "empty"


def content_entries(paths: ResearchPaths) -> list[str]:
    """The non-ignored top-level entries an existing-workspace analysis should read."""
    _require_safe_workspace(paths)
    return sorted(
        entry.name
        for entry in paths.workspace.iterdir()
        if entry.name not in IGNORE and not _is_managed_entry(entry, paths)
    )


def write_prior_knowledge(
    paths: ResearchPaths,
    markdown: str,
) -> dict[str, Any]:
    """Store prior knowledge once and return its stable NoteRef."""
    _require_safe_workspace(paths)
    if not isinstance(markdown, str) or not markdown.strip():
        raise CommandRejected(
            "prior-knowledge-required",
            "prior knowledge must be non-empty Markdown",
        )
    return management.write_note(
        paths,
        markdown,
        mime="text/markdown",
        title="Project prior knowledge",
    )


def _validate_note_ref(note_ref: dict[str, Any]) -> None:
    required = {"uri", "sha256", "mime", "title"}
    missing = sorted(required - set(note_ref))
    if missing:
        raise scope_ssot.RuleViolation(
            f"prior_knowledge NoteRef missing fields: {missing}"
        )
    digest = note_ref.get("sha256")
    if not isinstance(digest, str) or not re.fullmatch(
        r"[0-9a-f]{64}",
        digest,
    ):
        raise scope_ssot.RuleViolation(
            "prior_knowledge NoteRef sha256 must be 64 lowercase hex digits"
        )
    if note_ref.get("uri") != f"state/notes/{digest}.md":
        raise scope_ssot.RuleViolation(
            "prior_knowledge NoteRef uri must match its sha256"
        )


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "project"


def build_project_proposal(
    node_id: str,
    spec: dict,
    *,
    source: str,
    prior_knowledge: dict[str, Any] | None = None,
    item_id: str | None = None,
    change: str | None = None,
    rationale: str | None = None,
) -> dict:
    """Build a validated level=project Triage item. Raises RuleViolation on a bad spec."""
    node = {
        "id": node_id, "level": "project", "parents": [], "version": 1,
        "status": "ACTIVE", "spec": spec, "source": source,
    }
    if prior_knowledge is not None:
        _validate_note_ref(prior_knowledge)
        node["prior_knowledge"] = prior_knowledge
    scope_ssot.validate_node(node)  # reject-before-propose: spec must be project-legal
    return {
        "id": item_id or f"project-{_slug(node_id.rsplit('/', 1)[-1])}",
        "level": "project",
        "node_id": node_id,
        "op": "create",
        "gate": scope_ssot.REQUIRED_GATE["project"],
        "change": change or f"Define the project goal for {node_id}",
        "rationale": rationale or "Onboarding bootstrapped a project objective from the workspace; PM must ratify it.",
        "proposed_spec": spec,
        "proposed_node": node,
        "post_accept_actions": [],
    }


def project_node(
    node_id: str,
    spec: dict[str, Any],
    *,
    source: str,
    prior_knowledge: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the Project node shared by review and commit."""
    return build_project_proposal(
        node_id,
        spec,
        source=source,
        prior_knowledge=prior_knowledge,
    )["proposed_node"]


def review_project(
    paths: ResearchPaths,
    node: dict[str, Any],
) -> dict[str, Any]:
    return management.prepare_project_commit(paths, node)


def commit_project(
    paths: ResearchPaths,
    node: dict[str, Any],
    review_sha256: str,
    *,
    actor_id: str,
    review_id: str,
) -> dict[str, Any]:
    event = management.finalize_project_commit(
        paths,
        node,
        review_sha256,
        actor={"type": "user", "id": actor_id},
        review_id=review_id,
    )
    return {
        "status": "project_committed",
        "project_id": node["id"],
        "event_id": event["event_id"],
    }


def has_project_scope(paths: ResearchPaths) -> bool:
    """Return whether state contains an active Project."""
    _require_safe_workspace(paths)
    if paths.load_version() is None:
        return False
    projects = StateQuery(paths).show("project")["data"]
    return any(
        isinstance(project, dict)
        and project.get("level") == "project"
        and project.get("status") == "ACTIVE"
        for project in projects.values()
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--workspace", default=".")
    p.add_argument("--research-root")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("detect", help="classify the workspace as empty|existing")

    pw = sub.add_parser(
        "write-prior-knowledge",
        help="store Markdown and return a Project NoteRef",
    )
    pw.add_argument("--content", required=True)

    pb = sub.add_parser(
        "build-proposal",
        help="build a validated Project proposal",
    )
    pb.add_argument("--node-id", required=True)
    pb.add_argument("--spec", required=True, help="JSON: goal, contributions, out_of_scope")
    pb.add_argument("--source", required=True)
    pb.add_argument("--item-id", default=None)
    pb.add_argument(
        "--prior-knowledge",
        help="JSON NoteRef returned by write-prior-knowledge",
    )

    for name, help_text in (
        ("review-project", "prepare the single Project review"),
        ("commit-project", "commit the reviewed Project"),
    ):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("--node-id", required=True)
        command.add_argument("--spec", required=True)
        command.add_argument("--source", required=True)
        command.add_argument("--prior-knowledge")
        if name == "commit-project":
            command.add_argument("--review-sha256", required=True)
            command.add_argument("--actor-id", required=True)
            command.add_argument("--review-id", required=True)

    sub.add_parser(
        "has-project-scope",
        help="True iff a Project node is committed in the SSOT",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = resolve_paths(
        workspace=args.workspace,
        research_root=args.research_root,
    )
    try:
        if args.cmd == "detect":
            print(
                json.dumps(
                    {
                        "state": workspace_state(paths),
                        "content": content_entries(paths),
                        "research_root": str(paths.root),
                    },
                    ensure_ascii=False,
                )
            )
        elif args.cmd == "write-prior-knowledge":
            note_ref = write_prior_knowledge(paths, args.content)
            print(json.dumps({"note_ref": note_ref}, ensure_ascii=False))
        elif args.cmd == "build-proposal":
            prior_knowledge = (
                json.loads(args.prior_knowledge)
                if args.prior_knowledge
                else None
            )
            item = build_project_proposal(
                args.node_id,
                json.loads(args.spec),
                source=args.source,
                prior_knowledge=prior_knowledge,
                item_id=args.item_id,
            )
            print(json.dumps(item, ensure_ascii=False))
        elif args.cmd in {"review-project", "commit-project"}:
            prior_knowledge = (
                json.loads(args.prior_knowledge)
                if args.prior_knowledge
                else None
            )
            node = project_node(
                args.node_id,
                json.loads(args.spec),
                source=args.source,
                prior_knowledge=prior_knowledge,
            )
            result = (
                review_project(paths, node)
                if args.cmd == "review-project"
                else commit_project(
                    paths,
                    node,
                    args.review_sha256,
                    actor_id=args.actor_id,
                    review_id=args.review_id,
                )
            )
            print(json.dumps(result, ensure_ascii=False))
        elif args.cmd == "has-project-scope":
            print(
                json.dumps(
                    {"has_project_scope": has_project_scope(paths)},
                    ensure_ascii=False,
                )
            )
    except (
        CommandRejected,
        LockBusy,
        UnsupportedResearchVersion,
        UpgradeRequired,
        scope_ssot.RuleViolation,
        json.JSONDecodeError,
    ) as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": type(exc).__name__,
                    "detail": str(exc),
                },
                ensure_ascii=False,
            )
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
