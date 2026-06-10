"""Stage 4 — corpus conversion: manual backend tested, Docling pluggable + graceful."""

import json

import common
import convert_corpus as cc
import evaluate_conversion as ec

GOOD_PAPER = """# Event-Centric Video Retrieval

## Abstract
We study video retrieval. Our method matches events instead of frames and improves recall.
This abstract is long enough to clear the near-empty threshold for the readability gate by a margin.

## Introduction
Video retrieval matters. Existing systems index frames independently, which loses event structure.

## Method
We encode events with a transformer and align them to text queries.

## Experiments
On MSR-VTT we reach 47.3 Recall@5, beating the CLIP baseline.

## References
[1] Some reference here.
"""


def _seed_raw(tmp_root, files):
    home = common.ensure_project_skeleton("demo", root=tmp_root)
    for name, body in files.items():
        common.write_text(home / "inputs" / "corpus_raw" / name, body)
    return home


def test_manual_backend_registers_markdown_and_writes_reports(tmp_root):
    home = _seed_raw(tmp_root, {"ref1.md": GOOD_PAPER})
    manifest = cc.convert_corpus("demo", backend="manual", root=tmp_root)
    assert (home / "inputs" / "corpus_md" / "ref1.md").is_file()
    conv = home / "inputs" / "corpus_conversion"
    assert (conv / "file_manifest.json").is_file()
    assert (conv / "conversion_report.md").is_file()
    assert (conv / "readability_report.md").is_file()
    entry = manifest["sources"][0]
    assert entry["backend"] == "manual"
    assert entry["readability_status"] == "CONVERTED_VERIFIED"


def test_manifest_records_provenance_fields(tmp_root):
    _seed_raw(tmp_root, {"ref1.md": GOOD_PAPER})
    manifest = cc.convert_corpus("demo", backend="manual", root=tmp_root)
    entry = manifest["sources"][0]
    for field in ("source", "backend", "command", "output_md", "output_json",
                  "page_count", "readability_status"):
        assert field in entry


def test_excludes_failed_and_partial_from_accepted(tmp_root):
    files = {
        "good.md": GOOD_PAPER,
        "empty.md": "# x\n",                                   # near-empty -> failed
        "headingonly.md": "# Title\n\nsome body text " * 20,   # no abstract/intro -> partial
    }
    _seed_raw(tmp_root, files)
    manifest = cc.convert_corpus("demo", backend="manual", root=tmp_root)
    accepted = cc.accepted_corpus(manifest)
    names = {p.split("/")[-1] for p in accepted}
    assert "good.md" in names
    assert "empty.md" not in names
    assert "headingonly.md" not in names


def test_docling_backend_absent_degrades_gracefully(tmp_root):
    # Docling is not installed in this env; a PDF source must not crash the run.
    _seed_raw(tmp_root, {"paper.pdf": "%PDF-1.4 fake"})
    manifest = cc.convert_corpus("demo", backend="docling", root=tmp_root)
    entry = manifest["sources"][0]
    assert entry["readability_status"] in ("CONVERSION_FAILED", "CONVERTED_VERIFIED", "PARTIAL_CONVERSION")
    if entry["readability_status"] == "CONVERSION_FAILED":
        assert "docling" in (entry.get("note", "") + entry.get("command", "")).lower()


def test_manual_mode_pdf_marks_manual_md_required(tmp_root):
    _seed_raw(tmp_root, {"paper.pdf": "%PDF-1.4 fake"})
    manifest = cc.convert_corpus("demo", backend="manual", root=tmp_root)
    assert manifest["sources"][0]["readability_status"] == "MANUAL_INPUT_REQUIRED"


def test_readability_gate_statuses():
    assert ec.assess(GOOD_PAPER)[0] == "CONVERTED_VERIFIED"
    assert ec.assess("# x\n")[0] == "CONVERSION_FAILED"
    assert ec.assess("# Title\n\n" + "body text here " * 30)[0] == "PARTIAL_CONVERSION"
