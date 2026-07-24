from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "research-run" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "research-op" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import implementation_status  # noqa: E402
import driver  # noqa: E402
import management  # noqa: E402
from lib.interface.package import package_view_models  # noqa: E402
from lib.research_state import EventStore  # noqa: E402
from state_fixtures import CANONICAL_EXPERIMENT_ID, seed  # noqa: E402


ACTOR = {"type": "agent", "id": "implementation-test"}


def _planned_change(paths):
    return management.commit_change_operation(
        paths,
        "pkg-1",
        "insert",
        {
            "change_id": "add-module",
            "order": 1,
            "title": "Add the planned module",
            "validating_experiments": ["P1"],
            "plan": {
                "how_it_changes": "Add one deterministic module.",
                "code_locations": [
                    {
                        "id": "module",
                        "action": "ADD",
                        "path": "src/new_module.py",
                    }
                ],
                "verifications": [
                    {
                        "id": "module-content",
                        "label": "The module contains the expected value.",
                        "depends_on": ["module"],
                        "command": [
                            sys.executable,
                            "-c",
                            (
                                "from pathlib import Path; "
                                "assert Path('src/new_module.py').read_text() "
                                "== 'VALUE = 1\\n'"
                            ),
                        ],
                    }
                ],
            },
        },
        actor=ACTOR,
    )


def test_sync_tracks_code_and_invalidates_stale_verification(tmp_path):
    paths = seed(tmp_path, phase="IMPLEMENTING", vnext=True)
    _planned_change(paths)

    initial = implementation_status.synchronize(paths, "pkg-1")
    assert initial["changes"][0]["code_complete"] == 0
    assert initial["changes"][0]["verification_passed"] == 0
    initial_snapshot = driver.load_workflow_snapshot(paths, "pkg-1")
    assert initial_snapshot["experiments"][0]["implementationReadiness"] == "BLOCKED"
    assert initial_snapshot["experiments"][0]["currentChangeId"] == "add-module"
    initial_tracker = package_view_models(EventStore(paths).state())[0]["tracker"]
    assert initial_tracker["currentTaskId"] == "change:add-module"
    assert initial_tracker["totalTasks"] == 2
    assert initial_tracker["experiments"][0]["tasks"][0]["state"] == "CURRENT"
    assert initial_tracker["experiments"][0]["tasks"][0]["complete"] is False

    source = tmp_path / "src" / "new_module.py"
    source.parent.mkdir()
    source.write_text("VALUE = 1\n", encoding="utf-8")
    after_edit = implementation_status.synchronize(paths, "pkg-1")
    assert after_edit["changes"][0]["code_complete"] == 1
    assert after_edit["changes"][0]["verification_passed"] == 0

    verified = implementation_status.synchronize(
        paths,
        "pkg-1",
        run_verifications=True,
    )
    assert verified["complete"] is True
    projected_change = package_view_models(EventStore(paths).state())[0][
        "implementation"
    ]["changes"][0]
    assert projected_change["codeLocations"][0]["state"] == "PASS"
    assert projected_change["verifications"][0]["state"] == "PASS"
    assert projected_change["howItChanges"] == "Add one deterministic module."
    ready_snapshot = driver.load_workflow_snapshot(paths, "pkg-1")
    assert ready_snapshot["experiments"][0]["implementationReadiness"] == "PASS"
    ready_tracker = package_view_models(EventStore(paths).state())[0]["tracker"]
    assert ready_tracker["currentTaskId"] == "execute:P1"
    assert ready_tracker["experiments"][0]["tasks"][0]["complete"] is True
    assert ready_tracker["experiments"][0]["tasks"][1]["state"] == "CURRENT"

    source.write_text("VALUE = 2\n", encoding="utf-8")
    stale = implementation_status.synchronize(paths, "pkg-1")
    assert stale["changes"][0]["code_complete"] == 1
    assert stale["changes"][0]["verification_passed"] == 0
    change = EventStore(paths).state()["aggregates"]["change"][
        "pkg-1::change::add-module"
    ]
    assert change["validating_experiments"] == [CANONICAL_EXPERIMENT_ID]
    assert change["observations"]["verifications"]["module-content"]["state"] == (
        "STALE"
    )


def test_change_gateway_freezes_baseline_before_edit(tmp_path):
    paths = seed(tmp_path, phase="IMPLEMENTING", vnext=True)
    existing = tmp_path / "src" / "existing.py"
    existing.parent.mkdir()
    existing.write_text("already here\n", encoding="utf-8")

    try:
        management.commit_change_operation(
            paths,
            "pkg-1",
            "insert",
            {
                "change_id": "misclassified-add",
                "order": 1,
                "title": "Misclassified add",
                "validating_experiments": ["P1"],
                "plan": {
                    "how_it_changes": "Incorrectly label an existing file.",
                    "code_locations": [
                        {
                            "id": "existing",
                            "action": "ADD",
                            "path": "src/existing.py",
                            "baseline": {
                                "kind": "MISSING",
                                "fingerprint": "0" * 64,
                            },
                        }
                    ],
                    "verifications": [
                        {
                            "id": "exists",
                            "label": "Existing file is valid.",
                        }
                    ],
                },
            },
            actor=ACTOR,
        )
    except Exception as exc:
        assert getattr(exc, "rule", "") == "change-plan-invalid"
        assert "already exists" in str(exc)
    else:
        raise AssertionError("ADD must not accept a pre-existing path")


def test_launch_readiness_rejects_stale_checkbox_state(tmp_path):
    paths = seed(tmp_path, phase="IMPLEMENTATION_REVIEW", vnext=True)
    source = tmp_path / "src" / "ready.py"
    source.parent.mkdir()
    source.write_text("READY = True\n", encoding="utf-8")
    management.commit_change_operation(
        paths,
        "pkg-1",
        "insert",
        {
            "change_id": "launch-review",
            "order": 1,
            "title": "Review the ready implementation",
            "validating_experiments": ["P1"],
            "review": {
                "producer": "producer",
                "judge": "independent-judge",
                "result": "SOUND",
            },
            "plan": {
                "how_it_changes": "Reuse the reviewed module.",
                "code_locations": [
                    {
                        "id": "ready-module",
                        "action": "REUSE",
                        "path": "src/ready.py",
                    }
                ],
                "verifications": [
                    {
                        "id": "ready-check",
                        "label": "The module is ready.",
                        "command": [
                            sys.executable,
                            "-c",
                            "from src.ready import READY; assert READY",
                        ],
                    }
                ],
            },
        },
        actor=ACTOR,
    )

    try:
        management.apply_package_operation(
            paths,
            "pkg-1",
            operation="update",
            target="status",
            payload={
                "to": "READY_TO_LAUNCH",
                "review_change_id": "launch-review",
            },
            actor=ACTOR,
        )
    except Exception as exc:
        assert getattr(exc, "rule", "") == "implementation-status-stale"
    else:
        raise AssertionError("launch must reject unsynchronized checkbox state")

    result = implementation_status.synchronize(
        paths,
        "pkg-1",
        run_verifications=True,
    )
    assert result["complete"] is True
    management.apply_package_operation(
        paths,
        "pkg-1",
        operation="update",
        target="status",
        payload={
            "to": "READY_TO_LAUNCH",
            "review_change_id": "launch-review",
        },
        actor=ACTOR,
    )
    assert EventStore(paths).state()["aggregates"]["package"]["pkg-1"]["phase"] == (
        "READY_TO_LAUNCH"
    )
