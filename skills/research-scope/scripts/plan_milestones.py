#!/usr/bin/env python3
"""Propose governed Experiment specs for an accepted Direction.

The script reads a committed Direction through the bounded state query, builds
high-level validation Experiments, and submits pending proposals through the
research-op gateway.  It never reads an interface projection or writes state
files directly.
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
    *,
    control_mode: str = "CHECKPOINTED",
) -> list[dict[str, Any]]:
    """Return high-level Experiment nodes for a committed Direction."""
    direction_id = direction_node["id"]
    dslug = _direction_slug(direction_id)
    spec = direction_node["spec"]
    metric = _metric_label(spec["metric"])
    baselines = _baseline_label(spec["baselines"])
    success_gate = str(spec["success_gate"])
    specs = [
        (
            "M0-baseline-validity",
            "Reproduce the declared baseline with the agreed data split, logging artifacts and tolerance checks before any new variant receives evaluation time.",
            f"The declared baseline ({baselines}) for {metric} must reproduce within the accepted tolerance window before any downstream comparison is considered fair during review.",
        ),
        (
            "M1-main-hypothesis",
            "Run the main validation experiment for the accepted Direction, comparing the primary metric against declared baselines under the approved evaluation budget.",
            success_gate,
        ),
        (
            "M2-mechanism-validation",
            "Run a targeted ablation that removes the claimed mechanism while keeping data, budget, and evaluation scripts fixed for attribution review.",
            "The ablation must move the primary metric in the direction predicted by the hypothesis while preserving all agreed evaluation controls.",
        ),
        (
            "M3-robustness-validation",
            "Repeat the validated setting across agreed seeds, subsets, or evaluation slices before any result is treated as robust review evidence.",
            f"The {metric} result must clear the accepted gate without relying on a single lucky run or an undocumented evaluation slice.",
        ),
        (
            "M4-failure-boundary",
            "Document the failure boundary that should archive, pivot, or revise the Direction before results are interpreted opportunistically by any reviewer.",
            "Failure conditions must be explicit enough that the reviewer can choose archive, pivot, or revise without moving the accepted gate.",
        ),
    ]
    nodes: list[dict[str, Any]] = []
    for index, (suffix, purpose, gate) in enumerate(specs, start=1):
        node = {
            "id": f"exp-{dslug}-{suffix}",
            "level": "experiment",
            "parents": [direction_id],
            "version": 1,
            "status": "ACTIVE",
            "spec": {
                "purpose": purpose,
                "config_ref": f"scope:{direction_id}#{suffix.lower()}",
                "gate": gate,
                "control_mode": control_mode,
            },
            "package_id": None,
            "source": f"validation-plan:{direction_id}:{index}",
        }
        scope_ssot.validate_node(node)
        nodes.append(node)
    return nodes


def proposal_for(node: dict, direction_id: str) -> dict:
    suffix = node["id"].rsplit("/", 1)[-1]
    return {
        "id": f"proposal-{suffix}",
        "level": "experiment",
        "node_id": node["id"],
        "op": "create",
        "gate": scope_ssot.REQUIRED_GATE["experiment"],
        "change": f"Create validation Experiment {suffix} for {direction_id}",
        "rationale": (
            "The accepted Direction needs governed validation Experiments "
            "before package materialization."
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
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="print proposals without submitting them",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = ResearchPaths.resolve(
        workspace=args.workspace,
        research_root=args.research_root,
    )
    direction = latest_direction(args.direction_id, paths)
    proposals = [
        proposal_for(node, args.direction_id)
        for node in build_milestones(
            direction,
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
