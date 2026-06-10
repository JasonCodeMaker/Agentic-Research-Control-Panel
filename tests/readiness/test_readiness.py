"""Auto-research admission gate: horizon-by-dial readiness over the 5 run-ready criteria.

The gate verifies, for every experiment inside the unattended horizon the autonomy dial
sets, that the package fans the experiment out to its owning surfaces:
  C1 plan row valid (purpose/gate/after/output)         — always
  C2 implementation change card                         — if requiresCode
  C3 resolvable doc                                     — if complex
  C4 result-gate row scaffolded, gate filled, value blank — always (inverse polarity)
  C5 todo list + 3 ledger tables                        — package-level
"""

import sys
from pathlib import Path

SCRIPTS = (Path(__file__).resolve().parents[2]
           / "skills" / "research-dashboard" / "assets" / "dashboard" / "scripts")
sys.path.insert(0, str(SCRIPTS))
import learnings_lint as L  # noqa: E402


# ─── fixtures ────────────────────────────────────────────────────────────────

def exp(eid, **kw):
    base = {
        "id": eid,
        "purpose": "Run main validation",
        "after": [],
        "output": f"outputs/{eid}/result.json",
        "gate": "top-1 > baseline + 1.0",
        "status": "QUEUED",
    }
    base.update(kw)
    return base


def codes(*ids):
    return {"error": "error", "ids": set(ids)}


IMPL_FILLED_P1 = """<article data-card="changes-agent-detail"><ul data-list="changes-agent-detail">
<li><strong data-field="change-id">change-1</strong>
<code data-field="code-anchor">models/encoder.py:forward</code>
<div data-field="expected-sign">+</div>
<div data-field="expected-magnitude">+1-2% R@1</div>
<div data-field="validating-exp">P1</div></li>
</ul></article>"""

IMPL_PLACEHOLDER = """<article data-card="changes-agent-detail"><ul data-list="changes-agent-detail">
<li><strong data-field="change-id">change-1</strong>
<code data-field="code-anchor">file:function</code>
<div data-field="expected-sign">unmeasured</div>
<div data-field="expected-magnitude">unmeasured</div>
<div data-field="validating-exp">unmeasured</div></li>
</ul></article>"""


def result_gate(*rows):
    body = ""
    for r in rows:
        eid, gate, measured = r
        body += (
            f"<tr><td>{eid}</td><td>valid</td><td>ResNet-18</td><td>{gate}</td>"
            f"<td>{measured}</td><td>unmeasured</td><td>unmeasured</td>"
            f"<td>unmeasured</td><td>unmeasured</td><td>unmeasured</td></tr>"
        )
    return (
        '<table data-table="result-gate"><thead><tr><th>Exp ID</th></tr></thead>'
        f"<tbody>{body}</tbody></table>"
    )


TRACKER_READY = """
<ul class="todo-checklist" data-field="todo-list">
<li><label><input type="checkbox"> Run P0 baseline &mdash; <a href="#x">x</a></label></li>
</ul>
<table data-table="implementation-review"></table>
<table data-table="resource-allocation"></table>
<table data-table="live-check"></table>"""

TRACKER_NO_LEDGER = """
<ul class="todo-checklist" data-field="todo-list">
<li><label><input type="checkbox"> Run P0 baseline</label></li>
</ul>
<table data-table="implementation-review"></table>
<table data-table="live-check"></table>"""

TRACKER_EMPTY_TODO = """
<ul class="todo-checklist" data-field="todo-list">
<li><label><input type="checkbox"> unmeasured</label></li>
</ul>
<table data-table="implementation-review"></table>
<table data-table="resource-allocation"></table>
<table data-table="live-check"></table>"""


def codeset(violations):
    return {v.code for v in violations}


# ─── horizon-by-dial ─────────────────────────────────────────────────────────

def test_horizon_autonomous_returns_whole_dag():
    exps = [exp("P0"), exp("P1", after=["P0"])]
    got = {e["id"] for e in L.horizon("AUTONOMOUS", exps)}
    assert got == {"P0", "P1"}


def test_horizon_supervised_returns_only_frontier_at_launch():
    exps = [exp("P0"), exp("P1", after=["P0"])]
    got = {e["id"] for e in L.horizon("SUPERVISED", exps)}
    assert got == {"P0"}


def test_horizon_supervised_advances_when_root_completed():
    exps = [exp("P0", status="COMPLETED"), exp("P1", after=["P0"])]
    got = {e["id"] for e in L.horizon("SUPERVISED", exps)}
    assert got == {"P1"}


def test_horizon_unknown_dial_defaults_to_whole_dag_failsafe():
    exps = [exp("P0"), exp("P1", after=["P0"])]
    got = {e["id"] for e in L.horizon(None, exps)}
    assert got == {"P0", "P1"}


def test_horizon_checkpoints_folds_into_whole_dag():
    exps = [exp("P0"), exp("P1", after=["P0"])]
    got = {e["id"] for e in L.horizon("CHECKPOINTED", exps)}
    assert got == {"P0", "P1"}


# ─── C1 plan row ─────────────────────────────────────────────────────────────

def test_c1_valid_row_no_violations():
    assert L.check_plan_row("pkg", exp("P0"), {"P0"}) == []


def test_c1_purpose_over_12_words_errors():
    bad = exp("P0", purpose="Run a very long validation that clearly has far too many words to pass")
    assert "readiness-purpose-too-long" in codeset(L.check_plan_row("pkg", bad, {"P0"}))


def test_c1_compound_gate_errors():
    bad = exp("P0", gate="top-1 > baseline AND budget < 2h")
    assert "readiness-gate-compound" in codeset(L.check_plan_row("pkg", bad, {"P0"}))


