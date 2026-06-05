"""Stage-2b: R3 ideate banlist is scope-conditional — blocked under the same scope, reopened on a metric revise."""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "lib"))
sys.path.insert(0, str(_ROOT / "skills" / "research-ideate" / "scripts"))
import scope_ssot  # noqa: E402
import banlist  # noqa: E402


def test_banlisted_idea_not_reproposed():
    bl = [{"id": "i1", "kind": "idea", "failed_on_metric": "Recall@10", "scope_version": 1}]
    assert banlist.allowed(["i1", "i2"], bl) == ["i2"]  # i1 stays banned under the same scope


def test_idea_reopened_after_metric_revise():
    bl = [{"id": "i1", "kind": "idea", "failed_on_metric": "Recall@10", "scope_version": 1}]
    # a direction-level metric revise Recall@10 -> nDCG@10 reopens ideas that failed only on Recall@10
    out = scope_ssot.propagate(old_metric="Recall@10", new_metric="nDCG@10", memory=bl)
    bl2 = banlist.apply_reopen(bl, out["reopen"])
    assert banlist.allowed(["i1", "i2"], bl2) == ["i1", "i2"]  # i1 is viable again
