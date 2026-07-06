import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "skills" / "research-package" / "scripts"))

import create_from_scope  # noqa: E402
import scope_ssot  # noqa: E402
from tests.scope_fixtures import direction_node, project_node, task_spec  # noqa: E402


def _dashboard(tmp_path):
    root = tmp_path / "research_html"
    (root / "data").mkdir(parents=True)
    (root / "data" / "research-packages.js").write_text(
        "window.RESEARCH_PACKAGES = [];\n", encoding="utf-8")
    return root


def _direction_node(status="ACTIVE"):
    return direction_node(version=3, status=status, source="triage:t1")


def _project_node():
    return project_node()


def _write_direction_log(tmp_path, node=None):
    log = tmp_path / "outputs" / "_scope" / "transitions.jsonl"
    rec = scope_ssot.propose_transition(
        node or _direction_node(),
        op="create",
        gate="USER_CROSS_MODEL_AUDIT",
        log_path=log,
        trigger="accepted triage",
        cause="PM accepted direction",
    )
    return log, rec


def _milestone_node(parent, suffix, gate="Gate is explicit"):
    spec = task_spec(
        experiment=(
            f"Validate milestone {suffix} by running the agreed package phase, preserving "
            "review artifacts, and comparing only against committed Scope gates carefully."
        ),
        config=f"scope:{parent}#{suffix.lower()}",
        gate=gate,
    )
    return {
        "id": f"task/retrieval-v2/{suffix}",
        "level": "task",
        "parents": [parent],
        "version": 1,
        "status": "ACTIVE",
        "spec": spec,
        "source": f"test:{suffix}",
    }


def _write_milestones(log):
    recs = []
    for suffix, gate in [
        (
            "M0-baseline-validity",
            "The baseline must reproduce within the accepted tolerance window before any new retrieval variant is compared against it during package review.",
        ),
        (
            "M1-main-hypothesis",
            "The primary retrieval metric must improve by at least two absolute points over the declared baseline on the held out split.",
        ),
    ]:
        recs.append(scope_ssot.propose_transition(
            _milestone_node("dir/retrieval-v2", suffix, gate=gate),
            op="create",
            gate="AGENT_DEFERRED_ACK",
            log_path=log,
            trigger="accepted milestone",
            cause="PM accepted validation milestone",
        ))
    return recs


