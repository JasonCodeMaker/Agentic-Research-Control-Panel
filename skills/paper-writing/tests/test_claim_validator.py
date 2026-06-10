"""Stage 6 — claim validator: blocks unsupported claims, detects fact mutation (P0)."""

import common
import build_paper_context as bpc
import validate_claims as vc
from test_context_builder import _make_project, FULL_YAML

GOOD_EVIDENCE = {"inputs/results/main_table.md": "Recall@5 = 47.3 on MSR-VTT [vaswani2017]"}


def _draft(tmp_root, body, name="introduction.md"):
    home = common.project_dir("demo", root=tmp_root)
    path = home / "drafts" / name
    common.write_text(path, body)
    return path


def test_blocks_unsupported_intro_claim(tmp_root):
    _make_project(tmp_root, FULL_YAML, results_files={})  # evidence file absent -> C1 missing
    bpc.build_context("demo", root=tmp_root)
    path = _draft(tmp_root, "We propose EventRetr.\n")
    report = vc.validate_claims("demo", "introduction", path, root=tmp_root)
    assert report["blocked"] is True
    assert report["unsupported_claims"]


def test_allows_partial_claim(tmp_root):
    # evidence file exists but the declared number is absent -> C1 partial -> allowed
    _make_project(tmp_root, FULL_YAML, {"inputs/results/main_table.md": "Recall@5 reported, no number"})
    bpc.build_context("demo", root=tmp_root)
    path = _draft(tmp_root, "EventRetr narrows the gap on long clips.\n")
    report = vc.validate_claims("demo", "introduction", path, root=tmp_root)
    assert report["blocked"] is False


def test_detects_changed_numeric_value(tmp_root):
    _make_project(tmp_root, FULL_YAML, GOOD_EVIDENCE)
    bpc.build_context("demo", root=tmp_root)
    path = _draft(tmp_root, "EventRetr reaches Recall@5 of 51.0 on MSR-VTT.\n")  # locked value is 47.3
    report = vc.validate_claims("demo", "introduction", path, root=tmp_root)
    assert any("Recall@5" in v for v in report["changed_values"])


def test_clean_value_passes(tmp_root):
    _make_project(tmp_root, FULL_YAML, GOOD_EVIDENCE)
    bpc.build_context("demo", root=tmp_root)
    path = _draft(tmp_root, "EventRetr reaches Recall@5 of 47.3 on MSR-VTT.\n")
    report = vc.validate_claims("demo", "introduction", path, root=tmp_root)
    assert report["changed_values"] == []


def test_metric_name_near_unrelated_number_not_flagged(tmp_root):
    # The metric name appears with an UNRELATED number (epochs), not its own value.
    # A faithful draft must not be flagged as a fact mutation.
    _make_project(tmp_root, FULL_YAML, GOOD_EVIDENCE)
    bpc.build_context("demo", root=tmp_root)
    path = _draft(tmp_root, "We evaluate Recall@5 after training EventRetr for 100 epochs.\n")
    report = vc.validate_claims("demo", "introduction", path, root=tmp_root)
    assert report["changed_values"] == []


def test_metric_substring_of_other_token_not_flagged(tmp_root):
    # locked metric is Recall@5; the draft mentions a different metric Recall@50.
    _make_project(tmp_root, FULL_YAML, GOOD_EVIDENCE)
    bpc.build_context("demo", root=tmp_root)
    path = _draft(tmp_root, "A larger budget Recall@50 is left for future work.\n")
    report = vc.validate_claims("demo", "introduction", path, root=tmp_root)
    assert report["changed_values"] == []


def test_detects_changed_citation_key(tmp_root):
    _make_project(tmp_root, FULL_YAML, GOOD_EVIDENCE)
    bpc.build_context("demo", root=tmp_root)
    path = _draft(tmp_root, "Prior work \\cite{ghost2024} differs from ours \\cite{vaswani2017}.\n")
    report = vc.validate_claims("demo", "introduction", path, root=tmp_root)
    assert "ghost2024" in report["changed_citations"]
    assert "vaswani2017" not in report["changed_citations"]


def test_detects_changed_label(tmp_root):
    _make_project(tmp_root, FULL_YAML, GOOD_EVIDENCE)
    bpc.build_context("demo", root=tmp_root)
    path = _draft(tmp_root, "See Figure~\\ref{fig:ghost} for the pipeline.\n")  # locked label fig:pipeline
    report = vc.validate_claims("demo", "introduction", path, root=tmp_root)
    assert "fig:ghost" in report["changed_labels"]
