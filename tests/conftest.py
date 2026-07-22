"""Stable test layers selected by behavior, not duplicated test suites."""

from __future__ import annotations

from pathlib import Path

import pytest


CORE_FILES = {
    "tests/experiments/test_launch_policy.py",
    "tests/research-onboard/test_onboard_cli.py",
    "tests/research-package/test_draft_package_lifecycle.py",
    "tests/research_state/test_foundation.py",
    "tests/research_state/test_prompt_budget.py",
    "tests/research_state/test_transaction_kernel.py",
}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        relative = Path(str(item.path)).resolve().relative_to(
            Path(__file__).resolve().parents[1]
        ).as_posix()
        if relative in CORE_FILES or relative.startswith("tests/scenarios/"):
            item.add_marker(pytest.mark.core)
        if (
            relative.startswith("tests/research-dashboard/")
            or "interface_projection" in relative
        ):
            item.add_marker(pytest.mark.projection)
        elif "migration" in relative or relative.startswith("tests/research-init/"):
            item.add_marker(pytest.mark.migration)
        elif (
            relative.startswith("tests/demo/")
            or "parity" in relative
            or "writer_boundaries" in relative
            or "agent_read_boundaries" in relative
        ):
            item.add_marker(pytest.mark.release)
        else:
            item.add_marker(pytest.mark.integration)
