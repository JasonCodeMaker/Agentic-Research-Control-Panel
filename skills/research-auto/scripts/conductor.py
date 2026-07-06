"""Campaign conductor for /research-auto — deterministic routing over one Direction.

Given a committed Direction and its gate (the spec's success_gate), the conductor decides
the next campaign move: form/await scope, materialize, design the next experiment, run the package,
or exit (success / budget / no-candidate / ask). It owns gate evaluation, the typed cycle ledger, and
the authority guard. It never writes a package surface, never writes the SSOT, never disposes
Triage — its only writes are the campaign ledger and PACK under outputs/_auto/.
"""

import json
import re
import sys
import time
from pathlib import Path

_PIPE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PIPE / "lib"))
sys.path.insert(0, str(_PIPE / "skills" / "research-run" / "scripts"))
sys.path.insert(0, str(_PIPE / "skills" / "research-op" / "scripts"))
sys.path.insert(0, str(_PIPE / "skills" / "research-scope" / "scripts"))
import scope_ssot  # noqa: E402
import driver  # noqa: E402
import pack  # noqa: E402
import triage  # noqa: E402
from ops import _pkg_block  # noqa: E402

AUTONOMY_LEVELS = ("SUPERVISED", "CHECKPOINTED", "DEFERRED", "AUTONOMOUS")
AWAY_DIALS = frozenset({"DEFERRED", "AUTONOMOUS"})

ROUTES = ("FORM_DIRECTION", "AWAIT_RATIFICATION", "MATERIALIZE_PACKAGE", "DESIGN_EXPERIMENT",
          "RUN_PACKAGE", "SUCCESS_EXIT", "HALT_BUDGET", "HALT_NO_CANDIDATE", "ASK_USER")

CYCLE_FIELDS = ("cycle", "direction_id", "pkg_id", "exp_id", "hypothesis", "verdict",
                "measured", "gate_eval", "evidence", "next_action")
VERDICTS = frozenset({"PASS", "FAIL", "INCONCLUSIVE", "DIAGNOSTIC"})
GATE_EVALS = frozenset({"PASS", "FAIL", "UNEVALUATED"})

# experiments[] statuses that still leave the package something to execute or finish
_EXECUTABLE_EXP_STATUSES = frozenset({"pending", "queued", "running"})


class GateUnparseable(Exception):
    """Raised when a gate carries no machine-checkable comparator clause."""


# ---- gate parsing + evaluation ----

def parse_gate(gate_text):
    """Extract the first `<cmp> <number>` clause of a gate; raise if none exists."""
    m = re.search(r"(>=|<=|>|<)\s*([0-9]+(?:\.[0-9]+)?)", str(gate_text))
    if not m:
        raise GateUnparseable(f"no comparator clause in gate: {gate_text!r}")
    return {"cmp": m.group(1), "threshold": float(m.group(2))}

def evaluate_gate(measured, gate_text):
    """PASS/FAIL the campaign gate for a measured value; the value must come from verified facts."""
    gate = parse_gate(gate_text)
    value = float(measured)
    ops = {">=": value >= gate["threshold"], "<=": value <= gate["threshold"],
           ">": value > gate["threshold"], "<": value < gate["threshold"]}
    return "PASS" if ops[gate["cmp"]] else "FAIL"


# ---- campaign ledger (reject-before-write, PACK discipline) ----

def _slug(value):
    slug = re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")
    return slug or "direction"

def ledger_path(root, direction_id):
    """The campaign ledger home for a direction: outputs/_auto/<slug>/campaign.jsonl."""
    return Path(root) / "outputs" / "_auto" / _slug(direction_id.rsplit("/", 1)[-1]) / "campaign.jsonl"

def pack_path(root, direction_id):
    """The campaign PACK log next to the ledger."""
    return ledger_path(root, direction_id).parent / "_pack.jsonl"

def append_cycle(ledger, record):
    """Append one typed cycle record; reject a blank/missing field or illegal verdict before write."""
    missing = [f for f in CYCLE_FIELDS if not str(record.get(f, "")).strip()]
    if missing:
        raise ValueError(f"cycle record missing required fields: {missing}")
    if record["verdict"] not in VERDICTS:
        raise ValueError(f"verdict {record['verdict']!r} not in {sorted(VERDICTS)}")
    if record["gate_eval"] not in GATE_EVALS:
        raise ValueError(f"gate_eval {record['gate_eval']!r} not in {sorted(GATE_EVALS)}")
    if record["gate_eval"] == "PASS" and record["verdict"] != "PASS":
        raise ValueError("gate_eval PASS requires verdict PASS (an unproven result cannot clear the gate)")
    row = {**record, "ts": record.get("ts") or time.strftime("%Y-%m-%dT%H:%M:%S")}
    ledger = Path(ledger)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row

