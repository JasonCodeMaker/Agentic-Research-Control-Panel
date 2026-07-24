import hashlib
import json
import sys

import pytest

from lib.experiments.contracts import verify_result_evidence
from lib.experiments.extract import extract_result
from lib.experiments.launch import launch_run, prepare_run
from lib.experiments.result_tables import extract_result_tables
from lib.interface.build import build_interface
from lib.interface.package import package_view_models
from lib.research_state import CommandRejected, EventStore, ResearchPaths


AGENT = {"type": "agent", "id": "test"}
USER = {"type": "user", "id": "pm"}


def _launch(tmp_path, *, result_schema=None):
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    store = EventStore(paths)
    store.initialize()
    EventStore(paths, fixture_mode=True).commit(
        event_type="AggregateImported",
        aggregate_type="direction",
        aggregate_id="direction/pkg",
        payload={
            "record": {
                "id": "direction/pkg",
                "level": "direction",
                "parents": ["project/test"],
                "version": 1,
                "status": "ACTIVE",
                "source": "test",
                "spec": {},
            },
            "migration": {"source": "test-fixture"},
        },
        actor=AGENT,
        idempotency_key="seed-direction",
    )
    store.commit(
        event_type="AggregateUpserted",
        aggregate_type="package",
        aggregate_id="pkg",
        payload={
            "record": {
                "id": "pkg",
                "lifecycle": "ACTIVE",
                "phase": "READY_TO_LAUNCH",
                "blocker": None,
                "direction_id": "direction/pkg",
                "sourceVersion": 1,
                "sourceChange": "test",
                "sourceExperiments": [
                    {"id": "pkg::P1", "version": 1, "source": "test"}
                ],
            }
        },
        actor=AGENT,
        idempotency_key="seed-package",
    )
    experiment = {
        "id": "pkg::P1",
        "local_id": "P1",
        "package_id": "pkg",
        "direction_id": "direction/pkg",
        "scope_status": "ACTIVE",
        "scope_version": 1,
        "scope_source": "test",
        "scope_confirmation": "CONFIRMED",
        "confirmed_direction_version": 1,
        "status": "READY",
        "spec": {
            "purpose": "verify evidence",
            "config_ref": "config.yaml",
            "gate": "loss <= 1",
            "control_mode": "CHECKPOINTED",
        },
    }
    if result_schema is not None:
        experiment["resultSchema"] = result_schema
    EventStore(paths, fixture_mode=True).commit(
        event_type="AggregateUpserted",
        aggregate_type="experiment",
        aggregate_id="pkg::P1",
        payload={"record": experiment},
        actor=AGENT,
        idempotency_key="seed-experiment",
    )
    store.commit(
        event_type="DecisionRecorded",
        aggregate_type="decision",
        aggregate_id="ack",
        payload={
            "record": {
                "id": "ack",
                "kind": "LAUNCH_ACK",
                "status": "ACKNOWLEDGED",
                "package_id": "pkg",
                "experiment_id": "pkg::P1",
                "actor": USER,
                "evidence": [{"kind": "ACTOR_ATTESTATION"}],
            }
        },
        actor=USER,
        idempotency_key="seed-ack",
    )
    launched = launch_run(
        paths=paths,
        package_id="pkg",
        experiment_id="P1",
        run_id="run-one",
        command=[sys.executable, "-c", "print('loss=0.25')"],
        cwd=tmp_path,
        use_tmux=False,
    )
    return paths, launched


RESULT_SCHEMA = {
    "version": 1,
    "tables": [
        {
            "id": "effectiveness",
            "type": "main",
            "title": "Worked paired outcomes",
            "rowLabel": "Method / seed",
            "rows": [
                {
                    "id": "sqr-42",
                    "label": "SQR · seed 42",
                    "selector": {"method": "sqr", "seed": "42"},
                }
            ],
            "columns": [
                {
                    "id": "initial-r1",
                    "label": "Initial R@1 (%)",
                    "metric": "initial_r_at_1_pct",
                    "unit": "percent",
                },
                {
                    "id": "final-r1",
                    "label": "Final R@1 (%)",
                    "metric": "final_r_at_1_pct",
                    "unit": "percent",
                },
                {
                    "id": "repair-r1",
                    "label": "Repair@1 (%)",
                    "metric": "repair_at_1_pct",
                    "unit": "percent",
                    "nullable": True,
                },
                {
                    "id": "harm-r1",
                    "label": "Harm@1 (%)",
                    "metric": "harm_at_1_pct",
                    "unit": "percent",
                    "nullable": True,
                },
                {
                    "id": "delta-r1",
                    "label": "ΔR@1 (pp)",
                    "metric": "delta_r_at_1_pp",
                    "unit": "percentage_point",
                },
            ],
        },
        {
            "id": "comparison",
            "type": "ablation",
            "title": "SQR effect",
            "rowLabel": "Comparison",
            "rows": [
                {
                    "id": "sqr-vs-one-shot",
                    "label": "SQR − one-shot",
                    "selector": {
                        "method": "sqr_minus_one_shot",
                        "seed": "42",
                    },
                }
            ],
            "columns": [
                {
                    "id": "paired-delta",
                    "label": "Paired ΔR@1 (pp)",
                    "metric": "paired_delta_r_at_1_pp",
                    "unit": "percentage_point",
                }
            ],
        },
    ],
}


