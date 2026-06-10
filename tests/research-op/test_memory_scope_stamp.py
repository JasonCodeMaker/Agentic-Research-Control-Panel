"""Item 7 TDD gate: scope-stamped memory. An entry without scope_version is rejected before write; a
stamped entry persists; stamped entries round-trip into propagation (reopen/carry by version).

Ledger 1 selflearn-scope-stamped-memory / Ledger 3 scope-stamped memory (entry without scope_version
is rejected; propagation can invalidate/reopen by version).
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
import scope_ssot  # noqa: E402
from scope_ssot import RuleViolation  # noqa: E402


def test_memory_entry_without_scope_version_rejected(tmp_path):
    log = tmp_path / "memory.jsonl"
    with pytest.raises(RuleViolation):
        scope_ssot.append_memory(log, {"id": "m1", "kind": "IDEA", "failed_on_metric": "Recall@10"})
    assert not log.exists()  # reject-before-write


def test_memory_entry_with_scope_version_appended(tmp_path):
    log = tmp_path / "memory.jsonl"
    scope_ssot.append_memory(log, {"id": "m1", "kind": "IDEA",
                                   "failed_on_metric": "Recall@10", "scope_version": 1})
    lines = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert lines[0]["scope_version"] == 1


def test_stamped_memory_roundtrips_into_propagate(tmp_path):
    log = tmp_path / "memory.jsonl"
    scope_ssot.append_memory(log, {"id": "i1", "kind": "IDEA",
                                   "failed_on_metric": "Recall@10", "scope_version": 1})
    scope_ssot.append_memory(log, {"id": "r1", "kind": "RESULT",
                                   "metric": "nDCG@10", "scope_version": 1})
    memory = scope_ssot.read_log(log)
    out = scope_ssot.propagate(old_metric="Recall@10", new_metric="nDCG@10", memory=memory)
    assert out["REOPEN_IDEA"] == ["i1"]
    assert out["RETAIN"] == ["r1"]
