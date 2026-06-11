"""--target rule: the single mutation entry for the unified rules registry (核心问题 #2)."""

import json
import subprocess
import sys
from pathlib import Path

CLI = Path(__file__).resolve().parents[2] / "skills" / "research-op" / "scripts" / "research_op.py"


def _run(args, cwd):
    return subprocess.run([sys.executable, str(CLI)] + args, cwd=cwd, capture_output=True, text=True)


def _payload(**kw):
    p = {"level": "package", "pkg": "test-pkg", "kind": "binding", "slug": "one-notebook",
         "title": "One notebook per figure", "text": "Every figure gets its own notebook.",
         "rationale": "reproducibility", "addedAt": "2026-06-11"}
    p.update(kw)
    return json.dumps(p)


def _rules(tmp):
    text = (tmp / "research_html" / "data" / "rules.js").read_text()
    return json.loads(text[len("window.RESEARCH_RULES = "):].rstrip().rstrip(";"))


def test_insert_package_binding_rule(tmp_package):
    r = _run(["--pkg", "test-pkg", "--op", "insert", "--target", "rule",
              "--payload", _payload()], cwd=tmp_package)
    assert r.returncode == 0, r.stdout + r.stderr
    rows = _rules(tmp_package)
    assert rows[0]["id"] == "test-pkg#one-notebook" and rows[0]["origin"] == "user"
    log = tmp_package / "outputs" / "test-pkg" / "_actions.jsonl"
    assert any(json.loads(l)["target"] == "rule" for l in log.read_text().splitlines())


def test_insert_universal_rejected(tmp_package):
    r = _run(["--pkg", "test-pkg", "--op", "insert", "--target", "rule",
              "--payload", _payload(level="universal", id="R99")], cwd=tmp_package)
    assert r.returncode == 2
    assert json.loads(r.stdout)["rule"] == "rule-universal-writelock"


def test_insert_missing_fields_rejected(tmp_package):
    r = _run(["--pkg", "test-pkg", "--op", "insert", "--target", "rule",
              "--payload", json.dumps({"level": "package", "pkg": "test-pkg", "kind": "binding"})],
             cwd=tmp_package)
    assert r.returncode == 2
    assert json.loads(r.stdout)["rule"] == "rule-required-fields"


def test_insert_reserved_origin_rejected(tmp_package):
    r = _run(["--pkg", "test-pkg", "--op", "insert", "--target", "rule",
              "--payload", _payload(origin="selfevolve")], cwd=tmp_package)
    assert r.returncode == 2
    assert json.loads(r.stdout)["rule"] == "rule-origin-reserved"


def test_insert_markup_text_rejected(tmp_package):
    r = _run(["--pkg", "test-pkg", "--op", "insert", "--target", "rule",
              "--payload", _payload(text="<strong>Never paste metrics.</strong>")],
             cwd=tmp_package)
    assert r.returncode == 2
    assert json.loads(r.stdout)["rule"] == "rule-text-plain"


def test_lesson_requires_finalized_result(tmp_package):
    r = _run(["--pkg", "test-pkg", "--op", "insert", "--target", "rule",
              "--payload", _payload(kind="lesson", slug="no-mock")], cwd=tmp_package)
    assert r.returncode == 2
    assert json.loads(r.stdout)["rule"] == "rule-lesson-needs-result"


def test_lesson_ignores_verdict_words_outside_result_cells(tmp_package):
    results = tmp_package / "research_html" / "packages" / "test-pkg" / "results.html"
    results.write_text("<html><p>Allowed verdicts: PASS FAIL INCONCLUSIVE DIAGNOSTIC.</p></html>")
    r = _run(["--pkg", "test-pkg", "--op", "insert", "--target", "rule",
              "--payload", _payload(kind="lesson", slug="no-mock")], cwd=tmp_package)
    assert r.returncode == 2
    assert json.loads(r.stdout)["rule"] == "rule-lesson-needs-result"


def test_delete_prelaunch_only(tmp_package):
    _run(["--pkg", "test-pkg", "--op", "insert", "--target", "rule",
          "--payload", _payload()], cwd=tmp_package)
    # CONTEXT_LOADED is pre-launch → hard delete legal
    r = _run(["--pkg", "test-pkg", "--op", "delete", "--target", "rule",
              "--payload", json.dumps({"level": "package", "pkg": "test-pkg",
                                       "id": "test-pkg#one-notebook"})], cwd=tmp_package)
    assert r.returncode == 0, r.stdout
    assert _rules(tmp_package) == []


def test_update_retire_needs_reason(tmp_package):
    _run(["--pkg", "test-pkg", "--op", "insert", "--target", "rule",
          "--payload", _payload()], cwd=tmp_package)
    r = _run(["--pkg", "test-pkg", "--op", "update", "--target", "rule",
              "--payload", json.dumps({"level": "package", "pkg": "test-pkg",
                                       "id": "test-pkg#one-notebook", "status": "RETIRED"})],
             cwd=tmp_package)
    assert r.returncode == 2
    assert json.loads(r.stdout)["rule"] == "rule-lifecycle-fields"


def test_update_retire_with_reason_lands(tmp_package):
    _run(["--pkg", "test-pkg", "--op", "insert", "--target", "rule",
          "--payload", _payload()], cwd=tmp_package)
    r = _run(["--pkg", "test-pkg", "--op", "update", "--target", "rule",
              "--payload", json.dumps({"level": "package", "pkg": "test-pkg",
                                       "id": "test-pkg#one-notebook", "status": "RETIRED",
                                       "retireReason": "superseded by project rule"})],
             cwd=tmp_package)
    assert r.returncode == 0, r.stdout
    assert _rules(tmp_package)[0]["status"] == "RETIRED"


def test_retired_targets_point_to_rule(tmp_package):
    for tgt in ("package-invariant", "analysis-rule"):
        r = _run(["--pkg", "test-pkg", "--op", "insert", "--target", tgt,
                  "--payload", "{}"], cwd=tmp_package)
        assert r.returncode == 2
        env = json.loads(r.stdout)
        assert env["rule"] == "retired-target" and "--target rule" in env["suggested_fix"]
