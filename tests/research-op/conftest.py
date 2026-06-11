import json
from pathlib import Path

import pytest


@pytest.fixture
def tmp_package(tmp_path, monkeypatch):
    """Build a minimal research_html/ + outputs/ tree in tmp_path."""
    root = tmp_path / "research_html"
    (root / "packages" / "test-pkg").mkdir(parents=True)
    (root / "packages" / "test-pkg" / "index.html").write_text("<html></html>")
    (root / "packages" / "test-pkg" / "results.html").write_text("<html></html>")
    (root / "data").mkdir()
    (root / "data" / "research-packages.js").write_text(
        "const RESEARCH_PACKAGES = [\n"
        "  { id: 'test-pkg', category: 'in-progress', status: 'CONTEXT_LOADED' },\n"
        "];\n"
    )
    (root / "scripts").mkdir()
    (root / "scripts" / "learnings_lint.py").write_text("#!/usr/bin/env python3\nimport sys\nsys.exit(0)\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RESEARCH_RUNTIME_ROOT", str(tmp_path / "outputs"))
    return tmp_path
