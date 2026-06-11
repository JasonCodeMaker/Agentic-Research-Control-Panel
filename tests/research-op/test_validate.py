import sys
sys.path.insert(0, "skills/research-op/scripts")
import validate
from pathlib import Path


def test_methodstried_six_fields_passes_when_complete():
    p = {"method": "m", "hypothesis": "h", "gate": "g",
         "measured": "0.85", "verdict": "PASS", "evidencePath": "x"}
    assert validate.rule_methodstried_six_fields("pkg", "insert", "methodsTried", p) is None


def test_methodstried_six_fields_rejects_missing():
    p = {"method": "m", "hypothesis": "h"}
    rej = validate.rule_methodstried_six_fields("pkg", "insert", "methodsTried", p)
    assert rej is not None
    assert rej.rule == "methodstried-six-fields"
    assert "missing" in rej.actual


def test_methodstried_six_fields_rejects_extra():
    p = {"method": "m", "hypothesis": "h", "gate": "g",
         "measured": "0.85", "verdict": "pass", "evidencePath": "x",
         "notes": "extra"}
    rej = validate.rule_methodstried_six_fields("pkg", "insert", "methodsTried", p)
    assert rej is not None
    assert "notes" in rej.actual


def test_methodstried_source_ref_payload_requires_author_fields_only():
    p = {"source_ref": "result_table_P1:current_best", "method": "m", "hypothesis": "h", "gate": "g"}
    assert validate.rule_methodstried_six_fields("pkg", "insert", "methodsTried", p) is None


def test_fact_backed_manual_pass_without_source_ref_is_rejected(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "research_html" / "data" / "packages" / "pkg").mkdir(parents=True)
    p = {"method": "m", "hypothesis": "h", "gate": "g",
         "measured": "0.85", "verdict": "PASS", "evidencePath": "x"}
    rej = validate.rule_methodstried_manual_pass_forbidden("pkg", "insert", "methodsTried", p)
    assert rej is not None
    assert rej.rule == "manual-pass-forbidden"


def test_verdict_enum_accepts_pass_fail_inconclusive():
    for v in ("PASS", "FAIL", "INCONCLUSIVE"):
        p = {"verdict": v}
        assert validate.rule_methodstried_verdict_enum("pkg", "insert", "methodsTried", p) is None


def test_verdict_enum_rejects_others():
    for v in ("pass", "ok", "succeeded", "", None):
        rej = validate.rule_methodstried_verdict_enum("pkg", "insert", "methodsTried", {"verdict": v})
        assert rej is not None
        assert rej.rule == "methodstried-verdict-enum"


def test_payload_json_valid_accepts_valid_json():
    assert validate.rule_payload_json_valid("pkg", "insert", "methodsTried", '{"a":1}') is None


def test_payload_json_valid_rejects_malformed():
    rej = validate.rule_payload_json_valid("pkg", "insert", "methodsTried", "{broken")
    assert rej is not None
    assert rej.rule == "payload-json-valid"


def test_target_known_accepts_listed_target():
    known = {"methodsTried", "experiments-row"}
    assert validate.rule_target_known("pkg", "insert", "methodsTried", {}, known) is None


def test_target_known_rejects_unlisted_target():
    known = {"methodsTried", "experiments-row"}
    rej = validate.rule_target_known("pkg", "insert", "bogus", {}, known)
    assert rej is not None
    assert rej.rule == "target-known"


def test_target_known_passes_when_check_op():
    """check op has target=None, should always pass."""
    assert validate.rule_target_known("pkg", "check", None, {}, set()) is None


# ---- result-gate-ten-cols ----

def test_result_gate_ten_cols_passes_when_complete():
    p = {
        "exp_id": "e1", "validity": "VALID", "baseline": "0.80", "plan_gate": "R@1>0.85",
        "observed_metric": "0.86", "budget_use": "2h", "seed_status": "3/3",
        "artifact_completeness": "complete", "verdict": "PASS", "reason": "exceeded gate",
    }
    assert validate.rule_result_gate_ten_cols("pkg", "insert", "results-gate-row", p) is None