def _metric_csv(
    path,
    *,
    duplicate=False,
    missing=False,
    wrong_unit=False,
    undefined_repair=False,
    failed_final=False,
):
    rows = [
        ("sqr", "42", "initial_r_at_1_pct", "50", "percent"),
        ("sqr", "42", "final_r_at_1_pct", "50", "percent"),
        ("sqr", "42", "repair_at_1_pct", "50", "percent"),
        ("sqr", "42", "harm_at_1_pct", "50", "percent"),
        (
            "sqr",
            "42",
            "delta_r_at_1_pp",
            "0",
            "percent" if wrong_unit else "percentage_point",
        ),
        (
            "sqr_minus_one_shot",
            "42",
            "paired_delta_r_at_1_pp",
            "0",
            "percentage_point",
        ),
        ("sqr", "42", "unused_metric", "999", "count"),
    ]
    if duplicate:
        rows.append(rows[0])
    if missing:
        rows = [row for row in rows if row[2] != "harm_at_1_pct"]
    path.parent.mkdir(exist_ok=True)
    rendered = ["method,seed,metric,value,unit,status,reason\n"]
    for method, seed, metric, value, unit in rows:
        if failed_final and metric == "final_r_at_1_pct":
            rendered.append(
                f"{method},{seed},{metric},null,{unit},FAILED,"
                "evaluation process exited before this metric\n"
            )
        elif undefined_repair and metric == "repair_at_1_pct":
            rendered.append(
                f"{method},{seed},{metric},null,{unit},UNDEFINED,"
                "initial-wrong denominator is zero\n"
            )
        else:
            rendered.append(
                f"{method},{seed},{metric},{value},{unit},MEASURED,\n"
            )
    path.write_text("".join(rendered), encoding="utf-8")


def test_terminal_result_evidence_is_hash_bound(tmp_path):
    paths, launched = _launch(tmp_path)
    run = json.loads(launched.run_path.read_text(encoding="utf-8"))
    result_path = launched.run_dir / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["evidence"]
    assert all(
        {
            "uri",
            "sha256",
            "size_bytes",
            "kind",
            "package_id",
            "experiment_id",
            "run_id",
        }
        <= set(ref)
        for ref in result["evidence"]
    )
    verify_result_evidence(paths, run, result)

    (launched.run_dir / "log.txt").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(ValueError, match="mismatch"):
        verify_result_evidence(paths, run, result)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("protocol", None, "protocol must be an object"),
        ("measurements", [], "measurements must be an object"),
        (
            "decision_candidate",
            "RUN_NEXT_EXPERIMENT",
            "decision_candidate must be an object or null",
        ),
        ("status", "RUNNING", "status must be terminal"),
    ],
)
def test_terminal_result_requires_complete_scientific_shape(
    tmp_path,
    field,
    value,
    message,
):
    paths, launched = _launch(tmp_path)
    run = json.loads(launched.run_path.read_text(encoding="utf-8"))
    result = json.loads(
        (launched.run_dir / "result.json").read_text(encoding="utf-8")
    )
    result[field] = value

    with pytest.raises(ValueError, match=message):
        verify_result_evidence(paths, run, result)


