"""Stage-1 walking skeleton gate: the thin idea->verified-result loop composes end-to-end through the real gates."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "research-auto" / "scripts"))
import skeleton  # noqa: E402

INTENT = "contrastive pretraining improves recall"


def _citations(tmp_path, fabricated):
    real = tmp_path / "src_real.txt"
    real.write_text("real source", encoding="utf-8")
    cites = [{"id": "real2026", "source": str(real)}]
    if fabricated:
        cites.append({"id": "fake2026", "source": str(tmp_path / "does_not_exist.txt")})
    return cites


def test_walking_skeleton_smoke(tmp_path):
    r = skeleton.run(INTENT, pkg_id="2026-skeleton", runtime_root=tmp_path,
                     citations=_citations(tmp_path, fabricated=False), measured=0.9)
    # all six roles fired, in order
    assert [c.split(":")[0] for c in r["chain"]] == ["R1", "R2", "R3", "R4", "R5", "R6"]
    # the yardstick was read from the SSOT node, not invented
    assert r["yardstick"]["success_predicate"] == "measured >= 0.80"
    assert r["verdict"]["result"] == "PASS"
    assert r["acquitted"] is True
    assert r["ack_token"] == "T1:supervised-ack"
    # the scope write landed as an append-only transition in the SSOT log
    log = [json.loads(line) for line
           in (tmp_path / "_scope" / "transitions.jsonl").read_text().splitlines() if line.strip()]
    assert log[0]["node_id"] == "dir/2026-skeleton"
    assert log[0]["op"] == "create"


def test_fabricated_citation_rejected_by_r2(tmp_path):
    r = skeleton.run(INTENT, pkg_id="2026-skeleton", runtime_root=tmp_path,
                     citations=_citations(tmp_path, fabricated=True), measured=0.9)
    assert "real2026" in r["verified_citations"]   # grounded source survives
    assert "fake2026" in r["rejected_citations"]    # fabricated source rejected by R2 cite-exists
    assert "fake2026" not in r["verified_citations"]


def test_metric_miss_blocks_acquit(tmp_path):
    r = skeleton.run(INTENT, pkg_id="2026-skeleton", runtime_root=tmp_path,
                     citations=_citations(tmp_path, fabricated=False), measured=0.5)
    assert r["verdict"]["result"] == "FAIL"
    assert r["acquitted"] is False       # metric oracle blocks the terminal success transition
    assert r["ack_token"] is None
