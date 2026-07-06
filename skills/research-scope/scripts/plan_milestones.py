#!/usr/bin/env python3
"""Propose high-level validation milestones for an accepted Direction.

Milestones are SSOT Task nodes at the validation-objective level, not concrete
package experiments. This script reads only committed Direction nodes, then writes
pending Triage proposals for milestone Task nodes. The PM must accept/revise them
before package materialization.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PIPELINE_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PIPELINE_ROOT / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import scope_ssot  # noqa: E402
import triage  # noqa: E402


def _slug(value: str) -> str:
    import re
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "direction"


def _direction_slug(direction_id: str) -> str:
    return _slug(direction_id.rsplit("/", 1)[-1])


def _metric_label(metric) -> str:
    if isinstance(metric, dict):
        return str(metric.get("name") or json.dumps(metric, sort_keys=True, ensure_ascii=False))
    if isinstance(metric, list):
        return ", ".join(str(m) for m in metric)
    return str(metric)


def _baseline_label(baselines) -> str:
    if isinstance(baselines, list):
        return "; ".join(str(b) for b in baselines) if baselines else "declared baseline"
    return str(baselines or "declared baseline")


def latest_direction(direction_id: str, transitions_path: str | Path) -> dict:
    records = scope_ssot.read_log(transitions_path)
    hist = scope_ssot.history(direction_id, records)
    if not hist:
        raise SystemExit(f"Committed direction not found in {transitions_path}: {direction_id}")
    node = hist[-1].get("node")
    if not node:
        raise SystemExit(f"Transition for {direction_id} does not carry a node snapshot")
    if node.get("level") != "direction":
        raise SystemExit(f"--direction-id must point to a direction node, got level={node.get('level')!r}")
    if node.get("status") != "ACTIVE":
        raise SystemExit(f"Direction must be ACTIVE before milestone planning, got status={node.get('status')!r}")
    scope_ssot.validate_node(node)
    return node


def build_milestones(direction_node: dict, *, control_mode: str = "CHECKPOINTED") -> list[dict]:
    """Return high-level Task/Milestone node proposals for a Direction node."""
    direction_id = direction_node["id"]
    dslug = _direction_slug(direction_id)
    spec = direction_node["spec"]
    hypothesis = str(spec["hypothesis"])
    metric = _metric_label(spec["metric"])
    baselines = _baseline_label(spec["baselines"])
    success_gate = str(spec["success_gate"])
    specs = [
        (
            "M0-baseline-validity",
            "Reproduce the declared baseline with the agreed data split, logging artifacts and tolerance checks before any new variant receives evaluation time.",
            f"baseline evidence for {baselines}",
            f"The declared baseline for {metric} must reproduce within the accepted tolerance window before any downstream comparison is considered fair during review.",
        ),
        (
            "M1-main-hypothesis",
            "Run the main validation experiment for the accepted Direction, comparing the primary metric against declared baselines under the approved evaluation budget.",
            f"main result artifact for {metric}",
            success_gate,
        ),
        (
            "M2-mechanism-validation",
            "Run a targeted ablation that removes the claimed mechanism while keeping data, budget, and evaluation scripts fixed for attribution review.",
            "ablation artifact isolating the claimed mechanism",
            "The ablation must move the primary metric in the direction predicted by the hypothesis while preserving all agreed evaluation controls.",
        ),
        (
            "M3-robustness-validation",
            "Repeat the validated setting across agreed seeds, subsets, or evaluation slices before any result is treated as robust review evidence.",
            "robustness summary across the agreed evaluation slices",
            f"The {metric} result must clear the accepted gate without relying on a single lucky run or an undocumented evaluation slice.",
        ),
        (
            "M4-failure-boundary",
            "Document the failure boundary that should archive, pivot, or revise the Direction before results are interpreted opportunistically by any reviewer.",
            "failure-boundary report with stop or pivot recommendation",
            "Failure conditions must be explicit enough that the reviewer can choose archive, pivot, or revise without moving the accepted gate.",
        ),
    ]
    nodes = []
    for idx, (suffix, experiment, output, gate) in enumerate(specs, start=1):
        node = {
            "id": f"task/{dslug}/{suffix}",
            "level": "task",
            "parents": [direction_id],
            "version": 1,
            "status": "ACTIVE",
            "spec": {
                "experiment": experiment,
                "config": f"scope:{direction_id}#{suffix.lower()}",
                "gate": gate,
                "control_mode": control_mode,
            },
            "source": f"milestone-plan:{direction_id}:{idx}",
        }
        scope_ssot.validate_node(node)
        nodes.append(node)
    return nodes


def proposal_for(node: dict, direction_id: str) -> dict:
    suffix = node["id"].rsplit("/", 1)[-1]
    return {
        "id": f"milestone-{_direction_slug(direction_id)}-{suffix}",
        "level": "task",
        "node_id": node["id"],
        "op": "create",
        "gate": scope_ssot.REQUIRED_GATE["task"],
        "change": f"Create validation milestone {suffix} for {direction_id}",
        "rationale": "Accepted Direction needs high-level validation milestones before package materialization.",
        "proposed_spec": node["spec"],
        "proposed_node": node,
        "post_accept_actions": [],
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--direction-id", required=True)
    p.add_argument("--transitions", default="outputs/_scope/transitions.jsonl")
    p.add_argument("--triage", default="outputs/_scope/triage.jsonl")
    p.add_argument("--control-mode", default="CHECKPOINTED")
    p.add_argument("--dry-run", action="store_true", help="print proposals without writing triage")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    direction = latest_direction(args.direction_id, args.transitions)
    proposals = [proposal_for(node, args.direction_id)
                 for node in build_milestones(direction, control_mode=args.control_mode)]
    if args.dry_run:
        print(json.dumps(proposals, indent=2, ensure_ascii=False))
        return 0
    ids = [triage.propose(args.triage, item) for item in proposals]
    print(json.dumps({"proposed": ids}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