def test_extractor_adds_scientific_result_without_rewriting_run_intent(tmp_path):
    paths, launched = _launch(tmp_path)
    before = launched.run_path.read_bytes()
    table = launched.run_dir / "files" / "summary.json"
    table.parent.mkdir(exist_ok=True)
    table.write_text('{"loss": 0.25}\n', encoding="utf-8")

    result = extract_result(
        paths,
        launched.run_dir,
        payload={
            "protocol": {"name": "smoke"},
            "measurements": {"loss": 0.25},
            "verdict": "PASS",
            "validity": "VALID",
            "supported_claims": ["The smoke gate passed."],
            "unsupported_claims": [],
        },
        evidence_files=[table],
    )
    assert result["verdict"] == "PASS"
    assert result["validity"] == "VALID"
    assert any(ref["uri"].endswith("files/summary.json") for ref in result["evidence"])
    assert launched.run_path.read_bytes() == before

    result_path = launched.run_dir / "result.json"
    result_sha256 = hashlib.sha256(result_path.read_bytes()).hexdigest()
    store = EventStore(paths)
    run_events = [
        event
        for event in store.events()
        if event["aggregate_type"] == "run"
        and event["aggregate_id"] == "run-one"
    ]
    assert [event["event_type"] for event in run_events] == [
        "RunLaunchAuthorized",
        "RunLaunched",
        "RunTerminal",
        "RunResultFinalized",
    ]
    assert sum(
        event["event_type"] == "RunTerminal" for event in run_events
    ) == 1
    current = store.state()["aggregates"]["run"]["run-one"]
    assert current["status"] == "COMPLETED"
    assert current["latest_scientific_result"]["result_sha256"] == result_sha256
    assert current["latest_scientific_result"]["measurements"] == {"loss": 0.25}
    assert current["latest_scientific_result"]["evidence_count"] == len(
        result["evidence"]
    )
    build_interface(paths)
    interface_rows = [
        json.loads(line)
        for line in paths.interface_data.joinpath("live-runs.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    projected = next(row for row in interface_rows if row["run_id"] == "run-one")
    assert (
        projected["latest_scientific_result"]["result_sha256"]
        == result_sha256
    )

    repeated = extract_result(
        paths,
        launched.run_dir,
        payload={
            "protocol": {"name": "smoke"},
            "measurements": {"loss": 0.25},
            "verdict": "PASS",
            "validity": "VALID",
            "supported_claims": ["The smoke gate passed."],
            "unsupported_claims": [],
        },
        evidence_files=[table],
    )
    assert repeated == result
    assert sum(
        event["event_type"] == "RunResultFinalized"
        for event in store.events()
        if event["aggregate_type"] == "run"
        and event["aggregate_id"] == "run-one"
    ) == 1


def test_schema_backed_tables_are_extracted_from_hash_bound_csv(tmp_path):
    paths, launched = _launch(tmp_path, result_schema=RESULT_SCHEMA)
    source = launched.run_dir / "files" / "all_metrics.csv"
    _metric_csv(source)
    manifest = extract_result_tables(
        paths,
        launched.run_dir,
        source_csv=source,
    )

    result = extract_result(
        paths,
        launched.run_dir,
        payload={
            "protocol": {"name": "paired-four-query-example"},
            "measurements": {"loss": 0.25},
            "verdict": "PASS",
            "validity": "VALID",
            "supported_claims": [
                "q1 repair and q2 harm cancel, so paired delta is 0 pp."
            ],
            "unsupported_claims": [],
        },
        result_table_manifest=manifest,
    )

    assert [table["id"] for table in result["result_tables"]] == [
        "effectiveness",
        "comparison",
    ]
    assert result["result_table_manifest_uri"].endswith(
        "files/result-tables/manifest.json"
    )
    assert any(
        ref["uri"].endswith("files/all_metrics.csv")
        for ref in result["evidence"]
    )
    projected = package_view_models(
        EventStore(paths).state(),
        paths=paths,
    )[0]["resultBlocks"][0]
    assert [table["type"] for table in projected["tables"]] == [
        "main",
        "ablation",
    ]
    main = projected["tables"][0]
    assert main["state"] == "verified"
    assert main["rows"][0]["initial-r1"] == 50
    assert main["rows"][0]["final-r1"] == 50
    assert main["rows"][0]["repair-r1"] == 50
    assert main["rows"][0]["harm-r1"] == 50
    assert main["rows"][0]["delta-r1"] == 0


def test_schema_backed_result_cannot_finalize_without_table_manifest(tmp_path):
    paths, launched = _launch(tmp_path, result_schema=RESULT_SCHEMA)

    with pytest.raises(ValueError, match="missing table fields"):
        extract_result(
            paths,
            launched.run_dir,
            payload={
                "protocol": {"name": "missing-table-manifest"},
                "measurements": {"loss": 0.25},
                "verdict": "PASS",
                "validity": "VALID",
                "supported_claims": [],
                "unsupported_claims": [],
            },
        )


def test_result_table_preserves_null_with_an_explicit_reason(tmp_path):
    paths, launched = _launch(tmp_path, result_schema=RESULT_SCHEMA)
    source = launched.run_dir / "files" / "all_metrics.csv"
    _metric_csv(source, undefined_repair=True)
    manifest = extract_result_tables(
        paths,
        launched.run_dir,
        source_csv=source,
    )
    result = extract_result(
        paths,
        launched.run_dir,
        payload={
            "protocol": {"name": "zero-denominator"},
            "measurements": {"loss": 0.25},
            "verdict": "PASS",
            "validity": "VALID",
            "supported_claims": [],
            "unsupported_claims": [],
        },
        result_table_manifest=manifest,
    )
    table = package_view_models(
        EventStore(paths).state(),
        paths=paths,
    )[0]["resultBlocks"][0]["tables"][0]
    assert table["rows"][0]["repair-r1"] is None
    assert table["rows"][0]["_cells"]["repair-r1"] == {
        "status": "UNDEFINED",
        "reason": "initial-wrong denominator is zero",
    }
    assert result["result_schema_sha256"]


def test_required_metric_can_be_explicitly_failed_but_not_silently_missing(
    tmp_path,
):
    paths, launched = _launch(tmp_path, result_schema=RESULT_SCHEMA)
    source = launched.run_dir / "files" / "all_metrics.csv"
    _metric_csv(source, failed_final=True)
    manifest = extract_result_tables(
        paths,
        launched.run_dir,
        source_csv=source,
    )
    result = extract_result(
        paths,
        launched.run_dir,
        payload={
            "protocol": {"name": "explicit-metric-failure"},
            "measurements": {"loss": 0.25},
            "verdict": "INCONCLUSIVE",
            "validity": "PARTIAL",
            "supported_claims": [],
            "unsupported_claims": ["Final R@1 was not measured."],
        },
        result_table_manifest=manifest,
    )
    table = package_view_models(
        EventStore(paths).state(),
        paths=paths,
    )[0]["resultBlocks"][0]["tables"][0]
    assert table["rows"][0]["final-r1"] is None
    assert table["rows"][0]["_cells"]["final-r1"]["status"] == "FAILED"
    assert result["validity"] == "PARTIAL"


@pytest.mark.parametrize(
    ("duplicate", "missing", "wrong_unit", "message"),
    [
        (True, False, False, "expected exactly one source row, got 2"),
        (False, True, False, "expected exactly one source row, got 0"),
        (False, False, True, "unit mismatch"),
    ],
)
def test_result_table_extractor_fails_closed(
    tmp_path,
    duplicate,
    missing,
    wrong_unit,
    message,
):
    paths, launched = _launch(tmp_path, result_schema=RESULT_SCHEMA)
    source = launched.run_dir / "files" / "all_metrics.csv"
    _metric_csv(
        source,
        duplicate=duplicate,
        missing=missing,
        wrong_unit=wrong_unit,
    )

    with pytest.raises(ValueError, match=message):
        extract_result_tables(
            paths,
            launched.run_dir,
            source_csv=source,
        )


def test_extractor_rejects_a_verdict_that_contradicts_the_gate(tmp_path):
    paths, launched = _launch(tmp_path)

    with pytest.raises(CommandRejected, match="contradicts gate"):
        extract_result(
            paths,
            launched.run_dir,
            payload={
                "protocol": {"name": "smoke"},
                "measurements": {"loss": 0.25},
                "verdict": "FAIL",
                "validity": "VALID",
                "supported_claims": [],
                "unsupported_claims": ["The declared gate did not pass."],
            },
        )

    assert not any(
        event["event_type"] == "RunResultFinalized"
        for event in EventStore(paths).events()
        if event["aggregate_id"] == launched.run_id
    )


def test_result_finalization_cannot_replace_terminal_ownership(tmp_path):
    paths, launched = _launch(tmp_path)
    pending = prepare_run(
        paths=paths,
        package_id="pkg",
        experiment_id="P1",
        run_id="not-terminal",
        command=[sys.executable, "-c", "pass"],
        cwd=tmp_path,
    )
    store = EventStore(paths)
    with pytest.raises(CommandRejected, match="earlier RunTerminal"):
        store.commit(
            event_type="RunResultFinalized",
            aggregate_type="run",
            aggregate_id=pending.run_id,
            payload={"result": {}},
            actor=AGENT,
            idempotency_key="illegal-result-finalization",
            expected_version=1,
        )
    assert [
        event["event_type"]
        for event in store.events()
        if event["aggregate_type"] == "run"
        and event["aggregate_id"] == pending.run_id
    ] == ["RunLaunchAuthorized"]
    assert launched.status == "COMPLETED"
