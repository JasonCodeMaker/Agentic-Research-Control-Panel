"""State-backed Context Pack query contracts."""

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "lib"))

import context_pack  # noqa: E402
import context_pack.build as build  # noqa: E402
from research_state import EventStore, ResearchPaths, UpgradeRequired  # noqa: E402
from lib.research_state import (  # noqa: E402
    CommandRejected as LibCommandRejected,
    ResearchPaths as LibResearchPaths,
    StateQuery as LibStateQuery,
)
from tests.scope_fixtures import (  # noqa: E402
    direction_node,
    experiment_spec,
    project_node,
)


ACTOR = {"type": "system", "id": "test"}
EXPERIMENT_ID = "experiment/retrieval/M0-baseline"
EXPERIMENT_SOURCE = "fixture:context-pack-import"


def _ref():
    return {
        "uri": "experiments/pkg/exp/run/result.json",
        "sha256": "a" * 64,
        "size_bytes": 12,
        "kind": "FILE",
        "package_id": "pkg",
        "experiment_id": EXPERIMENT_ID,
        "run_id": "run",
    }


def _commit(store, event_type, aggregate_type, aggregate_id, record, index):
    writer = (
        EventStore(store.paths, migration_mode=True)
        if event_type == "AggregateImported"
        else store
    )
    return writer.commit(
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        payload={"record": record},
        actor=ACTOR,
        idempotency_key=f"seed:{index}:{aggregate_type}:{aggregate_id}",
        expected_version=0,
    )


def _seed(tmp_path):
    paths = ResearchPaths.resolve(workspace=tmp_path)
    store = EventStore(paths)
    store.initialize()
    rows = [
        (
            "AggregateImported",
            "project",
            "project/main",
            project_node(
                "project/main",
                source=EXPERIMENT_SOURCE,
                goal="Build an auditable research workflow",
                out_of_scope=["No unsupported claims"],
            ),
        ),
        (
            "AggregateImported",
            "direction",
            "dir/retrieval",
            direction_node(
                "dir/retrieval",
                parent="project/main",
                source=EXPERIMENT_SOURCE,
                hypothesis="Contrastive retrieval improves R@1",
                metric={"name": "R@1", "dir": "higher"},
                success_gate="R@1 >= 48",
            ),
        ),
        (
            "AggregateImported",
            "package",
            "pkg",
            {
                "id": "pkg",
                "slug": "pkg",
                "direction_id": "dir/retrieval",
                "sourceDirection": "dir/retrieval",
                "sourceVersion": 1,
                "sourceChange": EXPERIMENT_SOURCE,
                "sourceExperiments": [
                    {
                        "id": EXPERIMENT_ID,
                        "version": 1,
                        "source": EXPERIMENT_SOURCE,
                    }
                ],
                "lifecycle": "ACTIVE",
                "phase": "CONTEXT_LOADED",
                "methodsTried": [],
            },
        ),
        (
            "AggregateImported",
            "experiment",
            EXPERIMENT_ID,
            {
                "id": EXPERIMENT_ID,
                "local_id": "exp",
                "package_id": "pkg",
                "direction_id": "dir/retrieval",
                "status": "PLANNED",
                "spec": experiment_spec(
                    purpose="Reproduce the baseline",
                    config_ref="configs/base.yaml",
                    gate="R@1 within tolerance",
                    control_mode="SUPERVISED",
                ),
                "scope_version": 1,
                "scope_status": "ACTIVE",
                "scope_confirmation": "CONFIRMED",
                "confirmed_direction_version": 1,
                "scope_source": EXPERIMENT_SOURCE,
            },
        ),
        (
            "AggregateImported",
            "package",
            "old",
            {
                "id": "old",
                "direction_id": "dir/retrieval",
                "sourceDirection": "dir/retrieval",
                "sourceVersion": 1,
                "sourceChange": EXPERIMENT_SOURCE,
                "sourceExperiments": [],
                "category": "fail",
                "status": "ARCHIVED",
                "legacy_fact_store": {
                    "files": {
                        "tables/methods_tried.csv": {
                            "format": "csv",
                            "sha256": "b" * 64,
                            "data": [
                                {
                                    "row_id": "legacy-failed-method",
                                    "method": "hard-negative mining",
                                    "hypothesis": "mining helps",
                                    "gate": "R@1>=48",
                                    "measured": "44",
                                    "verdict": "FAIL",
                                }
                            ],
                        }
                    }
                },
            },
        ),
        (
            "RulePromoted",
            "rule",
            "rule.metric@1",
            {
                "id": "rule.metric",
                "version": "1",
                "level": "project",
                "kind": "constraint",
                "origin": "selfevolve",
                "content": "Verify the metric contract.",
                "evidence_refs": [_ref()],
            },
        ),
        (
            "LearningRecorded",
            "learning",
            "learning:metric",
            {
                "id": "learning:metric",
                "observation": "Mining failed under the accepted protocol.",
                "scope": {
                    "project": "project/main",
                    "packages": ["pkg"],
                    "task_types": ["retrieval"],
                },
                "evidence_refs": [_ref()],
                "evidence": [_ref()],
            },
        ),
        (
            "AggregateUpserted",
            "paper",
            "dpr",
            {"id": "dpr", "title": "Dense Passage Retrieval", "url": "https://example.test"},
        ),
        (
            "AggregateUpserted",
            "knowledge_edge",
            "edge-1",
            {"id": "edge-1", "from": "paper:dpr", "to": "paper:ours", "type": "EXTENDS"},
        ),
        (
            "AggregateUpserted",
            "knowledge_gap",
            "gap-1",
            {"id": "gap-1", "summary": "No zero-shot evaluation", "status": "open"},
        ),
        (
            "ProposalSubmitted",
            "proposal",
            "proposal-1",
            {
                "id": "proposal-1",
                "package_id": "pkg",
                "change": "Revise the baseline gate",
            },
        ),
        (
            "DecisionRecorded",
            "decision",
            "decision-pending",
            {
                "id": "decision-pending",
                "package_id": "pkg",
                "subject_id": "pkg",
                "status": "PENDING",
                "outcome": "ASK_USER",
                "evidence_refs": [_ref()],
                "evidence": [_ref()],
                "actor": ACTOR,
            },
        ),
        (
            "DecisionRecorded",
            "decision",
            "decision-resolved",
            {
                "id": "decision-resolved",
                "package_id": "pkg",
                "subject_id": "pkg",
                "status": "RESOLVED",
                "outcome": "APPROVED",
                "evidence": [_ref()],
                "actor": ACTOR,
            },
        ),
        (
            "AggregateImported",
            "run",
            "run-hidden",
            {
                "id": "run-hidden",
                "package_id": "pkg",
                "experiment_id": EXPERIMENT_ID,
                "status": "COMPLETED",
                "full_log": "secret-full-run-log",
            },
        ),
    ]
    for index, row in enumerate(rows):
        _commit(store, *row, index)
    return paths