def test_c1_after_unresolved_errors():
    bad = exp("P1", after=["P9"])
    assert "readiness-after-unresolved" in codeset(L.check_plan_row("pkg", bad, {"P0", "P1"}))


def test_c1_blank_purpose_errors():
    bad = exp("P0", purpose="unmeasured")
    assert "readiness-plan-incomplete" in codeset(L.check_plan_row("pkg", bad, {"P0"}))


# ─── C2 implementation (conditional on requiresCode) ─────────────────────────

def test_c2_requires_code_missing_card_errors():
    e = exp("P1", requiresCode=True)
    items = L.parse_change_items(IMPL_PLACEHOLDER)
    assert "readiness-impl-missing" in codeset(L.check_impl("pkg", e, items))


def test_c2_requires_code_with_filled_card_ok():
    e = exp("P1", requiresCode=True)
    items = L.parse_change_items(IMPL_FILLED_P1)
    assert L.check_impl("pkg", e, items) == []


def test_c2_no_code_requirement_skipped():
    e = exp("P1", requiresCode=False)
    items = L.parse_change_items(IMPL_PLACEHOLDER)
    assert L.check_impl("pkg", e, items) == []


# ─── C3 doc (conditional on complex), resolved on disk ───────────────────────

def test_c3_complex_doc_missing_errors(tmp_path):
    e = exp("P1", complex=True)  # default anchor docs/pipeline.html#p1
    assert "readiness-doc-missing" in codeset(L.check_doc("pkg", e, tmp_path))


def test_c3_complex_doc_resolves_ok(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "pipeline.html").write_text('<h3 id="p1">P1</h3>', encoding="utf-8")
    e = exp("P1", complex=True)
    assert L.check_doc("pkg", e, tmp_path) == []


def test_c3_not_complex_skipped(tmp_path):
    e = exp("P1", complex=False)
    assert L.check_doc("pkg", e, tmp_path) == []


# ─── C4 result-gate row (inverse polarity: blank measured is READY) ──────────

def test_c4_missing_row_errors():
    rows = L.parse_result_gate(result_gate(("P0", "g", "unmeasured")))
    assert "readiness-result-row-missing" in codeset(L.check_result_row("pkg", exp("P1"), rows))


def test_c4_row_present_gate_filled_value_blank_ok():
    rows = L.parse_result_gate(result_gate(("P1", "top-1 > baseline + 1.0", "unmeasured")))
    assert L.check_result_row("pkg", exp("P1"), rows) == []


def test_c4_row_present_gate_blank_errors():
    rows = L.parse_result_gate(result_gate(("P1", "unmeasured", "unmeasured")))
    assert "readiness-result-gate-blank" in codeset(L.check_result_row("pkg", exp("P1"), rows))


# ─── C5 tracker (package-level) ──────────────────────────────────────────────

def test_c5_ready_tracker_no_violations():
    assert L.check_tracker("pkg", TRACKER_READY) == []


def test_c5_missing_ledger_errors():
    assert "readiness-ledger-missing" in codeset(L.check_tracker("pkg", TRACKER_NO_LEDGER))


def test_c5_empty_todo_errors():
    assert "readiness-todo-empty" in codeset(L.check_tracker("pkg", TRACKER_EMPTY_TODO))


# ─── assess_readiness integration + the horizon-by-dial proof ────────────────

def _ready_pkg_dir(tmp_path, with_p1_doc=True):
    """A package dir where P0 and P1 are both fully fanned out."""
    (tmp_path / "docs").mkdir()
    if with_p1_doc:
        (tmp_path / "docs" / "pipeline.html").write_text('<h3 id="p1">P1</h3>', encoding="utf-8")
    (tmp_path / "implementation.html").write_text(IMPL_FILLED_P1, encoding="utf-8")
    (tmp_path / "results.html").write_text(
        result_gate(("P0", "g0 > 0", "unmeasured"), ("P1", "g1 > 0", "unmeasured")),
        encoding="utf-8",
    )
    (tmp_path / "tracker.html").write_text(TRACKER_READY, encoding="utf-8")


def _pkg():
    return {
        "id": "2026-06-04-demo",
        "experiments": [
            exp("P0", requiresCode=False, complex=False),
            exp("P1", after=["P0"], requiresCode=True, complex=True),
        ],
    }


def test_assess_readiness_fully_ready_passes(tmp_path):
    _ready_pkg_dir(tmp_path, with_p1_doc=True)
    rep = L.assess_readiness(_pkg(), "AUTONOMOUS", tmp_path)
    assert rep.errors() == []


def test_assess_readiness_autonomous_flags_downstream_gap(tmp_path):
    # P1 (downstream, complex) has no doc → AUTONOMOUS horizon includes P1 → error.
    _ready_pkg_dir(tmp_path, with_p1_doc=False)
    rep = L.assess_readiness(_pkg(), "AUTONOMOUS", tmp_path)
    assert "readiness-doc-missing" in {v.code for v in rep.errors()}


def test_assess_readiness_supervised_ignores_downstream_gap(tmp_path):
    # Same gap, but SUPERVISED horizon excludes P1 → no error (human present at the pause).
    _ready_pkg_dir(tmp_path, with_p1_doc=False)
    rep = L.assess_readiness(_pkg(), "SUPERVISED", tmp_path)
    assert rep.errors() == []


def test_assess_readiness_empty_experiments_errors(tmp_path):
    _ready_pkg_dir(tmp_path)
    rep = L.assess_readiness({"id": "x", "experiments": []}, "AUTONOMOUS", tmp_path)
    assert "readiness-no-experiments" in {v.code for v in rep.errors()}
