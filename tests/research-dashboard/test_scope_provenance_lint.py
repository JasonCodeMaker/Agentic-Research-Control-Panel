import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "skills" / "research-dashboard" / "assets" / "dashboard" / "scripts"))

import learnings_lint  # noqa: E402
import scope_ssot  # noqa: E402


def _direction_node():
    return {
        "id": "dir/retrieval-v2",
        "level": "direction",
        "parents": ["project/main"],
        "version": 1,
        "status": "ACTIVE",
        "spec": {
            "hypothesis": "better retrieval objective improves Recall@10",
            "metric": {"name": "Recall@10", "dir": "higher"},
            "baselines": ["xpool"],
            "success_gate": "Recall@10 >= baseline + 2",
        },
        "source": "test",
    }


def _task_node(suffix="M0-baseline-validity", version=1):
    return {
        "id": f"task/retrieval-v2/{suffix}",
        "level": "task",
        "parents": ["dir/retrieval-v2"],
        "version": version,
        "status": "ACTIVE",
        "spec": {
            "experiment": suffix,
            "config": f"configs/{suffix}.yaml",
            "gate": "Recall@10 >= baseline",
            "control_mode": "CHECKPOINTED",
        },
        "source": "test",
    }


def _scope_log(tmp_path, extra_task=False):
    log = tmp_path / "outputs" / "_scope" / "transitions.jsonl"
    direction = scope_ssot.propose_transition(
        _direction_node(), op="create", gate="USER_CROSS_MODEL_AUDIT", log_path=log)
    task = scope_ssot.propose_transition(
        _task_node(), op="create", gate="AGENT_DEFERRED_ACK", log_path=log)
    if extra_task:
        scope_ssot.propose_transition(
            _task_node("M1-main-hypothesis"), op="create", gate="AGENT_DEFERRED_ACK", log_path=log)
    return direction, task


def _data(pkg):
    return {
        "schema": {
            "in-progress": {
                "states": ["CONTEXT_LOADED"],
                "required": {"_all": []},
                "forbidden": [],
            }
        },
        "packages": [pkg],
        "contributionSpine": [],
    }


def _pkg(direction_rec, task_rec, parent_task=None):
    parent = parent_task or task_rec["node_id"]
    return {
        "id": "2026-06-03-retrieval-v2",
        "name": "Retrieval V2",
        "category": "in-progress",
        "status": "CONTEXT_LOADED",
        "pages": [],
        "sourceDirection": direction_rec["node_id"],
        "sourceVersion": direction_rec["scope_version"],
        "sourceChange": direction_rec["transaction_id"],
        "sourceTasks": [{
            "id": task_rec["node_id"],
            "scopeVersion": task_rec["scope_version"],
            "txn": task_rec["transaction_id"],
        }],
        "experiments": [{
            "id": "P0",
            "purpose": "Verify baseline",
            "after": [],
            "output": "outputs/2026-06-03-retrieval-v2/P0/result.json",
            "gate": "Recall@10 >= baseline",
            "status": "QUEUED",
            "sourceTask": parent,
        }],
    }


def test_lint_status_accepts_scope_materialized_package(tmp_path, monkeypatch):
    direction, task = _scope_log(tmp_path)
    monkeypatch.setattr(learnings_lint, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(learnings_lint, "SCOPE_LOG", tmp_path / "outputs" / "_scope" / "transitions.jsonl")
    monkeypatch.setattr(learnings_lint, "PACKAGES_DIR", tmp_path / "research_html" / "packages")

    rep = learnings_lint.lint_status(_data(_pkg(direction, task)))

    assert not rep.errors()


def test_lint_status_rejects_missing_active_scope_milestone(tmp_path, monkeypatch):
    direction, task = _scope_log(tmp_path, extra_task=True)
    monkeypatch.setattr(learnings_lint, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(learnings_lint, "SCOPE_LOG", tmp_path / "outputs" / "_scope" / "transitions.jsonl")
    monkeypatch.setattr(learnings_lint, "PACKAGES_DIR", tmp_path / "research_html" / "packages")

    rep = learnings_lint.lint_status(_data(_pkg(direction, task)))

    assert any(v.code == "scope-milestone-uncovered" for v in rep.errors())


def test_lint_status_rejects_stale_parent_task(tmp_path, monkeypatch):
    direction, task = _scope_log(tmp_path)
    monkeypatch.setattr(learnings_lint, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(learnings_lint, "SCOPE_LOG", tmp_path / "outputs" / "_scope" / "transitions.jsonl")
    monkeypatch.setattr(learnings_lint, "PACKAGES_DIR", tmp_path / "research_html" / "packages")

    rep = learnings_lint.lint_status(_data(_pkg(direction, task, parent_task="task/retrieval-v2/M9-stale")))

    assert any(v.code == "scope-parent-task-stale" for v in rep.errors())