def test_result_gate_ten_cols_rejects_missing():
    p = {"exp_id": "e1", "validity": "ok"}
    rej = validate.rule_result_gate_ten_cols("pkg", "insert", "results-gate-row", p)
    assert rej is not None
    assert rej.rule == "result-gate-ten-cols"
    assert "missing" in rej.actual


# ---- result-gate-validity-enum ----

def test_result_gate_validity_enum_accepts_valid():
    for v in ("VALID", "PARTIAL", "RESULT_FAIL", "UNMEASURED"):
        p = {"validity": v}
        assert validate.rule_result_gate_validity_enum("pkg", "insert", "results-gate-row", p) is None


def test_result_gate_validity_enum_rejects_invalid():
    rej = validate.rule_result_gate_validity_enum("pkg", "insert", "results-gate-row", {"validity": "unknown"})
    assert rej is not None
    assert rej.rule == "result-gate-validity-enum"


# ---- result-block-six-parts ----

_GOOD_BLOCK_HTML = (
    'data-block="title" data-block="summary" data-block="detail" '
    'data-block="main-table" data-block="insight" data-block="ablation"'
)


def test_result_block_six_parts_passes_when_complete():
    assert validate.rule_result_block_six_parts("pkg", "insert", "results-block", {"html": _GOOD_BLOCK_HTML}) is None


def test_result_block_six_parts_passes_with_no_ablation_comment():
    html = _GOOD_BLOCK_HTML.replace('data-block="ablation"', "<!-- no ablation -->")
    assert validate.rule_result_block_six_parts("pkg", "insert", "results-block", {"html": html}) is None


def test_result_block_six_parts_rejects_missing_anchor():
    html = _GOOD_BLOCK_HTML.replace('data-block="summary"', "")
    rej = validate.rule_result_block_six_parts("pkg", "insert", "results-block", {"html": html})
    assert rej is not None
    assert rej.rule == "result-block-six-parts"


# ---- result-block-details-closed ----

def test_result_block_details_closed_passes_when_no_open():
    html = "<details><summary>x</summary></details>"
    assert validate.rule_result_block_details_closed("pkg", "insert", "results-block", {"html": html}) is None


def test_result_block_details_closed_rejects_open_details():
    html = "<details open><summary>x</summary></details>"
    rej = validate.rule_result_block_details_closed("pkg", "insert", "results-block", {"html": html})
    assert rej is not None
    assert rej.rule == "result-block-details-closed"


# ---- live-check-twelve-cols ----

_GOOD_LIVE_ROW = {
    "time": "2026-05-24T10:00:00+10:00", "exp_id": "e1", "agent": "exp-agent-1",
    "run_state": "RUNNING", "last_log": "10:00:00", "progress": "50%",
    "metrics": "R@1=0.84", "resource": "1×A100", "artifacts": "ckpt-500.pt",
    "eta": "unknown", "action": "CONTINUE_RUN", "next_check": "10:10",
}


def test_live_check_twelve_cols_passes_when_complete():
    assert validate.rule_live_check_twelve_cols("pkg", "insert", "tracker-live-check-row", _GOOD_LIVE_ROW) is None


def test_live_check_twelve_cols_rejects_missing():
    p = {"time": "2026-05-24T10:00:00+10:00", "exp_id": "e1"}
    rej = validate.rule_live_check_twelve_cols("pkg", "insert", "tracker-live-check-row", p)
    assert rej is not None
    assert rej.rule == "live-check-twelve-cols"


# ---- live-check-time-local ----

def test_live_check_time_local_passes_with_offset():
    p = dict(_GOOD_LIVE_ROW)
    assert validate.rule_live_check_time_local("pkg", "insert", "tracker-live-check-row", p) is None


def test_live_check_time_local_rejects_utc_z():
    p = dict(_GOOD_LIVE_ROW, time="2026-05-24T00:00:00Z")
    rej = validate.rule_live_check_time_local("pkg", "insert", "tracker-live-check-row", p)
    assert rej is not None
    assert rej.rule == "live-check-time-local"