def read_ledger(ledger):
    """All cycle records for a campaign (empty if it has not started)."""
    ledger = Path(ledger)
    if not ledger.exists():
        return []
    return [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()]

def campaign_status(records, *, max_cycles):
    """Fold the ledger into the campaign position: cycles used, gate met, budget exhausted."""
    gate_met = any(r.get("gate_eval") == "PASS" for r in records)
    cycles_used = max((int(r.get("cycle", 0)) for r in records), default=0)
    return {"cycles_used": cycles_used, "gate_met": gate_met,
            "budget_exhausted": cycles_used >= max_cycles and not gate_met,
            "last": records[-1] if records else None}


# ---- router ----

# Per-route copy: (headline, next_action, offer, awaits_user, handoff-or-delegate key, command).
_ROUTE_TABLE = {
    "FORM_DIRECTION": (
        "No committed Direction matches this campaign yet.",
        "I'll shape the direction through /research-brainstorm, rank competing framings when needed, and propose it through Triage with your gate as the success gate.",
        "You ratify the Direction + gate + dial when the proposal lands — the campaign starts after that.",
        False, "handoff", "/research-brainstorm"),
    "AWAIT_RATIFICATION": (
        "A direction proposal for this campaign is waiting in Triage.",
        "Accept or reject the pending Direction — commit authority is yours, not the campaign's.",
        "Reply `accept` or `reject` (with edits if you want changes); the campaign resumes on accept.",
        True, "handoff", "triage dispose"),
    "ASK_USER": (
        "The campaign gate is not machine-checkable, so the loop cannot self-judge success.",
        "Restate the gate as a comparator clause (e.g. `R@1 >= 48`), or tell me to run supervised with you judging results.",
        "One sentence with a measurable gate unblocks the campaign.",
        True, "handoff", "user"),
    "SUCCESS_EXIT": (
        "The campaign gate has been cleared with verified evidence.",
        "Close out: terminal success routing + T1 acknowledgement, then the campaign report from the ledger.",
        "Confirm the terminal transition (T1); away-mode queued acks are listed in the report.",
        True, "delegate", "/research-run"),
    "HALT_BUDGET": (
        "The cycle budget is exhausted and the gate is still unmet.",
        "Stop honestly: campaign report + a Triage proposal to extend budget, revise the metric/scope, or archive the direction.",
        "Pick extend / revise / archive — the campaign never rewrites its own goalpost.",
        True, "handoff", "/research-scope"),
    "HALT_NO_CANDIDATE": (
        "No legal next experiment remains under the current scope.",
        "Stop and propose a scope revision through Triage, extend the design space, or archive the direction.",
        "Approve a scope revise, add a new constraint, or archive.",
        True, "handoff", "/research-scope"),
    "MATERIALIZE_PACKAGE": (
        "Committed scope exists but no open package carries this direction.",
        "Materialize the package from committed Scope state only (/research-package create_from_scope), then enter the run loop.",
        "This is mechanical; I'll continue into the first cycle when surfaces exist.",
        False, "delegate", "/research-package"),
    "RUN_PACKAGE": (
        "An executable experiment is on the package task spine.",
        "Delegate to /research-run: readiness, implementation/review, launch, monitoring, propagation, verification, terminal routing.",
        "I'll harvest the verdict into the campaign ledger and re-check the gate when the run completes.",
        False, "delegate", "/research-run"),
    "DESIGN_EXPERIMENT": (
        "The gate is unmet and the package has no executable experiment left — the campaign needs its next design.",
        "Design the next experiment from the Context Pack plus verified package evidence, then add it as an experiments-row through research-op.",
        "At SUPERVISED/CHECKPOINTED I pause for the designed row; at DEFERRED/AUTONOMOUS I proceed and queue the deferred ack.",
        False, "delegate", "/research-op"),
}

def render_next_step(action):
    """Plain-language Next-Smooth-Step copy for a campaign action (no raw FSM label as headline)."""
    headline, nxt, offer, awaits, _, _ = _ROUTE_TABLE[action["type"]]
    return {"type": action["type"], "headline": headline, "next_action": nxt, "offer": offer,
            "awaits_user": awaits, "details": action.get("message") or f"campaign route: {action['type']}"}

