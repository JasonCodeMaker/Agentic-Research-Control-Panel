"""Project-level rule ops: cross-package, human-ack-gated, synthetic --pkg _project context."""

import json
import subprocess
import sys
from pathlib import Path

CLI = Path(__file__).resolve().parents[2] / "skills" / "research-op" / "scripts" / "research_op.py"


def _run(args, cwd):
    return subprocess.run([sys.executable, str(CLI)] + args, cwd=cwd, capture_output=True, text=True)


def _payload(**kw):
    p = {"level": "project", "kind": "constraint", "slug": "no-eval-leak",
         "title": "No eval leakage", "text": "Never train on the eval split.",
         "rationale": "validity", "addedAt": "2026-06-11", "ack": "approved in chat 2026-06-11"}
    p.update(kw)
    return json.dumps(p)


def _rules(tmp):
    text = (tmp / "research_html" / "data" / "rules.js").read_text()
    return json.loads(text[len("window.RESEARCH_RULES = "):].rstrip().rstrip(";"))


def test_project_insert_requires_ack(tmp_package):
    r = _run(["--pkg", "_project", "--op", "insert", "--target", "rule",
              "--payload", _payload(ack="")], cwd=tmp_package)
    assert r.returncode == 2
    assert json.loads(r.stdout)["rule"] == "rule-project-needs-ack"


def test_project_insert_with_ack_lands(tmp_package):
    r = _run(["--pkg", "_project", "--op", "insert", "--target", "rule",
              "--payload", _payload()], cwd=tmp_package)
    assert r.returncode == 0, r.stdout + r.stderr
    rows = _rules(tmp_package)
    assert rows[0]["id"] == "PRJ-no-eval-leak" and rows[0]["level"] == "project"
    log = tmp_package / "outputs" / "_project" / "_actions.jsonl"
    assert log.exists()


def test_project_universal_writelock(tmp_package):
    r = _run(["--pkg", "_project", "--op", "insert", "--target", "rule",
              "--payload", _payload(level="universal")], cwd=tmp_package)
    assert r.returncode == 2
    assert json.loads(r.stdout)["rule"] == "rule-universal-writelock"


def test_project_insert_rejects_non_constraint_kind(tmp_package):
    r = _run(["--pkg", "_project", "--op", "insert", "--target", "rule",
              "--payload", _payload(kind="lesson")], cwd=tmp_package)
    assert r.returncode == 2
    assert json.loads(r.stdout)["rule"] == "rule-kind-mismatch"


def test_project_insert_rejects_bad_slug(tmp_package):
    r = _run(["--pkg", "_project", "--op", "insert", "--target", "rule",
              "--payload", _payload(slug="No Eval Leak")], cwd=tmp_package)
    assert r.returncode == 2
    assert json.loads(r.stdout)["rule"] == "rule-required-fields"


def test_project_insert_rejects_reserved_origin(tmp_package):
    r = _run(["--pkg", "_project", "--op", "insert", "--target", "rule",
              "--payload", _payload(origin="mirror")], cwd=tmp_package)
    assert r.returncode == 2
    assert json.loads(r.stdout)["rule"] == "rule-origin-reserved"


def test_project_insert_rejects_markup_text(tmp_package):
    r = _run(["--pkg", "_project", "--op", "insert", "--target", "rule",
              "--payload", _payload(text="<b>Never train on eval.</b>")], cwd=tmp_package)
    assert r.returncode == 2
    assert json.loads(r.stdout)["rule"] == "rule-text-plain"


def test_project_rule_rejects_unsupported_ops(tmp_package):
    r = _run(["--pkg", "_project", "--op", "registry-add", "--target", "rule",
              "--payload", json.dumps({"ack": "yes"})], cwd=tmp_package)
    assert r.returncode == 2
    assert json.loads(r.stdout)["rule"] == "rule-op-supported"


def test_project_insert_rejects_malformed_registry(tmp_package):
    rules = tmp_package / "research_html" / "data" / "rules.js"
    rules.write_text("window.RESEARCH_RULES = [{bad}];\n")
    r = _run(["--pkg", "_project", "--op", "insert", "--target", "rule",
              "--payload", _payload()], cwd=tmp_package)
    assert r.returncode == 2
    assert json.loads(r.stdout)["rule"] == "rule-store-malformed"


def test_project_delete_rejected_retire_instead(tmp_package):
    _run(["--pkg", "_project", "--op", "insert", "--target", "rule",
          "--payload", _payload()], cwd=tmp_package)
    r = _run(["--pkg", "_project", "--op", "delete", "--target", "rule",
              "--payload", json.dumps({"id": "PRJ-no-eval-leak", "ack": "yes"})], cwd=tmp_package)
    assert r.returncode == 2
    assert json.loads(r.stdout)["rule"] == "rule-no-hard-delete"


def test_project_retire_with_reason_lands(tmp_package):
    _run(["--pkg", "_project", "--op", "insert", "--target", "rule",
          "--payload", _payload()], cwd=tmp_package)
    r = _run(["--pkg", "_project", "--op", "update", "--target", "rule",
              "--payload", json.dumps({"id": "PRJ-no-eval-leak", "status": "RETIRED",
                                       "retireReason": "constraint lifted", "ack": "yes"})],
             cwd=tmp_package)
    assert r.returncode == 0, r.stdout
    assert _rules(tmp_package)[0]["status"] == "RETIRED"


def test_check_rule_runs_lint(tmp_package):
    r = _run(["--pkg", "_project", "--op", "check", "--target", "rule"], cwd=tmp_package)
    assert r.returncode == 0, r.stdout + r.stderr
