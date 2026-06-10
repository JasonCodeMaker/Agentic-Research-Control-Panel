"""TDD for scope-inspector.js pure logic (executed under node).

The Scope Inspector folds the canonical Scope SSOT logs in the browser. These
tests exercise the dependency-free fold/tree/triage/parse functions by requiring
the module under node, so the live-view behavior is verified, not just grepped.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE = (ROOT / "skills" / "research-dashboard" / "assets" / "dashboard" /
          "assets" / "scope-inspector.js")

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def _run(expr_body: str):
    """Require the module under node, run a JS body that returns a value, parse the JSON."""
    driver = (
        "const SI = require(%s);\n" % json.dumps(str(MODULE)) +
        "const out = (function(){ %s })();\n" % expr_body +
        "process.stdout.write(JSON.stringify(out));\n"
    )
    proc = subprocess.run(["node", "-e", driver], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_module_exists():
    assert MODULE.exists(), f"missing {MODULE}"


def test_syntax_node_check():
    proc = subprocess.run(["node", "--check", str(MODULE)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_fold_latest_version_wins():
    recs = [
        {"node_id": "dir/x", "node": {"id": "dir/x", "version": 1, "status": "ACTIVE", "parents": []}},
        {"node_id": "dir/x", "node": {"id": "dir/x", "version": 2, "status": "ACTIVE", "parents": []}},
    ]
    proj = _run("return SI.foldTransitions(%s);" % json.dumps(recs))
    assert set(proj) == {"dir/x"}
    assert proj["dir/x"]["version"] == 2


def test_active_tree_built_from_parents_not_level_names():
    recs = [
        {"node_id": "project/main", "node": {"id": "project/main", "level": "project", "status": "ACTIVE", "parents": []}},
        {"node_id": "dir/a", "node": {"id": "dir/a", "level": "direction", "status": "ACTIVE", "parents": ["project/main"]}},
        {"node_id": "dir/b", "node": {"id": "dir/b", "level": "direction", "status": "ACTIVE", "parents": ["project/main"]}},
        {"node_id": "dir/old", "node": {"id": "dir/old", "level": "direction", "status": "ARCHIVED", "parents": ["project/main"]}},
        {"node_id": "task/t1", "node": {"id": "task/t1", "level": "task", "status": "ACTIVE", "parents": ["dir/a"]}},
        {"node_id": "task/multi", "node": {"id": "task/multi", "level": "task", "status": "ACTIVE", "parents": ["dir/a", "dir/b"]}},
    ]
    tree = _run("return SI.activeTree(SI.foldTransitions(%s));" % json.dumps(recs))
    # archived node excluded from the active forest
    assert "dir/old" not in tree["active"]
    # root derived from the graph (no active parent), not from a hardcoded "project" level
    assert tree["roots"] == ["project/main"]
    assert tree["childrenOf"]["project/main"] == ["dir/a", "dir/b"]
    # a multi-homed task appears under each active parent
    assert "task/multi" in tree["childrenOf"]["dir/a"]
    assert "task/multi" in tree["childrenOf"]["dir/b"]
    assert tree["childrenOf"]["dir/a"] == ["task/multi", "task/t1"]  # sorted, stable


def test_history_groups_by_node_in_file_order():
    recs = [
        {"node_id": "dir/a", "op": "create", "transaction_id": "t0", "node": {"id": "dir/a", "version": 1}},
        {"node_id": "dir/b", "op": "create", "transaction_id": "t1", "node": {"id": "dir/b", "version": 1}},
        {"node_id": "dir/a", "op": "revise", "transaction_id": "t2", "node": {"id": "dir/a", "version": 2}},
    ]
    groups = _run("return SI.historyByNode(%s);" % json.dumps(recs))
    assert [r["op"] for r in groups["dir/a"]] == ["create", "revise"]
    assert [r["transaction_id"] for r in groups["dir/a"]] == ["t0", "t2"]
    assert [r["op"] for r in groups["dir/b"]] == ["create"]


def test_triage_fold_separates_pending_from_disposed():
    recs = [
        {"id": "p1", "change": "revise D1", "status": "pending"},
        {"id": "p2", "change": "add task", "status": "pending"},
        {"id": "p2", "status": "accepted"},   # disposed: latest status wins
    ]
    res = _run("return SI.foldTriage(%s);" % json.dumps(recs))
    assert sorted(i["id"] for i in res["pending"]) == ["p1"]
    assert sorted(i["id"] for i in res["disposed"]) == ["p2"]
    # pending item keeps its full proposal fields
    assert res["pending"][0]["change"] == "revise D1"


def test_parse_jsonl_reports_error_line_numbers():
    text = '{"a": 1}\n\nnot json\n{"b": 2}'
    res = _run("return SI.parseJsonl(%s);" % json.dumps(text))
    assert len(res["records"]) == 2
    assert len(res["errors"]) == 1
    assert res["errors"][0]["line"] == 3  # 1-based; blank line 2 skipped


def test_active_predicate_only_status_active():
    recs = [
        {"node_id": "n/keep", "node": {"id": "n/keep", "status": "ACTIVE", "parents": []}},
        {"node_id": "n/gone", "node": {"id": "n/gone", "status": "SUPERSEDED", "parents": []}},
    ]
    tree = _run("return SI.activeTree(SI.foldTransitions(%s));" % json.dumps(recs))
    assert set(tree["active"]) == {"n/keep"}
