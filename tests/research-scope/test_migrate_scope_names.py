import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "research-scope" / "scripts"))
import migrate_scope_names  # noqa: E402


def test_migrates_transition_record_to_spec_source(tmp_path):
    path = tmp_path / "transitions.jsonl"
    record = {
        "node_id": "dir/d1",
        "node": {
            "id": "dir/d1",
            "level": "direction",
            "parents": ["project/main"],
            "version": 1,
            "status": "ACTIVE",
            "yardstick": {
                "hypothesis": "h",
                "metric": "m",
                "baselines": ["b"],
                "success_predicate": "m >= b",
            },
            "provenance": "old",
        },
    }
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")

    report = migrate_scope_names.migrate_jsonl(path, write=True)
    migrated = json.loads(path.read_text(encoding="utf-8"))

    assert report["changed"] == 3
    assert "yardstick" not in migrated["node"]
    assert migrated["node"]["spec"]["success_gate"] == "m >= b"
    assert migrated["node"]["source"] == "old"


def test_rejects_mixed_old_new_node_fields(tmp_path):
    path = tmp_path / "transitions.jsonl"
    record = {
        "node_id": "dir/d1",
        "node": {
            "id": "dir/d1",
            "level": "direction",
            "yardstick": {"success_predicate": "old"},
            "spec": {"success_gate": "new"},
        },
    }
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")

    with pytest.raises(migrate_scope_names.MigrationError, match="mixed"):
        migrate_scope_names.migrate_jsonl(path, write=True)


def test_migrates_package_provenance_text(tmp_path):
    path = tmp_path / "research-packages.js"
    path.write_text(
        'window.RESEARCH_PACKAGES = [{id: "p", sourceScopeNode: "dir/d1", '
        'sourceScopeVersion: "1", sourceScopeTxn: "abc", '
        'sourceScopeMilestones: [{id: "task/d1/m0"}], '
        'experiments: [{id: "P0", parentTask: "task/d1/m0"}]}];\n',
        encoding="utf-8",
    )

    report = migrate_scope_names.migrate_inventory(path, write=True)
    text = path.read_text(encoding="utf-8")

    assert report["changed"] == 5
    assert "sourceDirection" in text
    assert "sourceVersion" in text
    assert "sourceChange" in text
    assert "sourceTasks" in text
    assert "sourceTask" in text
    assert "sourceScopeNode" not in text
    assert "parentTask" not in text
