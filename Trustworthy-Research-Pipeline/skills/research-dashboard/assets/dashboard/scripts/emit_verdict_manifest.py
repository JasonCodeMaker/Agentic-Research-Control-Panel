#!/usr/bin/env python3
"""Parse a GRDR trainer log + write a verdict_finalized manifest.

Designed to be called from a launcher at chain-done. Reads the last
'Candidate-expanded retrieval: {...}' dict from the log, then emits a
manifest JSON with the measured numbers shaped for propagate_apply.py.

Default verdict is 'inconclusive' — training-time eval on the test pool is
not the gate's full 4-cell evaluation. A downstream X-Pool launcher emits the
final pass/fail.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path


KEEP_KEYS = {
    "CanHit@20": "CH@20",
    "CanHit@50": "CH@50",
    "CanHit@100": "CH@100",
    "FullSetHit@All": "FullSet",
    "avg_candidates_per_query": "avg_cand",
    "pre_cap_avg_candidates_per_query": "avg_cand",
}


def parse_final_metrics(log_path: Path) -> dict:
    text = log_path.read_text(errors="ignore")
    pat = re.compile(r"Candidate-expanded retrieval:\s*(\{[^}]*\})", re.DOTALL)
    matches = pat.findall(text)
    if not matches:
        raise RuntimeError(f"no 'Candidate-expanded retrieval:' dict in {log_path}")
    return ast.literal_eval(matches[-1])


def shape_measured(metrics: dict) -> dict:
    out: dict[str, float] = {}
    for src, dst in KEEP_KEYS.items():
        if src in metrics and dst not in out:
            out[dst] = round(float(metrics[src]), 2)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--exp-id", required=True)
    ap.add_argument("--row-anchor", required=True)
    ap.add_argument("--gate", default="")
    ap.add_argument("--verdict", default="inconclusive",
                    choices=["pass", "fail", "inconclusive"])
    ap.add_argument("--phase", default="")
    ap.add_argument("--cell", default="")
    ap.add_argument("--evidence", default="")
    ap.add_argument("--phrase", default="")
    ap.add_argument("--best-model", default="")
    args = ap.parse_args()

    measured = shape_measured(parse_final_metrics(args.log))

    phrase = args.phrase or (
        f"{args.exp_id} training chain done; "
        f"CH@100={measured.get('CH@100', 'NA')} @ avg_cand={measured.get('avg_cand', 'NA')} "
        f"(Panda test pool); X-Pool rerank pending for final verdict"
    )

    manifest = {
        "event": "verdict_finalized",
        "exp_id": args.exp_id,
        "row_anchor": args.row_anchor,
        "measured": measured,
        "gate": args.gate,
        "verdict": args.verdict,
        "evidencePath": args.evidence,
        "lastActionPhrase": phrase,
    }
    for k, v in [("phase", args.phase), ("cell", args.cell), ("best_model", args.best_model)]:
        if v:
            manifest[k] = v

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