def test_live_check_time_local_rejects_utc_offset():
    p = dict(_GOOD_LIVE_ROW, time="2026-05-24T00:00:00+00:00")
    rej = validate.rule_live_check_time_local("pkg", "insert", "tracker-live-check-row", p)
    assert rej is not None
    assert rej.rule == "live-check-time-local"


# ---- lane-t1-ack-present ----

def test_lane_t1_ack_present_passes_when_ack_provided():
    state = {"category": "in-progress", "status": "NEXT_ACTION_READY"}
    payload = {"to_category": "success", "ack_token": "T1-2026-05-24"}
    assert validate.rule_lane_t1_ack_present("pkg", "update", "status", payload, state) is None


def test_lane_t1_ack_present_rejects_when_no_ack():
    state = {"category": "in-progress", "status": "NEXT_ACTION_READY"}
    payload = {"to_category": "success"}
    rej = validate.rule_lane_t1_ack_present("pkg", "update", "status", payload, state)
    assert rej is not None
    assert rej.rule == "lane-t1-ack-present"


def test_lane_t1_ack_present_passes_when_same_lane():
    state = {"category": "in-progress", "status": "IMPLEMENTING"}
    payload = {"to_category": "in-progress"}
    assert validate.rule_lane_t1_ack_present("pkg", "update", "status", payload, state) is None


# ---- lane-required-fields ----

def test_lane_required_fields_passes_success_with_all_fields():
    state = {"category": "in-progress"}
    payload = {
        "to_category": "success", "ack_token": "T1",
        "terminationMessage": "gate passed", "adoptionPath": "results.html#e1",
    }
    assert validate.rule_lane_required_fields("pkg", "update", "status", payload, state) is None


def test_lane_required_fields_rejects_success_missing_adoptionpath():
    state = {"category": "in-progress"}
    payload = {"to_category": "success", "ack_token": "T1", "terminationMessage": "done"}
    rej = validate.rule_lane_required_fields("pkg", "update", "status", payload, state)
    assert rej is not None
    assert rej.rule == "lane-required-fields"
    assert "adoptionPath" in rej.actual


# ---- doc-file-path-under-package ----

def test_doc_file_path_passes_valid():
    p = {"path": "research_html/packages/2026-05-01-slug/docs/overview.html"}
    assert validate.rule_doc_file_path_under_package("pkg", "insert", "doc-file", p) is None


def test_doc_file_path_rejects_wrong_location():
    p = {"path": "research_html/packages/2026-05-01-slug/results.html"}
    rej = validate.rule_doc_file_path_under_package("pkg", "insert", "doc-file", p)
    assert rej is not None
    assert rej.rule == "doc-file-path-under-package"


# ---- doc-card-six-parts ----

_GOOD_CARD_HTML = (
    'data-doc-slug="overview" data-doc-purpose="arch" '
    'data-doc-audience="agent" data-doc-status="stable" data-doc-anchor="#overview"'
)


def test_doc_card_six_parts_passes_when_complete():
    assert validate.rule_doc_card_six_parts("pkg", "insert", "doc-card", {"html": _GOOD_CARD_HTML}) is None


def test_doc_card_six_parts_rejects_missing_attr():
    html = _GOOD_CARD_HTML.replace("data-doc-purpose", "data-missing")
    rej = validate.rule_doc_card_six_parts("pkg", "insert", "doc-card", {"html": html})
    assert rej is not None
    assert rej.rule == "doc-card-six-parts"


# ---- doc-group-rationale-present ----

def test_doc_group_rationale_passes_when_present():
    p = {
        "html": _GOOD_CARD_HTML,
        "parent_section_html": '<section data-doc-group-rationale="explains approach">',
    }
    assert validate.rule_doc_group_rationale_present("pkg", "insert", "doc-card", p) is None


def test_doc_group_rationale_rejects_when_absent():
    p = {"html": _GOOD_CARD_HTML, "parent_section_html": "<section>no rationale</section>"}
    rej = validate.rule_doc_group_rationale_present("pkg", "insert", "doc-card", p)
    assert rej is not None
    assert rej.rule == "doc-group-rationale-present"


