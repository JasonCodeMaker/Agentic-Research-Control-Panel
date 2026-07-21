"""Canonical Experiment run-directory and metric-verification contract."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "research-run" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import skeleton  # noqa: E402
from state_fixtures import remove_interface, seed  # noqa: E402


SPEC = {"gate": "measured >= 0.80"}


def test_experiment_writes_canonical_run_files(tmp_path):
    paths = seed(tmp_path)
    remove_interface(paths)
    artifact = skeleton.experiment(
        "pkg-1",
        paths,
        measured=0.9,
        experiment_id="P1",
    )
    artifact_path = Path(artifact["path"])
    assert artifact_path == (
        paths.experiments / "pkg-1" / "P1" / "run-001" / "files" / "metric.json"
    )
    assert artifact["evidence"]["kind"] == "METRIC"
    assert json.loads(artifact_path.read_text(encoding="utf-8"))["measured"] == 0.9
    run_dir = artifact_path.parents[1]
    for name in (
        "run.json",
        "context.json",
        "events.jsonl",
        "metrics.jsonl",
        "status.json",
        "result.json",
        "log.txt",
    ):
        assert (run_dir / name).is_file()
    assert not paths.interface.exists()


def test_verify_reads_the_persisted_metric(tmp_path):
    paths = seed(tmp_path)
    artifact = skeleton.experiment(
        "pkg-1",
        paths,
        measured=0.9,
        experiment_id="P1",
    )
    artifact_path = Path(artifact["path"])
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    payload["measured"] = 0.5
    artifact_path.write_text(json.dumps(payload), encoding="utf-8")
    verdict = skeleton.verify(artifact_path, SPEC)
    assert verdict["measured"] == 0.5
    assert verdict["result"] == "FAIL"


def test_missing_metric_cannot_be_fabricated(tmp_path):
    with pytest.raises(FileNotFoundError):
        skeleton.verify(tmp_path / "missing.json", SPEC)


def test_unknown_or_duplicate_run_is_rejected(tmp_path):
    paths = seed(tmp_path)
    with pytest.raises(KeyError, match="found 0"):
        skeleton.experiment(
            "pkg-1",
            paths,
            measured=0.9,
            experiment_id="unknown",
        )
    skeleton.experiment(
        "pkg-1",
        paths,
        measured=0.9,
        experiment_id="P1",
    )
    with pytest.raises(FileExistsError):
        skeleton.experiment(
            "pkg-1",
            paths,
            measured=0.9,
            experiment_id="P1",
        )
