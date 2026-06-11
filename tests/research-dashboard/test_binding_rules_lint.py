"""Directive-propagation lint (Fix 3c, the E0 contract): a binding rule is a directive change, so it must
propagate to the tracker lastAction mirror + the registry lastUpdated in the same turn — otherwise the
package looks unchanged (the session-b07d0f85 Issue-3 symptom: rule added, tracker/registry untouched).
Binding rules now live as registry rows (data/rules.js), not bindingRules[] (核心问题 #2).
"""

import sys
from pathlib import Path

SCRIPTS = (Path(__file__).resolve().parents[2]
           / "skills" / "research-dashboard" / "assets" / "dashboard" / "scripts")
sys.path.insert(0, str(SCRIPTS))
import learnings_lint as L  # noqa: E402


def _data(pkg):
    return {"schema": {"in-progress": {"states": ["CONTEXT_LOADED"], "required": {"_all": []},
                                       "forbidden": []}},
            "packages": [pkg], "contributionSpine": []}


def _pkg(**kw):
    p = {"id": "p1", "category": "in-progress", "status": "CONTEXT_LOADED", "pages": []}
    p.update(kw)
    return p


def _binding(**kw):
    r = {"id": "p1#one-notebook", "level": "package", "pkg": "p1", "kind": "binding",
         "title": "One notebook per figure", "text": "one notebook per figure",
         "rationale": "repro", "source": "user", "origin": "user",
         "status": "ACTIVE", "addedAt": "2026-06-09"}
    r.update(kw)
    return r


def _codes(rep):
    return {v.code for v in rep.violations}


def test_binding_rule_missing_rule_text_is_error():
    rep = L.lint_status(_data(_pkg()), rules=[_binding(text="")])
    assert "rule-row-schema" in _codes(rep)


def test_unpropagated_binding_rule_warns():
    rep = L.lint_status(_data(_pkg()), rules=[_binding()])
    assert "directive-not-propagated" in _codes(rep)


def test_propagated_binding_rule_is_clean():
    rep = L.lint_status(_data(_pkg(lastAction="added figure-construction rule",
                                   lastUpdated="2026-06-09")),
                        rules=[_binding()])
    assert "directive-not-propagated" not in _codes(rep)
    assert "rule-row-schema" not in _codes(rep)


def test_no_binding_rules_no_warning():
    assert "directive-not-propagated" not in _codes(L.lint_status(_data(_pkg()), rules=[]))


def test_retired_binding_rule_does_not_warn():
    rep = L.lint_status(_data(_pkg()),
                        rules=[_binding(status="RETIRED", retireReason="superseded")])
    assert "directive-not-propagated" not in _codes(rep)
