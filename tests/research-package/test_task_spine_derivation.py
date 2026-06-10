import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "research-package" / "scripts"))

import create_research_package  # noqa: E402


def _dashboard(tmp_path):
    root = tmp_path / "research_html"
    (root / "data").mkdir(parents=True)
    (root / "data" / "research-packages.js").write_text(
        "window.RESEARCH_PACKAGES = [];\n", encoding="utf-8")
    return root


def _experiments():
    return [
        {
            "id": "P0",
            "purpose": "Verify baseline",
            "after": [],
            "output": "outputs/pkg/P0/result.json",
            "gate": "Recall@1 >= 42",
            "status": "queued",
            "measures": True,
            "requiresCode": False,
            "complex": False,
        },
        {
            "id": "P1",
            "purpose": "Train reranker",
            "after": ["P0"],
            "output": "outputs/pkg/P1/result.json",
            "gate": "Recall@1 >= 48",
            "status": "queued",
            "measures": True,
            "requiresCode": True,
            "complex": True,
            "docsAnchor": "docs/pipeline.html#p1",
        },
        {
            "id": "P2",
            "purpose": "Stage features",
            "after": ["P0"],
            "output": "outputs/pkg/P2/features.tar",
            "gate": "archive exists",
            "status": "queued",
            "measures": False,
            "requiresCode": False,
            "complex": False,
        },
    ]


def test_scaffold_derives_task_blocks_from_spine(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = _dashboard(tmp_path)

    rc = create_research_package.main([
        "--root", str(root),
        "--id", "2026-06-10-task-spine",
        "--name", "Task Spine",
        "--category", "in-progress",
        "--tag", "spine",
        "--tag-meaning", "task spine test",
        "--problem", "manual packages drift",
        "--objective", "derive task blocks",
        "--motivation", "alignment at birth",
        "--hypothesis", "typed spine prevents drift",
        "--primary-metric", "alignment violations",
        "--baseline", "manual scaffold",
        "--budget", "unmeasured",
        "--no-change-boundary", "no unrelated surfaces",
        "--next-action", "verify alignment",
        "--scope", "all",
        "--status", "CONTEXT_LOADED",
        "--experiments", json.dumps(_experiments()),
    ])

    assert rc == 0
    pkg = root / "packages" / "2026-06-10-task-spine"
    results = (pkg / "results.html").read_text(encoding="utf-8")
    implementation = (pkg / "implementation.html").read_text(encoding="utf-8")
    tracker = (pkg / "tracker.html").read_text(encoding="utf-8")
    docs = (pkg / "docs" / "pipeline.html").read_text(encoding="utf-8")

    assert results.count('data-exp-id="P0"') >= 2
    assert results.count('data-exp-id="P1"') >= 2
    assert 'data-field="exp-id">P2<' not in results
    assert 'data-table="result-slot-P0"' in results
    assert 'data-table="result-slot-P1"' in results
    assert 'data-table="result-slot-P2"' not in results
    assert 'data-exp-id="P1"' in implementation
    assert 'data-field="validating-exp">P1<' in implementation
    assert '<h3 id="p1" data-exp-id="P1">P1</h3>' in docs
    assert 'data-exp-id="P0"' in tracker
    assert 'data-exp-id="P1"' in tracker
    assert 'data-exp-id="P2"' in tracker

    # Re-running derivation is idempotent: no duplicate rows/cards appear.
    create_research_package.derive_task_blocks(pkg, _experiments())
    assert (pkg / "results.html").read_text(encoding="utf-8").count('data-table="result-slot-P1"') == 1
    assert (pkg / "implementation.html").read_text(encoding="utf-8").count('data-field="validating-exp">P1<') == 1
    assert (pkg / "tracker.html").read_text(encoding="utf-8").count('data-exp-id="P1"') == 1

