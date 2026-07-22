#!/usr/bin/env python3
"""Submit explicit Experiment evidence contracts for an accepted Direction.

The compatibility filename is retained, but the script no longer invents a
fixed milestone roster. Callers must provide the semantic decomposition as
JSON. The script validates each resulting Scope node and submits pending
proposals through Triage. It never commits Scope.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PIPELINE_ROOT = Path(__file__).resolve().parents[3]
for candidate in (
    PIPELINE_ROOT,
    PIPELINE_ROOT / "lib",
    Path(__file__).resolve().parent,
):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from lib.research_state import ResearchPaths, StateQuery  # noqa: E402
import scope_ssot  # noqa: E402
import triage  # noqa: E402


def _slug(value: str) -> str:
    import re
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "direction"


def _direction_slug(direction_id: str) -> str:
    return _slug(direction_id.rsplit("/", 1)[-1])


def latest_direction(direction_id: str, paths: ResearchPaths) -> dict[str, Any]:
    try:
        node = StateQuery(paths).show("direction", direction_id)["data"]
    except KeyError as exc:
        raise SystemExit(
            f"Committed Direction not found in research state: {direction_id}"
        ) from exc
    if node.get("level") != "direction":
        raise SystemExit(
            "--direction-id must point to a Direction, got "
            f"level={node.get('level')!r}"
        )
    if node.get("status") != "ACTIVE":
        raise SystemExit(
            "Direction must be ACTIVE before Experiment planning, got "
            f"status={node.get('status')!r}"
        )
    scope_ssot.validate_node(node)
    return node


def build_milestones(
    direction_node: dict[str, Any],
    contracts: list[dict[str, Any]],
    *,
    control_mode: str = "CHECKPOINTED",
) -> list[dict[str, Any]]:
    """Return Experiment nodes from an explicit evidence-contract list."""
    direction_id = direction_node["id"]
    dslug = _direction_slug(direction_id)
    if not isinstance(contracts, list) or not contracts:
        raise SystemExit("Experiment contracts must be a non-empty JSON list")

    nodes: list[dict[str, Any]] = []
    seen_slugs: set[str] = set()
    required = {"slug", "purpose", "config_ref", "gate"}
    allowed = required | {"control_mode"}
    for index, contract in enumerate(contracts, start=1):
        if not isinstance(contract, dict):
            raise SystemExit(f"Experiment contract {index} must be an object")
        missing = sorted(required - set(contract))
        unknown = sorted(set(contract) - allowed)
        if missing:
            raise SystemExit(
                f"Experiment contract {index} missing fields: {missing}"
            )
        if unknown:
            raise SystemExit(
                f"Experiment contract {index} has unknown fields: {unknown}"
            )
        suffix = _slug(str(contract["slug"]))
        if suffix in seen_slugs:
            raise SystemExit(f"Duplicate Experiment slug: {suffix}")
        seen_slugs.add(suffix)
        node = {
            "id": f"experiment/{dslug}/{suffix}",
            "level": "experiment",
            "parents": [direction_id],
            "version": 1,
            "status": "ACTIVE",
            "spec": {
                "purpose": contract["purpose"],
                "config_ref": contract["config_ref"],
                "gate": contract["gate"],
                "control_mode": contract.get("control_mode", control_mode),
            },
            "package_id": None,
            "source": f"evidence-contract:{direction_id}:{index}",
        }
        scope_ssot.validate_node(node)
        nodes.append(node)
    return nodes


def proposal_for(node: dict, direction_id: str) -> dict:
    suffix = node["id"].rsplit("/", 1)[-1]
    dslug = _direction_slug(direction_id)
    return {
        "id": f"proposal-{dslug}-{suffix}",
        "level": "experiment",
        "node_id": node["id"],
        "op": "create",
        "gate": scope_ssot.REQUIRED_GATE["experiment"],
        "change": f"Create Experiment {suffix} for {direction_id}",
        "rationale": (
            "The user-reviewed evidence decomposition requires this governed "
            "Experiment before package materialization."
        ),
        "proposed_spec": node["spec"],
        "proposed_node": node,
        "post_accept_actions": [],
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--workspace", default=".")
    p.add_argument("--research-root")
    p.add_argument("--direction-id", required=True)
    p.add_argument("--control-mode", default="CHECKPOINTED")
    contracts = p.add_mutually_exclusive_group(required=True)
    contracts.add_argument(
        "--contracts-json",
        help="JSON list of explicit Experiment evidence contracts",
    )
    contracts.add_argument(
        "--contracts-file",
        help="path to a JSON file containing explicit evidence contracts",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="print proposals without submitting them",
    )
    return p


def load_contracts(args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.contracts_json is not None:
        raw = args.contracts_json
    else:
        raw = Path(args.contracts_file).read_text(encoding="utf-8")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid Experiment contracts JSON: {exc}") from exc
    if not isinstance(value, list):
        raise SystemExit("Experiment contracts JSON must be a list")
    return value


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = ResearchPaths.resolve(
        workspace=args.workspace,
        research_root=args.research_root,
    )
    direction = latest_direction(args.direction_id, paths)
    contracts = load_contracts(args)
    proposals = [
        proposal_for(node, args.direction_id)
        for node in build_milestones(
            direction,
            contracts,
            control_mode=args.control_mode,
        )
    ]
    if args.dry_run:
        print(json.dumps(proposals, indent=2, ensure_ascii=False))
        return 0
    ids = [triage.propose(paths, item) for item in proposals]
    print(json.dumps({"proposed": ids}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