def next_action(*, direction_committed, pending_direction, status, open_pkg,
                has_executable_exp=False, no_candidate=False, dial="AUTONOMOUS", gate_parseable=True):
    """Route the campaign tick by strict precedence; returns one typed action with next_step copy."""
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
    _, _, _, _, kind, command = _ROUTE_TABLE[route]
    action = {"type": route, kind: command, "dial": dial,
              "message": f"cycles_used={status['cycles_used']} gate_met={status['gate_met']} open_pkg={open_pkg}"}
    action["next_step"] = render_next_step(action)
    return action


# ---- authority guard ----

def validate_campaign_action(action):
    """Reject any campaign action that smuggles commit/disposal authority; None means legal."""
    reasons = []
    t = action.get("type")
    if t not in ROUTES:
        reasons.append(f"unknown campaign route: {t!r}")
    if action.get("decision") in ("accept", "reject", "ACCEPTED", "REJECTED"):
        reasons.append("authority smuggle: a Triage disposal decision belongs to the user, not the campaign")
    dial = action.get("dial")
    for m in action.get("mutations", []):
        if isinstance(m, dict) and m.get("op") == "scope-transition":
            payload = m.get("payload") or {}
            level = payload.get("level")
            if level != "task":
                reasons.append(f"authority smuggle: the campaign never commits a {level or 'unknown'}-level scope-transition")
                continue
            if payload.get("gate") != "AGENT_DEFERRED_ACK":
                reasons.append("task transition must use the SSOT task gate AGENT_DEFERRED_ACK")
            if dial not in AWAY_DIALS:
                reasons.append(f"dial {dial!r} requires the Triage pause path for task proposals, not a self-commit")
            if not str(payload.get("deferred_ack", "")).strip():
                reasons.append("a self-committed task transition must queue a non-empty deferred_ack for the human")
        else:
            reasons += [f"mutation: {e}" for e in driver.validate_mutation(m)]
    if reasons:
        return {"rejected": True, "type": t, "reasons": reasons}
    return None


# ---- per-cycle task shaping ----

def milestone_task_node(direction_node, *, cycle, suffix, experiment, gate, dial):
    """Build a validated milestone Task node for a campaign cycle (the dial-keyed scope seam)."""
    if dial not in AUTONOMY_LEVELS:
        raise ValueError(f"unknown dial {dial!r}; expected one of {list(AUTONOMY_LEVELS)}")
    direction_id = direction_node["id"]
    node = {
        "id": f"task/{_slug(direction_id.rsplit('/', 1)[-1])}/{suffix}",
        "level": "task",
        "parents": [direction_id],
        "version": 1,
        "status": "ACTIVE",
        "spec": {"experiment": experiment,
                 "config": f"scope:{direction_id}#{suffix.lower()}",
                 "gate": gate,
                 "control_mode": dial},
        "source": f"research-auto:cycle-{cycle}:{suffix}",
    }
    scope_ssot.validate_node(node)
    return node


# ---- filesystem derivation ----

def committed_direction(root, direction_id):
    """The folded ACTIVE direction node for this id, or None if not committed."""
    records = scope_ssot.read_log(Path(root) / "outputs" / "_scope" / "transitions.jsonl")
    node = scope_ssot.fold(records).get(direction_id)
    if node and node.get("level") == "direction" and node.get("status") == "ACTIVE":
        return node
    return None

def _pending_matches_direction(item, direction_id):
    if item.get("node_id") == direction_id:
        return True
    proposed = item.get("proposed_node") or {}
    if isinstance(proposed, dict) and proposed.get("id") == direction_id:
        return True
    tail = _slug(direction_id.rsplit("/", 1)[-1])
    legacy_ids = {direction_id, _slug(direction_id), f"direction-{tail}"}
    return str(item.get("id", "")) in legacy_ids

def pending_direction_items(root, direction_id=None):
    """Pending direction-level Triage items (the campaign waits on these, never disposes them)."""
    log = Path(root) / "outputs" / "_scope" / "triage.jsonl"
    items = [p for p in triage.pending(log) if p.get("level") == "direction"]
    if direction_id is None:
        return items
    return [p for p in items if _pending_matches_direction(p, direction_id)]

def _js_string_value(raw):
    raw = raw.strip()
    if raw.startswith(("'", '"')) and len(raw) >= 2:
        try:
            return bytes(raw[1:-1], "utf-8").decode("unicode_escape")
        except UnicodeDecodeError:
            return raw[1:-1]
    return raw

def _top_level_value(block, field):
    bounds = _pkg_block.find_top_level_field_value(block, field)
    if bounds is None:
        return ""
    start, end = bounds
    return _js_string_value(block[start:end])

