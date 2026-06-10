"""Stage 5 — validate the generated adapter: required sections, no copied prose, human gate."""

from __future__ import annotations

import argparse
from pathlib import Path
import re

import common

REQUIRED_SECTIONS = [
    "## P0 — Hard Preserve",
    "## P2 — Target-Venue Patterns",
    "## P3 — Secondary / Exemplar Patterns",
    "## P4 — Active Profile Fallback",
    "## P5 — Cleanup Rules",
    "## Conflict Table",
    "## Section-Specific Guidance",
    "## Cautions & Human-Review Notes",
]
_N = 8  # n-gram window for the no-copy check


def _copy_violations(adapter_dir: Path, corpus_md_paths) -> list[str]:
    """Flag any 8-gram shared between corpus prose and the adapter/style cards."""
    corpus_ngrams = set()
    for p in corpus_md_paths or []:
        if Path(p).is_file():
            corpus_ngrams |= common.ngrams(common.read_text(Path(p)), _N)
    if not corpus_ngrams:
        return []
    violations = []
    targets = [adapter_dir / "dynamic_paper_adapter.md", adapter_dir / "style_profile.md"]
    targets += list((adapter_dir / "style_cards").glob("*.md"))
    for t in targets:
        if t.is_file() and (common.ngrams(common.read_text(t), _N) & corpus_ngrams):
            violations.append(t.name)
    return violations


def validate_adapter(paper_id, corpus_md_paths=None, root=None) -> dict:
    """Return validity, copy violations, missing sections, and human-gate state."""
    adapter_dir = common.project_dir(paper_id, root) / "adapter"
    adapter_path = adapter_dir / "dynamic_paper_adapter.md"
    if not adapter_path.is_file():
        return {"valid": False, "missing_sections": REQUIRED_SECTIONS,
                "copy_violations": [], "gate_confirmed": False, "conflict_table_ok": False}

    text = common.read_text(adapter_path)
    missing = [s for s in REQUIRED_SECTIONS if s not in text]
    copy_violations = _copy_violations(adapter_dir, corpus_md_paths)
    conflict_ok = ("target-corpus wins" in text.lower()) or ("profile default applies" in text.lower())

    review = adapter_dir / "adapter_review.md"
    gate_confirmed = review.is_file() and "STATUS: CONFIRMED" in common.read_text(review)

    valid = not missing and not copy_violations and conflict_ok
    return {
        "valid": valid,
        "missing_sections": missing,
        "copy_violations": copy_violations,
        "conflict_table_ok": conflict_ok,
        "gate_confirmed": gate_confirmed,
    }


def adapter_exists(paper_id, root=None) -> bool:
    """Return whether this project has a generated dynamic adapter."""
    return (common.project_dir(paper_id, root) / "adapter" / "dynamic_paper_adapter.md").is_file()


def load_active_adapter(paper_id, root=None) -> dict:
    """Load confirmed adapter rules as a small machine-readable policy for drafting/auditing."""
    adapter_dir = common.project_dir(paper_id, root) / "adapter"
    adapter_path = adapter_dir / "dynamic_paper_adapter.md"
    if not adapter_path.is_file():
        return {"exists": False, "gate_confirmed": False, "rules": {}}

    review = adapter_dir / "adapter_review.md"
    gate_confirmed = review.is_file() and "STATUS: CONFIRMED" in common.read_text(review)
    text = common.read_text(adapter_path)
    low = text.lower()
    rules = {}

    if re.search(r"\|\s*contribution format\s*\|[^|\n]*\|\s*numbered list\s*\|", low):
        rules["contribution_format"] = "numbered"
    elif re.search(r"\|\s*contribution format\s*\|[^|\n]*\|\s*prose contributions\s*\|", low):
        rules["contribution_format"] = "prose"

    hedge = re.search(r"\|\s*hedging\s*\|[^|\n]*\|\s*([^|\n]+?)\s*\|", low)
    if hedge:
        level = hedge.group(1).strip()
        rules["hedging_level"] = level
        if level in {"none", "forbidden"}:
            rules["hedging"] = "forbidden"
        else:
            rules["hedging"] = "bounded"

    return {"exists": True, "gate_confirmed": gate_confirmed, "rules": rules}


def confirm_adapter(paper_id, root=None) -> Path:
    """Human gate: flip the adapter review status to CONFIRMED (unlocks drafting)."""
    review = common.project_dir(paper_id, root) / "adapter" / "adapter_review.md"
    text = common.read_text(review).replace("STATUS: UNCONFIRMED", "STATUS: CONFIRMED")
    if "STATUS: CONFIRMED" not in text:
        text += "\nSTATUS: CONFIRMED\n"
    common.write_text(review, text)
    return review


def main() -> None:
    ap = argparse.ArgumentParser(description="Validate the generated adapter.")
    ap.add_argument("paper_id")
    ap.add_argument("--corpus", nargs="*", default=None)
    ap.add_argument("--confirm", action="store_true", help="confirm the human gate")
    args = ap.parse_args()
    if args.confirm:
        confirm_adapter(args.paper_id)
        print("adapter gate CONFIRMED.")
        return
    report = validate_adapter(args.paper_id, corpus_md_paths=args.corpus)
    print(f"valid={report['valid']} gate_confirmed={report['gate_confirmed']}")
    if report["missing_sections"]:
        print(f"  missing sections: {report['missing_sections']}")
    if report["copy_violations"]:
        print(f"  COPIED PROSE in: {report['copy_violations']}")


if __name__ == "__main__":
    main()
