"""Stage 3/6 — load the current section guide and run a style/cleanup audit (P4)."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import common

GENERIC_OVERCLAIMS = [
    "novel", "significant", "state-of-the-art", "comprehensive", "robust",
    "substantial", "promising", "impressive", "extensive experiments demonstrate",
]
EMPTY_TRANSITIONS = ["furthermore", "moreover", "additionally", "in addition", "notably", "importantly"]
HEDGES = ["may", "could", "might", "we believe", "possibly", "perhaps", "it is possible"]


def _whole_phrase_hits(text: str, phrases: list[str]) -> list[str]:
    """Return phrases that appear as whole words/phrases (not as substrings of longer words).

    Word-boundary matching keeps legitimate derived words from tripping the audit:
    'robustness' is a standard eval category, not the overclaim 'robust'; 'dismay' is not 'may'.
    """
    low = text.lower()
    return [p for p in phrases if re.search(r"\b" + re.escape(p) + r"\b", low)]


def guides_for(section: str) -> list[str]:
    """Return the guide names configured for one section — nothing else loads."""
    cfg = common.load_yaml(common.component_root() / "config" / "default_profile.yaml")
    return cfg.get("section_guides", {}).get(section, [section])


def load_guides(section: str) -> dict[str, str]:
    """Load ONLY the current section's guide files from the guide bank."""
    bank = common.component_root() / "references" / "global_guide_bank"
    out = {}
    for name in guides_for(section):
        path = bank / f"{name}.md"
        if path.is_file():
            out[name] = common.read_text(path)
    return out


def _role(paragraph: str, is_first: bool) -> str:
    """Heuristic paragraph-role classification for the audit report."""
    text = paragraph.lower()
    if any(w in text for w in ("however", "limitation", "fails", "cannot", "but ", "does not handle")):
        return "challenge"
    if any(w in text for w in ("we propose", "our method", "we use", "we design", "architecture")):
        return "method"
    if any(w in text for w in ("because", "advantage", "outperforms", "instead of")):
        return "advantage"
    if re.search(r"\d", paragraph) or any(w in text for w in ("table", "figure", "%", "achieves")):
        return "evidence"
    return "opening" if is_first else "body"


def _starts_with_empty_transition(paragraph: str) -> bool:
    lead = paragraph.lstrip().lower()
    return any(lead.startswith(t + ",") or lead.startswith(t + " ") for t in EMPTY_TRANSITIONS)


def audit_section(paper_id, section, file, root=None, adapter=None) -> dict:
    """Audit one section draft against its guide and the cleanup rules."""
    adapter = adapter or {}
    guides = guides_for(section)  # the load contract — only these guides
    text = common.read_text(Path(file))
    paragraphs = common.split_paragraphs(text)

    para_reports, scaffold = [], []
    empty_transitions, generic, hedging = [], [], []
    for i, para in enumerate(paragraphs):
        sentences = common.split_sentences(para)
        topic = sentences[0] if sentences else ""
        scaffold.append(topic)
        hits = _whole_phrase_hits(para, GENERIC_OVERCLAIMS)
        generic.extend(hits)
        is_empty = _starts_with_empty_transition(para)
        if is_empty:
            empty_transitions.append(topic)
        para_reports.append({
            "index": i,
            "topic_sentence": topic,
            "role": _role(para, i == 0),
            "generic_overclaims": hits,
            "empty_transition": is_empty,
        })

    # Hedging is flagged only when the active adapter/profile forbids it.
    if adapter.get("hedging") == "forbidden":
        for para in paragraphs:
            hedging.extend(_whole_phrase_hits(para, HEDGES))

    # Contribution-format rule (adapter-specific), checked only for the introduction.
    contribution_issue = None
    if adapter.get("contribution_format") == "numbered" and section.lower() in {
        "introduction", "introduction_first_pass", "final_introduction"
    }:
        if not re.search(r"^\s*(\d+\.|\(\d+\)|\\item)", text, re.MULTILINE):
            contribution_issue = "adapter requires a numbered contribution list; none found"

    ready = not (empty_transitions or generic or hedging or contribution_issue)
    return {
        "section": section,
        "guides_loaded": guides,
        "paragraphs": para_reports,
        "topic_scaffold": scaffold,
        "empty_transitions": empty_transitions,
        "generic_overclaims": generic,
        "hedging_flags": hedging,
        "contribution_issue": contribution_issue,
        "ready": ready,
    }


def write_revision_log(paper_id, section, entries, root=None) -> Path:
    """Append a section revision-log entry recording rules applied and evidence preserved."""
    home = common.project_dir(paper_id, root)
    path = home / "logs" / "section_revision_log.md"
    existing = common.read_text(path) if path.is_file() else "# Section Revision Log\n"
    block = [f"\n## {section}"]
    for e in entries:
        block.append(f"- rule: {e.get('rule', '')} — source: {e.get('source', '')}")
        if e.get("preserved"):
            block.append(f"  - preserved verbatim: {', '.join(e['preserved'])}")
    common.write_text(path, existing + "\n".join(block) + "\n")
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description="Audit one section draft against its guide.")
    ap.add_argument("paper_id")
    ap.add_argument("--section", required=True)
    ap.add_argument("--file", required=True)
    args = ap.parse_args()
    result = audit_section(args.paper_id, args.section, args.file)
    print(f"guides loaded: {result['guides_loaded']}")
    print(f"ready: {result['ready']}")
    for key in ("empty_transitions", "generic_overclaims", "hedging_flags"):
        if result[key]:
            print(f"  {key}: {result[key]}")


if __name__ == "__main__":
    main()
