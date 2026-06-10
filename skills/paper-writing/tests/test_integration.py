"""End-to-end: the loop composes (Success Criteria) — context -> plan -> adapter -> gated draft."""

import common
import paper_writing as pw
import build_paper_context as bpc
import workflow_kernel as wk
import generate_adapter as ga
import validate_adapter as va
from test_context_builder import _make_project, FULL_YAML
from test_corpus_conversion import GOOD_PAPER, _seed_raw


def test_loop_composes_to_a_gated_section(tmp_root):
    # 1. context from local evidence
    _make_project(tmp_root, FULL_YAML,
                  {"inputs/results/main_table.md": "Recall@5 = 47.3 on MSR-VTT [vaswani2017]"})
    bpc.build_context("demo", root=tmp_root)

    # 2. plan from the ML/DL profile (NeurIPS -> ml_conference), no corpus
    plan = wk.build_plan("demo", root=tmp_root)
    assert plan["profile"] == "ml_conference"

    # 3. adapter without corpus, stopped at the human gate
    ga.generate_adapter("demo", "NeurIPS", corpus_md_paths=None, root=tmp_root)
    assert va.validate_adapter("demo", root=tmp_root)["gate_confirmed"] is False
    va.confirm_adapter("demo", root=tmp_root)
    assert va.validate_adapter("demo", root=tmp_root)["gate_confirmed"] is True

    # 4. a faithful section draft clears both gates
    home = common.project_dir("demo", root=tmp_root)
    good = home / "drafts" / "introduction.md"
    common.write_text(good, "We present EventRetr. It reaches Recall@5 of 47.3 on MSR-VTT.\n")
    gate = pw._draft_gate("demo", "introduction", good, root=tmp_root)
    assert gate["ready"] is True

    # 5. a draft that mutates a locked fact is blocked
    bad = home / "drafts" / "introduction_bad.md"
    common.write_text(bad, "We present a novel EventRetr reaching Recall@5 of 88.0.\n")
    bad_gate = pw._draft_gate("demo", "introduction", bad, root=tmp_root)
    assert bad_gate["ready"] is False
    assert bad_gate["claims"]["changed_values"]          # 88.0 != locked 47.3
    assert bad_gate["audit"]["generic_overclaims"]        # 'novel'


def test_export_concatenates_drafts(tmp_root):
    common.ensure_project_skeleton("demo", root=tmp_root)
    home = common.project_dir("demo", root=tmp_root)
    common.write_text(home / "drafts" / "abstract.md", "# Abstract\nWe present EventRetr.\n")
    common.write_text(home / "drafts" / "conclusion.md", "# Conclusion\nEventRetr works.\n")
    out = pw.export("demo", "markdown", root=tmp_root)
    text = common.read_text(out)
    assert "Abstract" in text and "Conclusion" in text


def test_adapter_gate_blocks_draft_until_confirmed(tmp_root):
    _make_project(tmp_root, FULL_YAML,
                  {"inputs/results/main_table.md": "Recall@5 = 47.3 on MSR-VTT [vaswani2017]"})
    bpc.build_context("demo", root=tmp_root)
    ga.generate_adapter("demo", "NeurIPS", corpus_md_paths=None, root=tmp_root)
    home = common.project_dir("demo", root=tmp_root)
    draft = home / "drafts" / "introduction.md"
    common.write_text(draft, "We present EventRetr. It reaches Recall@5 of 47.3 on MSR-VTT.\n")
    blocked = pw._draft_gate("demo", "introduction", draft, root=tmp_root)
    assert blocked["ready"] is False
    assert blocked["adapter_blocked"] is True
    va.confirm_adapter("demo", root=tmp_root)
    ready = pw._draft_gate("demo", "introduction", draft, root=tmp_root)
    assert ready["ready"] is True


def test_confirmed_adapter_rule_affects_draft_audit(tmp_root):
    _make_project(tmp_root, FULL_YAML,
                  {"inputs/results/main_table.md": "Recall@5 = 47.3 on MSR-VTT [vaswani2017]"})
    bpc.build_context("demo", root=tmp_root)
    numbered = GOOD_PAPER + "\n## Contributions\n1. First contribution.\n2. Second contribution.\n"
    _seed_raw(tmp_root, {"numbered.md": numbered})
    import convert_corpus as cc
    corpus = cc.accepted_corpus(cc.convert_corpus("demo", backend="manual", root=tmp_root))
    ga.generate_adapter("demo", "NeurIPS", corpus_md_paths=corpus, root=tmp_root)
    va.confirm_adapter("demo", root=tmp_root)
    home = common.project_dir("demo", root=tmp_root)
    draft = home / "drafts" / "introduction.md"
    common.write_text(draft, "We present EventRetr. It reaches Recall@5 of 47.3 on MSR-VTT.\n")
    gate = pw._draft_gate("demo", "introduction", draft, root=tmp_root)
    assert gate["ready"] is False
    assert "numbered contribution list" in gate["audit"]["contribution_issue"]


def test_latex_export_converts_markdown_to_latex_scaffold(tmp_root):
    common.ensure_project_skeleton("demo", root=tmp_root)
    home = common.project_dir("demo", root=tmp_root)
    common.write_text(home / "drafts" / "abstract.md", "# Abstract\n- Keeps Recall@5 of 47.3.\n")
    out = pw.export("demo", "latex", root=tmp_root)
    text = common.read_text(out)
    assert "\\documentclass" in text
    assert "\\section{Abstract}" in text
    assert "\\begin{itemize}" in text
    assert out.suffix == ".tex"
