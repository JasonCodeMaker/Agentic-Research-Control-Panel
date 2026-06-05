"""Step 3 — append-only fold determinism + optimistic concurrency (plan §17.4)."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

from self_evolve import store  # noqa: E402


def _t(eid, ver, frm, to, *, key=None, tid=None):
    return {
        "transition_id": tid or f"trn_{eid}_{ver}_{to}",
        "entity_id": eid, "entity_version": ver,
        "expected_from_state": frm, "to_state": to,
        "idempotency_key": key or f"{eid}:{ver}:{to}",
    }


def test_fresh_version_reads_as_observed():
    assert store.current_state([], "rule.x", "1.0.0") == "observed"


def test_append_then_fold(tmp_path):
    log = tmp_path / "transitions.jsonl"
    store.append_transition(log, _t("rule.x", "1.0.0", "observed", "candidate"))
    store.append_transition(log, _t("rule.x", "1.0.0", "candidate", "validating"))
    assert store.current_state(store.read_log(log), "rule.x", "1.0.0") == "validating"


def test_concurrency_conflict_rejects_before_write(tmp_path):
    log = tmp_path / "transitions.jsonl"
    store.append_transition(log, _t("rule.x", "1.0.0", "observed", "candidate"))
    # stale expected_from_state (still thinks it's observed)
    with pytest.raises(store.ConcurrencyConflict):
        store.append_transition(log, _t("rule.x", "1.0.0", "observed", "validating"))
    # nothing extra was written
    assert len(store.read_log(log)) == 1


def test_idempotent_skip_does_not_double_append(tmp_path):
    log = tmp_path / "transitions.jsonl"
    store.append_transition(log, _t("rule.x", "1.0.0", "observed", "candidate"))
    rec, skipped = store.append_transition(log, _t("rule.x", "1.0.0", "observed", "candidate"))
    assert skipped is True
    assert len(store.read_log(log)) == 1


def test_duplicate_delivery_in_log_is_deduped_in_fold():
    # same transition_id appears twice (at-least-once delivery)
    recs = [_t("rule.x", "1.0.0", "observed", "candidate", tid="trn_1"),
            _t("rule.x", "1.0.0", "observed", "candidate", tid="trn_1")]
    assert store.fold(recs) == {("rule.x", "1.0.0"): "candidate"}


def test_independent_entities_fold_order_independent():
    a1 = _t("rule.a", "1.0.0", "observed", "candidate", tid="a1")
    a2 = _t("rule.a", "1.0.0", "candidate", "validating", tid="a2")
    b1 = _t("rule.b", "1.0.0", "observed", "candidate", tid="b1")
    interleavings = [[a1, b1, a2], [b1, a1, a2], [a1, a2, b1]]
    folds = [store.fold(seq) for seq in interleavings]
    assert all(f == folds[0] for f in folds)
    assert folds[0] == {("rule.a", "1.0.0"): "validating", ("rule.b", "1.0.0"): "candidate"}


def test_active_version_lookup(tmp_path):
    log = tmp_path / "transitions.jsonl"
    for frm, to in [("observed", "candidate"), ("candidate", "validating"),
                    ("validating", "provisional"), ("provisional", "active")]:
        store.append_transition(log, _t("rule.x", "2.1.0", frm, to))
    assert store.active_version(store.read_log(log), "rule.x") == "2.1.0"
