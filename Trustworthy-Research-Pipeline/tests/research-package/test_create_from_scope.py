import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "skills" / "research-package" / "scripts"))

import create_from_scope  # noqa: E402
import scope_ssot  # noqa: E402


def _dashboard(tmp_path):
    root = tmp_path / "research_html"
    (root / "data").mkdir(parents=True)
    (root / "data" / "research-packages.js").write_text(
        "window.RESEARCH_PACKAGES = [];\n", encoding="utf-8")
    return root


def _direction_node(status="active"):
    return {
        "id": "dir/retrieval-v2",
        "level": "direction",
        "parents": ["project/main"],
        "version": 3,
        "status": status,
        "yardstick": {
            "hypothesis": "Contrastive retrieval improves zero-shot Recall@1",
            "metric": {"name": "Recall@1", "dir": "higher"},
            "baselines": ["CLIP zero-shot = 42.3"],
            "success_predicate": "Recall@1 >= 48",
        },
        "provenance": "triage:t1",
    }


def _project_node():
    return {
        "id": "project/main",
        "level": "project",
        "parents": [],
        "version": 1,
        "status": "active",
        "yardstick": {
            "north_star": "trustworthy auto research",
            "contribution_spine": "SSOT plus gates",
            "non_goals": "paper writing",
        },
        "provenance": "triage:p1",
    }


def _write_direction_log(tmp_path, node=None):
    log = tmp_path / "var" / "research" / "_scope" / "transitions.jsonl"
    rec = scope_ssot.propose_transition(
        node or _direction_node(),
        op="create",
        gate="user+xmodel-audit",
        log_path=log,
        trigger="accepted triage",
        cause="PM accepted direction",
    )
    return log, rec


def _milestone_node(parent, suffix, gate="Gate is explicit"):
    return {
        "id": f"task/retrieval-v2/{suffix}",
        "level": "task",
        "parents": [parent],
        "version": 1,
        "status": "active",
        "yardstick": {
            "experiment": f"Validate {suffix}",
            "config_ref": f"scope:{parent}#{suffix.lower()}",
            "gate_predicate": gate,
            "autonomy_level": "checkpoints",
        },
        "provenance": f"test:{suffix}",
    }


def _write_milestones(log):
    recs = []
    for suffix, gate in [
        ("M0-baseline-validity", "Baseline reproduced within tolerance"),
        ("M1-main-hypothesis", "Recall@1 >= 48"),
    ]:
        recs.append(scope_ssot.propose_transition(
            _milestone_node("dir/retrieval-v2", suffix, gate=gate),
            op="create",
            gate="agent+async-ack",
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
    assert 'sourceScopeNode: "dir/retrieval-v2"' in inventory
    assert f'sourceScopeTxn: "{rec["txn_id"]}"' in inventory
    assert "sourceScopeMilestones" in inventory
    assert f'"txn": "{milestone_recs[0]["txn_id"]}"' in inventory
    assert "experiments" in inventory
    assert '"parentTask": "task/retrieval-v2/M0-baseline-validity"' in inventory
    assert '"purpose": "Verify baseline"' in inventory
    assert "Contrastive retrieval improves zero-shot Recall@1" in inventory
    assert 'primaryMetricVsGate: "Recall@1 vs Recall@1 >= 48"' in inventory


def test_pending_triage_without_committed_transition_cannot_materialize(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _dashboard(tmp_path)
    triage = tmp_path / "var" / "research" / "_scope" / "triage.jsonl"
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
    log = tmp_path / "var" / "research" / "_scope" / "transitions.jsonl"
    scope_ssot.propose_transition(_project_node(), op="create", gate="user", log_path=log)

    with pytest.raises(SystemExit, match="level='project'"):
        create_from_scope.main([
            "--direction-id", "project/main",
            "--id", "2026-06-03-main",
            "--transitions", str(log),
        ])


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
