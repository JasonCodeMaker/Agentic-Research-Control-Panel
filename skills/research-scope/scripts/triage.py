"""Triage admission gate: the agent proposes; dispose records an explicit PM decision.

A proposal lands as a pending item in the Triage queue and never touches the Scope SSOT. The PM alone
decides whether to accept or reject the visible proposal. After that explicit decision, the agent may
record it here. An accepted transition still goes through research-op; rejection leaves the SSOT
untouched. This keeps the objective cascade PM-decision-gated.
"""

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
RESEARCH_OP_SCRIPTS = REPO_ROOT / "skills" / "research-op" / "scripts"
if str(RESEARCH_OP_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(RESEARCH_OP_SCRIPTS))

import management
from lib.research_state import (
    CommandRejected,
    LockBusy,
    ResearchPaths,
    UnsupportedResearchVersion,
    UpgradeRequired,
)


def resolve_paths(*, workspace=".", research_root=None):
    """Resolve the sole management root for this workspace."""
    return ResearchPaths.resolve(
        workspace=workspace,
        research_root=research_root,
    )


def proposal_hash(item):
    """Hash the proposal content the PM is asked to dispose."""
    return management.proposal_content_hash(item)


def propose(paths, item):
    """Append an agent-proposed scope change as a pending Triage item. Does not touch the SSOT."""
    record, _event = management.submit_proposal(
        paths,
        item,
    )
    return record["id"]


def _read(paths):
    return management.proposal_records(paths)


def pending(paths):
    """Items still awaiting human disposition (latest status per id wins)."""
    return management.pending_proposals(paths)


def dispose(
    paths,
    item_id,
    decision,
    expected_proposal_hash,
    *,
    actor=None,
):
    """Record an explicit PM decision (ACCEPTED | REJECTED). Never mutates the SSOT itself."""
    status, _event = management.dispose_proposal(
        paths,
        item_id,
        decision,
        expected_proposal_hash,
        actor=actor,
    )
    return status


def main(argv=None):
    """CLI so the skill can drive the Triage queue via Bash(python3 *)."""
    import argparse
    p = argparse.ArgumentParser(
        description="Triage admission gate for agent-proposed scope changes."
    )
    p.add_argument("--workspace", default=".")
    p.add_argument("--research-root")
    sub = p.add_subparsers(dest="cmd", required=True)
    pp = sub.add_parser("propose")
    pp.add_argument(
        "--item",
        required=True,
        help="JSON object; must include an 'id'",
    )
    sub.add_parser("pending")
    pd = sub.add_parser("dispose")
    pd.add_argument("--id", required=True)
    pd.add_argument(
        "--decision",
        required=True,
        choices=("ACCEPTED", "REJECTED"),
    )
    pd.add_argument("--proposal-hash", required=True)
    pd.add_argument(
        "--actor-type",
        choices=("user", "agent", "system"),
        default="agent",
        help="decision actor type; disposition requires an explicit user actor",
    )
    pd.add_argument(
        "--actor-id",
        default="research-scope-cli",
        help="stable identity for the decision actor",
    )
    args = p.parse_args(argv)
    paths = resolve_paths(
        workspace=args.workspace,
        research_root=args.research_root,
    )
    try:
        if args.cmd == "propose":
            print(propose(paths, json.loads(args.item)))
        elif args.cmd == "pending":
            print(json.dumps(pending(paths), ensure_ascii=False))
        elif args.cmd == "dispose":
            print(
                dispose(
                    paths,
                    args.id,
                    args.decision,
                    args.proposal_hash,
                    actor={"type": args.actor_type, "id": args.actor_id},
                )
            )
    except (
        CommandRejected,
        LockBusy,
        UnsupportedResearchVersion,
        UpgradeRequired,
        ValueError,
    ) as exc:
        print(
            json.dumps(
                {
                    "rejected": True,
                    "rule": getattr(exc, "rule", type(exc).__name__),
                    "detail": str(exc),
                },
                ensure_ascii=False,
            )
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
