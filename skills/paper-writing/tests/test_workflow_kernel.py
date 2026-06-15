"""Stage 2 — domain-neutral stage order, profile resolution, corpus-free paper plan."""

from pathlib import Path

import common
import build_paper_context as bpc
import workflow_kernel as wk
from test_context_builder import _make_project, FULL_YAML

COMPONENT = Path(__file__).resolve().parent.parent


def test_stage_order_is_enforceable():
    assert wk.next_stage([]) == "context"
    assert wk.next_stage(["context"]) == "plan"
    assert wk.is_legal_next("context", "plan") is True
    # cannot skip straight from context to compression
    assert wk.is_legal_next("context", "compression") is False


def test_section_order_has_introduction_twice():
    order = wk.SECTION_ORDER
    assert order.index("introduction_first_pass") < order.index("evaluation")
    assert order.index("evaluation") < order.index("final_introduction")
    assert order.index("final_introduction") < order.index("abstract")


def test_systems_tokens_isolated_to_systems_profile():
    kernel_dir = COMPONENT / "references" / "workflow_kernel"
    forbidden = ["smartparagraph", "NSDI", "SIGCOMM", "CoNEXT"]
    for path in kernel_dir.rglob("*.md"):
        if path.name == "systems_networking.md":
            continue
        text = path.read_text(encoding="utf-8")
        for tok in forbidden:
            assert tok not in text, f"systems token {tok!r} leaked into {path.name}"


def test_systems_profile_actually_contains_systems_rules():
    text = (COMPONENT / "references" / "workflow_kernel" / "profiles" / "systems_networking.md").read_text()
    assert "smartparagraph" in text
    assert "NSDI" in text


def test_resolve_profile_from_venue():
    assert wk.resolve_profile("NeurIPS") == "ml_conference"
    assert wk.resolve_profile("NSDI") == "systems_networking"
    # unknown venue -> default
    assert wk.resolve_profile("SomeUnknownVenue2099") == "ml_dl_general"


def test_ml_dl_profile_drives_plan_without_corpus(tmp_root):
    _make_project(tmp_root, FULL_YAML,
                  {"inputs/results/main_table.md": "Recall@5 = 47.3 on MSR-VTT [vaswani2017]"})
    bpc.build_context("demo", root=tmp_root)
    result = wk.build_plan("demo", root=tmp_root)  # no adapter, no corpus
    plan_path = tmp_root / "projects" / "demo" / "context" / "paper_plan.md"
    plan = common.read_text(plan_path)
    # plan follows kernel section order and assigns the main claim
    assert "Draft-0 Introduction" in plan or "introduction_first_pass" in plan
    assert "EventRetr improves Recall@5" in plan  # claim mapped into the plan
    assert result["profile"] == "ml_conference"   # NeurIPS -> ml_conference
    assert "ml_conference" in plan or "ml_dl_general" in plan
    assert result["plan_path"] == str(plan_path)
    assert not (tmp_root / "projects" / "demo" / "drafts" / "paper_plan.md").exists()
