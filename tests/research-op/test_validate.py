import sys
sys.path.insert(0, "skills/research-op/scripts")
import validate


def test_methodstried_six_fields_passes_when_complete():
    p = {"method": "m", "hypothesis": "h", "gate": "g",
         "measured": "0.85", "verdict": "pass", "evidencePath": "x"}
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


def test_verdict_enum_accepts_pass_fail_inconclusive():
    for v in ("pass", "fail", "inconclusive"):
        p = {"verdict": v}
        assert validate.rule_methodstried_verdict_enum("pkg", "insert", "methodsTried", p) is None


def test_verdict_enum_rejects_others():
    for v in ("PASS", "ok", "succeeded", "", None):
        rej = validate.rule_methodstried_verdict_enum("pkg", "insert", "methodsTried", {"verdict": v})
        assert rej is not None
        assert rej.rule == "methodstried-verdict-enum"


def test_brainstorm_section_rejects_non_brainstorm_category():
    rej = validate.rule_brainstorm_category_only(
        "pkg", "insert", "brainstorm-section", {},
        state={"category": "in-progress", "status": "CONTEXT_LOADED"},
    )
    assert rej is not None
    assert rej.rule == "brainstorm-category-only"


def test_brainstorm_section_accepts_brainstorm_category():
    rej = validate.rule_brainstorm_category_only(
        "pkg", "insert", "brainstorm-section", {},
        state={"category": "brainstorm", "status": "EXPLORING"},
    )
    assert rej is None
