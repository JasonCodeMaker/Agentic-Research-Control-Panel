"""Stage 5 — adapter generation: corpus-derived, no copied prose, human-gated."""

import pytest
import subprocess
import sys
from pathlib import Path

import common
import build_paper_context as bpc
import convert_corpus as cc
import adapter_inputs as ai
import generate_adapter as ga
import validate_adapter as va
from test_context_builder import _make_project, FULL_YAML
from test_corpus_conversion import GOOD_PAPER, _seed_raw

COMPONENT = Path(__file__).resolve().parent.parent

REQUIRED_SECTIONS = [
    "P0", "P2", "P3", "P4", "P5",
    "Conflict Table", "Section-Specific Guidance", "Cautions",
]


def _project_with_context(tmp_root):
    home = _make_project(tmp_root, FULL_YAML,
                         {"inputs/results/main_table.md": "Recall@5 = 47.3 on MSR-VTT [vaswani2017]"})
    bpc.build_context("demo", root=tmp_root)
    return home


def test_refuses_raw_pdf_corpus(tmp_root):
    _project_with_context(tmp_root)
    with pytest.raises(ValueError):
        ai.collect_inputs("demo", "NeurIPS", corpus_md_paths=["/some/paper.pdf"], root=tmp_root)


def test_generates_adapter_without_corpus(tmp_root):
    _project_with_context(tmp_root)
    result = ga.generate_adapter("demo", "NeurIPS", corpus_md_paths=None, root=tmp_root)
    text = common.read_text(tmp_root / "projects" / "demo" / "adapter" / "dynamic_paper_adapter.md")
    for s in REQUIRED_SECTIONS:
        assert s in text
    assert result["has_corpus"] is False
    assert result["profile"] == "ml_conference"
    # validates clean (no corpus -> nothing to copy) but the human gate is still closed
    report = va.validate_adapter("demo", corpus_md_paths=None, root=tmp_root)
    assert report["valid"] is True
    assert report["gate_confirmed"] is False


def test_extracts_style_cards_without_quotes(tmp_root):
    home = _project_with_context(tmp_root)
    _seed_raw(tmp_root, {"ref1.md": GOOD_PAPER})
    manifest = cc.convert_corpus("demo", backend="manual", root=tmp_root)
    corpus = cc.accepted_corpus(manifest)
    ga.generate_adapter("demo", "NeurIPS", corpus_md_paths=corpus, root=tmp_root)
    cards = list((home / "adapter" / "style_cards").glob("*.md"))
    assert cards, "expected at least one style card"
    report = va.validate_adapter("demo", corpus_md_paths=corpus, root=tmp_root)
    assert report["valid"] is True
    assert report["copy_violations"] == []


def test_rejects_style_cards_with_copied_sentences(tmp_root):
    home = _project_with_context(tmp_root)
    _seed_raw(tmp_root, {"ref1.md": GOOD_PAPER})
    manifest = cc.convert_corpus("demo", backend="manual", root=tmp_root)
    corpus = cc.accepted_corpus(manifest)
    ga.generate_adapter("demo", "NeurIPS", corpus_md_paths=corpus, root=tmp_root)
    # inject a verbatim corpus sentence into a style card
    card = next((home / "adapter" / "style_cards").glob("*.md"))
    common.write_text(card, common.read_text(card) +
                      "\nOur method matches events instead of frames and improves recall.\n")
    report = va.validate_adapter("demo", corpus_md_paths=corpus, root=tmp_root)
    assert report["valid"] is False
    assert report["copy_violations"]


def test_conflict_table_marks_target_over_global(tmp_root):
    _project_with_context(tmp_root)
    _seed_raw(tmp_root, {"ref1.md": GOOD_PAPER})
    manifest = cc.convert_corpus("demo", backend="manual", root=tmp_root)
    corpus = cc.accepted_corpus(manifest)
    ga.generate_adapter("demo", "NeurIPS", corpus_md_paths=corpus, root=tmp_root)
    text = common.read_text(tmp_root / "projects" / "demo" / "adapter" / "dynamic_paper_adapter.md")
    assert "Conflict Table" in text
    assert "target-corpus" in text.lower()


def test_human_gate_blocks_until_confirmed(tmp_root):
    _project_with_context(tmp_root)
    ga.generate_adapter("demo", "NeurIPS", corpus_md_paths=None, root=tmp_root)
    assert va.validate_adapter("demo", root=tmp_root)["gate_confirmed"] is False
    assert va.load_active_adapter("demo", root=tmp_root)["gate_confirmed"] is False
    va.confirm_adapter("demo", root=tmp_root)
    assert va.validate_adapter("demo", root=tmp_root)["gate_confirmed"] is True
    assert va.load_active_adapter("demo", root=tmp_root)["gate_confirmed"] is True


def test_cli_confirm_does_not_require_venue(tmp_path):
    review = tmp_path / "paper" / "projects" / "demo" / "adapter" / "adapter_review.md"
    common.write_text(review, "STATUS: UNCONFIRMED\n")
    result = subprocess.run(
        [sys.executable, str(COMPONENT / "scripts" / "paper_writing.py"), "adapter", "demo", "--confirm"],
        cwd=tmp_path, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0
    assert "STATUS: CONFIRMED" in common.read_text(review)


def test_active_adapter_extracts_numbered_contribution_rule(tmp_root):
    _project_with_context(tmp_root)
    numbered = GOOD_PAPER + "\n## Contributions\n1. First contribution.\n2. Second contribution.\n"
    _seed_raw(tmp_root, {"numbered.md": numbered})
    manifest = cc.convert_corpus("demo", backend="manual", root=tmp_root)
    corpus = cc.accepted_corpus(manifest)
    ga.generate_adapter("demo", "NeurIPS", corpus_md_paths=corpus, root=tmp_root)
    va.confirm_adapter("demo", root=tmp_root)
    active = va.load_active_adapter("demo", root=tmp_root)
    assert active["rules"]["contribution_format"] == "numbered"
