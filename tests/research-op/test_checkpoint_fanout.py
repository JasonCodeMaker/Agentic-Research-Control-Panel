import sys

sys.path.insert(0, "skills/research-op/scripts")
import events


def test_checkpoint_saved_fanout_inserts_tracker_rows_and_preserves_mapping():
    calls = []

    def dispatch(op, pkg, target, payload):
        calls.append((op, pkg, target, payload))
        return "PASSED", [f"{op}:{target}"]

    payload = {
        "exp_id": "P1",
        "artifact": "var/research/run/P1/checkpoint.pt",
        "measured": "Recall@1=0.42",
    }

    validation, files = events.fanout("CHECKPOINT_SAVED", "test-pkg", payload, dispatch)

    assert validation == "PASSED"
    assert files == [
        "insert:tracker-live-check-row",
        "insert:tracker-resource-allocation-row",
        "insert:results-gate-row",
        "update:results-verdict",
        "update:experiments-status",
        "update:last-updated-time",
        "update:last-updated-time",
    ]
    assert [(op, target) for op, _, target, _ in calls] == [
        ("insert", "tracker-live-check-row"),
        ("insert", "tracker-resource-allocation-row"),
        ("insert", "results-gate-row"),
        ("update", "results-verdict"),
        ("update", "experiments-status"),
        ("update", "last-updated-time"),
        ("update", "last-updated-time"),
    ]
    assert [pkg for _, pkg, _, _ in calls] == ["test-pkg"] * 7
    assert calls[0][3] == {
        "exp_id": "P1",
        "run_state": "COMPLETED",
        "metrics": "Recall@1=0.42",
    }
    assert calls[1][3] == {"exp_id": "P1", "status": "COMPLETED"}
    assert calls[2][3]["exp_id"] == "P1"
    assert calls[2][3]["observed_metric"] == "Recall@1=0.42"
    assert calls[3][3] == {"exp_id": "P1", "measured": "Recall@1=0.42", "to": "PASS"}
    assert calls[4][3] == {"id": "P1", "to": "COMPLETED"}
    assert calls[5][3] == {"page": "tracker.html"}
    assert calls[6][3] == {"page": "results.html"}
    assert payload == {
        "exp_id": "P1",
        "artifact": "var/research/run/P1/checkpoint.pt",
        "measured": "Recall@1=0.42",
    }


def test_checkpoint_saved_fanout_skips_legacy_verdict_update_for_fact_backed_packages(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pkg = "fact-pkg"
    (tmp_path / "research_html" / "data" / "packages" / pkg).mkdir(parents=True)
    calls = []

    def dispatch(op, pkg, target, payload):
        calls.append((op, target, payload))
        return "PASSED", [f"{op}:{target}"]

    validation, files = events.fanout(
        "CHECKPOINT_SAVED",
        pkg,
        {
            "exp_id": "P1",
            "artifact": "var/research/run/P1/checkpoint.pt",
            "measured": "Recall@1=0.42",
        },
        dispatch,
    )

    assert validation == "PASSED"
    assert "insert:results-gate-row" in files
    assert ("update", "results-verdict") not in [(op, target) for op, target, _ in calls]
    assert [target for _, target, _ in calls] == [
        "tracker-live-check-row",
        "tracker-resource-allocation-row",
        "results-gate-row",
        "experiments-status",
    ]
