"""Phase 0 — the I/O loader + CLI: read real stores, write pack artifacts."""
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "skills" / "research-dashboard" / "scripts"))

import context_pack.build as build  # noqa: E402
import ensure_dashboard  # noqa: E402
import scope_ssot  # noqa: E402
from tests.scope_fixtures import direction_node  # noqa: E402
from tests.scope_fixtures import project_node, task_node  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node required to read JS data")


_PACKAGES_JS = '''window.RESEARCH_PACKAGES = [
  { id: "2026-06-03-retrieval-v2", name: "Retrieval V2", category: "in-progress",
    status: "CONTEXT_LOADED", sourceDirection: "dir/retrieval-v2",
    sourceVersion: "3", sourceChange: "txn-dir",
    sourceTasks: [{ id: "task/retrieval-v2/M0-baseline-validity", scopeVersion: 1, txn: "txn-task" }],
    experiments: [{ id: "P0", sourceTask: "task/retrieval-v2/M0-baseline-validity" }],
    activeGate: "R@1>=48", primaryMetricVsGate: "R@1 vs 48", nextRoute: "run P0",
    methodsTried: [] },
  { id: "2026-05-01-old", name: "Old", category: "fail", status: "ARCHIVED",
    terminationMessage: "did not clear",
    methodsTried: [
      { method: "hard-negative mining", hypothesis: "mining lifts R@1", gate: "R@1>=48",
        measured: "R@1=44", verdict: "FAIL",
        evidencePath: "packages/2026-05-01-old/results.html#m1" } ] },
  { id: "2026-04-01-win", name: "Win", category: "success", status: "ADOPTED",
    terminationMessage: "adopted", adoptionPath: "models/encoder.py#L40",
    methodsTried: [
      { method: "dual-encoder", hypothesis: "dual beats CLIP", gate: "R@1>=48",
        measured: "R@1=51", verdict: "PASS",
        evidencePath: "packages/2026-04-01-win/results.html#w1" } ] },
];
'''

def _append_registry_rows(root, rows):
    """Append rows to the scaffolded data/rules.js (keeps the universal mirror)."""
    rules_js = root / "data" / "rules.js"
    prefix = "window.RESEARCH_RULES = "
    existing = json.loads(rules_js.read_text(encoding="utf-8")[len(prefix):].rstrip().rstrip(";"))
    rules_js.write_text(prefix + json.dumps(existing + rows) + ";\n", encoding="utf-8")


def _setup(tmp_path):
    root = tmp_path / "research_html"
    ensure_dashboard.ensure_dashboard(root, force=False)
    (root / "data" / "research-packages.js").write_text(_PACKAGES_JS, encoding="utf-8")
    (root / "packages" / "2026-05-01-old").mkdir(parents=True, exist_ok=True)

    # direction node + scope log
    log = tmp_path / "outputs" / "_scope" / "transitions.jsonl"
    scope_ssot.propose_transition(project_node(), op="create", gate="USER_ONLY", log_path=log)
    node = direction_node(version=3)
    scope_ssot.propose_transition(node, op="create", gate="USER_CROSS_MODEL_AUDIT", log_path=log)
    scope_ssot.propose_transition(
        task_node("task/retrieval-v2/M0-baseline-validity", control_mode="SUPERVISED"),
        op="create", gate="AGENT_DEFERRED_ACK", log_path=log)

    # learned project rule + package lesson rows in the unified registry
    _append_registry_rows(root, [
        {"id": "PRJ-reproduce-baseline", "level": "project", "kind": "constraint",
         "title": "Reproduce the baseline", "text": "Always reproduce the baseline before claiming a lift.",
         "rationale": "validity", "source": "user", "origin": "user",
         "status": "ACTIVE", "addedAt": "2026-06-04"},
        {"id": "2026-05-01-old#mining-temperature", "level": "package", "pkg": "2026-05-01-old",
         "kind": "lesson", "title": "Mining needs temperature scaling",
         "text": "Hard-negative mining diverges without temperature scaling above 0.1.",
         "rationale": "insight-temp", "source": "analysis", "origin": "user",
         "status": "ACTIVE", "addedAt": "2026-06-04"},
    ])
    return root, log


