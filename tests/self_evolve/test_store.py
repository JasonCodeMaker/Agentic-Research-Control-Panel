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
    assert store.current_state([], "rule.x", "1.0.0") == "OBSERVED"


def test_append_then_fold(tmp_path):
    log = tmp_path / "transitions.jsonl"
    store.append_transition(log, _t("rule.x", "1.0.0", "OBSERVED", "CANDIDATE"))
    store.append_transition(log, _t("rule.x", "1.0.0", "CANDIDATE", "VALIDATING"))
    assert store.current_state(store.read_log(log), "rule.x", "1.0.0") == "VALIDATING"


def test_concurrency_conflict_rejects_before_write(tmp_path):
    log = tmp_path / "transitions.jsonl"
    store.append_transition(log, _t("rule.x", "1.0.0", "OBSERVED", "CANDIDATE"))
    # stale expected_from_state (still thinks it's OBSERVED)
    with pytest.raises(store.ConcurrencyConflict):
        store.append_transition(log, _t("rule.x", "1.0.0", "OBSERVED", "VALIDATING"))
    # nothing extra was written
    assert len(store.read_log(log)) == 1


def test_idempotent_skip_does_not_double_append(tmp_path):
    log = tmp_path / "transitions.jsonl"
    store.append_transition(log, _t("rule.x", "1.0.0", "OBSERVED", "CANDIDATE"))
    rec, skipped = store.append_transition(log, _t("rule.x", "1.0.0", "OBSERVED", "CANDIDATE"))
    assert skipped is True
    assert len(store.read_log(log)) == 1


def test_duplicate_delivery_in_log_is_deduped_in_fold():
    # same transition_id appears twice (at-least-once delivery)
    recs = [_t("rule.x", "1.0.0", "OBSERVED", "CANDIDATE", tid="trn_1"),
            _t("rule.x", "1.0.0", "OBSERVED", "CANDIDATE", tid="trn_1")]
    assert store.fold(recs) == {("rule.x", "1.0.0"): "CANDIDATE"}


def test_independent_entities_fold_order_independent():
    a1 = _t("rule.a", "1.0.0", "OBSERVED", "CANDIDATE", tid="a1")
    a2 = _t("rule.a", "1.0.0", "CANDIDATE", "VALIDATING", tid="a2")
    b1 = _t("rule.b", "1.0.0", "OBSERVED", "CANDIDATE", tid="b1")
    interleavings = [[a1, b1, a2], [b1, a1, a2], [a1, a2, b1]]
    folds = [store.fold(seq) for seq in interleavings]
    assert all(f == folds[0] for f in folds)
    assert folds[0] == {("rule.a", "1.0.0"): "VALIDATING", ("rule.b", "1.0.0"): "CANDIDATE"}
