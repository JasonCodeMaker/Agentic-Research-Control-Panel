"""Stage 7 — mechanical LaTeX/PDF pre-submission audit. Reports actionable fixes; never edits source."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
from pathlib import Path

import common


def _pdf_pages(pdf_file: Path) -> int | None:
    """Read page count via pdfinfo when available."""
    if not shutil.which("pdfinfo"):
        return None
    try:
        out = subprocess.run(["pdfinfo", str(pdf_file)], capture_output=True, text=True, check=True).stdout
    except subprocess.CalledProcessError:
        return None
    m = re.search(r"^Pages:\s+(\d+)", out, re.MULTILINE)
    return int(m.group(1)) if m else None


def _nonembedded_fonts(pdf_file: Path) -> list[str]:
    """List fonts whose emb column is 'no' via pdffonts when available."""
    if not shutil.which("pdffonts"):
        return []
    try:
        out = subprocess.run(["pdffonts", str(pdf_file)], capture_output=True, text=True, check=True).stdout
    except subprocess.CalledProcessError:
        return []
    bad = []
    for line in out.splitlines()[2:]:  # skip header rows
        cols = line.split()
        if len(cols) >= 5 and cols[3] == "no":   # emb column
            bad.append(cols[0])
    return bad


def _undefined_from_log(log_text: str) -> tuple[list[str], list[str]]:
    refs = re.findall(r"Reference `([^']+)'.*undefined", log_text)
    cites = re.findall(r"Citation `([^']+)'.*undefined", log_text)
    return refs, cites


def _latex_log_issues(log_text: str) -> list[str]:
    """Extract common LaTeX problems that are actionable before submission."""
    issues = []
    for pattern, label in (
        (r"Overfull \\hbox[^\n]*", "Overfull hbox"),
        (r"Underfull \\hbox[^\n]*", "Underfull hbox"),
        (r"LaTeX Warning: Label\(s\) may have changed", "rerun LaTeX"),
        (r"! LaTeX Error: ([^\n]+)", "LaTeX error"),
    ):
        for hit in re.findall(pattern, log_text):
            detail = hit if isinstance(hit, str) else " ".join(hit)
            issues.append(f"{label}: {detail}")
    return issues


def _figure_refs(tex_text: str) -> list[str]:
    return re.findall(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]*)\}", tex_text)


def _figure_exists(tex_dir: Path, ref: str) -> bool:
    """A figure exists if the referenced file (or an extension-completed form) is present."""
    cand = tex_dir / ref
    if cand.is_file():
        return True
    if not cand.suffix:  # latex completes the extension
        return any((tex_dir / (ref + ext)).is_file() for ext in (".pdf", ".png", ".jpg", ".jpeg", ".eps"))
    return False


def _anonymization_issues(tex_text: str) -> list[str]:
    """Flag likely author identity leaks for anonymous submissions."""
    issues = []
    author = re.search(r"\\author\{([^}]*)\}", tex_text, re.DOTALL)
    if author and "anonymous" not in author.group(1).lower():
        issues.append("author block is not anonymous")
    if re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", tex_text):
        issues.append("email address appears in source")
    if re.search(r"\\(thanks|affiliation|institute)\{", tex_text):
        issues.append("affiliation/thanks macro appears in source")
    return issues


def _source_issues(tex_text: str) -> list[str]:
    """Flag common source-level problems independent of a full LaTeX compile."""
    issues = []
    if tex_text.count("{") != tex_text.count("}"):
        issues.append("brace count is unbalanced")
    if re.search(r"\b(TODO|FIXME|TBD)\b", tex_text):
        issues.append("TODO/FIXME/TBD placeholder remains")
    if "??" in tex_text:
        issues.append("unresolved reference marker '??' appears in source")
    return issues


def presubmission_check(paper_id, tex_files=None, log_file=None, pdf_file=None,
                        page_limit=None, anonymous=False, root=None) -> dict:
    """Run the mechanical checks and return a report. Source files are never modified."""
    tex_files = [Path(t) for t in (tex_files or [])]
    fixes = []
    safe_fixes_preview = []

    page_count = _pdf_pages(Path(pdf_file)) if pdf_file else None
    page_ok = None
    if page_count is not None and page_limit is not None:
        page_ok = page_count <= page_limit
        if not page_ok:
            fixes.append(f"Page count {page_count} exceeds limit {page_limit} — compress.")

    nonembedded = _nonembedded_fonts(Path(pdf_file)) if pdf_file else []
    for f in nonembedded:
        fixes.append(f"Embed font {f} (try \\usepackage[T1]{{fontenc}} or /prepress).")

    undefined_refs, undefined_citations, latex_log_issues = ([], [], [])
    if log_file and Path(log_file).is_file():
        log_text = common.read_text(Path(log_file))
        refs, cites = _undefined_from_log(log_text)
        undefined_refs, undefined_citations = sorted(set(refs)), sorted(set(cites))
        fixes += [f"Resolve undefined reference: {r}" for r in undefined_refs]
        fixes += [f"Resolve undefined citation: {c}" for c in undefined_citations]
        latex_log_issues = _latex_log_issues(log_text)
        fixes += latex_log_issues

    missing_figures, all_labels, anonymization_issues, source_issues = [], [], [], []
    for tex in tex_files:
        if not tex.is_file():
            continue
        text = common.read_text(tex)
        if anonymous:
            anonymization_issues += _anonymization_issues(text)
        source_issues += _source_issues(text)
        for ref in _figure_refs(text):
            if not _figure_exists(tex.parent, ref):
                missing_figures.append(ref)
                fixes.append(f"Add missing figure file: {ref}")
        all_labels += re.findall(r"\\label\{([^}]*)\}", text)

    duplicate_labels = sorted({lbl for lbl in all_labels if all_labels.count(lbl) > 1})
    fixes += [f"Resolve duplicate label: {lbl}" for lbl in duplicate_labels]
    fixes += [f"Fix anonymization issue: {i}" for i in sorted(set(anonymization_issues))]
    fixes += [f"Fix source issue: {i}" for i in sorted(set(source_issues))]

    if duplicate_labels:
        safe_fixes_preview.append("Rename duplicate labels and update matching references.")
    if source_issues:
        safe_fixes_preview.append("Remove TODO/FIXME/TBD placeholders and resolve visible '??' markers.")
    if anonymization_issues:
        safe_fixes_preview.append("Replace author/affiliation/email fields with anonymous placeholders.")

    return {
        "page_count": page_count,
        "page_ok": page_ok,
        "nonembedded_fonts": nonembedded,
        "undefined_refs": undefined_refs,
        "undefined_citations": undefined_citations,
        "latex_log_issues": latex_log_issues,
        "missing_figures": missing_figures,
        "duplicate_labels": duplicate_labels,
        "anonymization_issues": sorted(set(anonymization_issues)),
        "source_issues": sorted(set(source_issues)),
        "safe_fixes_preview": safe_fixes_preview,
        "fixes": fixes,
    }


def _write_report(paper_id, report, root=None) -> Path:
    home = common.project_dir(paper_id, root)
    lines = ["# Pre-Submission Check", "",
             "| Check | Status | Details |", "| --- | --- | --- |",
             f"| Page count | {report['page_ok']} | {report['page_count']} |",
             f"| Non-embedded fonts | {'ok' if not report['nonembedded_fonts'] else 'FAIL'} | {report['nonembedded_fonts']} |",
             f"| Undefined refs | {'ok' if not report['undefined_refs'] else 'FAIL'} | {report['undefined_refs']} |",
             f"| Undefined citations | {'ok' if not report['undefined_citations'] else 'FAIL'} | {report['undefined_citations']} |",
             f"| LaTeX log issues | {'ok' if not report['latex_log_issues'] else 'FAIL'} | {report['latex_log_issues']} |",
             f"| Missing figures | {'ok' if not report['missing_figures'] else 'FAIL'} | {report['missing_figures']} |",
             f"| Duplicate labels | {'ok' if not report['duplicate_labels'] else 'FAIL'} | {report['duplicate_labels']} |",
             f"| Anonymization | {'ok' if not report['anonymization_issues'] else 'FAIL'} | {report['anonymization_issues']} |",
             f"| Source issues | {'ok' if not report['source_issues'] else 'FAIL'} | {report['source_issues']} |",
             "", "## Suggested fixes (not applied)"]
    lines += [f"- {f}" for f in report["fixes"]] or ["- none"]
    lines += ["", "## Safe fix preview (not applied)"]
    lines += [f"- {f}" for f in report["safe_fixes_preview"]] or ["- none"]
    return common.write_text(home / "logs" / "presubmission_check.md", "\n".join(lines) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="Mechanical LaTeX/PDF pre-submission checks (report only).")
    ap.add_argument("paper_id")
    ap.add_argument("--tex", nargs="*", default=None)
    ap.add_argument("--log", default=None)
    ap.add_argument("--pdf", default=None)
    ap.add_argument("--page-limit", type=int, default=None)
    ap.add_argument("--anonymous", action="store_true")
    args = ap.parse_args()
    report = presubmission_check(args.paper_id, tex_files=args.tex, log_file=args.log,
                                 pdf_file=args.pdf, page_limit=args.page_limit,
                                 anonymous=args.anonymous)
    path = _write_report(args.paper_id, report)
    print(f"pre-submission report written: {path}")
    for f in report["fixes"]:
        print(f"  - {f}")


if __name__ == "__main__":
    main()