# ---- experiments-pre-launch-only ----

def test_experiments_pre_launch_only_passes_when_all_queued():
    state = {"category": "in-progress"}
    p = {"existing_experiments_status_list": ["QUEUED", "QUEUED"]}
    assert validate.rule_experiments_pre_launch_only("pkg", "delete", "experiments-row", p, state) is None


def test_experiments_pre_launch_only_rejects_when_running():
    state = {"category": "in-progress"}
    p = {"existing_experiments_status_list": ["RUNNING", "QUEUED"]}
    rej = validate.rule_experiments_pre_launch_only("pkg", "delete", "experiments-row", p, state)
    assert rej is not None
    assert rej.rule == "experiments-pre-launch-only"


# ---- methodstried-terminal-frozen ----

def test_methodstried_terminal_frozen_passes_in_progress():
    state = {"category": "in-progress", "status": "RESULT_ANALYSIS"}
    assert validate.rule_methodstried_terminal_frozen("pkg", "delete", "methodsTried", {}, state) is None


def test_methodstried_terminal_frozen_rejects_in_success():
    state = {"category": "success", "status": "ADOPTED"}
    rej = validate.rule_methodstried_terminal_frozen("pkg", "delete", "methodsTried", {}, state)
    assert rej is not None
    assert rej.rule == "methodstried-terminal-frozen"


def test_methodstried_terminal_frozen_rejects_in_fail():
    state = {"category": "fail", "status": "ARCHIVED"}
    rej = validate.rule_methodstried_terminal_frozen("pkg", "delete", "methodsTried", {}, state)
    assert rej is not None
    assert rej.rule == "methodstried-terminal-frozen"


def _make_plan(tmp_path, pkg, predicate):
    p = tmp_path / "research_html" / "packages" / pkg / "plan.html"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        f'<html><span data-objective-field="success.predicate">{predicate}</span></html>'
    )
    return p


def test_verdict_mechanical_pass_when_measured_meets_gate(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _make_plan(tmp_path, "pkg", "measured >= 0.85")
    rej = validate.rule_verdict_mechanical(
        "pkg", "update", "results-verdict",
        {"measured": "0.87", "verdict": "PASS"},
        state={"category": "in-progress", "status": "RESULT_ANALYSIS"},
    )
    assert rej is None


def test_verdict_mechanical_rejects_pass_when_measured_below_gate(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _make_plan(tmp_path, "pkg", "measured >= 0.85")
    rej = validate.rule_verdict_mechanical(
        "pkg", "update", "results-verdict",
        {"measured": "0.82", "verdict": "PASS"},
        state={"category": "in-progress", "status": "RESULT_ANALYSIS"},
    )
    assert rej is not None
    assert rej.rule == "verdict-mechanical"
    assert "FAIL" in rej.expected
    assert "PASS" in rej.actual


def test_verdict_mechanical_skips_complex_predicate(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _make_plan(tmp_path, "pkg", "measured > baseline + 0.02")
    rej = validate.rule_verdict_mechanical(
        "pkg", "update", "results-verdict",
        {"measured": "0.82", "verdict": "PASS"},
        state={"category": "in-progress", "status": "RESULT_ANALYSIS"},
    )
    assert rej is None  # Stop-Gate handles complex predicates, not us.


# ---- analysis-rule-slug-kebab ----

def test_analysis_rule_slug_kebab_passes_valid():
    rej = validate.rule_analysis_rule_slug_kebab("pkg", "insert", "analysis-rule", {"slug": "my-rule-1"})
    assert rej is None


def test_analysis_rule_slug_kebab_rejects_invalid():
    for bad in ("MyRule", "my_rule", "my rule", ""):
        rej = validate.rule_analysis_rule_slug_kebab("pkg", "insert", "analysis-rule", {"slug": bad})
        assert rej is not None, f"expected reject for {bad!r}"


def test_analysis_rule_no_bold_rejects_strong():
    rej = validate.rule_analysis_rule_no_bold("pkg", "insert", "analysis-rule", {"prose": "<strong>bad</strong>"})
    assert rej is not None
