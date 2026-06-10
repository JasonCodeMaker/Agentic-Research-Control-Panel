import sys
from pathlib import Path

SCRIPTS = (Path(__file__).resolve().parents[2]
           / "skills" / "research-dashboard" / "assets" / "dashboard" / "scripts")
sys.path.insert(0, str(SCRIPTS))
import learnings_lint as L  # noqa: E402


def exp(eid, **kw):
    base = {
        "id": eid,
        "purpose": "Run validation",
        "after": [],
        "output": f"outputs/{eid}/result.json",
        "gate": "Recall@1 >= 48",
        "status": "queued",
        "measures": True,
        "requiresCode": False,
        "complex": False,
    }
    base.update(kw)
    return base


def codes(report):
    return {v.code for v in report.violations}


def _write_pkg(base, *, results="", impl="", tracker="", docs=""):
    if results:
        (base / "results.html").write_text(results, encoding="utf-8")
    if impl:
        (base / "implementation.html").write_text(impl, encoding="utf-8")
    if tracker:
        (base / "tracker.html").write_text(tracker, encoding="utf-8")
    if docs:
        (base / "docs").mkdir(exist_ok=True)
        (base / "docs" / "pipeline.html").write_text(docs, encoding="utf-8")


def result_gate(*exp_ids):
    rows = "".join(
        '<tr data-exp-id="{eid}"><td data-field="exp-id">{eid}</td>'
        '<td data-validity="missing">missing</td><td>baseline</td>'
        '<td data-field="plan-gate">Recall@1 >= 48</td>'
        '<td data-field="observed-metric">unmeasured</td>'
        '<td>unmeasured</td><td>unmeasured</td><td>unmeasured</td>'
        '<td data-field="verdict">unmeasured</td><td>unmeasured</td></tr>'.format(eid=eid)
        for eid in exp_ids
    )
    return '<table data-table="result-gate"><tbody data-table-body="result-gate">' + rows + "</tbody></table>"


def result_slot(eid):
    return (
        '<table data-table="result-slot-{eid}" data-exp-id="{eid}">'
        '<tbody><tr><td>unmeasured</td></tr></tbody></table>'
    ).format(eid=eid)


def test_alignment_requires_predefined_result_table_for_measures_task(tmp_path):
    _write_pkg(
        tmp_path,
        results=result_gate("P0"),
        tracker='<ul data-field="todo-list"><li data-exp-id="P0"><label><input type="checkbox"> Run P0</label></li></ul>'
                '<table data-table="resource-allocation"></table><table data-table="live-check"></table>',
    )
    rep = L.assess_alignment({"id": "pkg", "experiments": [exp("P0")]}, tmp_path)
    assert "alignment-result-table-missing" in codes(rep)


def test_alignment_detects_reverse_orphans_and_status_contradiction(tmp_path):
    _write_pkg(
        tmp_path,
        results=result_gate("P0", "P9") + result_slot("P0"),
        impl='<ul data-list="changes-agent-detail"><li data-exp-id="P8"><div data-field="validating-exp">P8</div></li></ul>',
        tracker='<ul data-field="todo-list"><li data-exp-id="P0"><label><input type="checkbox"> Run P0</label></li></ul>'
                '<table data-table="resource-allocation"></table><table data-table="live-check"></table>',
    )
    rep = L.assess_alignment({"id": "pkg", "experiments": [exp("P0", status="completed")]}, tmp_path)
    assert "alignment-orphan-gate-row" in codes(rep)
    assert "alignment-orphan-change-card" in codes(rep)
    assert "alignment-status-contradiction" in codes(rep)


def test_alignment_flags_unset_legacy_rows_as_warning_only(tmp_path):
    _write_pkg(tmp_path, results="", tracker="")
    legacy = {"id": "P0", "purpose": "Run validation", "after": [],
              "output": "outputs/P0/result.json", "gate": "Recall@1 >= 48"}
    rep = L.assess_alignment({"id": "pkg", "experiments": [legacy]}, tmp_path)
    warnings = {v.code for v in rep.warnings()}
    assert "alignment-flags-unset" in warnings
    assert rep.errors() == []


