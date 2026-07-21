"""Deterministic Direction-campaign routing over unified research state."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

PIPELINE_ROOT = Path(__file__).resolve().parents[3]
for candidate in (
    PIPELINE_ROOT,
    PIPELINE_ROOT / "lib",
    PIPELINE_ROOT / "skills" / "research-op" / "scripts",
    PIPELINE_ROOT / "skills" / "research-run" / "scripts",
):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from lib.research_state import (  # noqa: E402
    ResearchPaths,
    StateQuery,
)
from lib.research_state.io import canonical_json  # noqa: E402
import management  # noqa: E402
import driver  # noqa: E402


AUTONOMY_LEVELS = ("SUPERVISED", "CHECKPOINTED", "DEFERRED", "AUTONOMOUS")
AWAY_DIALS = frozenset({"DEFERRED", "AUTONOMOUS"})
ROUTES = (
    "FORM_DIRECTION",
    "AWAIT_RATIFICATION",
    "MATERIALIZE_PACKAGE",
    "DESIGN_EXPERIMENT",
    "RUN_PACKAGE",
    "SUCCESS_EXIT",
    "HALT_BUDGET",
    "HALT_NO_CANDIDATE",
    "ASK_USER",
)
CYCLE_FIELDS = (
    "cycle",
    "direction_id",
    "pkg_id",
    "exp_id",
    "run_id",
    "hypothesis",
    "verdict",
    "measured",
    "gate_eval",
    "evidence",
    "next_action",
)
VERDICTS = frozenset({"PASS", "FAIL", "INCONCLUSIVE", "DIAGNOSTIC"})
GATE_EVALS = frozenset({"PASS", "FAIL", "UNEVALUATED"})
EXECUTABLE_EXP_STATUSES = frozenset({"PLANNED", "READY", "ACTIVE"})
TERMINAL_RUN_STATUSES = frozenset({"COMPLETED", "FAILED", "HALTED", "SKIPPED"})


class GateUnparseable(Exception):
    """The charter gate has no machine-checkable comparator."""


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def parse_gate(gate_text: Any) -> dict[str, Any]:
    match = re.search(r"(>=|<=|>|<)\s*([0-9]+(?:\.[0-9]+)?)", str(gate_text))
    if not match:
        raise GateUnparseable(f"no comparator clause in gate: {gate_text!r}")
    return {"cmp": match.group(1), "threshold": float(match.group(2))}


def evaluate_gate(measured: Any, gate_text: Any) -> str:
    gate = parse_gate(gate_text)
    value = float(measured)
    outcomes = {
        ">=": value >= gate["threshold"],
        "<=": value <= gate["threshold"],
        ">": value > gate["threshold"],
        "<": value < gate["threshold"],
    }
    return "PASS" if outcomes[gate["cmp"]] else "FAIL"


def campaign_id(direction_id: str) -> str:
    """Campaign identity is the Direction identity; no filesystem slug store."""
    return direction_id


def campaign_cycles(
    source: ResearchPaths | dict[str, Any],
    direction_id: str,
) -> list[dict[str, Any]]:
    view = (
        StateQuery(source).campaign(direction_id)["data"]
        if isinstance(source, ResearchPaths)
        else source
    )
    if "aggregates" in view:
        record = view["aggregates"]["campaign"].get(
            campaign_id(direction_id),
            {},
        )
    else:
        record = view.get("campaign") or {}
    rows = record.get("cycles") if isinstance(record, dict) else []
    return copy.deepcopy(rows) if isinstance(rows, list) else []


def _validate_cycle_shape(record: dict[str, Any]) -> None:
    missing = [
        field
        for field in CYCLE_FIELDS
        if record.get(field) in (None, "", [], {})
    ]
    if missing:
        raise ValueError(f"cycle record missing required fields: {missing}")
    if record["verdict"] not in VERDICTS:
        raise ValueError(
            f"verdict {record['verdict']!r} not in {sorted(VERDICTS)}"
        )
    if record["gate_eval"] not in GATE_EVALS:
        raise ValueError(
            f"gate_eval {record['gate_eval']!r} not in {sorted(GATE_EVALS)}"
        )
    if record["gate_eval"] == "PASS" and record["verdict"] != "PASS":
        raise ValueError("gate_eval PASS requires verdict PASS")
    if record["next_action"] not in ROUTES:
        raise ValueError(
            f"next_action {record['next_action']!r} not in {list(ROUTES)}"
        )


def _validate_cycle_witness(
    view: dict[str, Any],
    record: dict[str, Any],
) -> None:
    package_id = str(record["pkg_id"])
    requested_experiment = str(record["exp_id"])
    run_id = str(record["run_id"])
    if "aggregates" in view:
        packages = view["aggregates"]["package"]
        experiments = view["aggregates"]["experiment"]
        run = view["aggregates"]["run"].get(run_id)
    else:
        packages = {
            str(package["id"]): package
            for package in view.get("packages", [])
        }
        experiments = view.get("experiments", {})
        run = view.get("run")
    if package_id not in packages:
        raise ValueError(f"cycle package does not exist: {package_id}")
    experiment_id, _ = driver.resolve_bound_experiment(
        experiments,
        package_id,
        requested_experiment,
    )
    if not isinstance(run, dict):
        raise ValueError(f"cycle run does not exist: {run_id}")
    if run.get("package_id") != package_id:
        raise ValueError(f"cycle run {run_id} belongs to another package")
    run_experiment_id, _ = driver.resolve_bound_experiment(
        experiments,
        package_id,
        [
            run.get("experiment_id"),
            run.get("experiment_local_id"),
        ],
    )
    if run_experiment_id != experiment_id:
        raise ValueError(f"cycle run {run_id} belongs to another experiment")
    if run.get("status") not in TERMINAL_RUN_STATUSES:
        raise ValueError(f"cycle run is not terminal: {run_id}")


def append_cycle(
    paths: ResearchPaths,
    direction_id: str,
    record: dict[str, Any],
    *,
    actor: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Append one validated cycle through ``CampaignUpdated``."""
    _validate_cycle_shape(record)
    if record["direction_id"] != direction_id:
        raise ValueError("cycle direction_id does not match the campaign")
    query = StateQuery(paths).campaign(
        direction_id,
        package_id=str(record["pkg_id"]),
        run_id=str(record["run_id"]),
    )
    view = query["data"]
    _validate_cycle_witness(view, record)
    aggregate_id = campaign_id(direction_id)
    current = view.get("campaign") or {}
    cycles = (
        copy.deepcopy(current.get("cycles", []))
        if isinstance(current, dict)
        else []
    )
    cycle_number = int(record["cycle"])
    if any(int(row.get("cycle", -1)) == cycle_number for row in cycles):
        existing = next(
            row for row in cycles if int(row.get("cycle", -1)) == cycle_number
        )
        if existing == record or {
            key: existing.get(key) for key in record
        } == record:
            return copy.deepcopy(existing)
        raise ValueError(f"campaign cycle already exists: {cycle_number}")
    row = {
        **copy.deepcopy(record),
        "ts": record.get("ts") or time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    cycles.append(row)
    version = int(view["campaign_version"])
    management.update_campaign(
        paths,
        aggregate_id,
        {
            "direction_id": direction_id,
            "cycles": cycles,
            "status": (
                "SUCCEEDED"
                if row["gate_eval"] == "PASS"
                else "RUNNING"
            ),
            "route": row["next_action"],
            "updated_at": row["ts"],
        },
        expected_version=version,
        actor=actor or {"type": "agent", "id": "research-auto"},
        idempotency_key=(
            f"campaign:{aggregate_id}:cycle:{cycle_number}:{_digest(row)}"
        ),
    )
    return row


def append_pack(
    paths: ResearchPaths,
    direction_id: str,
    bundle: dict[str, Any],
    *,
    actor: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Append an away-mode handoff bundle to the Campaign aggregate."""
    required = {
        "attempted",
        "found",
        "hypothesis_state",
        "next_action",
        "blocking_decision",
    }
    missing = sorted(
        field for field in required if bundle.get(field) in (None, "", [], {})
    )
    if missing:
        raise ValueError(f"campaign PACK missing fields: {missing}")
    if bundle["next_action"] not in ROUTES:
        raise ValueError(
            f"campaign PACK next_action must be one of {list(ROUTES)}"
        )
    view = StateQuery(paths).campaign(direction_id)["data"]
    aggregate_id = campaign_id(direction_id)
    current = view.get("campaign") or {}
    packs = copy.deepcopy(current.get("packs", [])) if isinstance(current, dict) else []
    row = {
        **copy.deepcopy(bundle),
        "ts": bundle.get("ts") or time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    packs.append(row)
    version = int(view["campaign_version"])
    management.update_campaign(
        paths,
        aggregate_id,
        {
            "direction_id": direction_id,
            "packs": packs,
            "status": current.get("status", "RUNNING"),
            "route": row["next_action"],
            "updated_at": row["ts"],
        },
        expected_version=version,
        actor=actor or {"type": "agent", "id": "research-auto"},
        idempotency_key=(
            f"campaign:{aggregate_id}:pack:{len(packs)}:{_digest(row)}"
        ),
    )
    return row


def campaign_status(
    records: list[dict[str, Any]],
    *,
    max_cycles: int,
) -> dict[str, Any]:
    gate_met = any(row.get("gate_eval") == "PASS" for row in records)
    cycles_used = max(
        (int(row.get("cycle", 0)) for row in records),
        default=0,
    )
    return {
        "cycles_used": cycles_used,
        "gate_met": gate_met,
        "budget_exhausted": cycles_used >= max_cycles and not gate_met,
        "last": records[-1] if records else None,
    }


_ROUTE_TABLE = {
    "FORM_DIRECTION": (
        "No committed Direction matches this campaign yet.",
        "Shape it through /research-brainstorm and submit it through Triage.",
        "Ratify the Direction, gate, and dial when the proposal lands.",
        False,
        "handoff",
        "/research-brainstorm",
    ),
    "AWAIT_RATIFICATION": (
        "A Direction proposal is waiting in Triage.",
        "Accept, revise, or reject it; the campaign cannot dispose Triage.",
        "The campaign resumes only after human ratification.",
        True,
        "handoff",
        "triage dispose",
    ),
    "ASK_USER": (
        "The campaign gate is not machine-checkable.",
        "Restate it with one comparator clause.",
        "A measurable gate unblocks deterministic evaluation.",
        True,
        "handoff",
        "user",
    ),
    "SUCCESS_EXIT": (
        "The gate has cleared with verified evidence.",
        "Complete terminal routing and its T1 acknowledgement.",
        "The Campaign aggregate contains the evidence-backed report.",
        True,
        "delegate",
        "/research-run",
    ),
    "HALT_BUDGET": (
        "The cycle budget is exhausted and the gate is unmet.",
        "Propose extend, revise, or archive through Triage.",
        "The campaign never moves its own goalpost.",
        True,
        "handoff",
        "/research-scope",
    ),
    "HALT_NO_CANDIDATE": (
        "No legal next experiment remains.",
        "Propose a scope revision or archive through Triage.",
        "Add constraints or expand the design space explicitly.",
        True,
        "handoff",
        "/research-scope",
    ),
    "MATERIALIZE_PACKAGE": (
        "Committed scope has no active package.",
        "Materialize it from accepted state through /research-package.",
        "This creates the Package and binds its accepted Scope Experiments.",
        False,
        "delegate",
        "/research-package",
    ),
    "RUN_PACKAGE": (
        "An executable experiment is available.",
        "Delegate execution and monitoring to /research-run.",
        "Its terminal run will witness the next Campaign cycle.",
        False,
        "delegate",
        "/research-run",
    ),
    "DESIGN_EXPERIMENT": (
        "The gate is unmet and no executable experiment remains.",
        "Design the next experiment from state context and verified evidence.",
        "Add it through the research-op Experiment facade.",
        False,
        "delegate",
        "/research-op",
    ),
}


def render_next_step(action: dict[str, Any]) -> dict[str, Any]:
    headline, next_action_text, offer, awaits, _, _ = _ROUTE_TABLE[action["type"]]
    return {
        "type": action["type"],
        "headline": headline,
        "next_action": next_action_text,
        "offer": offer,
        "awaits_user": awaits,
        "details": action.get("message")
        or f"campaign route: {action['type']}",
    }


def next_action(
    *,
    direction_committed: bool,
    pending_direction: bool,
    status: dict[str, Any],
    open_pkg: str | None,
    has_executable_exp: bool = False,
    no_candidate: bool = False,
    dial: str = "AUTONOMOUS",
    gate_parseable: bool = True,
) -> dict[str, Any]:
    if not direction_committed:
        route = "AWAIT_RATIFICATION" if pending_direction else "FORM_DIRECTION"
    elif not gate_parseable:
        route = "ASK_USER"
    elif status["gate_met"]:
        route = "SUCCESS_EXIT"
    elif status["budget_exhausted"]:
        route = "HALT_BUDGET"
    elif no_candidate:
        route = "HALT_NO_CANDIDATE"
    elif open_pkg is None:
        route = "MATERIALIZE_PACKAGE"
    elif has_executable_exp:
        route = "RUN_PACKAGE"
    else:
        route = "DESIGN_EXPERIMENT"
    _, _, _, _, key, command = _ROUTE_TABLE[route]
    action = {
        "type": route,
        key: command,
        "dial": dial,
        "message": (
            f"cycles_used={status['cycles_used']} "
            f"gate_met={status['gate_met']} open_pkg={open_pkg}"
        ),
    }
    action["next_step"] = render_next_step(action)
    return action


def validate_campaign_action(action: dict[str, Any]) -> dict[str, Any] | None:
    reasons = []
    action_type = action.get("type")
    if action_type not in ROUTES:
        reasons.append(f"unknown campaign route: {action_type!r}")
    if action.get("decision") in {"accept", "reject", "ACCEPTED", "REJECTED"}:
        reasons.append("authority smuggle: Triage disposal belongs to the user")
    dial = action.get("dial")
    for mutation in action.get("mutations", []):
        if isinstance(mutation, dict) and mutation.get("op") == "scope-transition":
            payload = mutation.get("payload") or {}
            level = payload.get("level")
            if level != "experiment":
                reasons.append(
                    "authority smuggle: campaigns never commit Project or "
                    "Direction scope"
                )
                continue
            if payload.get("gate") != "AGENT_DEFERRED_ACK":
                reasons.append("Experiment spec transition requires AGENT_DEFERRED_ACK")
            if dial not in AWAY_DIALS:
                reasons.append(f"dial {dial!r} requires the Triage pause path")
            if not str(payload.get("deferred_ack") or "").strip():
                reasons.append("self-proposed Experiment spec requires deferred_ack")
        else:
            reasons.extend(
                f"mutation: {reason}"
                for reason in driver.validate_mutation(mutation)
            )
    if reasons:
        return {"rejected": True, "type": action_type, "reasons": reasons}
    return None


def committed_direction(
    source: ResearchPaths | dict[str, Any],
    direction_id: str,
) -> dict[str, Any] | None:
    view = (
        StateQuery(source).campaign(direction_id)["data"]
        if isinstance(source, ResearchPaths)
        else source
    )
    node = (
        view["aggregates"]["direction"].get(direction_id)
        if "aggregates" in view
        else view.get("direction")
    )
    if isinstance(node, dict) and node.get("status") == "ACTIVE":
        return copy.deepcopy(node)
    return None


def pending_direction_items(
    source: ResearchPaths | dict[str, Any],
    direction_id: str | None = None,
) -> list[dict[str, Any]]:
    if isinstance(source, ResearchPaths):
        if direction_id is None:
            return StateQuery(source).pending_directions()["data"]
        else:
            view = StateQuery(source).campaign(direction_id)["data"]
            return copy.deepcopy(view["pending_directions"])
    else:
        state = source
    if "aggregates" not in state:
        return copy.deepcopy(state.get("pending_directions", []))
    rows = []
    for item in state["aggregates"]["proposal"].values():
        if not isinstance(item, dict) or item.get("disposition") != "PENDING":
            continue
        proposed = item.get("proposed_node")
        level = (
            proposed.get("level")
            if isinstance(proposed, dict)
            else item.get("level")
        )
        if level != "direction":
            continue
        target = (
            proposed.get("id")
            if isinstance(proposed, dict)
            else item.get("node_id")
        )
        if direction_id is None or target == direction_id:
            rows.append(copy.deepcopy(item))
    return rows


def detect_open_package(
    source: ResearchPaths | dict[str, Any],
    direction_id: str,
) -> tuple[str | None, bool]:
    view = (
        StateQuery(source).campaign(direction_id)["data"]
        if isinstance(source, ResearchPaths)
        else source
    )
    if "aggregates" in view:
        candidates = [
            (package_id, package)
            for package_id, package in view["aggregates"]["package"].items()
            if isinstance(package, dict)
            and (
                package.get("direction_id") == direction_id
                or package.get("sourceDirection") == direction_id
            )
            and package.get("lifecycle") == "ACTIVE"
        ]
        experiments = view["aggregates"]["experiment"].values()
    else:
        candidates = [
            (str(package["id"]), package)
            for package in view.get("packages", [])
            if package.get("lifecycle") == "ACTIVE"
        ]
        experiments = view.get("experiments", {}).values()
    if not candidates:
        return (None, False)
    package_id, _ = sorted(candidates, key=lambda item: str(item[0]))[-1]
    executable = any(
        isinstance(experiment, dict)
        and experiment.get("package_id") == package_id
        and experiment.get("status") in EXECUTABLE_EXP_STATUSES
        for experiment in experiments
    )
    return str(package_id), executable


def _add_location_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--research-root")


def _paths(args: argparse.Namespace) -> ResearchPaths:
    return ResearchPaths.resolve(
        workspace=args.workspace,
        research_root=args.research_root,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    status_parser = sub.add_parser("status")
    _add_location_arguments(status_parser)
    status_parser.add_argument("--direction-id", required=True)
    status_parser.add_argument("--max-cycles", type=int, default=5)
    status_parser.add_argument(
        "--dial",
        default="AUTONOMOUS",
        choices=AUTONOMY_LEVELS,
    )
    status_parser.add_argument("--gate", default="")
    status_parser.add_argument("--no-candidate", action="store_true")

    gate_parser = sub.add_parser("gate-eval")
    gate_parser.add_argument("--measured", required=True)
    gate_parser.add_argument("--gate", required=True)

    cycle_parser = sub.add_parser("append-cycle")
    _add_location_arguments(cycle_parser)
    cycle_parser.add_argument("--direction-id", required=True)
    cycle_parser.add_argument("--record", required=True)

    pack_parser = sub.add_parser("pack")
    _add_location_arguments(pack_parser)
    pack_parser.add_argument("--direction-id", required=True)
    pack_parser.add_argument("--bundle", required=True)
    args = parser.parse_args(argv)

    if args.cmd == "gate-eval":
        print(json.dumps({"gate_eval": evaluate_gate(args.measured, args.gate)}))
        return 0

    paths = _paths(args)
    if args.cmd == "status":
        view = StateQuery(paths).campaign(args.direction_id)["data"]
        node = committed_direction(view, args.direction_id)
        gate_text = args.gate or (
            (node or {}).get("spec", {}).get("success_gate", "")
        )
        try:
            parse_gate(gate_text)
            gate_parseable = True
        except GateUnparseable:
            gate_parseable = False
        open_package, executable = detect_open_package(view, args.direction_id)
        records = campaign_cycles(view, args.direction_id)
        folded = campaign_status(records, max_cycles=args.max_cycles)
        action = next_action(
            direction_committed=node is not None,
            pending_direction=bool(
                pending_direction_items(view, args.direction_id)
            ),
            status=folded,
            open_pkg=open_package,
            has_executable_exp=executable,
            no_candidate=args.no_candidate,
            dial=args.dial,
            gate_parseable=gate_parseable,
        )
        position = {
            "direction_committed": node is not None,
            "gate": gate_text,
            "gate_parseable": gate_parseable,
            "open_pkg": open_package,
            "has_executable_exp": executable,
            **folded,
        }
        print(
            json.dumps(
                {"state": position, "action": action},
                ensure_ascii=False,
            )
        )
    elif args.cmd == "append-cycle":
        row = append_cycle(
            paths,
            args.direction_id,
            json.loads(args.record),
        )
        print(json.dumps(row, ensure_ascii=False))
    else:
        row = append_pack(
            paths,
            args.direction_id,
            json.loads(args.bundle),
        )
        print(
            json.dumps(
                {
                    "campaign": f"campaign/{campaign_id(args.direction_id)}",
                    "pack": row,
                },
                ensure_ascii=False,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
