"""Phase 0 — pure Context Pack assembler (node-free, deterministic)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

import context_pack  # noqa: E402


def _inputs(**over):
    base = {
        "project_node": {
            "id": "project/main",
            "spec": {
                "goal": (
                    "Build an auditable retrieval workflow that keeps intent, evidence, "
                    "package execution, and user decisions aligned across repeated experiments."
                ),
                "contributions": [
                    "Keep ratified project intent readable before package execution begins.",
                    "Bind accepted validation tasks to package experiments through provenance.",
                ],
                "out_of_scope": [
                    "Do not claim production adoption without evidence from accepted gates.",
                ],
            },
        },
        "direction_node": {
            "id": "dir/retrieval-v2",
            "spec": {
                "hypothesis": "Contrastive retrieval improves zero-shot Recall@1",
                "metric": {"name": "Recall@1", "dir": "higher"},
                "baselines": ["CLIP zero-shot = 42.3"],
                "success_gate": "Recall@1 >= 48",
            },
        },
        "task_nodes": [
            {
                "id": "task/retrieval-v2/M0-baseline-validity",
                "spec": {
                    "experiment": "Reproduce the baseline before testing the retrieval variant.",
                    "config": "scope:dir/retrieval-v2#m0",
                    "gate": "Baseline must reproduce inside the accepted tolerance.",
                    "control_mode": "SUPERVISED",
                },
            },
        ],
        "package_provenance": {
            "sourceDirection": "dir/retrieval-v2",
            "sourceVersion": 3,
            "sourceChange": "txn-dir",
            "sourceTasks": [{"id": "task/retrieval-v2/M0-baseline-validity"}],
        },
        "pending_scope": [
            {
                "id": "triage-1",
                "level": "task",
                "node_id": "task/retrieval-v2/M0-baseline-validity",
                "change": "Revise the baseline validity gate",
            },
        ],
        "active_pkg": "2026-06-03-retrieval-v2",
        "scope_version": 3,
        "global_scope_version": 5,
        "generated_at": "2026-06-04T00:00:00Z",
        "packages": [
            {
                "id": "2026-05-01-old-idea", "category": "fail", "status": "ARCHIVED",
                "methodsTried": [
                    {"method": "hard-negative mining", "hypothesis": "mining lifts R@1",
                     "gate": "R@1>=48", "measured": "R@1=44", "verdict": "FAIL",
                     "evidencePath": "packages/2026-05-01-old-idea/results.html#m1"},
                ],
            },
            {
                "id": "2026-04-01-win", "category": "success", "status": "ADOPTED",
                "adoptionPath": "models/encoder.py#L40",
                "methodsTried": [
                    {"method": "dual-encoder", "hypothesis": "dual-encoder beats CLIP",
                     "gate": "R@1>=48", "measured": "R@1=51", "verdict": "PASS",
                     "evidencePath": "packages/2026-04-01-win/results.html#w1"},
                ],
            },
        ],
        "learned_rules": ["Always reproduce the baseline before claiming a lift."],
        "analysis_rules": [
            {"pkg": "2026-05-01-old-idea", "slug": "mining-needs-temperature",
             "prose": "Hard-negative mining diverges without temperature scaling above 0.1."},
        ],
    }
    base.update(over)
    return base


# ── content ───────────────────────────────────────────────────────────────

def test_direction_section_carries_spec():
    pack = context_pack.assemble(_inputs())
    md = context_pack.render_md(pack)
    assert "Contrastive retrieval improves zero-shot Recall@1" in md
    assert "Recall@1 >= 48" in md  # success predicate


def test_scope_boot_sections_carry_project_tasks_and_provenance():
    pack = context_pack.assemble(_inputs())
    md = context_pack.render_md(pack)
    keys = {s.key for s in pack.sections}
    assert {"project", "direction", "tasks", "package_provenance", "pending_scope"} <= keys
    assert "Build an auditable retrieval workflow" in md
    assert "Do not claim production adoption" in md
    assert "task/retrieval-v2/M0-baseline-validity" in md
    assert "sourceDirection: dir/retrieval-v2" in md
    assert "triage-1" in md
    assert "unratified" in md


def test_failed_methods_are_cross_package_and_evidence_linked():
    pack = context_pack.assemble(_inputs())
    md = context_pack.render_md(pack)
    assert "hard-negative mining" in md
    # evidence anchor present (faithfulness guarantee 2)
    assert "packages/2026-05-01-old-idea/results.html#m1" in md


def test_adopted_wins_listed_with_adoption_path():
    pack = context_pack.assemble(_inputs())
    md = context_pack.render_md(pack)
    assert "dual-encoder" in md
    assert "models/encoder.py#L40" in md or "results.html#w1" in md


def test_rules_merge_learned_and_analysis_with_anchor():
    pack = context_pack.assemble(_inputs())
    md = context_pack.render_md(pack)
    assert "Always reproduce the baseline" in md
    assert "temperature scaling" in md
    assert "analysis.html#rule-mining-needs-temperature" in md


# ── determinism ─────────────────────────────────────────────────────────────

def test_byte_identical_on_rerun():
    a = context_pack.render_md(context_pack.assemble(_inputs()))
    b = context_pack.render_md(context_pack.assemble(_inputs()))
    assert a == b


def test_package_input_order_does_not_change_output():
    inp1 = _inputs()
    inp2 = _inputs(packages=list(reversed(inp1["packages"])))
    assert context_pack.render_md(context_pack.assemble(inp1)) == \
           context_pack.render_md(context_pack.assemble(inp2))


# ── budget + protected floor ────────────────────────────────────────────────

def test_budget_protects_floor_and_prunes_overlay_first():
    pack = context_pack.assemble(
        _inputs(gaps=[{"id": "G1", "summary": "x" * 1000, "status": "open"}]),
        budget_chars=400,
    )
    md = context_pack.render_md(pack)
    # protected floor survives
    assert "hard-negative mining" in md
    assert "Always reproduce the baseline" in md
    # prunable project overlays are dropped/truncated under a tight budget
    assert pack.stamp["truncated"] is True
    assert "G1" not in md


def test_floor_never_pruned_even_when_over_budget():
    # budget far below the floor size → floor still fully present
    pack = context_pack.assemble(_inputs(), budget_chars=50)
    md = context_pack.render_md(pack)
    assert "hard-negative mining" in md  # protected failure stays


# ── stamp + staleness ───────────────────────────────────────────────────────

def test_stamp_records_scope_version_and_sources_present():
    pack = context_pack.assemble(_inputs())
    assert pack.stamp["scope_version"] == 3
    assert pack.stamp["global_scope_version"] == 5
    assert pack.stamp["sourceDirection"] == "dir/retrieval-v2"
    assert pack.stamp["pendingScope"] == ["triage-1"]
    assert pack.stamp["generated_at"] == "2026-06-04T00:00:00Z"
    assert "failed_methods" in pack.stamp["sources_present"]


def test_is_stale_when_scope_version_advanced():
    pj = context_pack.render_json(context_pack.assemble(_inputs()))
    assert context_pack.is_stale(pj, current_scope_version=6) is True
    assert context_pack.is_stale(pj, current_scope_version=5) is False


# ── shape + graceful degradation ────────────────────────────────────────────

def test_render_json_shape():
    pj = context_pack.render_json(context_pack.assemble(_inputs()))
    assert set(pj) >= {"stamp", "sections"}
    assert all({"key", "title", "lines", "protected"} <= set(s) for s in pj["sections"])


def test_registry_sections_papers_edges_gaps():
    inp = _inputs(
        papers_registry=[{"id": "dpr2020", "title": "Dense Passage Retrieval", "url": "http://x"}],
        edges=[{"from": "paper:dpr2020", "to": "paper:ours", "type": "EXTENDS", "evidence": "sec 3"}],
        gaps=[{"id": "G1", "summary": "no zero-shot evaluation", "status": "open"}],
    )
    md = context_pack.render_md(context_pack.assemble(inp))
    assert "Dense Passage Retrieval" in md                 # papers registry section
    assert "EXTENDS" in md and "paper:dpr2020" in md       # relationships (typed edge)
    assert "no zero-shot evaluation" in md                 # open gaps


def test_registry_sections_absent_when_empty():
    # default fixture has no registries → those sections do not appear
    pack = context_pack.assemble(_inputs())
    keys = {s.key for s in pack.sections}
    assert "relationships" not in keys and "open_gaps" not in keys and "papers_registry" not in keys


def test_graceful_empty_inputs():
    empty = {
        "direction_node": None, "active_pkg": None, "scope_version": 0,
        "generated_at": "2026-06-04T00:00:00Z", "packages": [],
        "learned_rules": [], "analysis_rules": [],
    }
    pack = context_pack.assemble(empty)          # must not raise
    md = context_pack.render_md(pack)
    assert isinstance(md, str) and md.strip()    # still renders a header
    assert pack.stamp["sources_present"] == []
