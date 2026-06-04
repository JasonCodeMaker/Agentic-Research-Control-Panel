"""research-reflect — the self-learning PROPOSER (read-only on the live corpus).

Observes the signals the rest of the pipeline emits (audit log, scope transitions), detects recurring
failure (doom-loops) and scope-thrash, and stages rule proposals under pending/. It NEVER lands a
change — the applier (research-apply) is a separate, human-gated skill (producer != authority).
"""

import hashlib
import json
from collections import Counter
from pathlib import Path


def detect_doom_loop(actions, threshold=3):
    """Surface a finding when >= threshold consecutive identical failures appear in the audit log."""
    findings = []
    streak_key, streak = None, 0
    for a in actions:
        if a.get("validation") in ("rejected", "failed"):
            key = (a.get("op"), a.get("target"), a.get("rule"))
            streak = streak + 1 if key == streak_key else 1
            streak_key = key
            if streak == threshold:  # emit once, when the threshold is first reached
                findings.append({"kind": "doom-loop", "signature": key, "count": streak})
        else:
            streak_key, streak = None, 0
    return findings


def detect_scope_thrash(transitions, threshold=3):
    """Surface a finding for any node revised >= threshold times (recurring goalpost churn)."""
    counts = Counter(t["node_id"] for t in transitions if t.get("op") == "revise")
    return [{"kind": "scope-thrash", "node_id": node, "count": n}
            for node, n in counts.items() if n >= threshold]


def propose(pending_dir, finding, suggested_diff):
    """Stage a rule proposal under pending/<id>/ — staging only, never the live corpus."""
    pending_dir = Path(pending_dir)
    pid = "p-" + hashlib.sha256(json.dumps(finding, sort_keys=True).encode()).hexdigest()[:10]
    d = pending_dir / pid
    d.mkdir(parents=True, exist_ok=True)
    (d / "proposal.json").write_text(
        json.dumps({"finding": finding, "suggested_diff": suggested_diff, "status": "staged"}, indent=2),
        encoding="utf-8")
    return pid


def _read_jsonl(path):
    """Read a JSONL log into a list of records (empty if the file is absent)."""
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def main(argv=None):
    """CLI: scan the audit log + scope transitions and stage one proposal per finding."""
    import argparse
    p = argparse.ArgumentParser(description="research-reflect: detect recurring failure, stage rule proposals.")
    p.add_argument("--actions", default="", help="path to outputs/<pkg>/_actions.jsonl")
    p.add_argument("--transitions", default="", help="path to outputs/_scope/transitions.jsonl")
    p.add_argument("--pending-dir", required=True, help="staging dir for proposals")
    p.add_argument("--threshold", type=int, default=3)
    args = p.parse_args(argv)
    findings = []
    if args.actions:
        findings += detect_doom_loop(_read_jsonl(args.actions), args.threshold)
    if args.transitions:
        findings += detect_scope_thrash(_read_jsonl(args.transitions), args.threshold)
    staged = []
    for f in findings:
        if f["kind"] == "doom-loop":
            diff = f"After {f['count']} identical failures of {f['signature']}, require an approach or scope change before retrying."
        else:
            diff = f"Node {f['node_id']} was revised {f['count']} times; require human review before further scope revisions."
        staged.append(propose(args.pending_dir, f, diff))
    print(json.dumps({"findings": findings, "staged": staged}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
