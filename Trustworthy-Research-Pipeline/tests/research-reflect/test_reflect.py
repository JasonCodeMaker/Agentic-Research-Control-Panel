"""Stage-3: research-reflect observes the corpus read-only, detects doom-loops / scope-thrash, and
stages proposals under pending/ — it never writes the live rules."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "research-reflect" / "scripts"))
import reflect  # noqa: E402


def _fail(rule):
    return {"op": "update", "target": "status", "rule": rule, "validation": "rejected"}


def test_doom_loop_detected():
    actions = [_fail("acquit-needs-verdict")] * 4
    findings = reflect.detect_doom_loop(actions, threshold=3)
    assert findings and findings[0]["kind"] == "doom-loop"


def test_cross_package_dead_end_detected_above_threshold():
    cross = [
        {"method": "mining", "hypothesis": "h", "packages": ["a", "b", "c"], "count": 3},
        {"method": "rerank", "hypothesis": "h", "packages": ["a"], "count": 1},
    ]
    out = reflect.detect_cross_package_dead_end(cross, threshold=2)
    assert len(out) == 1
    assert out[0]["kind"] == "cross-package-dead-end"
    assert out[0]["method"] == "mining"
    assert out[0]["count"] == 3


def test_cross_package_dead_end_silent_below_threshold():
    cross = [{"method": "mining", "hypothesis": "h", "packages": ["a"], "count": 1}]
    assert reflect.detect_cross_package_dead_end(cross, threshold=2) == []


def test_no_doom_loop_below_threshold():
    actions = [_fail("acquit-needs-verdict")] * 2
    assert reflect.detect_doom_loop(actions, threshold=3) == []


def test_scope_thrash_detected():
    transitions = [{"node_id": "dir/x", "op": "revise"} for _ in range(4)]
    findings = reflect.detect_scope_thrash(transitions, threshold=3)
    assert findings and findings[0]["kind"] == "scope-thrash" and findings[0]["node_id"] == "dir/x"


def test_propose_stages_without_touching_live_rules(tmp_path):
    pending = tmp_path / "pending"
    rules = tmp_path / "project-rules.md"
    rules.write_text("# rules\n", encoding="utf-8")
    pid = reflect.propose(pending, {"kind": "doom-loop"}, suggested_diff="cap retries at 3")
    assert (pending / pid / "proposal.json").exists()
    assert rules.read_text() == "# rules\n"  # the proposer never mutates the live corpus
