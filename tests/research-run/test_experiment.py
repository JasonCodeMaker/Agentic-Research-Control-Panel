"""Item 4 TDD gate: R4 produces a verified metric artifact on disk; R5 reads the metric from that
artifact (not from an in-memory argument); the artifact value never enters the SSOT yardstick.

Ledger 1 r4-experiment / Ledger 3 verified runtime artifact (read artifact value and SSOT yardstick
separately; artifact value cannot be copied into SSOT).
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "skills" / "research-run" / "scripts"))
import scope_ssot  # noqa: E402
import skeleton  # noqa: E402

YARD = {"success_predicate": "measured >= 0.80"}


def test_experiment_writes_artifact_file(tmp_path):
    art = skeleton.experiment("2026-x", tmp_path, measured=0.9)
    p = Path(art["path"])
    assert p.exists()
    assert p.parent.name == "artifacts"
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["measured"] == 0.9
    assert data["artifact_id"] == art["artifact_id"]


def test_verify_reads_metric_from_artifact_not_arg(tmp_path):
    art = skeleton.experiment("2026-x", tmp_path, measured=0.9)
    # tamper the artifact on disk; verify must reflect the file, proving it reads disk
    p = Path(art["path"])
    data = json.loads(p.read_text(encoding="utf-8"))
    data["measured"] = 0.5
    p.write_text(json.dumps(data), encoding="utf-8")
    verdict = skeleton.verify(art["path"], YARD)
    assert verdict["measured"] == 0.5
    assert verdict["result"] == "FAIL"


def test_missing_artifact_cannot_acquit(tmp_path):
    with pytest.raises(FileNotFoundError):
        skeleton.verify(str(tmp_path / "artifacts" / "nope.json"), YARD)  # no fabricated metric


def test_artifact_value_not_copied_into_ssot(tmp_path):
    skeleton.run("contrastive pretraining improves recall", pkg_id="2026-x",
                 runtime_root=tmp_path, citations=[], measured=0.9)
    proj = scope_ssot.fold(scope_ssot.read_log(tmp_path / "_scope" / "transitions.jsonl"))
    yard = proj["dir/2026-x"]["yardstick"]
    assert not (scope_ssot.READING_FIELDS & set(yard))  # no reading leaked into the SSOT
    assert "measured" not in yard
