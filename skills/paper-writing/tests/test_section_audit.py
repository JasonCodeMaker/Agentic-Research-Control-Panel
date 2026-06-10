"""Stage 3/6 — section audit loads only the current guide and flags style violations."""

import common
import section_audit as sa


def _draft(tmp_root, body):
    home = common.ensure_project_skeleton("demo", root=tmp_root)
    path = home / "drafts" / "introduction.md"
    common.write_text(path, body)
    return path


def test_loads_only_requested_section_guide(tmp_root):
    path = _draft(tmp_root, "We propose EventRetr. It improves Recall@5 by 13x.\n")
    result = sa.audit_section("demo", "introduction", path, root=tmp_root)
    assert result["guides_loaded"] == ["introduction", "paragraph_flow"]
    assert "method" not in result["guides_loaded"]
    assert "experiments" not in result["guides_loaded"]


def test_reports_roles_and_topic_sentences(tmp_root):
    body = (
        "Video retrieval matters for search at scale. Current systems index frames independently.\n\n"
        "We propose EventRetr, which matches events instead of frames. It achieves 47.3 Recall@5.\n"
    )
    path = _draft(tmp_root, body)
    result = sa.audit_section("demo", "introduction", path, root=tmp_root)
    paras = result["paragraphs"]
    assert len(paras) == 2
    assert paras[0]["topic_sentence"].startswith("Video retrieval matters")
    assert all("role" in p for p in paras)
    assert result["topic_scaffold"][1].startswith("We propose EventRetr")


def test_flags_empty_transition_and_generic_overclaim(tmp_root):
    body = (
        "We propose a novel EventRetr method. It is state-of-the-art.\n\n"
        "Furthermore, the model is robust and significant.\n"
    )
    path = _draft(tmp_root, body)
    result = sa.audit_section("demo", "introduction", path, root=tmp_root)
    assert result["empty_transitions"]          # 'Furthermore,' opener
    assert result["generic_overclaims"]         # novel / state-of-the-art / robust / significant
    assert result["ready"] is False


def test_overclaim_matching_is_word_boundary(tmp_root):
    # 'robustness experiments' is a legitimate eval category, not the overclaim 'robust'.
    body = "We include robustness experiments and an analysis of model novelty drivers.\n"
    path = _draft(tmp_root, body)
    result = sa.audit_section("demo", "introduction", path, root=tmp_root)
    assert result["generic_overclaims"] == []


def test_hedging_matching_is_word_boundary(tmp_root):
    # 'dismay' contains 'may' but is not a hedge; must not flag even when hedging is forbidden.
    body = "To our dismay we discovered an error and fixed it.\n"
    path = _draft(tmp_root, body)
    result = sa.audit_section("demo", "introduction", path, root=tmp_root, adapter={"hedging": "forbidden"})
    assert result["hedging_flags"] == []


def test_revision_log_records_rules_and_preserved(tmp_root):
    common.ensure_project_skeleton("demo", root=tmp_root)
    sa.write_revision_log(
        "demo", "introduction",
        [{"rule": "claim-first topic sentence", "source": "profile", "preserved": ["47.3", "vaswani2017"]}],
        root=tmp_root,
    )
    log = common.read_text(tmp_root / "projects" / "demo" / "logs" / "section_revision_log.md")
    assert "claim-first topic sentence" in log
    assert "preserved verbatim: 47.3, vaswani2017" in log


def test_respects_adapter_hedging_rule(tmp_root):
    body = "EventRetr may improve retrieval and could reduce error.\n"
    path = _draft(tmp_root, body)
    forbidden = sa.audit_section("demo", "introduction", path, root=tmp_root,
                                 adapter={"hedging": "forbidden"})
    bounded = sa.audit_section("demo", "introduction", path, root=tmp_root,
                               adapter={"hedging": "bounded"})
    assert forbidden["hedging_flags"]
    assert not bounded["hedging_flags"]