def _array_object_items(array_text):
    if not array_text.strip().startswith("["):
        return
    i = 1
    n = len(array_text)
    while i < n - 1:
        s_end = _pkg_block._skip_string(array_text, i)
        if s_end is not None:
            i = s_end
            continue
        c_end = _pkg_block._skip_comment(array_text, i)
        if c_end is not None:
            i = c_end
            continue
        if array_text[i] == "{":
            item_end = _pkg_block.find_matching_close(array_text, i)
            yield array_text[i:item_end]
            i = item_end
            continue
        i += 1

def _has_executable_experiment(block):
    bounds = _pkg_block.find_top_level_field_value(block, "experiments")
    if bounds is None:
        return False
    start, end = bounds
    for item in _array_object_items(block[start:end]):
        if _top_level_value(item, "status").lower() in _EXECUTABLE_EXP_STATUSES:
            return True
    return False

def detect_open_package(root, direction_id):
    """(pkg_id, has_executable_exp) for the in-progress package materialized from this direction."""
    inv = Path(root) / "research_html" / "data" / "research-packages.js"
    if not inv.exists():
        return (None, False)
    text = inv.read_text(encoding="utf-8")
    for m in re.finditer(r"\{\s*(?:id|['\"]id['\"])\s*:", text):
        try:
            block = text[m.start():_pkg_block.find_matching_close(text, m.start())]
        except ValueError:
            continue
        pkg_id = _top_level_value(block, "id")
        if not pkg_id:
            continue
        if _top_level_value(block, "sourceDirection") != direction_id:
            continue
        if _top_level_value(block, "category") != "in-progress":
            continue
        return (pkg_id, _has_executable_experiment(block))
    return (None, False)


# ---- CLI ----

def main(argv=None):
    """CLI so the skill drives every routing decision reproducibly from disk via Bash(python3 *)."""
    import argparse
    p = argparse.ArgumentParser(description="Campaign conductor for /research-auto.")
    sub = p.add_subparsers(dest="cmd", required=True)
    ps = sub.add_parser("status")
    ps.add_argument("--root", default=".")
    ps.add_argument("--direction-id", required=True)
    ps.add_argument("--max-cycles", type=int, default=5)
    ps.add_argument("--dial", default="AUTONOMOUS", choices=AUTONOMY_LEVELS)
    ps.add_argument("--gate", default="", help="override gate; default = direction success_gate")
    ps.add_argument("--no-candidate", action="store_true")
    pg = sub.add_parser("gate-eval")
    pg.add_argument("--measured", required=True)
    pg.add_argument("--gate", required=True)
    pa = sub.add_parser("append-cycle")
    pa.add_argument("--root", default=".")
    pa.add_argument("--direction-id", required=True)
    pa.add_argument("--record", required=True, help="JSON cycle record")
    pp = sub.add_parser("pack")
    pp.add_argument("--root", default=".")
    pp.add_argument("--direction-id", required=True)
    pp.add_argument("--bundle", required=True, help="JSON PACK bundle")
    args = p.parse_args(argv)

    if args.cmd == "status":
        node = committed_direction(args.root, args.direction_id)
        gate_text = args.gate or (node or {}).get("spec", {}).get("success_gate", "")
        try:
            parse_gate(gate_text)
            gate_parseable = True
        except GateUnparseable:
            gate_parseable = False
        open_pkg, executable = detect_open_package(args.root, args.direction_id)
        records = read_ledger(ledger_path(args.root, args.direction_id))
        status = campaign_status(records, max_cycles=args.max_cycles)
        action = next_action(direction_committed=node is not None,
                             pending_direction=bool(pending_direction_items(args.root, args.direction_id)),
                             status=status, open_pkg=open_pkg, has_executable_exp=executable,
                             no_candidate=args.no_candidate, dial=args.dial, gate_parseable=gate_parseable)
        state = {"direction_committed": node is not None, "gate": gate_text,
                 "gate_parseable": gate_parseable, "open_pkg": open_pkg,
                 "has_executable_exp": executable, **status}
        print(json.dumps({"state": state, "action": action}, ensure_ascii=False))
    elif args.cmd == "gate-eval":
        print(json.dumps({"gate_eval": evaluate_gate(args.measured, args.gate)}))
    elif args.cmd == "append-cycle":
        row = append_cycle(ledger_path(args.root, args.direction_id), json.loads(args.record))
        print(json.dumps(row, ensure_ascii=False))
    elif args.cmd == "pack":
        pack.write_pack(pack_path(args.root, args.direction_id), json.loads(args.bundle))
        print(json.dumps({"pack": str(pack_path(args.root, args.direction_id))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
