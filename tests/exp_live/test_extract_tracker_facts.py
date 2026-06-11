import csv
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills" / "research-exp-live" / "scripts" / "extract_tracker_facts.py"


def _write_status(root: Path, payload: dict) -> Path:
    status = root / "outputs" / "2026-06-11-demo" / "runs" / "P1-r1" / "status.json"
    status.parent.mkdir(parents=True)
    status.write_text(json.dumps(payload), encoding="utf-8")
    return status


def _run_extractor(root: Path, status: Path) -> subprocess.CompletedProcess[str]:
    assert SCRIPT.exists(), "extractor script is missing"
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo-root",
            str(root),
            "--status",
            str(status.relative_to(root)),
            "--agent",
            "codex",
            "--live-action",
            "CONTINUE_RUN",
            "--next-check",
            "2026-06-11T10:30:00+10:00",
        ],
        capture_output=True,
        text=True,
    )


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_extracts_live_check_and_resource_rows_from_status_json(tmp_path):
    status = _write_status(
        tmp_path,
        {
            "run_id": "P1-r1",
            "pkg": "2026-06-11-demo",
            "exp_id": "P1",
            "status": "RUNNING",
            "progress": {"epoch": 2, "total": 10, "percent": 20},
            "latest_metrics": {"Recall@1": 42.1},
            "source_map": {"Recall@1": "outputs/2026-06-11-demo/runs/P1-r1/eval.json"},
            "resource": {"gpu": "0", "mem_gb": 19.5},
            "eta": "unknown",
            "last_output_at": 1781139600,
            "started_at": 1781136000,
        },
    )

    result = _run_extractor(tmp_path, status)

    assert result.returncode == 0, result.stderr + result.stdout
    tables_dir = tmp_path / "research_html" / "data" / "packages" / "2026-06-11-demo" / "tables"
    live_rows = _read_rows(tables_dir / "live_checks.csv")
    resource_rows = _read_rows(tables_dir / "resource_allocation.csv")

    assert live_rows == [
        {
            "row_id": "P1:P1-r1",
            "time": "2026-06-11T11:00:00+10:00",
            "exp_id": "P1",
            "run_id": "P1-r1",
            "agent": "codex",
            "run_state": "RUNNING",
            "last_log": "2026-06-11T11:00:00+10:00",
            "progress": '{"epoch":2,"percent":20,"total":10}',
            "metrics": '{"Recall@1":42.1}',
            "resource": '{"gpu":"0","mem_gb":19.5}',
            "artifacts": '{"Recall@1":"outputs/2026-06-11-demo/runs/P1-r1/eval.json"}',
            "eta": "unknown",
            "action": "CONTINUE_RUN",
            "next_check": "2026-06-11T10:30:00+10:00",
            "source_artifact": "outputs/2026-06-11-demo/runs/P1-r1/status.json",
            "source_mtime": live_rows[0]["source_mtime"],
            "extractor": "extract_tracker_facts.py",
            "extracted_at": live_rows[0]["extracted_at"],
        }
    ]
    assert live_rows[0]["source_mtime"]
    assert live_rows[0]["extracted_at"]

    assert resource_rows == [
        {
            "row_id": "P1:P1-r1",
            "exp_id": "P1",
            "purpose": "",
            "dependency": "",
            "target": "",
            "capacity": '{"gpu":"0","mem_gb":19.5}',
            "assigned": "",
            "reason": "",
            "agent": "codex",
            "command_cwd_env": "",
            "session_job": "",
            "runtime_root": "outputs/2026-06-11-demo/runs/P1-r1",
            "log_path": "",
            "expected_duration": "",
            "status": "RUNNING",
            "source_artifact": "outputs/2026-06-11-demo/runs/P1-r1/status.json",
            "source_mtime": resource_rows[0]["source_mtime"],
            "extractor": "extract_tracker_facts.py",
            "extracted_at": resource_rows[0]["extracted_at"],
        }
    ]
    assert resource_rows[0]["source_mtime"]
    assert resource_rows[0]["extracted_at"]


def test_missing_status_json_fails_closed_without_writing_csv(tmp_path):
    status = tmp_path / "outputs" / "2026-06-11-demo" / "runs" / "P1-r1" / "status.json"

    result = _run_extractor(tmp_path, status)

    assert result.returncode == 2
    assert "status.json" in result.stderr
    assert not (
        tmp_path
        / "research_html"
        / "data"
        / "packages"
        / "2026-06-11-demo"
        / "tables"
        / "live_checks.csv"
    ).exists()
    assert not (
        tmp_path
        / "research_html"
        / "data"
        / "packages"
        / "2026-06-11-demo"
        / "tables"
        / "resource_allocation.csv"
    ).exists()


def test_malformed_status_json_fails_closed_without_writing_csv(tmp_path):
    status = tmp_path / "outputs" / "2026-06-11-demo" / "runs" / "P1-r1" / "status.json"
    status.parent.mkdir(parents=True)
    status.write_text("{not-json", encoding="utf-8")

    result = _run_extractor(tmp_path, status)

    assert result.returncode == 2
    assert "status.json" in result.stderr
    tables_dir = tmp_path / "research_html" / "data" / "packages" / "2026-06-11-demo" / "tables"
    assert not (tables_dir / "live_checks.csv").exists()
    assert not (tables_dir / "resource_allocation.csv").exists()
