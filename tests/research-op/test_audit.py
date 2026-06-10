import json
import os
from pathlib import Path

import sys
sys.path.insert(0, "skills/research-op/scripts")
import audit


def test_append_writes_jsonl_line(tmp_path, monkeypatch):
    monkeypatch.setenv("RESEARCH_RUNTIME_ROOT", str(tmp_path))
    audit.append(
        "test-pkg",
        op="check", target=None, event=None,
        state_before={"category": "in-progress", "status": "CONTEXT_LOADED"},
        state_after ={"category": "in-progress", "status": "CONTEXT_LOADED"},
        validation="PASSED", rule=None,
        files_touched=[], payload={"scope": "all"},
        user_intent=None, duration_ms=42,
    )
    log = tmp_path / "test-pkg" / "_actions.jsonl"
    assert log.exists()
    entry = json.loads(log.read_text().strip())
    assert entry["op"] == "check"
    assert entry["validation"] == "PASSED"
    assert entry["payload"]["scope"] == "all"
    assert "payload_sha256" in entry


def test_append_creates_parent_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("RESEARCH_RUNTIME_ROOT", str(tmp_path / "deep" / "nested"))
    audit.append(
        "test-pkg", op="check", target=None, event=None,
        state_before={}, state_after={},
        validation="PASSED", rule=None, files_touched=[], payload={},
        user_intent=None, duration_ms=1,
    )
    assert (tmp_path / "deep" / "nested" / "test-pkg" / "_actions.jsonl").exists()