def test_materializes_committed_direction_as_package(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _dashboard(tmp_path)
    log, rec = _write_direction_log(tmp_path)
    milestone_recs = _write_milestones(log)

    rc = create_from_scope.main([
        "--direction-id", "dir/retrieval-v2",
        "--id", "2026-06-03-retrieval-v2",
        "--transitions", str(log),
    ])

    assert rc == 0
    assert (tmp_path / "research_html" / "packages" / "2026-06-03-retrieval-v2" / "index.html").exists()
    inventory = (tmp_path / "research_html" / "data" / "research-packages.js").read_text(encoding="utf-8")
    assert 'id: "2026-06-03-retrieval-v2"' in inventory
    assert 'sourceDirection: "dir/retrieval-v2"' in inventory
    assert f'sourceChange: "{rec["transaction_id"]}"' in inventory
    assert "sourceTasks" in inventory
    assert f'"txn": "{milestone_recs[0]["transaction_id"]}"' in inventory
    assert "experiments" in inventory
    assert '"sourceTask": "task/retrieval-v2/M0-baseline-validity"' in inventory
    assert '"purpose": "Verify baseline"' in inventory
    assert "Adding supervised contrastive pretraining" in inventory
    assert "primaryMetricVsGate" in inventory
    assert "two absolute points" in inventory


def test_conversion_consumes_brainstorms_and_writes_provenance(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = _dashboard(tmp_path)
    (root / "data" / "brainstorms.js").write_text(
        'window.BRAINSTORMS = [{"id":"bs-1","title":"Idea one","idea":"first"},'
        '{"id":"bs-2","title":"Idea two","idea":"second"},'
        '{"id":"bs-3","title":"Keep me","idea":"third"}];\n', encoding="utf-8")
    log, _ = _write_direction_log(tmp_path)
    _write_milestones(log)

    rc = create_from_scope.main([
        "--direction-id", "dir/retrieval-v2",
        "--id", "2026-06-03-retrieval-v2",
        "--transitions", str(log),
        "--source-brainstorms", '["bs-1","bs-2"]',
    ])

    assert rc == 0
    prov = (root / "packages" / "2026-06-03-retrieval-v2" / "brainstorm.html").read_text(encoding="utf-8")
    assert "Idea one" in prov and "Idea two" in prov
    # consumed ideas are gone from the lane store; the unrelated one remains
    remaining = (root / "data" / "brainstorms.js").read_text(encoding="utf-8")
    assert "bs-1" not in remaining and "bs-2" not in remaining
    assert "bs-3" in remaining


def test_pending_triage_without_committed_transition_cannot_materialize(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _dashboard(tmp_path)
    triage = tmp_path / "outputs" / "_scope" / "triage.jsonl"
    triage.parent.mkdir(parents=True)
    triage.write_text('{"id":"t1","level":"direction","status":"pending"}\n', encoding="utf-8")

    with pytest.raises(SystemExit, match="Committed direction not found"):
        create_from_scope.main([
            "--direction-id", "dir/retrieval-v2",
            "--id", "2026-06-03-retrieval-v2",
        ])

    assert not (tmp_path / "research_html" / "packages" / "2026-06-03-retrieval-v2").exists()


def test_committed_direction_without_milestones_cannot_materialize(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _dashboard(tmp_path)
    log, _ = _write_direction_log(tmp_path)

    with pytest.raises(SystemExit, match="No accepted high-level validation milestones"):
        create_from_scope.main([
            "--direction-id", "dir/retrieval-v2",
            "--id", "2026-06-03-retrieval-v2",
            "--transitions", str(log),
        ])

    assert not (tmp_path / "research_html" / "packages" / "2026-06-03-retrieval-v2").exists()


def test_non_direction_node_rejected(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _dashboard(tmp_path)
    log = tmp_path / "outputs" / "_scope" / "transitions.jsonl"
    scope_ssot.propose_transition(_project_node(), op="create", gate="USER_ONLY", log_path=log)

    with pytest.raises(SystemExit, match="level='project'"):
        create_from_scope.main([
            "--direction-id", "project/main",
            "--id", "2026-06-03-main",
            "--transitions", str(log),
        ])


def test_experiment_rows_set_readiness_flags():
    def ms(suffix):
        return {"node": {"id": f"task/d/{suffix}", "spec": {"gate": "g"}}}
    rows = create_from_scope._experiment_rows(
        "pkg", [ms("M0-baseline-validity"), ms("M1-main-hypothesis")])
    # baseline validity runs an existing baseline: no code, not complex
    assert rows[0]["requiresCode"] is False
    assert rows[0]["complex"] is False
    # the main hypothesis typically needs a code change and a pipeline doc
    assert rows[1]["requiresCode"] is True
    assert rows[1]["complex"] is True
    # a complex phase points at a real (not-yet-written) pipeline doc so the
    # readiness gate bites until it is authored; a simple phase links the docs index
    assert rows[0]["docsAnchor"] == "docs/index.html"
    assert rows[1]["docsAnchor"] == "docs/pipeline.html#p1"


def test_default_scope_includes_implementation_and_results(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _dashboard(tmp_path)
    log, _ = _write_direction_log(tmp_path)
    _write_milestones(log)

    rc = create_from_scope.main([
        "--direction-id", "dir/retrieval-v2",
        "--id", "2026-06-03-retrieval-v2",
        "--transitions", str(log),
    ])

    assert rc == 0
    pkgdir = tmp_path / "research_html" / "packages" / "2026-06-03-retrieval-v2"
    assert (pkgdir / "implementation.html").exists()  # C2 home
    assert (pkgdir / "results.html").exists()          # C4 home


def test_duplicate_package_rejected_before_write(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _dashboard(tmp_path)
    log, _ = _write_direction_log(tmp_path)
    _write_milestones(log)
    package_dir = tmp_path / "research_html" / "packages" / "2026-06-03-retrieval-v2"
    package_dir.mkdir(parents=True)

    with pytest.raises(SystemExit, match="Package already exists"):
        create_from_scope.main([
            "--direction-id", "dir/retrieval-v2",
            "--id", "2026-06-03-retrieval-v2",
            "--transitions", str(log),
        ])
