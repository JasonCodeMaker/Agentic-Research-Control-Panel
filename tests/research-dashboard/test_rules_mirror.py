"""rules.js is a disposable view over bundled universal cards plus state rules."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from lib.interface import build_interface  # noqa: E402
from lib.research_state import EventStore, ResearchPaths  # noqa: E402


ACTOR = {"type": "agent", "id": "rules-projection-test"}


def _workspace(tmp_path):
    paths = ResearchPaths.resolve(workspace=tmp_path)
    store = EventStore(paths)
    store.initialize()
    build_interface(paths)
    return paths, store


def _load(root):
    text = (root / "data" / "rules.js").read_text()
    return json.loads(text[len("window.RESEARCH_RULES = ") :].rstrip().rstrip(";"))


def test_build_writes_rules_js_with_universal_mirror(tmp_path):
    paths, _ = _workspace(tmp_path)
    rules = _load(paths.interface)
    ids = {row["id"] for row in rules}
    assert {"R1", "R18", "T1", "T24"} <= ids
    r1 = next(row for row in rules if row["id"] == "R1")
    assert r1["level"] == "universal" and r1["origin"] == "mirror"
    assert r1["kind"] == "form" and r1["source"] == "rules/html-rules.html#R1"
    assert r1["title"]
    t1 = next(row for row in rules if row["id"] == "T1")
    assert t1["kind"] == "trust"
    assert t1["source"] == "rules/trustworthy-research-rules.html#T1"


def test_rebuild_projects_non_mirror_rule_from_state(tmp_path):
    paths, store = _workspace(tmp_path)
    store.commit(
        event_type="AggregateUpserted",
        aggregate_type="rule",
        aggregate_id="PRJ-x",
        payload={
            "record": {
                "id": "PRJ-x",
                "level": "project",
                "kind": "constraint",
                "title": "Project constraint",
                "status": "ACTIVE",
                "origin": "user",
            }
        },
        actor=ACTOR,
        idempotency_key="rules-projection:project-rule",
    )

    build_interface(paths)
    after = _load(paths.interface)
    assert any(row["id"] == "PRJ-x" for row in after)
    assert any(row["id"] == "R1" for row in after)


def test_complete_rebuild_refreshes_chrome_and_rejects_interface_authority(tmp_path):
    paths, _ = _workspace(tmp_path)
    (paths.interface / "assets" / "research.js").write_text("// stale chrome")
    (paths.interface / "data" / "research-packages.js").write_text(
        "window.RESEARCH_PACKAGES = [{ id: 'forged' }];\n"
    )

    build_interface(paths)

    assert "stale chrome" not in (
        paths.interface / "assets" / "research.js"
    ).read_text()
    assert "forged" not in (
        paths.interface / "data" / "research-packages.js"
    ).read_text()


def test_malformed_interface_rules_registry_is_rebuilt_from_state(tmp_path):
    paths, _ = _workspace(tmp_path)
    bad = "window.BAD_RULES = [{ id: 'forged' }];\n"
    (paths.interface / "data" / "rules.js").write_text(bad)

    build_interface(paths)

    rebuilt = (paths.interface / "data" / "rules.js").read_text()
    assert rebuilt != bad
    assert "window.RESEARCH_RULES" in rebuilt
    assert any(row["id"] == "R1" for row in _load(paths.interface))
