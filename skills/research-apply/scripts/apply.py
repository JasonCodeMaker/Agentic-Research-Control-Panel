"""research-apply — the self-learning APPLIER (human-gated). Separate skill from the proposer.

Landing a staged proposal requires BOTH a distinct human action (a non-empty human token) AND a
clearing jury verdict. An ungated/auto invocation is refused, so the loop can never rewrite away its
own constraints. The corpus it edits is the project rules only — never the universal protocols,
skills, or validators. The landing itself goes through research-op --target rule (the single rule
entry), which re-validates the ack and writes data/rules.js + the audit line.
"""

import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import verifier  # noqa: E402

RESEARCH_OP = Path(__file__).resolve().parents[3] / "skills" / "research-op" / "scripts" / "research_op.py"

# Canonical proposal status values shared with research-reflect.
PROPOSAL_STATUS = ("STAGED", "LANDED")


def _slugify(text):
    """Kebab slug from rule prose (first 6 words)."""
    words = re.findall(r"[a-z0-9]+", str(text).lower())[:6]
    return "-".join(words) or "rule"


def apply(proposal_dir, *, human_token, jury_verdict):
    """Land a staged proposal as a project rule via research-op. Requires human action + sound jury."""
    if not human_token or not str(human_token).strip():
        raise PermissionError("landing a self-learning proposal requires a distinct human action")
    if jury_verdict not in verifier.ACQUIT_STATES:
        raise ValueError(f"jury did not clear the diff: verdict={jury_verdict!r}")
    proposal_dir = Path(proposal_dir)
    proposal = json.loads((proposal_dir / "proposal.json").read_text(encoding="utf-8"))
    prose = proposal["suggested_diff"]
    finding = proposal.get("finding") or {}
    payload = {"level": "project", "kind": "constraint", "slug": _slugify(prose),
               "title": prose[:60], "text": prose,
               "rationale": finding.get("kind") or "self-learning proposal",
               "source": f"research-reflect proposal {proposal_dir.name}",
               "origin": "apply", "addedAt": datetime.date.today().isoformat(),
               "ack": str(human_token)}
    r = subprocess.run([sys.executable, str(RESEARCH_OP), "--pkg", "_project", "--op", "insert",
                        "--target", "rule", "--payload", json.dumps(payload)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"research-op rejected the landing: {r.stdout}{r.stderr}")
    proposal["status"] = "LANDED"
    proposal["landed_by"] = human_token
    (proposal_dir / "proposal.json").write_text(json.dumps(proposal, indent=2), encoding="utf-8")
    return Path("research_html/data/rules.js")


def main(argv=None):
    """CLI: land a staged proposal (human-gated). Raises if ungated — nothing lands."""
    import argparse
    p = argparse.ArgumentParser(description="research-apply: land a staged proposal into the project rules.")
    p.add_argument("--proposal-dir", required=True)
    p.add_argument("--human-token", default="", help="the distinct human action (e.g. the approving message)")
    p.add_argument("--jury-verdict", required=True, help="must be a clearing verdict (sound) to land")
    args = p.parse_args(argv)
    landed = apply(args.proposal_dir, human_token=args.human_token, jury_verdict=args.jury_verdict)
    print(f"landed -> {landed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
