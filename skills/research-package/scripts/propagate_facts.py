#!/usr/bin/env python3
"""Surface newly-locked research artifacts since the last propagation cursor.

This tool implements the Fact Propagation Contract (WORKFLOW.md §5 Step 3.5):
every artifact that lands during a research run (checkpoint, candidate JSON,
sentinel, phase marker, chain-done) is a "locked fact" that the agent must
propagate to every owning surface (results.html, next-action.html, registry,
tracker Resume Block) in the same turn the artifact is observed.

The cursor (manifests/.propagation_cursor) stores the epoch time of the last
successful propagation. Each invocation lists artifacts whose mtime is strictly
greater than the cursor. After applying the indicated updates, the agent re-runs
with --bump to advance the cursor.

Usage:
    propagate_facts.py [--runtime-root PATH] [--bump]

Default --runtime-root: var/research/<package-id> derived from the package dir.
The script is expected to live under research_html/packages/<package-id>/scripts/.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path


CURSOR_NAME = ".propagation_cursor"

SURFACE_MAP: dict[str, list[str]] = {
    "checkpoint": [
        "tracker.html live-check row",
        "results.html Track 1 row + headline strip + result-gate row for owning phase",
        "manifests/<phase>_canhit100.txt sentinel if a new best",
    ],
    "candidate_json": [
        "results.html Track 2 (zero-shot) row or Track 3 (scalability) row",
        "manifests/summary.csv (rerun summarize_results.py)",
    ],
    "sentinel": [
        "tracker.html Resume Block (Last action)",
        "results.html headline strip + result-gate Observed metric cell",
        "research_html/data/research-packages.js (nextRoute, currentBlocker, lastAction, lastUpdated)",
    ],
    "phase_marker": [
        "tracker.html live-check row, tick to-do for closed phase",
    ],
    "chain_done": [
        "results.html final tables + verdict chips",
        "next-action.html chosen route + cited evidence",
        "research_html/data/research-packages.js (nextRoute → STOPPED or run_next_experiment_from_step4; openRuns)",
        "tracker.html Resume Block + mark chain row completed + to-do ticks",
    ],
}


def find_runtime_root(script_path: Path) -> Path:
    """Derive var/research/<package-id> from the script's location.

    Expected layout: research_html/packages/<package-id>/scripts/propagate_facts.py
    """
    pkg_dir = script_path.parent.parent
    package_id = pkg_dir.name
    repo_root = pkg_dir.parents[2]
    return repo_root / "var" / "research" / package_id


def load_cursor(runtime_root: Path) -> float:
    path = runtime_root / "manifests" / CURSOR_NAME
    if not path.exists():
        return 0.0
    try:
        return float(path.read_text().strip() or 0)
    except ValueError:
        return 0.0


def bump_cursor(runtime_root: Path) -> Path:
    path = runtime_root / "manifests" / CURSOR_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{time.time():.6f}\n")
    return path


def scan_artifacts(runtime_root: Path, cursor: float) -> dict[str, list[dict]]:
    facts: dict[str, list[dict]] = {k: [] for k in SURFACE_MAP}

    for p in runtime_root.glob("output/**/best_model.pt"):
        m = p.stat().st_mtime
        if m > cursor:
            facts["checkpoint"].append({"path": str(p), "mtime": m})

    for p in runtime_root.glob("candidates/**/*.json"):
        m = p.stat().st_mtime
        if m > cursor:
            facts["candidate_json"].append({"path": str(p), "mtime": m})

    manifests = runtime_root / "manifests"
    if manifests.exists():
        for p in manifests.glob("*.txt"):
            m = p.stat().st_mtime
            if m > cursor:
                value = p.read_text().strip() if p.stat().st_size < 4096 else "<large>"
                facts["sentinel"].append({"path": str(p), "mtime": m, "value": value})

    logs = runtime_root / "logs"
    if logs.exists():
        ts_re = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] (---|===) (.+)$")
        for log in logs.glob("*chain*.log"):
            if log.stat().st_mtime <= cursor:
                continue
            for line in log.read_text(errors="ignore").splitlines():
                match = ts_re.match(line)
                if not match:
                    continue
                ts_s, kind, body = match.groups()
                try:
                    ts = time.mktime(time.strptime(ts_s, "%Y-%m-%d %H:%M:%S"))
                except ValueError:
                    continue
                if ts <= cursor:
                    continue
                facts["phase_marker"].append({"path": str(log), "mtime": ts, "marker": f"{kind} {body}"})
                if "done ===" in line:
                    facts["chain_done"].append({"path": str(log), "mtime": ts, "marker": body.strip()})

    return facts


def emit_report(facts: dict[str, list[dict]], cursor: float) -> str:
    now = time.time()
    cursor_label = (
        time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(cursor)) if cursor else "unset"
    )
    lines = [
        "# Propagation Report",
        f"cursor: {cursor:.0f} ({cursor_label})",
        f"now:    {now:.0f} ({time.strftime('%Y-%m-%d %H:%M:%S')})",
        "",
    ]
    total = sum(len(v) for v in facts.values())
    if total == 0:
        lines.append("**No new facts since cursor.** Skip Step 3.5 safely this turn.")
        return "\n".join(lines)

    for kind in SURFACE_MAP:
        items = facts[kind]
        if not items:
            continue
        lines.append(f"## {kind} ({len(items)} new)")
        lines.append("")
        lines.append("Surfaces to update in the same turn:")
        for s in SURFACE_MAP[kind]:
            lines.append(f"- {s}")
        lines.append("")
        lines.append("Artifacts:")
        for it in sorted(items, key=lambda d: d["mtime"]):
            stamp = time.strftime("%H:%M:%S", time.localtime(it["mtime"]))
            extra = f" = {it['value']}" if "value" in it else ""
            marker = f" {it['marker']}" if "marker" in it else ""
            lines.append(f"- {stamp} `{it['path']}`{extra}{marker}")
        lines.append("")

    lines.append("---")
    lines.append("After applying all updates, run `propagate_facts.py --bump` to advance the cursor.")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runtime-root", type=Path, default=None,
                        help="Override the runtime root (default: derived from script location)")
    parser.add_argument("--bump", action="store_true",
                        help="Advance the cursor to now and exit (use after applying updates)")
    args = parser.parse_args()

    runtime_root = args.runtime_root or find_runtime_root(Path(__file__).resolve())
    if not runtime_root.exists():
        print(f"error: runtime root not found: {runtime_root}", file=sys.stderr)
        return 2

    if args.bump:
        path = bump_cursor(runtime_root)
        print(f"cursor bumped to now: {path}")
        return 0

    cursor = load_cursor(runtime_root)
    facts = scan_artifacts(runtime_root, cursor)
    print(emit_report(facts, cursor))
    return 0


if __name__ == "__main__":
    sys.exit(main())
