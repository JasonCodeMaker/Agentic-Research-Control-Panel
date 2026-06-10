"""Stage 6 — claim validator: support gate for Abstract/Introduction + P0 fact-mutation checks."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import common
import build_paper_context as bpc

# Sections where every contribution claim must already be supported.
_CLAIM_BEARING = {"abstract", "introduction", "introduction_first_pass", "final_introduction"}
_BLOCKING_STATUS = {"MISSING", "OVERCLAIM"}

# Connector tokens that may sit between a metric name and its value
# ("Recall@5 of 47.3", "Acc = 88", "47.3 Recall@5"). Anything else (e.g. "after 100 epochs")
# means the number is unrelated and must not be treated as the metric's value.
_CONNECTORS = r"(?:=|:|of|is|are|at|to|reach(?:es)?|achiev\w*|scor\w*|hits?|equals?|yields?|~|\(|≈)"


def _changed_values(draft: str, metrics: list[dict]) -> list[str]:
    """Flag a metric whose value ADJACENT in the draft differs from the locked value.

    Only numbers sitting next to the metric name (optionally through one connector) count as
    that metric's reported value. A number elsewhere on the line — epoch counts, layer counts,
    years — is unrelated and is ignored, so faithful drafts are never falsely blocked.
    """
    flagged = []
    for m in metrics or []:
        name, locked = str(m.get("name", "")), str(m.get("value", ""))
        if not name:
            continue
        esc = re.escape(name)
        # name not glued to a larger token (so 'Recall@5' does not match inside 'Recall@50')
        after = re.compile(r"(?<![\w@])" + esc + r"(?![\w])\s*" + _CONNECTORS + r"?\s*(\d+(?:\.\d+)?)")
        before = re.compile(r"(\d+(?:\.\d+)?)\s*" + _CONNECTORS + r"?\s*(?<![\w@])" + esc + r"(?![\w])")
        adjacent = after.findall(draft) + before.findall(draft)
        if adjacent and locked not in adjacent:
            flagged.append(f"{name}: locked {locked}, draft has {sorted(set(adjacent))}")
    return flagged


def _changed_citations(draft: str, locked_keys: list[str]) -> list[str]:
    """Flag citation keys used in the draft that are not in the locked set."""
    keys = set()
    for grp in re.findall(r"\\cite[a-z]*\{([^}]*)\}", draft):
        keys |= {k.strip() for k in grp.split(",")}
    return sorted(k for k in keys if k and k not in set(locked_keys or []))


def _changed_labels(draft: str, locked_labels: list[str]) -> list[str]:
    """Flag \\ref targets not defined in the draft and not in the locked label set."""
    defined = set(re.findall(r"\\label\{([^}]*)\}", draft))
    refs = set(re.findall(r"\\[a-z]*ref\{([^}]*)\}", draft))
    allowed = defined | set(locked_labels or [])
    return sorted(r for r in refs if r not in allowed)


def validate_claims(paper_id, section, draft_file, root=None) -> dict:
    """Validate one section draft against claim support and P0 locked facts."""
    home = common.project_dir(paper_id, root)
    spec = common.load_yaml(home / "paper.yaml")
    term = spec.get("terminology", {}) or {}
    metrics = (spec.get("evidence", {}) or {}).get("metrics", [])
    draft = common.read_text(Path(draft_file))

    statuses, claims = bpc.compute_statuses(paper_id, root)
    unsupported = []
    if section.lower() in _CLAIM_BEARING:
        for c in (claims.get("main", []) or []) + (claims.get("secondary", []) or []):
            if statuses.get(c["id"]) in _BLOCKING_STATUS:
                unsupported.append(f"[{c['id']}] {c.get('text', '')}")

    changed_values = _changed_values(draft, metrics)
    changed_citations = _changed_citations(draft, term.get("citation_keys", []))
    changed_labels = _changed_labels(draft, term.get("latex_labels", []))

    blocked = bool(unsupported or changed_values or changed_citations or changed_labels)
    return {
        "section": section,
        "blocked": blocked,
        "unsupported_claims": unsupported,
        "changed_values": changed_values,
        "changed_citations": changed_citations,
        "changed_labels": changed_labels,
        "ok": not blocked,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Validate claims + P0 facts in a section draft.")
    ap.add_argument("paper_id")
    ap.add_argument("--section", required=True)
    ap.add_argument("--file", required=True)
    args = ap.parse_args()
    report = validate_claims(args.paper_id, args.section, args.file)
    print(f"blocked={report['blocked']}")
    for key in ("unsupported_claims", "changed_values", "changed_citations", "changed_labels"):
        if report[key]:
            print(f"  {key}: {report[key]}")


if __name__ == "__main__":
    main()
