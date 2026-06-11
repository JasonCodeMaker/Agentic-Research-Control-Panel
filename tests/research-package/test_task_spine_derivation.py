import json
import re
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


def _assert_opening_tag_has(html, tag, *attrs):
    for match in re.finditer(rf"<{tag}\b[^>]*>", html):
        opening_tag = match.group(0)
        if all(attr in opening_tag for attr in attrs):
            return
    raise AssertionError(f"missing <{tag}> with attrs: {attrs}")


def _table_body_selectors(html):
    return re.findall(r'data-table-body="([^"]+)"', html)


def test_scaffold_marks_page_projection_surfaces_and_preserves_table_body_selectors(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = _dashboard(tmp_path)
    package_id = "2026-06-11-projection-markers"

    rc = create_research_package.main([
        "--root", str(root),
        "--id", package_id,
        "--name", "Projection Markers",
        "--category", "in-progress",
        "--tag", "facts",
        "--tag-meaning", "fact projection test",
        "--problem", "new packages lack projection anchors",
        "--objective", "mark projection surfaces at scaffold time",
        "--motivation", "lint can find fact-backed sections",
        "--hypothesis", "stable markers prevent projection drift",
        "--primary-metric", "projection-marker coverage",
        "--baseline", "manual markers",
        "--budget", "unmeasured",
        "--no-change-boundary", "do not rename table body selectors",
        "--next-action", "verify scaffold",
        "--scope", "all",
        "--status", "CONTEXT_LOADED",
    ])

    assert rc == 0
    pkg = root / "packages" / package_id
    pages = {
        "index.html": (pkg / "index.html").read_text(encoding="utf-8"),
        "plan.html": (pkg / "plan.html").read_text(encoding="utf-8"),
        "tracker.html": (pkg / "tracker.html").read_text(encoding="utf-8"),
        "results.html": (pkg / "results.html").read_text(encoding="utf-8"),
        "analysis.html": (pkg / "analysis.html").read_text(encoding="utf-8"),
    }

    for filename, page_id in [
        ("index.html", "overview"),
        ("plan.html", "plan"),
        ("tracker.html", "tracker"),
        ("results.html", "results"),
        ("analysis.html", "analysis"),
    ]:
        _assert_opening_tag_has(
            pages[filename],
            "body",
            f'data-page="{page_id}"',
            f'data-package-id="{package_id}"',
        )

    _assert_opening_tag_has(
        pages["index.html"],
        "section",
        'data-section="user-zone"',
        'data-fact-projection="overview"',
    )
    _assert_opening_tag_has(
        pages["plan.html"],
        "section",
        'data-section="pipeline-timeline"',
        'data-fact-projection="plan"',
    )
    _assert_opening_tag_has(
        pages["tracker.html"],
        "section",
        'data-section="user-zone"',
        'data-fact-projection="tracker"',
    )
    _assert_opening_tag_has(
        pages["results.html"],
        "section",
        'data-list="result-blocks"',
        'data-fact-projection="results"',
    )
    _assert_opening_tag_has(
        pages["analysis.html"],
        "section",
        'data-section="rules"',
        'data-fact-projection="analysis"',
    )
    _assert_opening_tag_has(
        pages["analysis.html"],
        "section",
        'data-section="insight"',
        'data-fact-projection="analysis"',
    )

    implementation = (pkg / "implementation.html").read_text(encoding="utf-8")
    assert _table_body_selectors(pages["tracker.html"]) == [
        "live-check",
        "live-check-history",
        "considered-routes",
        "resource-allocation",
    ]
    assert _table_body_selectors(pages["results.html"]) == [
        "result-block-main",
        "result-gate",
    ]
    assert _table_body_selectors(implementation) == ["test-rule-catalog"]


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
    assert 'data-list="result-blocks"' in results
    assert 'data-fact-projection="results"' in results
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
