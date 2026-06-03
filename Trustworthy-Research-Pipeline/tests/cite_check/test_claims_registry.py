"""Item 6 TDD gate: the R6 claim registry. Every registered claim must map to a verified artifact;
an orphan claim is rejected before any line hits the registry.

Ledger 1 r6-write / Ledger 3 claim registry (every claim id maps to a verified artifact id; orphan
claim fails R6).
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
import cite_check  # noqa: E402


def test_register_resolved_claims_appends(tmp_path):
    log = tmp_path / "claims.jsonl"
    claims = [{"id": "c1", "artifact_id": "exp-001"}, {"id": "c2", "artifact_id": "exp-002"}]
    cite_check.register_claims(log, claims, {"exp-001", "exp-002"})
    lines = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert [c["id"] for c in lines] == ["c1", "c2"]


def test_orphan_claim_rejected_before_write(tmp_path):
    log = tmp_path / "claims.jsonl"
    claims = [{"id": "c1", "artifact_id": "exp-001"}, {"id": "c3", "artifact_id": "ghost"}]
    with pytest.raises(ValueError):
        cite_check.register_claims(log, claims, {"exp-001"})
    assert not log.exists()  # reject-before-write: orphan blocks the whole batch


def test_register_appends_one_line_per_claim(tmp_path):
    log = tmp_path / "claims.jsonl"
    cite_check.register_claims(log, [{"id": "c1", "artifact_id": "a"}], {"a"})
    cite_check.register_claims(log, [{"id": "c2", "artifact_id": "a"}], {"a"})
    assert len([line for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]) == 2
