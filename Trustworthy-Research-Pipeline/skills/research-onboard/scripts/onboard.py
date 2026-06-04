#!/usr/bin/env python3
"""research-onboard: the deterministic on-ramp behind the steps 1->3 bridge.

Detects whether the workspace is empty or existing, scaffolds a deep-learning
project skeleton in place, writes a project-level prior-knowledge artifact, and
builds a *validated* Project-node Triage proposal. It never commits the SSOT —
the proposal flows through the same triage.py gate research-scope uses.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PIPELINE_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PIPELINE_ROOT / "lib"))

import scope_ssot  # noqa: E402

# Entries that never count as "project content" when deciding empty vs existing.
IGNORE = frozenset({
    ".git", ".gitignore", ".gitkeep", ".pytest_cache", "__pycache__", ".DS_Store",
    "research_html", "outputs",
})

# In-place deep-learning skeleton (mirrors the create-project layout).
SKELETON_DIRS = (
    "src", "scripts", "configs", "data", "dataset", "baselines",
    "logs", "results", "results/ours", "wandb", "figures", "analysis",
)
GITKEEP_DIRS = ("data", "dataset", "logs", "results", "baselines", "wandb", "figures", "analysis")

CLAUDE_STUB = """# CLAUDE.md

<!-- Prepend your project specifics above the Trustworthy Research Pipeline protocols.
     See the pipeline's CLAUDE.md -> "Per-project customization". -->

## Project
One-paragraph description (system, datasets, agent stack).

## Motivation and Goal
The central bottleneck this project attacks.

## Global Optimization Objective
The primary objective and the success rule (metric X must improve under budget Y).

## Current Best
The live anchor record (checkpoint path, metric values, validation seeds).
"""


def workspace_state(cwd) -> str:
    """'empty' if the directory holds nothing but pipeline-managed/noise entries, else 'existing'."""
    cwd = Path(cwd)
    for entry in cwd.iterdir():
        if entry.name not in IGNORE:
            return "existing"
    return "empty"


def content_entries(cwd) -> list[str]:
    """The non-ignored top-level entries an existing-workspace analysis should read."""
    return sorted(e.name for e in Path(cwd).iterdir() if e.name not in IGNORE)


def scaffold_skeleton(cwd) -> list[str]:
    """Create the in-place DL skeleton (idempotent). Returns the directories ensured."""
    cwd = Path(cwd)
    for d in SKELETON_DIRS:
        (cwd / d).mkdir(parents=True, exist_ok=True)
    (cwd / "src" / "__init__.py").touch()
    for d in GITKEEP_DIRS:
        (cwd / d / ".gitkeep").touch()
    return list(SKELETON_DIRS)


def write_project_claude_stub(cwd) -> bool:
    """Write a CLAUDE.md stub only if absent. Returns True if written, False if left untouched."""
    path = Path(cwd) / "CLAUDE.md"
    if path.exists():
        return False
    path.write_text(CLAUDE_STUB, encoding="utf-8")
    return True


def prior_knowledge_path(state_root) -> Path:
    """Project-level prior-knowledge artifact, sibling to the scope logs."""
    return Path(state_root) / "_scope" / "prior_knowledge.md"


def write_prior_knowledge(state_root, markdown: str) -> Path:
    """Write the prior-knowledge markdown the later roles read. Returns its path."""
    path = prior_knowledge_path(state_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")
    return path


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "project"


def build_project_proposal(node_id: str, yardstick: dict, *, provenance: str,
                           item_id: str | None = None, change: str | None = None,
                           rationale: str | None = None) -> dict:
    """Build a validated level=project Triage item. Raises RuleViolation on a bad yardstick."""
    node = {
        "id": node_id, "level": "project", "parents": [], "version": 1,
        "status": "active", "yardstick": yardstick, "provenance": provenance,
    }
    scope_ssot.validate_node(node)  # reject-before-propose: yardstick must be project-legal
    return {
        "id": item_id or f"project-{_slug(node_id.rsplit('/', 1)[-1])}",
        "level": "project",
        "node_id": node_id,
        "op": "create",
        "gate": scope_ssot.REQUIRED_GATE["project"],
        "change": change or f"Define the project north-star for {node_id}",
        "rationale": rationale or "Onboarding bootstrapped a project objective from the workspace; PM must ratify it.",
        "proposed_yardstick": yardstick,
        "proposed_node": node,
        "post_accept_actions": [],
    }


def has_project_scope(transitions_path) -> bool:
    """True iff the committed SSOT already holds an active Project node (backs the dashboard auto-chain)."""
    projection = scope_ssot.fold(scope_ssot.read_log(transitions_path))
    return any(n.get("level") == "project" and n.get("status") == "active" for n in projection.values())


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    pd = sub.add_parser("detect", help="classify the workspace as empty|existing")
    pd.add_argument("--cwd", default=".")

    ps = sub.add_parser("scaffold", help="create the in-place DL skeleton + CLAUDE.md stub")
    ps.add_argument("--cwd", default=".")

    pw = sub.add_parser("write-prior-knowledge", help="write outputs/_scope/prior_knowledge.md")
    pw.add_argument("--state-root", default="outputs")
    pw.add_argument("--content", required=True)

    pb = sub.add_parser("build-proposal", help="build a validated project Triage item (pipe to triage.py)")
    pb.add_argument("--node-id", required=True)
    pb.add_argument("--yardstick", required=True, help="JSON: north_star, contribution_spine, non_goals")
    pb.add_argument("--provenance", required=True)
    pb.add_argument("--item-id", default=None)

    ph = sub.add_parser("has-project-scope", help="True iff a Project node is committed in the SSOT")
    ph.add_argument("--transitions", default="outputs/_scope/transitions.jsonl")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "detect":
        print(json.dumps({"state": workspace_state(args.cwd),
                          "content": content_entries(args.cwd)}, ensure_ascii=False))
    elif args.cmd == "scaffold":
        created = scaffold_skeleton(args.cwd)
        wrote = write_project_claude_stub(args.cwd)
        print(json.dumps({"created_dirs": created, "claude_md_written": wrote}, ensure_ascii=False))
    elif args.cmd == "write-prior-knowledge":
        path = write_prior_knowledge(args.state_root, args.content)
        print(json.dumps({"path": str(path)}, ensure_ascii=False))
    elif args.cmd == "build-proposal":
        item = build_project_proposal(args.node_id, json.loads(args.yardstick),
                                      provenance=args.provenance, item_id=args.item_id)
        print(json.dumps(item, ensure_ascii=False))
    elif args.cmd == "has-project-scope":
        print(json.dumps({"has_project_scope": has_project_scope(args.transitions)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
