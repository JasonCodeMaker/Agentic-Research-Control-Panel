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
    if node.get("status") != "active":
        raise SystemExit(f"Direction must be active before milestone planning, got status={node.get('status')!r}")
    scope_ssot.validate_node(node)
    return node


def build_milestones(direction_node: dict, *, autonomy_level: str = "checkpoints") -> list[dict]:
    """Return high-level Task/Milestone node proposals for a Direction node."""
    direction_id = direction_node["id"]
    dslug = _direction_slug(direction_id)
    y = direction_node["yardstick"]
    hypothesis = str(y["hypothesis"])
    metric = _metric_label(y["metric"])
    baselines = _baseline_label(y["baselines"])
    success_predicate = str(y["success_predicate"])
    specs = [
        (
            "M0-baseline-validity",
            "Validate that the declared baseline is reproducible before testing new variants.",
            f"baseline evidence for {baselines}",
            f"{metric} baseline reproduced within declared tolerance",
        ),
        (
            "M1-main-hypothesis",
            f"Validate the main direction hypothesis: {hypothesis}",
            f"main result artifact for {metric}",
            success_predicate,
        ),
        (
            "M2-mechanism-validation",
            "Validate that the claimed mechanism is necessary via targeted ablation.",
            "ablation artifact isolating the claimed mechanism",
            "Ablation changes the primary metric in the direction predicted by the hypothesis",
        ),
        (
            "M3-robustness-validation",
            "Validate robustness across seeds, subsets, or settings before adoption.",
            "robustness summary across the agreed evaluation slices",
            f"{metric} clears the accepted gate without relying on a single lucky run",
        ),
        (
            "M4-failure-boundary",
            "Pre-register the failure boundary that should archive, pivot, or revise scope.",
            "failure-boundary report with stop or pivot recommendation",
            "Failure conditions are explicit before result interpretation",
        ),
    ]
    nodes = []
    for idx, (suffix, experiment, output, gate) in enumerate(specs, start=1):
        node = {
            "id": f"task/{dslug}/{suffix}",
            "level": "task",
            "parents": [direction_id],
            "version": 1,
            "status": "active",
            "yardstick": {
                "experiment": experiment,
                "config_ref": f"scope:{direction_id}#{suffix.lower()}",
                "gate_predicate": gate,
                "autonomy_level": autonomy_level,
            },
            "provenance": f"milestone-plan:{direction_id}:{idx}",
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
        "proposed_yardstick": node["yardstick"],
        "proposed_node": node,
        "post_accept_actions": [],
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--direction-id", required=True)
    p.add_argument("--transitions", default="var/research/_scope/transitions.jsonl")
    p.add_argument("--triage", default="var/research/_scope/triage.jsonl")
    p.add_argument("--autonomy-level", default="checkpoints")
    p.add_argument("--dry-run", action="store_true", help="print proposals without writing triage")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    direction = latest_direction(args.direction_id, args.transitions)
    proposals = [proposal_for(node, args.direction_id)
                 for node in build_milestones(direction, autonomy_level=args.autonomy_level)]
    if args.dry_run:
        print(json.dumps(proposals, indent=2, ensure_ascii=False))
        return 0
    ids = [triage.propose(args.triage, item) for item in proposals]
    print(json.dumps({"proposed": ids}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
