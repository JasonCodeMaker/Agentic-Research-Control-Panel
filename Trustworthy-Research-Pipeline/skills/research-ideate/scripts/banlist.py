"""R3 ideate banlist — scope-conditional. A failed idea is banned only while the scope that failed
it still holds; a metric revise reopens ideas that failed only on the old metric (via
scope_ssot.propagate). The banlist is SSOT-version-stamped memory.
"""


def allowed(candidates, banlist):
    """Filter out candidate idea ids that are currently banned."""
    banned = {entry["id"] for entry in banlist}
    return [c for c in candidates if c not in banned]


def apply_reopen(banlist, reopened_ids):
    """Drop banlist entries whose idea was reopened by a scope transition."""
    reopened = set(reopened_ids)
    return [entry for entry in banlist if entry["id"] not in reopened]


def main(argv=None):
    """CLI over the banlist file (a JSON array of {id, ...} entries) for Bash(python3 *)."""
    import argparse
    import json
    from pathlib import Path
    p = argparse.ArgumentParser(description="research-ideate scope-conditional banlist.")
    sub = p.add_subparsers(dest="cmd", required=True)
    pa = sub.add_parser("allowed"); pa.add_argument("--banlist", required=True); pa.add_argument("--candidates", required=True, help="JSON array of candidate idea ids")
    pr = sub.add_parser("reopen"); pr.add_argument("--banlist", required=True); pr.add_argument("--reopened", required=True, help="JSON array of reopened idea ids")
    args = p.parse_args(argv)
    bfile = Path(args.banlist)
    banlist = json.loads(bfile.read_text(encoding="utf-8")) if bfile.exists() else []
    if args.cmd == "allowed":
        print(json.dumps(allowed(json.loads(args.candidates), banlist), ensure_ascii=False))
    elif args.cmd == "reopen":
        kept = apply_reopen(banlist, json.loads(args.reopened))
        bfile.write_text(json.dumps(kept, indent=2), encoding="utf-8")
        print(json.dumps([e["id"] for e in kept], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
