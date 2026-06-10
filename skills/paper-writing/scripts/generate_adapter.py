"""Stage 5 — generate style cards, a style profile, and a human-gated dynamic adapter.

Style cards describe STRUCTURE and STATISTICS only — never corpus prose. That is what guarantees the
"no copied/paraphrased corpus" invariant; `validate_adapter` enforces it with an n-gram check.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import common
import workflow_kernel as wk
import adapter_inputs as ai

# Canonical adapter gate state values.
ADAPTER_GATE = ("UNCONFIRMED", "CONFIRMED")

GATE_MARKER = "STATUS: UNCONFIRMED"


def _style_card(md_text: str, paper_id: str, role: str) -> dict:
    """Compute a structural style card (numbers + booleans, no copied sentences)."""
    low = md_text.lower()
    sentences = common.split_sentences(md_text)
    avg_len = round(sum(len(s.split()) for s in sentences) / max(1, len(sentences)), 1)
    headings = [h.strip("# ").strip() for h in re.findall(r"^#+\s.*$", md_text, re.MULTILINE)]
    we_count = len(re.findall(r"\bwe\b", low))
    passive_count = len(re.findall(r"\b(was|were|been|is\s+\w+ed)\b", low))
    hedges = len(re.findall(r"\b(may|might|could|possibly|perhaps)\b", low))
    math_density = md_text.count("$") + len(re.findall(r"\\\(|\\\[|\\begin\{equation", md_text))
    numbered_contrib = bool(re.search(r"^\s*(\d+\.|\(\d+\))", md_text, re.MULTILINE))
    standalone_rw = any("related work" in h.lower() for h in headings)

    absent = []
    if not numbered_contrib:
        absent.append("no numbered contribution list")
    if not standalone_rw:
        absent.append("no standalone related-work heading")
    if hedges == 0:
        absent.append("no hedging language")

    return {
        "paper_id": paper_id,
        "role": role,
        "avg_sentence_words": avg_len,
        "section_order": headings,
        "voice": "active-dominant" if we_count >= passive_count else "passive-dominant",
        "hedging_level": "low" if hedges <= 2 else "medium" if hedges <= 6 else "high",
        "math_density": "light" if math_density <= 3 else "moderate" if math_density <= 12 else "heavy",
        "numbered_contributions": numbered_contrib,
        "standalone_related_work": standalone_rw,
        "absent_patterns": absent,
    }


def _render_card(card: dict) -> str:
    lines = [
        f"## Paper Style Card: {card['paper_id']}",
        "",
        f"- corpus role: {card['role']}",
        f"- avg sentence length (words): {card['avg_sentence_words']}",
        f"- voice: {card['voice']}",
        f"- hedging level: {card['hedging_level']}",
        f"- math density: {card['math_density']}",
        f"- numbered contributions: {card['numbered_contributions']}",
        f"- standalone related work: {card['standalone_related_work']}",
        "- observed section order: " + " > ".join(card["section_order"][:12]),
        "- what this paper does NOT do: " + ("; ".join(card["absent_patterns"]) or "none observed"),
    ]
    return "\n".join(lines) + "\n"


def _aggregate(cards: list[dict]) -> dict:
    """Pick the most common observed patterns across style cards."""
    if not cards:
        return {}

    def mode(key):
        vals = [c[key] for c in cards]
        return max(set(vals), key=vals.count)

    return {
        "voice": mode("voice"),
        "hedging_level": mode("hedging_level"),
        "math_density": mode("math_density"),
        "numbered_contributions": mode("numbered_contributions"),
        "standalone_related_work": mode("standalone_related_work"),
        "n": len(cards),
    }


def _conflict_table(profile: dict, has_corpus: bool) -> str:
    """Target corpus beats global guide defaults (P2 > P3) on observed dimensions."""
    rows = ["| Dimension | Global guide default | Target corpus pattern | Resolution |",
            "| --- | --- | --- | --- |"]
    if has_corpus and profile:
        contrib = "numbered list" if profile["numbered_contributions"] else "prose contributions"
        rw = "standalone section" if profile["standalone_related_work"] else "integrated into intro"
        rows.append(f"| Contribution format | numbered list | {contrib} | target-corpus wins |")
        rows.append(f"| Related-work placement | integrated | {rw} | target-corpus wins |")
        rows.append(f"| Hedging | bounded | {profile['hedging_level']} | target-corpus wins |")
    else:
        rows.append("| (no corpus) | profile default | — | profile default applies |")
    return "\n".join(rows)


def generate_adapter(paper_id, venue, corpus_md_paths=None, root=None) -> dict:
    """Build style cards -> style profile -> dynamic_paper_adapter.md; stop at the human gate."""
    bundle = ai.collect_inputs(paper_id, venue, corpus_md_paths, root)
    home = common.project_dir(paper_id, root)
    profile_name = bundle["profile"]

    cards = []
    cards_dir = home / "adapter" / "style_cards"
    cards_dir.mkdir(parents=True, exist_ok=True)
    for path in bundle["corpus_md"]:
        card = _style_card(common.read_text(Path(path)), Path(path).stem, role="primary_target")
        cards.append(card)
        common.write_text(cards_dir / f"{card['paper_id']}_style_card.md", _render_card(card))

    aggregate = _aggregate(cards)
    common.write_text(home / "adapter" / "style_profile.md", _render_style_profile(venue, aggregate))

    adapter_text = _render_adapter(paper_id, venue, profile_name, aggregate, bundle["has_corpus"])
    common.write_text(home / "adapter" / "dynamic_paper_adapter.md", adapter_text)
    common.write_text(home / "adapter" / "adapter_review.md", _render_review(paper_id, venue))

    return {
        "profile": profile_name,
        "has_corpus": bundle["has_corpus"],
        "style_cards": [c["paper_id"] for c in cards],
        "adapter_path": str(home / "adapter" / "dynamic_paper_adapter.md"),
        "gate": "UNCONFIRMED",
    }


def _render_style_profile(venue: str, agg: dict) -> str:
    if not agg:
        return f"# Style Profile: {venue}\n\nNo corpus provided. Profile defaults apply.\n"
    return (
        f"# Style Profile: {venue}\nGenerated from {agg['n']} papers.\n\n"
        f"- voice: {agg['voice']}\n- hedging level: {agg['hedging_level']}\n"
        f"- math density: {agg['math_density']}\n"
        f"- numbered contributions: {agg['numbered_contributions']}\n"
        f"- standalone related work: {agg['standalone_related_work']}\n"
    )


def _render_adapter(paper_id, venue, profile_name, agg, has_corpus) -> str:
    p2 = ("Follow the observed target-corpus conventions in `style_profile.md`."
          if has_corpus else f"No corpus provided. Use `{profile_name}` venue hints for {venue}.")
    return f"""# Dynamic Paper Adapter: {paper_id}
