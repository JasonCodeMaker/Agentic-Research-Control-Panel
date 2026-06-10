"""Stage 5 — collect and validate adapter inputs. The adapter never reads raw PDFs."""

from __future__ import annotations

from pathlib import Path

import common
import workflow_kernel as wk


def validate_corpus_paths(corpus_md_paths) -> list[str]:
    """Reject raw PDFs and non-Markdown — corpus must be converted Markdown first."""
    clean = []
    for p in corpus_md_paths or []:
        suffix = Path(p).suffix.lower()
        if suffix == ".pdf":
            raise ValueError(f"adapter must not read raw PDFs directly: {p} "
                             f"(run convert-corpus first, then pass inputs/corpus_md/)")
        if suffix not in (".md", ".markdown", ".txt"):
            raise ValueError(f"corpus input must be Markdown/text, got {p}")
        clean.append(str(p))
    return clean


def collect_inputs(paper_id, venue, corpus_md_paths=None, root=None) -> dict:
    """Assemble the required + optional adapter inputs; enforce the no-raw-PDF rule."""
    home = common.project_dir(paper_id, root)
    context_path = home / "context" / "paper_context.md"
    cem_path = home / "context" / "claim_evidence_map.md"
    if not context_path.is_file():
        raise FileNotFoundError("paper_context.md missing — run `paper-writing context` first.")
    if not venue:
        raise ValueError("target venue is required for adapter generation.")

    corpus = validate_corpus_paths(corpus_md_paths)
    return {
        "paper_id": paper_id,
        "venue": venue,
        "profile": wk.resolve_profile(venue, root),
        "context_path": str(context_path),
        "cem_path": str(cem_path),
        "corpus_md": corpus,
        "has_corpus": bool(corpus),
    }
