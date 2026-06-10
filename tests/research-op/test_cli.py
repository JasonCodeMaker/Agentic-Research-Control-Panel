import json
import subprocess
import sys
from pathlib import Path

CLI = Path(__file__).resolve().parents[2] / "skills" / "research-op" / "scripts" / "research_op.py"
CREATE = Path(__file__).resolve().parents[2] / "skills" / "research-package" / "scripts" / "create_research_package.py"


def _run(args, cwd):
    return subprocess.run(
        [sys.executable, str(CLI)] + args,
        cwd=cwd, capture_output=True, text=True,
    )


def test_check_passes_on_legal_state(tmp_package):
    r = _run(["--pkg", "test-pkg", "--op", "check"], cwd=tmp_package)
    assert r.returncode == 0, r.stderr
    log = tmp_package / "outputs" / "test-pkg" / "_actions.jsonl"
    entry = json.loads(log.read_text().strip())
    assert entry["op"] == "check"
    assert entry["validation"] == "PASSED"


def test_check_scope_alignment_invokes_alignment_lint(tmp_package):
    lint = tmp_package / "research_html" / "scripts" / "learnings_lint.py"
    lint.write_text(
        "#!/usr/bin/env python3\n"
        "import json, pathlib, sys\n"
        "pathlib.Path('lint_args.json').write_text(json.dumps(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    r = _run(["--pkg", "test-pkg", "--op", "check", "--scope", "alignment"], cwd=tmp_package)
    assert r.returncode == 0, r.stderr + r.stdout
    assert json.loads((tmp_package / "lint_args.json").read_text()) == ["alignment", "--pkg", "test-pkg"]


def test_state_gate_rejects_illegal_insert(tmp_package):
    r = _run(["--pkg", "test-pkg", "--op", "insert", "--target", "methodsTried",
              "--payload", "{}"], cwd=tmp_package)
    assert r.returncode == 2
    envelope = json.loads(r.stdout)
    assert envelope["rejected"] is True
    assert envelope["phase"] == "state-gate"
    assert envelope["rule"] == "illegal-transition"


def test_insert_experiments_row_fans_out_task_blocks(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "research_html"
    (root / "data").mkdir(parents=True)
    (root / "data" / "research-packages.js").write_text("window.RESEARCH_PACKAGES = [];\n", encoding="utf-8")

    create = subprocess.run([
        sys.executable, str(CREATE),
        "--root", str(root),
        "--id", "2026-06-10-op-growth",
        "--name", "Op Growth",
        "--category", "in-progress",
        "--tag", "growth",
        "--tag-meaning", "research-op growth path",
        "--problem", "late task inserts drift",
        "--objective", "fan out task blocks",
        "--motivation", "alignment on growth",
        "--hypothesis", "research-op can derive blocks",
        "--primary-metric", "alignment violations",
        "--baseline", "manual insert",
        "--budget", "unmeasured",
        "--no-change-boundary", "no unrelated surfaces",
        "--next-action", "insert P1",
        "--scope", "all",
        "--status", "CONTEXT_LOADED",
    ], cwd=tmp_path, capture_output=True, text=True)
    assert create.returncode == 0, create.stderr + create.stdout

    payload = {
        "id": "P1",
        "purpose": "Train reranker",
        "after": [],
        "output": "outputs/P1/result.json",
        "gate": "Recall@1 >= 48",
        "status": "queued",
        "measures": True,
        "requiresCode": True,
        "complex": True,
        "docsAnchor": "docs/pipeline.html#p1",
    }
    r = _run([
        "--pkg", "2026-06-10-op-growth",
        "--op", "insert",
        "--target", "experiments-row",
        "--payload", json.dumps(payload),
    ], cwd=tmp_path)
    assert r.returncode == 0, r.stderr + r.stdout
    pkg = root / "packages" / "2026-06-10-op-growth"
    assert 'data-table="result-slot-P1"' in (pkg / "results.html").read_text(encoding="utf-8")
    assert 'data-field="validating-exp">P1<' in (pkg / "implementation.html").read_text(encoding="utf-8")
    assert '<h3 id="p1" data-exp-id="P1">P1</h3>' in (pkg / "docs" / "pipeline.html").read_text(encoding="utf-8")
    assert 'data-exp-id="P1"' in (pkg / "tracker.html").read_text(encoding="utf-8")
    log_entries = [
        json.loads(line)
        for line in (tmp_path / "outputs" / "2026-06-10-op-growth" / "_actions.jsonl").read_text().splitlines()
    ]
    assert log_entries[-1]["target"] == "experiments-row"
    assert len(log_entries[-1]["files_touched"]) >= 4

    impl = pkg / "implementation.html"
    impl.write_text(
        impl.read_text(encoding="utf-8").replace(
            '<div data-field="expected-sign">unmeasured</div>',
            '<div data-field="expected-sign">positive</div>',
            1,
        ),
        encoding="utf-8",
    )
    rejected = _run([
        "--pkg", "2026-06-10-op-growth",
        "--op", "delete",
        "--target", "experiments-row",
        "--payload", json.dumps({"id": "P1", "existing_experiments_status_list": []}),
    ], cwd=tmp_path)
    assert rejected.returncode == 2
    envelope = json.loads(rejected.stdout)
    assert envelope["rule"] == "experiments-delete-bound-content"


def test_update_experiments_row_fans_out_task_blocks(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "research_html"
    (root / "data").mkdir(parents=True)
    (root / "data" / "research-packages.js").write_text("window.RESEARCH_PACKAGES = [];\n", encoding="utf-8")

    base_row = {
        "id": "P1",
        "purpose": "Train reranker",
        "after": [],
        "output": "outputs/P1/result.json",
        "gate": "Recall@1 >= 48",
        "status": "queued",
        "measures": True,
        "requiresCode": False,
        "complex": False,
    }
    create = subprocess.run([
        sys.executable, str(CREATE),
        "--root", str(root),
        "--id", "2026-06-10-op-retype",
        "--name", "Op Retype",
        "--category", "in-progress",
        "--tag", "retype",
        "--tag-meaning", "research-op retype path",
        "--problem", "retyped tasks drift",
        "--objective", "fan out on update",
        "--motivation", "alignment on retype",
        "--hypothesis", "update derives blocks",
        "--primary-metric", "alignment violations",
        "--baseline", "insert only",
        "--budget", "unmeasured",
        "--no-change-boundary", "no unrelated surfaces",
        "--next-action", "retype P1",
        "--scope", "all",
        "--status", "CONTEXT_LOADED",
        "--experiments", json.dumps([base_row]),
    ], cwd=tmp_path, capture_output=True, text=True)
    assert create.returncode == 0, create.stderr + create.stdout

    pkg = root / "packages" / "2026-06-10-op-retype"
    assert not (pkg / "docs" / "pipeline.html").exists()
    assert 'data-field="validating-exp">P1<' not in (pkg / "implementation.html").read_text(encoding="utf-8")

    retyped = dict(base_row, requiresCode=True, complex=True, docsAnchor="docs/pipeline.html#p1")
    r = _run([
        "--pkg", "2026-06-10-op-retype",
        "--op", "update",
        "--target", "experiments-row",
        "--payload", json.dumps({"id": "P1", "row": retyped}),
    ], cwd=tmp_path)
    assert r.returncode == 0, r.stderr + r.stdout
    assert 'data-field="validating-exp">P1<' in (pkg / "implementation.html").read_text(encoding="utf-8")
    assert '<h3 id="p1" data-exp-id="P1">P1</h3>' in (pkg / "docs" / "pipeline.html").read_text(encoding="utf-8")
    log_entries = [
        json.loads(line)
        for line in (tmp_path / "outputs" / "2026-06-10-op-retype" / "_actions.jsonl").read_text().splitlines()
    ]
    assert log_entries[-1]["target"] == "experiments-row"
    assert len(log_entries[-1]["files_touched"]) >= 3


def test_update_package_fields_from_cli(tmp_package):
    inv = tmp_package / "research_html" / "data" / "research-packages.js"
    inv.write_text(
        "const RESEARCH_PACKAGES = [\n"
        "  { id: 'test-pkg', category: 'in-progress', status: 'CONTEXT_LOADED',\n"
        "    objectiveContract: { baseline: 'old' },\n"
        "    experiments: [{\"id\":\"P0\",\"purpose\":\"old\",\"status\":\"QUEUED\"}],\n"
        "  },\n"
        "];\n"
    )
    results = tmp_package / "research_html" / "packages" / "test-pkg" / "results.html"
    results.write_text(
        '<table><tbody data-table-body="result-gate">'
        '<tr data-exp-id="P0"><td data-field="exp-id">P0</td>'
        '<td data-validity="missing">missing</td>'
        '<td data-field="baseline">old baseline</td>'
        '<td data-field="plan-gate">old gate</td></tr>'
        '</tbody></table><time data-field="last-updated">2026-06-01</time>'
    )

    r = _run([
        "--pkg", "test-pkg", "--op", "update", "--target", "objectiveContract",
        "--payload", json.dumps({"field": "baseline", "to": "new baseline"}),
    ], cwd=tmp_package)
    assert r.returncode == 0, r.stderr + r.stdout

    r = _run([
        "--pkg", "test-pkg", "--op", "update", "--target", "experiments-row",
        "--payload", json.dumps({"id": "P0", "row": {"id": "P0", "purpose": "new", "status": "QUEUED"}}),
    ], cwd=tmp_package)
    assert r.returncode == 0, r.stderr + r.stdout

    r = _run([
        "--pkg", "test-pkg", "--op", "update", "--target", "results-gate-row",
        "--payload", json.dumps({"exp_id": "P0", "cells": {"baseline": "new baseline", "plan-gate": "new gate"}}),
    ], cwd=tmp_package)
    assert r.returncode == 0, r.stderr + r.stdout

    assert "new baseline" in inv.read_text()
    assert '"purpose": "new"' in inv.read_text()
    assert "new gate" in results.read_text()
    log_entries = [
        json.loads(line)
        for line in (tmp_package / "outputs" / "test-pkg" / "_actions.jsonl").read_text().splitlines()
    ]
    assert [e["target"] for e in log_entries] == ["objectiveContract", "experiments-row", "results-gate-row"]


def test_update_last_updated_time_repairs_broken_footer(tmp_package):
    results = tmp_package / "research_html" / "packages" / "test-pkg" / "results.html"
    results.write_text('<footer class="footer-note">P26-06-10</time></footer>')

    r = _run([
        "--pkg", "test-pkg", "--op", "update", "--target", "last-updated-time",
        "--payload", json.dumps({"page": "results.html"}),
    ], cwd=tmp_package)
    assert r.returncode == 0, r.stderr + r.stdout

    text = results.read_text()
    assert '<time data-field="last-updated"' in text
    assert "P26-06-10" not in text
