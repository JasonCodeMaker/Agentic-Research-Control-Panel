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

SCOPE_SCHEMA = {
    "levels": {
        "project": {
            "order": ["goal", "contributions", "out_of_scope"],
            "primary": ["goal"],
            "fields": {
                "goal": {"kind": "text", "label": "Goal", "minWords": 20, "maxWords": 100},
                "contributions": {"kind": "list", "label": "Contributions", "minWords": 5, "maxWords": 50},
                "out_of_scope": {"kind": "list", "label": "Out of scope", "minWords": 5, "maxWords": 50},
            },
        },
        "direction": {
            "order": ["hypothesis", "metric", "baselines", "success_gate"],
            "primary": ["hypothesis", "metric"],
            "fields": {
                "hypothesis": {"kind": "text", "label": "Hypothesis", "minWords": 20, "maxWords": 100},
                "metric": {"kind": "metric", "label": "Metric", "minWords": 20, "maxWords": 100},
                "baselines": {"kind": "list", "label": "Baselines", "minWords": 5, "maxWords": 50},
                "success_gate": {"kind": "text", "label": "Success gate", "minWords": 20, "maxWords": 100},
            },
        },
        "task": {
            "order": ["experiment", "config", "gate", "control_mode"],
            "primary": ["experiment", "control_mode"],
            "fields": {
                "experiment": {"kind": "text", "label": "Experiment", "minWords": 20, "maxWords": 100},
                "config": {"kind": "ref", "label": "Config"},
                "gate": {"kind": "text", "label": "Gate", "minWords": 20, "maxWords": 100},
                "control_mode": {"kind": "enum", "label": "Control mode",
                                 "values": ["SUPERVISED", "CHECKPOINTED", "DEFERRED", "AUTONOMOUS"]},
            },
        },
    },
    "oldNodeFields": ["yardstick", "provenance"],
    "readingFields": ["measured", "result", "verdict", "metric_value", "current_best"],
}

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


def test_triage_fold_preserves_proposal_fields_after_disposition():
    recs = [
        {"id": "p2", "change": "add task", "status": "pending", "proposed_node": {"id": "task/t1"}},
        {"id": "p2", "status": "accepted"},
    ]
    res = _run("return SI.foldTriage(%s);" % json.dumps(recs))
    assert res["accepted"][0]["change"] == "add task"
    assert res["accepted"][0]["proposed_node"]["id"] == "task/t1"
    assert res["accepted"][0]["status"] == "accepted"


def test_build_keeps_transition_and_triage_parse_errors_separate():
    transition_text = '{"node_id":"project/main","node":{"id":"project/main","level":"project","status":"ACTIVE","parents":[],"spec":{}}}'
    triage_text = '{"id":"p1","status":"pending"}\nnot json'
    expr = (
        "return SI.buildSnapshot({status:'ok', text:%s}, {status:'ok', text:%s}, %s);"
        % (json.dumps(transition_text), json.dumps(triage_text), json.dumps(SCOPE_SCHEMA))
    )
    res = _run(expr)
    assert res["errors"] == []
    assert len(res["triageErrors"]) == 1
    assert res["triageStatus"] == "ok"


def test_schema_health_reports_old_keys_missing_fields_and_word_counts():
    projection = {
        "project/main": {
            "id": "project/main",
            "level": "project",
            "status": "ACTIVE",
            "parents": [],
            "yardstick": {},
            "spec": {
                "goal": "too short",
                "contributions": ["short"],
                "measured": 0.91,
            },
        }
    }
    res = _run("return SI.schemaHealth(%s, %s);" % (json.dumps(projection), json.dumps(SCOPE_SCHEMA)))
    messages = [i["message"] for i in res["issues"]]
    assert any("yardstick" in m for m in messages)
    assert any("out_of_scope" in m for m in messages)
    assert any("goal" in m and "20-100" in m for m in messages)
    assert any("contributions[0]" in m and "5-50" in m for m in messages)
    assert any("measured" in m for m in messages)


def test_current_understanding_counts_active_scope_and_package_links():
    projection = {
        "project/main": {"id": "project/main", "level": "project", "status": "ACTIVE",
                         "parents": [], "spec": {"goal": "Build a reliable research workflow."}},
        "dir/a": {"id": "dir/a", "level": "direction", "status": "ACTIVE",
                  "parents": ["project/main"], "spec": {"hypothesis": "Improve retrieval stability."}},
        "task/t1": {"id": "task/t1", "level": "task", "status": "ACTIVE",
                    "parents": ["dir/a"], "spec": {"experiment": "Run baseline reproduction."}},
        "task/old": {"id": "task/old", "level": "task", "status": "ARCHIVED",
                     "parents": ["dir/a"], "spec": {"experiment": "Old run."}},
    }
    triage = {"pending": [{"id": "p1"}], "accepted": [], "rejected": [], "disposed": []}
    packages = [
        {"id": "pkg-a", "sourceDirection": "dir/a", "experiments": [{"id": "P0", "sourceTask": "task/t1"}]},
        {"id": "pkg-b", "sourceTasks": [{"id": "task/t1"}]},
    ]
    res = _run(
        "return SI.currentUnderstanding(%s, %s, %s, %s);"
        % (json.dumps(projection), json.dumps(triage), json.dumps(packages), json.dumps(SCOPE_SCHEMA))
    )
    assert res["activeTotal"] == 3
    assert res["activeByLevel"]["direction"] == 1
    assert res["pendingProposals"] == 1
    assert res["linkedPackages"] == 2
    assert res["rootSummaries"][0]["id"] == "project/main"


