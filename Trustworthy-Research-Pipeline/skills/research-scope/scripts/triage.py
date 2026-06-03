"""Triage admission gate: the agent may PROPOSE a scope change; only the human PM disposes it.

A proposal lands as a pending item in the Triage queue and never touches the Scope SSOT. The human
accepts (then the transition is committed via research-op's scope-transition op) or rejects (archived,
SSOT untouched). This keeps the objective cascade PM-write-only.
"""

import json
from pathlib import Path


def propose(triage_log, item):
    """Append an agent-proposed scope change as a pending Triage item. Does not touch the SSOT."""
    triage_log = Path(triage_log)
    triage_log.parent.mkdir(parents=True, exist_ok=True)
    record = {**item, "status": "pending"}
    with triage_log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return item["id"]


def _read(triage_log):
    triage_log = Path(triage_log)
    if not triage_log.exists():
        return []
    return [json.loads(line) for line in triage_log.read_text(encoding="utf-8").splitlines() if line.strip()]


def pending(triage_log):
    """Items still awaiting human disposition (latest status per id wins)."""
    latest = {}
    for rec in _read(triage_log):
        latest[rec["id"]] = rec
    return [rec for rec in latest.values() if rec["status"] == "pending"]


def dispose(triage_log, item_id, decision):
    """Record a human disposition (accept | reject). Never mutates the SSOT itself."""
    if decision not in ("accept", "reject"):
        raise ValueError(f"decision must be accept|reject, got {decision!r}")
    triage_log = Path(triage_log)
    status = "accepted" if decision == "accept" else "archived"
    with triage_log.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"id": item_id, "status": status}, ensure_ascii=False) + "\n")
    return status


def main(argv=None):
    """CLI so the skill can drive the Triage queue via Bash(python3 *)."""
    import argparse
    p = argparse.ArgumentParser(description="Triage admission gate for agent-proposed scope changes.")
    sub = p.add_subparsers(dest="cmd", required=True)
    pp = sub.add_parser("propose"); pp.add_argument("--log", required=True); pp.add_argument("--item", required=True, help="JSON object; must include an 'id'")
    pn = sub.add_parser("pending"); pn.add_argument("--log", required=True)
    pd = sub.add_parser("dispose"); pd.add_argument("--log", required=True); pd.add_argument("--id", required=True); pd.add_argument("--decision", required=True, choices=("accept", "reject"))
    args = p.parse_args(argv)
    if args.cmd == "propose":
        print(propose(args.log, json.loads(args.item)))
    elif args.cmd == "pending":
        print(json.dumps(pending(args.log), ensure_ascii=False))
    elif args.cmd == "dispose":
        print(dispose(args.log, args.id, args.decision))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