def test_build_writes_full_pack_without_dashboard_context_core(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root, log = _setup(tmp_path)
    triage = tmp_path / "outputs" / "_scope" / "triage.jsonl"
    triage.write_text(
        json.dumps({
            "id": "triage-task-gate",
            "status": "pending",
            "level": "task",
            "node_id": "task/retrieval-v2/M0-baseline-validity",
            "change": "Revise the baseline gate before launch",
        }) + "\n",
        encoding="utf-8",
    )

    build.build("research_html", "2026-06-03-retrieval-v2",
                transitions_path=str(log), triage_path=str(triage),
                generated_at="2026-06-04T00:00:00Z")

    md = (tmp_path / "outputs" / "2026-06-03-retrieval-v2" / "context_pack.md").read_text(encoding="utf-8")
    pj = json.loads((tmp_path / "outputs" / "2026-06-03-retrieval-v2" / "context_pack.json").read_text(encoding="utf-8"))

    # full pack carries direction + project/package knowledge
    assert "Build an auditable research workflow" in md
    assert "Adding supervised contrastive pretraining" in md
    assert "task/retrieval-v2/M0-baseline-validity" in md
    assert "sourceDirection: dir/retrieval-v2" in md
    assert "triage-task-gate" in md
    assert "hard-negative mining" in md                                  # cross-package failure
    assert "temperature scaling" in md                                   # package lesson row from the registry
    assert "Always reproduce the baseline" in md                         # learned rule
    assert pj["stamp"]["scope_version"] == 3
    assert pj["stamp"]["global_scope_version"] == 3
    assert pj["stamp"]["sourceDirection"] == "dir/retrieval-v2"
    assert pj["stamp"]["pendingScope"] == ["triage-task-gate"]
    assert not (root / "data" / "context-core.js").exists()


def test_build_surfaces_knowledge_registries(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root, log = _setup(tmp_path)
    data = root / "data"
    (data / "papers.jsonl").write_text(
        json.dumps({"id": "dpr2020", "title": "Dense Passage Retrieval", "url": "http://x"}) + "\n",
        encoding="utf-8")
    (data / "edges.jsonl").write_text(
        json.dumps({"from": "paper:dpr2020", "to": "paper:ours", "type": "EXTENDS", "evidence": "sec3"}) + "\n",
        encoding="utf-8")
    (data / "gaps.jsonl").write_text(
        json.dumps({"id": "G1", "summary": "no zero-shot eval", "status": "open"}) + "\n",
        encoding="utf-8")

    build.build("research_html", "2026-06-03-retrieval-v2", transitions_path=str(log),
                generated_at="2026-06-04T00:00:00Z")

    md = (tmp_path / "outputs" / "2026-06-03-retrieval-v2" / "context_pack.md").read_text(encoding="utf-8")
    for needle in ("Dense Passage Retrieval", "EXTENDS", "no zero-shot eval"):
        assert needle in md


def test_build_includes_active_package_binding_rules_for_the_active_package(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root, log = _setup(tmp_path)
    _append_registry_rows(root, [
        {"id": "2026-06-03-retrieval-v2#keep-one-run-ledger", "level": "package",
         "pkg": "2026-06-03-retrieval-v2", "kind": "binding",
         "title": "Keep one run ledger",
         "text": "Keep all run status updates in the package tracker ledger.",
         "rationale": "avoid stale run context", "source": "user", "origin": "user",
         "status": "ACTIVE", "addedAt": "2026-06-05"},
        {"id": "2026-05-01-old#ignore-other-binding", "level": "package",
         "pkg": "2026-05-01-old", "kind": "binding",
         "title": "Other package binding",
         "text": "This binding belongs to another package.",
         "rationale": "scope", "source": "user", "origin": "user",
         "status": "ACTIVE", "addedAt": "2026-06-05"},
    ])

    build.build("research_html", "2026-06-03-retrieval-v2",
                transitions_path=str(log), generated_at="t0")

    md = (tmp_path / "outputs" / "2026-06-03-retrieval-v2" / "context_pack.md").read_text(encoding="utf-8")
    assert "Keep all run status updates in the package tracker ledger." in md
    assert "This binding belongs to another package." not in md


def test_build_fails_closed_on_malformed_rules_registry(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root, log = _setup(tmp_path)
    (root / "data" / "rules.js").write_text("window.BAD_RULES = [];\n", encoding="utf-8")

    with pytest.raises(ValueError, match="rules registry"):
        build.build("research_html", "2026-06-03-retrieval-v2", transitions_path=str(log))


def test_build_degrades_gracefully_without_optional_stores(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "research_html"
    ensure_dashboard.ensure_dashboard(root, force=False)
    (root / "data" / "research-packages.js").write_text(_PACKAGES_JS, encoding="utf-8")
    log = tmp_path / "outputs" / "_scope" / "transitions.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("", encoding="utf-8")  # no direction

    # no project/package rule rows or knowledge registries — must still build
    build.build("research_html", "2026-06-03-retrieval-v2",
                transitions_path=str(log), generated_at="2026-06-04T00:00:00Z")

    md = (tmp_path / "outputs" / "2026-06-03-retrieval-v2" / "context_pack.md").read_text(encoding="utf-8")
    assert "hard-negative mining" in md          # cross-package failure still compiled from packages
    assert not (root / "data" / "context-core.js").exists()


def test_cli_main(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root, log = _setup(tmp_path)
    rc = build.main(["--pkg", "2026-06-03-retrieval-v2", "--transitions", str(log)])
    assert rc == 0
    assert (tmp_path / "outputs" / "2026-06-03-retrieval-v2" / "context_pack.json").exists()


def test_ensure_fresh_rebuilds_only_when_scope_advanced(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root, log = _setup(tmp_path)
    build.build("research_html", "2026-06-03-retrieval-v2", transitions_path=str(log),
                generated_at="t0")

    # fresh (scope unchanged) → no rebuild, artifact untouched
    assert build.ensure_fresh("research_html", "2026-06-03-retrieval-v2", transitions_path=str(log),
                              generated_at="t1") is False
    pj = json.loads((tmp_path / "outputs" / "2026-06-03-retrieval-v2" / "context_pack.json").read_text())
    assert pj["stamp"]["generated_at"] == "t0"

    # advance the scope (a project revise leaves the direction version alone) → stale → rebuild
    project = scope_ssot.fold(scope_ssot.read_log(str(log)))["project/main"]
    project["version"] = 2
    scope_ssot.propose_transition(project, op="revise", gate="USER_ONLY", log_path=log)
    assert build.ensure_fresh("research_html", "2026-06-03-retrieval-v2", transitions_path=str(log),
                              generated_at="t-project") is True
    pj_project = json.loads((tmp_path / "outputs" / "2026-06-03-retrieval-v2" / "context_pack.json").read_text())
    assert pj_project["stamp"]["scope_version"] == 3
    assert pj_project["stamp"]["global_scope_version"] == 4
    assert pj_project["stamp"]["generated_at"] == "t-project"

    # advance the scope again with a metric revise → stale → rebuild
    node = scope_ssot.fold(scope_ssot.read_log(str(log)))["dir/retrieval-v2"]
    node["version"] = 4
    scope_ssot.propose_transition(node, op="revise", gate="USER_CROSS_MODEL_AUDIT", log_path=log)
    assert build.ensure_fresh("research_html", "2026-06-03-retrieval-v2", transitions_path=str(log),
                              generated_at="t2") is True
    pj2 = json.loads((tmp_path / "outputs" / "2026-06-03-retrieval-v2" / "context_pack.json").read_text())
    assert pj2["stamp"]["scope_version"] == 4
    assert pj2["stamp"]["global_scope_version"] == 5
    assert pj2["stamp"]["generated_at"] == "t2"


def test_ensure_fresh_rebuilds_when_triage_changes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root, log = _setup(tmp_path)
    triage = tmp_path / "outputs" / "_scope" / "triage.jsonl"
    triage.write_text("", encoding="utf-8")
    build.build("research_html", "2026-06-03-retrieval-v2", transitions_path=str(log),
                triage_path=str(triage), generated_at="t0")

    triage.write_text(
        json.dumps({
            "id": "triage-task-gate",
            "status": "pending",
            "level": "task",
            "node_id": "task/retrieval-v2/M0-baseline-validity",
            "change": "Revise the baseline gate before launch",
        }) + "\n",
        encoding="utf-8",
    )
    assert build.ensure_fresh("research_html", "2026-06-03-retrieval-v2",
                              transitions_path=str(log), triage_path=str(triage),
                              generated_at="t-triage") is True
    pj = json.loads((tmp_path / "outputs" / "2026-06-03-retrieval-v2" / "context_pack.json").read_text())
    assert pj["stamp"]["triage_version"] == 1
    assert pj["stamp"]["pendingScope"] == ["triage-task-gate"]
    assert pj["stamp"]["generated_at"] == "t-triage"


def test_ensure_fresh_rebuilds_when_learning_sources_change(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root, log = _setup(tmp_path)
    build.build("research_html", "2026-06-03-retrieval-v2", transitions_path=str(log),
                generated_at="t0")

    _append_registry_rows(root, [
        {"id": "PRJ-new-learning", "level": "project", "kind": "constraint",
         "title": "New learning", "text": "Check the new learning source before proposing work.",
         "rationale": "freshness", "source": "user", "origin": "user",
         "status": "ACTIVE", "addedAt": "2026-06-05"},
    ])

    assert build.ensure_fresh("research_html", "2026-06-03-retrieval-v2",
                              transitions_path=str(log), generated_at="t-learning") is True
    pj = json.loads((tmp_path / "outputs" / "2026-06-03-retrieval-v2" / "context_pack.json").read_text())
    assert pj["stamp"]["generated_at"] == "t-learning"
    assert pj["stamp"]["learning_fingerprint"]


def test_cli_if_stale_builds_then_skips(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    root, log = _setup(tmp_path)
    assert build.main(["--pkg", "2026-06-03-retrieval-v2", "--transitions", str(log),
                       "--if-stale"]) == 0
    assert "rebuilt" in capsys.readouterr().out
    # second call: already fresh, no rebuild
    assert build.main(["--pkg", "2026-06-03-retrieval-v2", "--transitions", str(log),
                       "--if-stale"]) == 0
    assert "already fresh" in capsys.readouterr().out


def test_ensure_fresh_builds_when_pack_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root, log = _setup(tmp_path)
    assert build.ensure_fresh("research_html", "2026-06-03-retrieval-v2", transitions_path=str(log),
                              generated_at="t0") is True
    assert (tmp_path / "outputs" / "2026-06-03-retrieval-v2" / "context_pack.json").exists()


def test_build_py_runs_as_script(tmp_path, monkeypatch):
    """The SKILL prose invokes `python lib/context_pack/build.py` — it must self-bootstrap sys.path."""
    import subprocess as sp
    monkeypatch.chdir(tmp_path)
    root, log = _setup(tmp_path)
    rc = sp.run([sys.executable, str(ROOT / "lib" / "context_pack" / "build.py"),
                 "--pkg", "2026-06-03-retrieval-v2", "--transitions", str(log)],
                capture_output=True, text=True)
    assert rc.returncode == 0, rc.stderr
    assert (tmp_path / "outputs" / "2026-06-03-retrieval-v2" / "context_pack.md").exists()