def test_package_readiness_guides_scope_first_package_creation():
    projection = {
        "project/main": {"id": "project/main", "level": "project", "status": "ACTIVE",
                         "parents": [], "spec": {}},
        "dir/a": {"id": "dir/a", "level": "direction", "status": "ACTIVE",
                  "parents": ["project/main"], "spec": {}},
        "dir/b": {"id": "dir/b", "level": "direction", "status": "ACTIVE",
                  "parents": ["project/main"], "spec": {}},
        "dir/c": {"id": "dir/c", "level": "direction", "status": "ACTIVE",
                  "parents": ["project/main"], "spec": {}},
        "task/a/m0": {"id": "task/a/m0", "level": "task", "status": "ACTIVE",
                      "parents": ["dir/a"], "spec": {}},
        "task/c/m0": {"id": "task/c/m0", "level": "task", "status": "ACTIVE",
                      "parents": ["dir/c"], "spec": {}},
    }
    triage = {"pending": [
        {"id": "task-b", "proposed_node": {"id": "task/b/m0", "parents": ["dir/b"]}},
    ]}
    packages = [{"id": "pkg-c", "sourceDirection": "dir/c"}]

    res = _run(
        "return SI.packageReadiness(%s, %s, %s);"
        % (json.dumps(projection), json.dumps(triage), json.dumps(packages))
    )

    by_id = {item["directionId"]: item for item in res["items"]}
    assert by_id["dir/a"]["state"] == "ready_to_materialize"
    assert by_id["dir/a"]["nextAction"] == "/research-package from-scope dir/a"
    assert by_id["dir/a"]["taskCount"] == 1
    assert by_id["dir/b"]["state"] == "pending_tasks"
    assert by_id["dir/b"]["pendingTaskCount"] == 1
    assert by_id["dir/b"]["nextSkill"] == "/research-scope"
    assert by_id["dir/c"]["state"] == "materialized"
    assert by_id["dir/c"]["packageId"] == "pkg-c"
    assert by_id["dir/c"]["nextAction"] == "/research-run pkg-c"


def test_package_readiness_reports_missing_and_pending_direction():
    projection = {
        "project/main": {"id": "project/main", "level": "project", "status": "ACTIVE",
                         "parents": [], "spec": {}},
    }
    triage = {"pending": [
        {"id": "dir-pending", "proposed_node": {"id": "dir/new", "parents": ["project/main"]}},
    ]}

    res = _run(
        "return SI.packageReadiness(%s, %s, []);"
        % (json.dumps(projection), json.dumps(triage))
    )

    assert res["state"] == "pending_direction"
    assert res["nextSkill"] == "/research-scope"
    assert "Accept, revise, or reject" in res["nextAction"]


def test_linked_packages_include_experiment_source_task():
    packages = [
        {"id": "pkg-a", "sourceDirection": "dir/a", "experiments": [{"id": "P0", "sourceTask": "task/t1"}]},
        {"id": "pkg-b", "sourceTasks": [{"id": "task/t1"}], "experiments": [{"id": "P1"}]},
    ]
    res = _run("return SI.linkedPackages(%s, %s);" % (json.dumps("task/t1"), json.dumps(packages)))
    assert [p["id"] for p in res] == ["pkg-a", "pkg-b"]
    assert res[0]["matchedExperiments"][0]["id"] == "P0"


def test_package_provenance_health_reports_missing_scope_links():
    projection = {"dir/a": {"id": "dir/a", "status": "ACTIVE"}}
    packages = [
        {
            "id": "pkg-a",
            "sourceDirection": "dir/missing",
            "sourceTasks": [{"id": "task/missing"}],
            "experiments": [{"id": "P0", "sourceTask": "task/missing"}],
        }
    ]
    res = _run("return SI.packageProvenanceHealth(%s, %s);" % (json.dumps(projection), json.dumps(packages)))
    messages = [i["message"] for i in res["issues"]]
    assert any("sourceDirection" in m and "dir/missing" in m for m in messages)
    assert any("sourceTasks" in m and "task/missing" in m for m in messages)
    assert any("experiments[].sourceTask" in m and "P0" in m for m in messages)


def test_history_timeline_includes_latest_first_diff():
    recs = [
        {"node_id": "dir/a", "transaction_id": "t1", "op": "create",
         "node": {"id": "dir/a", "spec": {"hypothesis": "old text"}}},
        {"node_id": "dir/a", "transaction_id": "t2", "op": "revise",
         "node": {"id": "dir/a", "spec": {"hypothesis": "new text", "success_gate": "pass"}}},
    ]
    res = _run("return SI.historyTimeline(%s);" % json.dumps(recs))
    assert [r["transaction_id"] for r in res] == ["t2", "t1"]
    assert any(d["field"] == "spec.hypothesis" for d in res[0]["diff"])
    assert any(d["field"] == "spec.success_gate" and d["type"] == "added" for d in res[0]["diff"])


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
