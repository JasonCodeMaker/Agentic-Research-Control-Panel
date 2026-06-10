"""Check op — read-only audit."""

import subprocess
from pathlib import Path


def handle(pkg: str, target: str | None, payload: dict, state: dict) -> tuple[str, list[str]]:
    """Run the relevant subset of learnings_lint.py for `scope`."""
    scope = payload.get("scope", "all")
    files_inspected: list[str] = []
    lint_args = ["python3", "research_html/scripts/learnings_lint.py"]
    if scope == "all":
        lint_args.append("all")
    else:
        lint_args += ["lint-status", "--pkg", pkg]
    r = subprocess.run(lint_args, capture_output=True, text=True)
    if r.returncode != 0:
        # Non-zero is informational here; check never writes, just reports.
        return "OP_REJECTED", files_inspected
    files_inspected.append(f"research_html/packages/{pkg}/")
    if scope == "all":
        files_inspected.append("research_html/data/research-packages.js")
    return "PASSED", files_inspected
