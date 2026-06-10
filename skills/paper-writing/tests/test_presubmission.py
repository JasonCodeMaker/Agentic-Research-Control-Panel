"""Stage 7 — mechanical LaTeX/PDF pre-submission checks. Report only, never modify source."""

import shutil

import common
import presubmission_check as pc


def _minimal_pdf(path, pages=1):
    """Build a tiny but structurally valid PDF so real pdfinfo/pdffonts can parse it."""
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            ("<< /Type /Pages /Kids [%s] /Count %d >>"
             % (" ".join(f"{3+i} 0 R" for i in range(pages)), pages)).encode()]
    for _ in range(pages):
        objs.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>")
    header = b"%PDF-1.4\n"
    body, offsets = b"", []
    for n, obj in enumerate(objs, start=1):
        offsets.append(len(header) + len(body))
        body += f"{n} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_pos = len(header) + len(body)
    xref = b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        xref += ("%010d 00000 n \n" % off).encode()
    trailer = (b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
               % (len(objs) + 1, xref_pos))
    path.write_bytes(header + body + xref + trailer)


def _project(tmp_root):
    return common.ensure_project_skeleton("demo", root=tmp_root)


def test_detects_undefined_refs_and_citations(tmp_root):
    home = _project(tmp_root)
    log = home / "exports" / "latex" / "paper.log"
    common.write_text(log,
        "LaTeX Warning: Reference `fig:ghost' on page 1 undefined on input line 5.\n"
        "LaTeX Warning: Citation `ghost2024' on page 2 undefined on input line 9.\n")
    report = pc.presubmission_check("demo", log_file=log, root=tmp_root)
    assert "fig:ghost" in report["undefined_refs"]
    assert "ghost2024" in report["undefined_citations"]
    assert report["fixes"]


def test_lists_missing_figure_files(tmp_root):
    home = _project(tmp_root)
    figs = home / "exports" / "latex" / "figs"
    common.write_text(figs / "exists.pdf", "%PDF-1.4\n")
    tex = home / "exports" / "latex" / "paper.tex"
    common.write_text(tex,
        "\\includegraphics{figs/exists.pdf}\n\\includegraphics[width=1in]{figs/missing.pdf}\n")
    report = pc.presubmission_check("demo", tex_files=[tex], root=tmp_root)
    assert any("missing.pdf" in m for m in report["missing_figures"])
    assert all("exists.pdf" not in m for m in report["missing_figures"])


def test_reads_page_count_and_fonts_from_pdf(tmp_root):
    if not shutil.which("pdfinfo"):
        import pytest
        pytest.skip("pdfinfo not available")
    home = _project(tmp_root)
    pdf = home / "exports" / "pdf" / "paper.pdf"
    pdf.parent.mkdir(parents=True, exist_ok=True)
    _minimal_pdf(pdf, pages=3)
    report = pc.presubmission_check("demo", pdf_file=pdf, page_limit=8, root=tmp_root)
    assert report["page_count"] == 3
    assert report["page_ok"] is True
    assert isinstance(report["nonembedded_fonts"], list)  # no fonts -> empty list


def test_page_count_none_without_pdf(tmp_root):
    _project(tmp_root)
    report = pc.presubmission_check("demo", root=tmp_root)
    assert report["page_count"] is None


def test_detects_duplicate_labels(tmp_root):
    home = _project(tmp_root)
    tex = home / "exports" / "latex" / "paper.tex"
    common.write_text(tex, "\\label{fig:a}\n\\label{fig:a}\n\\label{fig:b}\n")
    report = pc.presubmission_check("demo", tex_files=[tex], root=tmp_root)
    assert "fig:a" in report["duplicate_labels"]
    assert "fig:b" not in report["duplicate_labels"]


def test_does_not_modify_source(tmp_root):
    home = _project(tmp_root)
    tex = home / "exports" / "latex" / "paper.tex"
    original = "\\includegraphics{figs/missing.pdf}\n"
    common.write_text(tex, original)
    pc.presubmission_check("demo", tex_files=[tex], root=tmp_root)
    assert common.read_text(tex) == original  # unchanged


def test_detects_anonymization_and_source_issues(tmp_root):
    home = _project(tmp_root)
    tex = home / "exports" / "latex" / "paper.tex"
    common.write_text(tex,
        "\\author{Jane Doe}\\thanks{University}\n"
        "Contact jane@example.edu. TODO fix this. See Figure~\\ref{fig:x}??\n")
    report = pc.presubmission_check("demo", tex_files=[tex], anonymous=True, root=tmp_root)
    assert report["anonymization_issues"]
    assert report["source_issues"]
    assert report["safe_fixes_preview"]


def test_detects_common_latex_log_issues(tmp_root):
    home = _project(tmp_root)
    log = home / "exports" / "latex" / "paper.log"
    common.write_text(log,
        "Overfull \\hbox (12.0pt too wide) in paragraph at lines 1--2\n"
        "! LaTeX Error: File `missing.sty' not found.\n")
    report = pc.presubmission_check("demo", log_file=log, root=tmp_root)
    assert any("Overfull hbox" in issue for issue in report["latex_log_issues"])
    assert any("LaTeX error" in issue for issue in report["latex_log_issues"])
