"""E3 draft reads tracker.html#chosen-route (folded canon), with legacy next-action fallback."""

import sys
from pathlib import Path

SCRIPTS = (Path(__file__).resolve().parents[2]
           / "skills" / "research-dashboard" / "assets" / "dashboard" / "scripts")
sys.path.insert(0, str(SCRIPTS))
import learnings_lint  # noqa: E402

TRACKER_TERMINAL = """<html><body>
<div data-route data-field="chosen-route">archive_or_stop</div>
<div data-field="chosen-route-reason">metric never cleared the gate after 3 seeds</div>
</body></html>"""

TRACKER_NONTERMINAL = """<html><body>
<div data-route data-field="chosen-route">run_next_experiment_from_step4</div>
<div data-field="chosen-route-reason">next sweep cell</div>
</body></html>"""

LEGACY_NEXT_ACTION = """<html><body>
<div data-field="route">archive_or_stop</div>
<div data-field="reason">done</div>
</body></html>"""


def _pkg(tmp_path, monkeypatch, pid, html, fname="tracker.html",
         cat="in-progress", status="NEXT_ACTION_READY"):
    pdir = tmp_path / pid
    pdir.mkdir(parents=True)
    (pdir / fname).write_text(html, encoding="utf-8")
    monkeypatch.setattr(learnings_lint, "PACKAGES_DIR", tmp_path)
    return {"id": pid, "category": cat, "status": status}


def test_e3_reads_tracker_chosen_route(tmp_path, monkeypatch):
    pkg = _pkg(tmp_path, monkeypatch, "2026-01-01-x", TRACKER_TERMINAL)
    e3 = learnings_lint.detect_e3(pkg)
    assert e3 is not None
    assert e3["suggested_category"] == "fail"
    assert e3["suggested_status"] == "ARCHIVED"


def test_e3_none_when_route_not_terminal(tmp_path, monkeypatch):
    pkg = _pkg(tmp_path, monkeypatch, "2026-01-01-y", TRACKER_NONTERMINAL)
    assert learnings_lint.detect_e3(pkg) is None


def test_e3_falls_back_to_legacy_next_action(tmp_path, monkeypatch):
    pkg = _pkg(tmp_path, monkeypatch, "2026-01-01-z", LEGACY_NEXT_ACTION, fname="next-action.html")
    e3 = learnings_lint.detect_e3(pkg)
    assert e3 is not None
    assert e3["suggested_category"] == "fail"
