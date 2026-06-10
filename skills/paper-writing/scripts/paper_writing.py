"""Unified `paper-writing` entry point — dispatches a mode to the backing script function.

Usage: python3.13 scripts/paper_writing.py <mode> <paper_id> [options]
Modes: init, context, convert-corpus, adapter, plan, draft, revise, audit, export, presubmit.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import common
import build_paper_context as bpc
import convert_corpus as cc
import generate_adapter as ga
import validate_adapter as va
import workflow_kernel as wk
import section_audit as sa
import validate_claims as vc
import presubmission_check as pc


def _draft_gate(paper_id, section, file, root=None) -> dict:
    """The draft/revise gate: section audit + claim validation must both pass."""
    adapter = va.load_active_adapter(paper_id, root=root)
    adapter_blocked = adapter["exists"] and not adapter["gate_confirmed"]
    audit = sa.audit_section(paper_id, section, file, root=root, adapter=adapter["rules"])
    claims = vc.validate_claims(paper_id, section, file, root=root)
    ready = (not adapter_blocked) and audit["ready"] and not claims["blocked"]
    return {"ready": ready, "audit": audit, "claims": claims,
            "adapter": adapter, "adapter_blocked": adapter_blocked}


def _audit_with_adapter(paper_id, section, file, root=None) -> dict:
    """Audit a section with confirmed adapter rules when available."""
    adapter = va.load_active_adapter(paper_id, root=root)
    return sa.audit_section(paper_id, section, file, root=root,
                            adapter=adapter["rules"] if adapter["gate_confirmed"] else {})


def _latex_escape_heading(text: str) -> str:
    """Escape heading text while preserving common LaTeX commands in the body elsewhere."""
    return (text.replace("\\", "\\textbackslash{}")
                .replace("&", "\\&")
                .replace("%", "\\%")
                .replace("_", "\\_")
                .replace("#", "\\#"))


def _markdown_to_latex(markdown: str) -> str:
    """Small Markdown-to-LaTeX converter for section drafts; preserves math/cites/refs in body text."""
    lines, out, in_items = markdown.splitlines(), [], False

    def close_items():
        nonlocal in_items
        if in_items:
            out.append("\\end{itemize}")
            in_items = False

    for raw in lines:
        line = raw.rstrip()
        if not line:
            close_items()
            out.append("")
            continue
        heading = re.match(r"^(#{1,4})\s+(.+)$", line)
        if heading:
            close_items()
            level, title = len(heading.group(1)), _latex_escape_heading(heading.group(2).strip())
            cmd = {1: "section", 2: "subsection", 3: "subsubsection"}.get(level, "paragraph")
            out.append(f"\\{cmd}{{{title}}}")
            continue
        item = re.match(r"^\s*[-*]\s+(.+)$", line)
        if item:
            if not in_items:
                out.append("\\begin{itemize}")
                in_items = True
            out.append(f"\\item {item.group(1).strip()}")
            continue
        close_items()
        out.append(line)
    close_items()
    return "\n".join(out).strip() + "\n"


def export(paper_id, fmt="markdown", root=None) -> Path:
    """Export section drafts in kernel order as Markdown or a compilable LaTeX scaffold."""
    home = common.project_dir(paper_id, root)
    drafts = home / "drafts"
    out_dir = home / "exports" / ("latex" if fmt == "latex" else "markdown")
    out_dir.mkdir(parents=True, exist_ok=True)
    parts = []
    seen = set()
    for key in wk.SECTION_ORDER:
        for cand in (drafts / f"{key}.md", drafts / f"{key}_final.md", drafts / f"{key}_draft0.md"):
            if cand.is_file() and cand.name not in seen:
                seen.add(cand.name)
                parts.append(common.read_text(cand))
    for extra in sorted(drafts.glob("*.md")):
        if extra.name not in seen and extra.name != "paper_plan.md":
            seen.add(extra.name)
            parts.append(common.read_text(extra))
    out = out_dir / (f"{paper_id}.tex" if fmt == "latex" else f"{paper_id}.md")
    body = "\n\n".join(parts) + "\n"
    if fmt == "latex":
        body = (
            "\\documentclass{article}\n"
            "\\usepackage[T1]{fontenc}\n"
            "\\usepackage{graphicx}\n"
            "\\usepackage{amsmath,amssymb}\n"
            "\\usepackage{hyperref}\n"
            "\\begin{document}\n\n"
            + _markdown_to_latex(body)
            + "\n\\end{document}\n"
        )
    common.write_text(out, body)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(prog="paper-writing", description="Standalone paper production component.")
    sub = ap.add_subparsers(dest="mode", required=True)

    def add(name, **kw):
        p = sub.add_parser(name, **kw)
        p.add_argument("paper_id")
        return p

    add("init")
    add("context")
    p_conv = add("convert-corpus"); p_conv.add_argument("--backend", default="docling")
    p_adp = add("adapter")
    p_adp.add_argument("--venue", default=None)
    p_adp.add_argument("--corpus", nargs="*", default=None)
    p_adp.add_argument("--confirm", action="store_true")
    add("plan").add_argument("--profile", default=None)
    for m in ("draft", "revise", "audit"):
        pm = add(m); pm.add_argument("--section", required=True); pm.add_argument("--file", required=True)
    add("export").add_argument("--format", default="markdown", choices=["markdown", "latex"])
    p_ps = add("presubmit")
    p_ps.add_argument("--tex", nargs="*", default=None)
    p_ps.add_argument("--log", default=None)
    p_ps.add_argument("--pdf", default=None)
    p_ps.add_argument("--page-limit", type=int, default=None)
    p_ps.add_argument("--anonymous", action="store_true")

    args = ap.parse_args()
    pid = args.paper_id

    if args.mode == "init":
        print(f"initialised: {common.init_project(pid)}")
    elif args.mode == "context":
        r = bpc.build_context(pid); print(f"context built; gaps={len(r['gaps'])}")
    elif args.mode == "convert-corpus":
        m = cc.convert_corpus(pid, backend=args.backend)
        print(f"converted {len(m['sources'])}; accepted {len(cc.accepted_corpus(m))}")
    elif args.mode == "adapter":
        if args.confirm:
            va.confirm_adapter(pid); print("adapter gate CONFIRMED.")
        else:
            if not args.venue:
                raise SystemExit("--venue is required unless --confirm is used.")
            r = ga.generate_adapter(pid, args.venue, corpus_md_paths=args.corpus)
            print(f"adapter generated ({r['profile']}); HUMAN GATE open — review then --confirm.")
    elif args.mode == "plan":
        r = wk.build_plan(pid, profile=args.profile); print(f"plan built ({r['profile']}).")
    elif args.mode in ("draft", "revise", "audit"):
        if args.mode == "audit":
            r = _audit_with_adapter(pid, args.section, args.file); print(f"ready={r['ready']}")
        else:
            r = _draft_gate(pid, args.section, args.file)
            print(f"ready={r['ready']} (adapter_blocked={r['adapter_blocked']} "
                  f"audit.ready={r['audit']['ready']} blocked={r['claims']['blocked']})")
    elif args.mode == "export":
        print(f"exported: {export(pid, args.format)}")
    elif args.mode == "presubmit":
        r = pc.presubmission_check(pid, tex_files=args.tex, log_file=args.log,
                                   pdf_file=args.pdf, page_limit=args.page_limit,
                                   anonymous=args.anonymous)
        print(f"pre-submission fixes: {len(r['fixes'])}")


if __name__ == "__main__":
    main()