Target venue: {venue} · Active profile: {profile_name} · Corpus-derived: {has_corpus}

## P0 — Hard Preserve
Never modify: facts, all \\cite{{}} citation keys, LaTeX math, variable names/notation, numerical
results, footnotes, \\ref{{}}/\\label{{}}, model/dataset/proper-noun names, locked claims in context/.

## P2 — Target-Venue Patterns
{p2}

## P3 — Secondary / Exemplar Patterns
Apply secondary-corpus or lab-exemplar patterns only when P2 is silent.

## P4 — Active Profile Fallback
Fall back to `references/workflow_kernel/profiles/{profile_name}.md` for any dimension P2/P3 leave open.

## P5 — Cleanup Rules
Remove AI-taste phrases, unsupported overclaims, empty transitions, generic adjectives, and mechanical
LaTeX/PDF issues (see `scripts/section_audit.py`).

## Conflict Table
{_conflict_table(agg, has_corpus)}

## Section-Specific Guidance
- Abstract / Introduction: claim-first, every claim `supported` in the claim-evidence map.
- Method: intuition before formalism; one pipeline figure.
- Experiments: each claim maps to a subsection; ablations isolate one variable.
- Related Work: cluster by approach; position against the closest cluster.

## Cautions & Human-Review Notes
- Style cards describe structure only; no corpus prose is reproduced here.
- This adapter is a PROPOSAL. It does not govern the manuscript until a human confirms it.
"""


def _render_review(paper_id, venue) -> str:
    return (
        f"# Adapter Review Gate: {paper_id}\n\n{GATE_MARKER}\n\n"
        f"Target venue: {venue}\n\n"
        "Phase 1 complete. Review `dynamic_paper_adapter.md`. Edit it directly if anything is wrong.\n"
        "To confirm, run `validate_adapter.confirm_adapter` (flips STATUS to CONFIRMED).\n"
        "No manuscript revision may begin until this gate is confirmed.\n"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate the project/venue adapter (stops at human gate).")
    ap.add_argument("paper_id")
    ap.add_argument("--venue", required=True)
    ap.add_argument("--corpus", nargs="*", default=None, help="converted Markdown corpus paths")
    args = ap.parse_args()
    result = generate_adapter(args.paper_id, args.venue, corpus_md_paths=args.corpus)
    print(f"adapter generated ({result['profile']}, corpus={result['has_corpus']}): {result['adapter_path']}")
    print("HUMAN GATE: review the adapter, then confirm before drafting.")


if __name__ == "__main__":
    main()
