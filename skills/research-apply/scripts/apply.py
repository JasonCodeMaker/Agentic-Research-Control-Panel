"""research-apply — the self-learning APPLIER (human-gated). Separate skill from the proposer.

Landing a staged proposal requires BOTH a distinct human action (a non-empty human token) AND a
clearing jury verdict. An ungated/auto invocation is refused, so the loop can never rewrite away its
own constraints. The corpus it edits is the project rules only — never the universal protocols,
skills, or validators.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
import verifier  # noqa: E402


def apply(proposal_dir, *, human_token, jury_verdict, rules_path):
    """Land a staged proposal into the project rules. Requires a human action + a sound jury verdict."""
    if not human_token or not str(human_token).strip():
        raise PermissionError("landing a self-learning proposal requires a distinct human action")
    if jury_verdict not in verifier.ACQUIT_STATES:
        raise ValueError(f"jury did not clear the diff: verdict={jury_verdict!r}")
    proposal_dir = Path(proposal_dir)
    proposal = json.loads((proposal_dir / "proposal.json").read_text(encoding="utf-8"))
    rules_path = Path(rules_path)
    with rules_path.open("a", encoding="utf-8") as f:
        f.write(f"- {proposal['suggested_diff']}\n")
    proposal["status"] = "landed"
    proposal["landed_by"] = human_token
    (proposal_dir / "proposal.json").write_text(json.dumps(proposal, indent=2), encoding="utf-8")
    return rules_path


def main(argv=None):
    """CLI: land a staged proposal (human-gated). Raises if ungated — nothing lands."""
    import argparse
    p = argparse.ArgumentParser(description="research-apply: land a staged proposal into the project rules.")
    p.add_argument("--proposal-dir", required=True)
    p.add_argument("--human-token", default="", help="the distinct human action (e.g. the approving message)")
    p.add_argument("--jury-verdict", required=True, help="must be a clearing verdict (sound) to land")
    p.add_argument("--rules-path", required=True)
    args = p.parse_args(argv)
    landed = apply(args.proposal_dir, human_token=args.human_token,
                   jury_verdict=args.jury_verdict, rules_path=args.rules_path)
    print(f"landed -> {landed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
