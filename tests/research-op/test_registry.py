"""Phases 4-6 — project-level knowledge registries (papers / edges / gaps) via research-op."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "research-op" / "scripts"))

CLI = ROOT / "skills" / "research-op" / "scripts" / "research_op.py"
sys.path.insert(0, str(ROOT))
from lib.research_state import EventStore, ResearchPaths  # noqa: E402


# The state-backed research-op CLI owns validation, deduplication, and storage.

def _run(args):
    return subprocess.run([sys.executable, str(CLI)] + args, capture_output=True, text=True)


def _seed_package(workspace):
    paths = ResearchPaths.resolve(workspace=workspace, research_root=".research")
    store = EventStore(paths)
    store.initialize()
    EventStore(paths, fixture_mode=True).commit(
        event_type="AggregateImported",
        aggregate_type="package",
        aggregate_id="test-pkg",
        payload={
            "record": {
                "id": "test-pkg",
                "lifecycle": "ACTIVE",
                "phase": "CONTEXT_LOADED",
                "blocker": None,
            },
            "migration": {"source": "test-fixture"},
        },
        actor={"type": "system", "id": "test"},
        idempotency_key="seed-package",
        expected_version=0,
    )
    return paths


def test_cli_registry_add_paper(tmp_path):
    paths = _seed_package(tmp_path)
    r = _run(["--pkg", "test-pkg", "--op", "registry-add", "--target", "paper",
              "--payload", json.dumps({"id": "dpr2020", "title": "Dense Passage Retrieval",
                                       "url": "https://arxiv.org/abs/2004.04906"}),
              "--workspace", str(tmp_path),
              "--research-root", ".research"])
    assert r.returncode == 0, r.stderr
    result = json.loads(r.stdout)
    assert result["status"] == "added"
    paper = EventStore(paths).state()["aggregates"]["paper"]["dpr2020"]
    assert paper["title"] == "Dense Passage Retrieval"
    assert not (tmp_path / "research_html" / "data" / "papers.jsonl").exists()
    audit = paths.audit_actions.read_text(encoding="utf-8")
    assert '"entry_skill":"research-op"' in audit and '"validation":"PASSED"' in audit


def test_cli_registry_add_rejects_bad_edge_type(tmp_path):
    paths = _seed_package(tmp_path)
    r = _run(["--pkg", "test-pkg", "--op", "registry-add", "--target", "edge",
              "--payload", json.dumps({"from": "paper:a", "to": "paper:b", "type": "bogus"}),
              "--workspace", str(tmp_path),
              "--research-root", ".research"])
    assert r.returncode == 2
    env = json.loads(r.stdout)
    assert env["rejected"] is True and env["rule"] == "edge-type-unknown"
    assert EventStore(paths).state()["aggregates"]["knowledge_edge"] == {}
    assert not (tmp_path / "research_html" / "data" / "edges.jsonl").exists()
    audit = paths.audit_actions.read_text(encoding="utf-8")
    assert "edge-type-unknown" in audit and '"validation":"OP_REJECTED"' in audit


@pytest.mark.parametrize(
    ("target", "payload", "aggregate_type"),
    [
        ("paper", {"id": "p1", "title": "Paper One"}, "paper"),
        (
            "edge",
            {"from": "paper:p1", "to": "gap:g1", "type": "ADDRESSES_GAP"},
            "knowledge_edge",
        ),
        ("gap", {"id": "g1", "summary": "Missing evaluation"}, "knowledge_gap"),
    ],
)
def test_cli_registry_targets_map_to_typed_state(
    tmp_path,
    target,
    payload,
    aggregate_type,
):
    paths = _seed_package(tmp_path)
    if target == "edge":
        for prerequisite_target, prerequisite_payload in (
            ("paper", {"id": "p1", "title": "Paper One"}),
            ("gap", {"id": "g1", "summary": "Missing evaluation"}),
        ):
            prerequisite = _run(
                [
                    "--pkg",
                    "test-pkg",
                    "--op",
                    "registry-add",
                    "--target",
                    prerequisite_target,
                    "--payload",
                    json.dumps(prerequisite_payload),
                    "--workspace",
                    str(tmp_path),
                    "--research-root",
                    ".research",
                ]
            )
            assert prerequisite.returncode == 0, prerequisite.stdout + prerequisite.stderr
    result = _run(
        [
            "--pkg",
            "test-pkg",
            "--op",
            "registry-add",
            "--target",
            target,
            "--payload",
            json.dumps(payload),
            "--workspace",
            str(tmp_path),
            "--research-root",
            ".research",
        ]
    )

    assert result.returncode == 0, result.stdout + result.stderr
    output = json.loads(result.stdout)
    assert output["aggregate"].startswith(f"{aggregate_type}/")
    assert len(EventStore(paths).state()["aggregates"][aggregate_type]) == 1