def test_alignment_field_caps_are_always_on_for_legacy_rows(tmp_path):
    # Transcribed from the real GRDR 2026-06-09-storage-matched-ann P1 entry (spec §1.3):
    # semicolon-joined three-clause gate, no need flags.
    grdr_p1 = {
        "id": "P1",
        "purpose": "Implement IVF-PQ + OPQ FAISS builders + resident-vector search dispatch in eval_ann.py",
        "after": [],
        "output": "baselines/ann_dense_retrieval/eval_ann.py (build_ivfpq_index, build_opq_ivfpq_index)",
        "gate": "Two builders mirror build_ivf_index (normalize->train->add); HNSW/IVF-Flat anchors + "
                "GRDR runtime unchanged (verified vs Current-Best); search routes through FAISS-native "
                "index.search() over resident codes (no cold QueryVideoStore reload).",
        "status": "completed",
    }
    rep = L.assess_alignment({"id": "pkg", "experiments": [grdr_p1]}, tmp_path)
    errors = {v.code for v in rep.errors()}
    warnings = {v.code for v in rep.warnings()}
    assert "alignment-gate-compound" in errors
    assert "alignment-flags-unset" in warnings


def test_alignment_measures_defaults_true_when_any_flag_set(tmp_path):
    _write_pkg(
        tmp_path,
        impl='<ul data-list="changes-agent-detail"><li data-exp-id="P0">'
             '<div data-field="validating-exp">P0</div></li></ul>',
        tracker='<ul data-field="todo-list"><li data-exp-id="P0"><label><input type="checkbox"> Run P0</label></li></ul>'
                '<table data-table="resource-allocation"></table><table data-table="live-check"></table>',
    )
    row = exp("P0", requiresCode=True)
    del row["measures"]  # flag key absent — must default to measuring, not vacuous-pass
    rep = L.assess_alignment({"id": "pkg", "experiments": [row]}, tmp_path)
    errors = codes(rep)
    assert "alignment-result-row-missing" in errors
    assert "alignment-result-table-missing" in errors


def test_alignment_thread_anchor_clean_on_derived_gate_row(tmp_path):
    # The derived row carries data-exp-id on the <tr> tag itself — no false warning.
    _write_pkg(
        tmp_path,
        results=result_gate("P0") + result_slot("P0"),
        tracker='<ul data-field="todo-list"><li data-exp-id="P0"><label><input type="checkbox"> Run P0</label></li></ul>'
                '<table data-table="resource-allocation"></table><table data-table="live-check"></table>',
    )
    rep = L.assess_alignment({"id": "pkg", "experiments": [exp("P0")]}, tmp_path)
    assert "alignment-thread-anchor-missing" not in codes(rep)


def test_alignment_thread_anchor_missing_fires_without_attribute(tmp_path):
    bare_row = ('<table data-table="result-gate"><tbody data-table-body="result-gate">'
                '<tr><td data-field="exp-id">P0</td>'
                '<td data-field="plan-gate">Recall@1 >= 48</td></tr></tbody></table>')
    _write_pkg(
        tmp_path,
        results=bare_row + result_slot("P0"),
        tracker='<ul data-field="todo-list"><li data-exp-id="P0"><label><input type="checkbox"> Run P0</label></li></ul>'
                '<table data-table="resource-allocation"></table><table data-table="live-check"></table>',
    )
    rep = L.assess_alignment({"id": "pkg", "experiments": [exp("P0")]}, tmp_path)
    assert "alignment-thread-anchor-missing" in {v.code for v in rep.warnings()}


def test_alignment_terminal_requires_resolved_measures_task(tmp_path):
    _write_pkg(
        tmp_path,
        results=result_gate("P0") + result_slot("P0"),
        tracker='<ul data-field="todo-list"><li data-exp-id="P0"><label><input type="checkbox"> Run P0</label></li></ul>'
                '<table data-table="resource-allocation"></table><table data-table="live-check"></table>',
    )
    rep = L.assess_alignment({"id": "pkg", "experiments": [exp("P0", status="running")]}, tmp_path, terminal=True)
    assert "alignment-terminal-unresolved" in codes(rep)


def test_gate_compound_catches_semicolon_and_multiple_comparators():
    semicolon = exp("P0", gate="Recall@1 >= 48; latency <= 2h")
    comparators = exp("P0", gate="Recall@1 >= 48 with latency <= 2h")
    assert "readiness-gate-compound" in {v.code for v in L.check_plan_row("pkg", semicolon, {"P0"})}
    assert "readiness-gate-compound" in {v.code for v in L.check_plan_row("pkg", comparators, {"P0"})}