def test_build_is_ephemeral_and_hash_stamped(tmp_path):
    paths = _seed(tmp_path)
    full, core = build.build(paths, "pkg", generated_at="t0")
    payload = context_pack.render_json(full)
    state = EventStore(paths).state()

    assert payload["stamp"]["source_seq"] == state["source_seq"]
    assert payload["stamp"]["source_hash"] == state["source_hash"]
    assert "Contrastive retrieval improves R@1" in context_pack.render_md(full)
    assert "Verify the metric contract" in context_pack.render_md(core)
    assert not list(paths.root.rglob("context_pack.*"))


def test_query_reads_state_entities_not_interface(tmp_path):
    paths = _seed(tmp_path)
    bad = paths.interface / "data" / "rules.js"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("this is intentionally malformed", encoding="utf-8")

    md = context_pack.render_md(build.build(paths, "pkg")[0])
    for needle in (
        "Reproduce the baseline",
        "hard-negative mining",
        "Mining failed under the accepted protocol",
        "Dense Passage Retrieval",
        "EXTENDS",
        "No zero-shot evaluation",
    ):
        assert needle in md

    shutil.rmtree(paths.interface)
    assert context_pack.render_md(build.build(paths, "pkg")[0]) == md


def test_state_query_context_is_bounded_and_accepts_lib_research_paths(tmp_path):
    _seed(tmp_path)
    paths = LibResearchPaths.resolve(workspace=tmp_path)
    result = LibStateQuery(paths).context("pkg", phase="CONTEXT_LOADED")
    serialized = json.dumps(result, sort_keys=True)
    assert result["source_seq"] == result["data"]["stamp"]["source_seq"]
    assert result["source_hash"] == result["data"]["stamp"]["source_hash"]
    assert "phase: CONTEXT_LOADED" in serialized
    assert "control_mode=SUPERVISED" in serialized
    assert "decision-pending" in serialized
    assert "decision-resolved" not in serialized
    assert "secret-full-run-log" not in serialized
    selection = result["data"]["selection"]
    assert selection["package"] == {
        "id": "pkg",
        "lifecycle": "ACTIVE",
        "phase": "CONTEXT_LOADED",
        "blocker": None,
    }
    assert selection["experiments"] == [
        {
            "id": EXPERIMENT_ID,
            "status": "PLANNED",
            "control_mode": "SUPERVISED",
        }
    ]
    assert selection["pending_decision_ids"] == ["decision-pending"]
    assert selection["evidence_refs"] == [_ref()]


def test_compact_context_is_hard_bounded_and_reports_omissions(tmp_path):
    _seed(tmp_path)
    paths = LibResearchPaths.resolve(workspace=tmp_path)

    result = LibStateQuery(paths).compact_context(
        "pkg",
        phase="CONTEXT_LOADED",
        experiment_id=EXPERIMENT_ID,
    )
    serialized = json.dumps(
        result,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    assert len(serialized) <= 4_000
    assert result["data"]["view"] == "compact"
    assert result["data"]["action"]["experiment_id"] == EXPERIMENT_ID
    assert result["data"]["omitted"]["history"] is True
    assert result["data"]["budget"]["limit_chars"] == 4_000
    assert result["data"]["budget"]["serialized_chars"] == len(serialized)
    assert "secret-full-run-log" not in serialized

    with pytest.raises(LibCommandRejected, match="mandatory intent"):
        LibStateQuery(paths).compact_context("pkg", budget_chars=512)


def test_state_query_context_uses_one_authoritative_snapshot(tmp_path, monkeypatch):
    _seed(tmp_path)
    paths = LibResearchPaths.resolve(workspace=tmp_path)
    from lib.research_state.store import EventStore as LibEventStore

    real_state = LibEventStore.state
    reads = []

    def counted_state(self, *args, **kwargs):
        reads.append(self.paths.current)
        return real_state(self, *args, **kwargs)

    monkeypatch.setattr(LibEventStore, "state", counted_state)
    result = LibStateQuery(paths).context("pkg")

    assert len(reads) == 1
    assert result["source_seq"] == result["data"]["stamp"]["source_seq"]
    assert result["source_hash"] == result["data"]["stamp"]["source_hash"]


def test_package_binding_rule_is_scoped(tmp_path):
    paths = _seed(tmp_path)
    store = EventStore(paths)
    _commit(
        store,
        "RulePromoted",
        "rule",
        "rule.pkg@1",
        {
            "id": "rule.pkg",
            "version": "1",
            "level": "package",
            "kind": "binding",
            "package_id": "pkg",
            "origin": "selfevolve",
            "content": "Keep one run ledger.",
            "evidence_refs": [_ref()],
        },
        100,
    )
    _commit(
        store,
        "RulePromoted",
        "rule",
        "rule.other@1",
        {
            "id": "rule.other",
            "version": "1",
            "level": "package",
            "kind": "binding",
            "package_id": "other",
            "origin": "selfevolve",
            "content": "Other package only.",
            "evidence_refs": [_ref()],
        },
        101,
    )
    md = context_pack.render_md(build.build(paths, "pkg")[0])
    assert "Keep one run ledger" in md
    assert "Other package only" not in md


def test_unknown_package_fails(tmp_path):
    paths = _seed(tmp_path)
    with pytest.raises(KeyError, match="unknown package"):
        build.build(paths, "missing")


def test_unmigrated_legacy_workspace_requires_upgrade(tmp_path):
    (tmp_path / "research_html").mkdir()
    with pytest.raises(UpgradeRequired, match="upgrade-required"):
        build.build(tmp_path, "pkg")


def test_cli_prints_projection_and_does_not_persist(tmp_path, capsys):
    paths = _seed(tmp_path)
    rc = build.main(
        [
            "--workspace",
            str(tmp_path),
            "--research-root",
            str(paths.root),
            "--pkg",
            "pkg",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["stamp"]["source_hash"]
    assert not list(paths.root.rglob("context_pack.*"))


def test_persistence_refresh_api_is_not_exposed():
    assert not hasattr(build, "ensure_fresh")
