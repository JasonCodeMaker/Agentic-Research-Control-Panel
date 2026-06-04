# Multi-Agent Ranking & Independent-Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port ARIS's multi-agent ranking mechanism into the Trustworthy-Research-Pipeline as a reusable independent-ranking utility (`lib/ranking`) wired into three gates — R3 ideate (rank hypotheses → top-K), research-brainstorm (N ideas → 1 Direction), code implementation review (acquit one implementation) — using **independent sub-agents** for both generation and scoring.

**Naming note:** this is *multi-agent* (N independent generators + 1 independent ranker), but it is **not a multi-judge voting panel** — and intentionally so. Per ARIS `acceptance-gate.md`, N same-family voters are "correlated blindness in a jury costume," not independence. Ranking uses a **single independent ranker**; the acquit verdict is a single judge. (A same-family ranker *panel* would only buy variance-reduction on the taste task and is deliberately skipped for simplicity.)

**Architecture (simplified per design review):**
- **Ranking (ideate, brainstorm):** generation fans out across **independent Claude sub-agents** (firepower); scoring/ranking is done by a **single separate independent Claude sub-agent** (the bench). Same-family is acceptable here because a human ratifies (brainstorm) and real experiments adjudicate downstream. Independence is by **sub-agent role identity** (`producer != judge`), not model id. There is **no autonomy→independence table** — the autonomy dial governs only pause cadence.
- **Acquit (code implementation):** two layers. (1) **Correctness — same-family:** reuse the existing `superpowers:requesting-code-review` code-reviewer subagent on the local diff. (2) **Faithfulness/deception — cross-family:** route "does this code faithfully implement the hypothesis?" to Codex (`mcp__codex__codex`, in-environment). If no external model is reachable, degrade to a same-family verdict marked `degraded: true` and lean on the T1 human ack. The `research-op` gate enforces *presence + distinct judge + acquit*; cross-family is preferred-and-recorded, not hard-blocked.
  - **Gate keys on the destination, not the source (Gap 3):** the gate fires on **entering `READY_TO_LAUNCH`** from any other status — not only from `IMPLEMENTATION_REVIEW`. This closes the `IMPLEMENTING → READY_TO_LAUNCH` and (if the enum is ever reconciled) `DECISION_ADJUDICATION → READY_TO_LAUNCH` bypasses. (`DECISION_ADJUDICATION` exists in `WORKFLOW.md` but not in the enforced `transitions.py`/`schema.js` enum — a pre-existing state-machine mismatch, flagged but out of scope here.)
  - **Autonomy-independent (Gap 4):** the gate **always** requires present + distinct judge + `sound`, regardless of autonomy level — consistent with "dial = pause cadence only." `supervised` does **not** relax it; the human-in-the-loop simply supplies/attests the verdict (`judge: "human"`). Only the *cross-family preference* degrades (→ `degraded: true`). This is intentionally **stricter than** the existing terminal `rule_acquit_judge_independent`, which still relaxes at supervised.

`lib/ranking` is self-contained (no `lib/verifier` import). Its invariants: well-formedness, real-candidate ids, `producer != judge` — re-checked **both** at `assess_ranking` (caller-side) **and** at `write_ranking_verdict` (persistence boundary, Gap 2) so a malformed audit record can never be written even if a caller skips the assess step.

**Tech Stack:** Python 3.13 (project conda env), pytest, the `research-op` rule registry (`skills/research-op/scripts/validate.py`), the `Agent` tool for sub-agent fan-out, `mcp__codex__codex` for the cross-family faithfulness verdict. Skills are Markdown prose.

**Pipeline root (all paths relative to it):** `/home/uqzzha35/Project/Trustworthy-Research-Pipeline/Trustworthy-Research-Pipeline`

**Run tests with the project conda env:** `python3.13 -m pytest <path> -v`

---

### Task 1: `lib/ranking` — `rank_request` + `parse_ranking`

**Files:**
- Create: `lib/ranking/__init__.py`
- Test: `tests/ranking/test_ranking.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/ranking/test_ranking.py`:

```python
"""Unit gate for lib/ranking — the deterministic ranking-jury guard (no model call)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
import ranking  # noqa: E402


def test_rank_request_passes_paths_not_content():
    req = ranking.rank_request(
        ["hyp-001", "hyp-002"],
        ["outputs/pkg/ideate/candidates.json"],
        "Rank for a top-venue submission.",
        top_k=2,
    )
    assert req["candidate_ids"] == ["hyp-001", "hyp-002"]
    assert req["candidate_artifact_paths"] == ["outputs/pkg/ideate/candidates.json"]
    assert req["top_k"] == 2
    assert "instruction" in req  # only ids + paths handed over, never candidate content


def test_parse_ranking_accepts_clean_json():
    raw = '{"ranking": ["hyp-002", "hyp-001"], "rationale": {"hyp-002": "stronger signal"}}'
    out = ranking.parse_ranking(raw, ["hyp-001", "hyp-002"])
    assert out["ranking"] == ["hyp-002", "hyp-001"]
    assert out["rationale"]["hyp-002"] == "stronger signal"


def test_parse_ranking_tolerates_code_fence_and_prose():
    raw = 'Here is my ranking:\n```json\n{"ranking": ["hyp-001"]}\n```\n'
    out = ranking.parse_ranking(raw, ["hyp-001", "hyp-002"])
    assert out["ranking"] == ["hyp-001"]


def test_parse_ranking_rejects_unknown_id():
    with pytest.raises(ranking.RankingError):
        ranking.parse_ranking('{"ranking": ["hyp-999"]}', ["hyp-001", "hyp-002"])


def test_parse_ranking_rejects_unparseable():
    with pytest.raises(ranking.RankingError):
        ranking.parse_ranking("no json here", ["hyp-001"])


def test_parse_ranking_rejects_empty_ranking():
    with pytest.raises(ranking.RankingError):
        ranking.parse_ranking('{"ranking": []}', ["hyp-001"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3.13 -m pytest tests/ranking/test_ranking.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ranking'`.

- [ ] **Step 3: Write minimal implementation**

Create `lib/ranking/__init__.py`:

```python
"""Ranking jury — the deterministic guard for an independent-sub-agent candidate ranking.

Generation fans out across independent sub-agents; the ordering is produced by a SEPARATE
independent sub-agent (the bench). This lib owns only the deterministic half: building a
file-paths-only request, validating that a returned ranking is well-formed, references only real
candidates, and was produced by a judge distinct from the generator (producer != judge), selecting
the top-K, and persisting an inspectable verdict record. A generator may DRIVE breadth but never
RANK its own candidates. Independence here is by sub-agent ROLE identity, not model id — two Claude
sub-agents are independent enough for a ranking (a human ratifies and experiments adjudicate).
"""

import json
import uuid
from pathlib import Path


class RankingError(Exception):
    """Raised when a ranking request/verdict is malformed or self-judged."""


def rank_request(candidate_ids, candidate_artifact_paths, question, *, top_k):
    """Build the file-paths-only request the agent hands to a separate scoring sub-agent."""
    return {
        "question": question,
        "candidate_ids": list(candidate_ids),
        "candidate_artifact_paths": list(candidate_artifact_paths),  # paths only — never inlined
        "top_k": top_k,
        "instruction": (
            "Read the candidate artifacts. Rank the candidate_ids best-first for the stated goal. "
            'Reply as JSON: {"ranking": [id, ...], "rationale": {id: reason}}. '
            "Use only the given ids; do not invent candidates."
        ),
    }


def parse_ranking(raw_text, candidate_ids):
    """Map a scoring sub-agent reply (JSON, possibly fenced/prose-wrapped) to a ranking; reject unknown ids."""
    known = set(candidate_ids)
    text = (raw_text or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise RankingError("could not find a JSON object in the reply")
    try:
        obj = json.loads(text[start:end + 1])
    except (ValueError, json.JSONDecodeError) as exc:
        raise RankingError(f"could not parse ranking JSON: {exc}")
    order = obj.get("ranking")
    if not isinstance(order, list) or not order:
        raise RankingError("ranking must be a non-empty list")
    unknown = [r for r in order if r not in known]
    if unknown:
        raise RankingError(f"ranking references unknown candidate ids: {unknown}")
    return {"ranking": order, "rationale": obj.get("rationale") or {}}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3.13 -m pytest tests/ranking/test_ranking.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add lib/ranking/__init__.py tests/ranking/test_ranking.py
git commit -m "feat(ranking): add rank_request + parse_ranking to lib/ranking"
```

---

### Task 2: `lib/ranking` — `assess_ranking` (the independence guard)

Simplified: well-formed + real ids + `producer != judge`. No autonomy level, no family check.

**Files:**
- Modify: `lib/ranking/__init__.py` (append `assess_ranking`)
- Test: `tests/ranking/test_ranking.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/ranking/test_ranking.py`:

```python
def _ids():
    return ["hyp-001", "hyp-002", "hyp-003"]


def test_distinct_roles_same_model_passes():
    # Two Claude sub-agents are independent enough for a ranking — distinct ROLE ids.
    assert ranking.assess_ranking(
        ["hyp-001"], _ids(), producer="gen:lens-scaling", judge="ranker") is None


def test_producer_equals_judge_rejected():
    assert ranking.assess_ranking(
        ["hyp-001"], _ids(), producer="ranker", judge="ranker") is not None


def test_missing_identity_rejected():
    assert ranking.assess_ranking(["hyp-001"], _ids(), producer="", judge="ranker") is not None


def test_fabricated_id_rejected():
    assert ranking.assess_ranking(
        ["hyp-999"], _ids(), producer="gen", judge="ranker") is not None


def test_duplicate_ranking_rejected():
    assert ranking.assess_ranking(
        ["hyp-001", "hyp-001"], _ids(), producer="gen", judge="ranker") is not None


def test_empty_ranking_rejected():
    assert ranking.assess_ranking([], _ids(), producer="gen", judge="ranker") is not None


def test_ranking_longer_than_candidates_rejected():
    assert ranking.assess_ranking(
        ["hyp-001", "hyp-002", "hyp-003", "hyp-004"], _ids(),
        producer="gen", judge="ranker") is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3.13 -m pytest tests/ranking/test_ranking.py -v`
Expected: the 7 new tests ERROR/FAIL on `AttributeError: module 'ranking' has no attribute 'assess_ranking'`.

- [ ] **Step 3: Write minimal implementation**

Append to `lib/ranking/__init__.py`:

```python
def assess_ranking(order, candidate_ids, *, producer, judge):
    """Return a violation reason if this ranking is malformed or self-judged, else None."""
    candidates = set(candidate_ids)
    if not isinstance(order, list) or not order:
        return "ranking must be a non-empty list"
    if len(order) != len(set(order)):
        return "ranking has duplicate ids"
    if any(r not in candidates for r in order):
        return "ranking references ids that are not candidates"
    if len(order) > len(candidates):
        return "ranking is longer than the candidate set"
    if not producer or not judge:
        return "ranking needs both producer and judge role identities"
    if producer == judge:
        return "producer == judge (a generator may DRIVE breadth but never RANK its own candidates)"
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3.13 -m pytest tests/ranking/test_ranking.py -v`
Expected: PASS (13 tests total).

- [ ] **Step 5: Commit**

```bash
git add lib/ranking/__init__.py tests/ranking/test_ranking.py
git commit -m "feat(ranking): add assess_ranking (well-formed + real ids + producer!=judge)"
```

---

### Task 3: `lib/ranking` — `select_top_k` + verdict persistence

**Files:**
- Modify: `lib/ranking/__init__.py` (append)
- Test: `tests/ranking/test_ranking_record.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/ranking/test_ranking_record.py`:

```python
"""Persisted-verdict gate for lib/ranking — selection + audit record round-trip."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
import ranking  # noqa: E402


def test_select_top_k_truncates():
    assert ranking.select_top_k(["a", "b", "c"], 2) == ["a", "b"]


def test_select_top_k_k_larger_than_list():
    assert ranking.select_top_k(["a"], 3) == ["a"]


def _record(producer="gen:ideate", judge="ranker"):
    return {
        "producer": producer,
        "judge": judge,
        "scope_version": 1,
        "candidate_set_id": "ideate/candidates.json",
        "candidate_set": ["hyp-001", "hyp-002", "hyp-003"],
        "ranking": ["hyp-002", "hyp-001"],
        "selected": ["hyp-002"],
        "rationale": {"hyp-002": "stronger signal"},
    }


def test_write_then_read_round_trip(tmp_path):
    rec = ranking.write_ranking_verdict(tmp_path, _record())
    assert rec["ranking_id"]
    again = ranking.read_ranking_verdict(tmp_path, rec["ranking_id"])
    assert again["selected"] == ["hyp-002"]
    assert again["judge"] == "ranker"


def test_write_rejects_self_judged(tmp_path):
    with pytest.raises(ranking.RankingError):
        ranking.write_ranking_verdict(tmp_path, _record(producer="ranker", judge="ranker"))


def test_write_rejects_missing_field(tmp_path):
    rec = _record()
    del rec["selected"]
    with pytest.raises(ranking.RankingError):
        ranking.write_ranking_verdict(tmp_path, rec)


def test_write_rejects_empty_selected(tmp_path):
    rec = _record()
    rec["selected"] = []
    with pytest.raises(ranking.RankingError):
        ranking.write_ranking_verdict(tmp_path, rec)


def test_write_allows_scope_version_zero(tmp_path):
    rec = _record()
    rec["scope_version"] = 0
    out = ranking.write_ranking_verdict(tmp_path, rec)
    assert out["scope_version"] == 0


# --- Gap 2: write re-validates internal consistency, not just field presence ---


def test_write_rejects_ranking_outside_candidate_set(tmp_path):
    rec = _record()
    rec["ranking"] = ["hyp-002", "hyp-999"]  # hyp-999 is not in candidate_set
    with pytest.raises(ranking.RankingError):
        ranking.write_ranking_verdict(tmp_path, rec)


def test_write_rejects_selected_not_in_ranking(tmp_path):
    rec = _record()
    rec["selected"] = ["hyp-003"]  # not present in ranking
    with pytest.raises(ranking.RankingError):
        ranking.write_ranking_verdict(tmp_path, rec)


def test_write_rejects_duplicate_ranking(tmp_path):
    rec = _record()
    rec["ranking"] = ["hyp-002", "hyp-002"]
    with pytest.raises(ranking.RankingError):
        ranking.write_ranking_verdict(tmp_path, rec)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3.13 -m pytest tests/ranking/test_ranking_record.py -v`
Expected: FAIL with `AttributeError: module 'ranking' has no attribute 'select_top_k'`.

- [ ] **Step 3: Write minimal implementation**

Append to `lib/ranking/__init__.py`:

```python
def select_top_k(order, k):
    """Return the first k ids of the ranking (mechanical, judgment-free)."""
    return list(order)[:k]


_RECORD_REQUIRED = ("producer", "judge", "scope_version", "candidate_set_id",
                    "candidate_set", "ranking", "selected")


def _missing_fields(record):
    out = []
    for field in _RECORD_REQUIRED:
        value = record.get(field)
        if value is None or (isinstance(value, (str, list, dict)) and len(value) == 0):
            out.append(field)
    return out


def write_ranking_verdict(verdicts_dir, record):
    """Persist a structured ranking verdict; reject (raise) before write if incomplete, self-judged,
    or internally inconsistent (defense-in-depth: re-validate even if the caller skipped assess_ranking)."""
    missing = _missing_fields(record)
    if missing:
        raise RankingError(f"ranking verdict missing required fields: {missing}")
    if record["producer"] == record["judge"]:
        raise RankingError(
            "producer == judge (a generator may DRIVE breadth but never RANK its own candidates)")
    order, cset, selected = record["ranking"], set(record["candidate_set"]), record["selected"]
    if len(order) != len(set(order)):
        raise RankingError("ranking has duplicate ids")
    fabricated = [r for r in order if r not in cset]
    if fabricated:
        raise RankingError(f"ranking references ids not in candidate_set: {fabricated}")
    not_ranked = [s for s in selected if s not in set(order)]
    if not_ranked:
        raise RankingError(f"selected contains ids not in ranking: {not_ranked}")
    out = dict(record)
    out.setdefault("ranking_id", uuid.uuid4().hex[:12])
    path = Path(verdicts_dir) / f"{out['ranking_id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def read_ranking_verdict(verdicts_dir, ranking_id):
    """Read a persisted ranking verdict record by id."""
    return json.loads((Path(verdicts_dir) / f"{ranking_id}.json").read_text(encoding="utf-8"))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3.13 -m pytest tests/ranking/ -v`
Expected: PASS (all ranking tests, 23 total).

- [ ] **Step 5: Commit**

```bash
git add lib/ranking/__init__.py tests/ranking/test_ranking_record.py
git commit -m "feat(ranking): add select_top_k + ranking verdict persistence"
```

---

### Task 4: Consumer 3 — launch acquit gate in `research-op` (keyed on entering `READY_TO_LAUNCH`)

**Entering `READY_TO_LAUNCH` from any other status** requires a `reviewer_verdict` that (a) is present, (b) was produced by a judge distinct from the implementer, and (c) acquits (`sound`). Keying on the *destination* (Gap 3) closes every bypass path, not just `IMPLEMENTATION_REVIEW`. The gate is **autonomy-independent** (Gap 4): it never relaxes at `supervised` — the human just supplies the verdict. Cross-family is **preferred and recorded** (`degraded` flag) in skill prose, **not** hard-blocked here.

**Files:**
- Modify: `skills/research-op/scripts/validate.py` (add two rules + register them)
- Test: `tests/research-op/test_impl_review_gate.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/research-op/test_impl_review_gate.py`:

```python
"""Launch acquit gate: entering READY_TO_LAUNCH from any status needs a distinct, acquitting verdict."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "research-op" / "scripts"))
import validate  # noqa: E402

_IN_REVIEW = {"category": "in-progress", "status": "IMPLEMENTATION_REVIEW"}
_IMPLEMENTING = {"category": "in-progress", "status": "IMPLEMENTING"}


def _launch_payload(verdict=None):
    p = {"to_status": "READY_TO_LAUNCH"}
    if verdict is not None:
        p["reviewer_verdict"] = verdict
    return p


def _v(producer="impl:coder", judge="reviewer", result="sound"):
    return {"producer": producer, "judge": judge, "result": result,
            "scope_version": 1, "artifact_id": "diff-1"}


def test_launch_without_reviewer_verdict_rejected():
    rej = validate.validate("test-pkg", "update", "status", _launch_payload(), _IN_REVIEW)
    assert rej is not None and rej.rule == "launch-needs-verdict"


def test_launch_with_distinct_sound_verdict_passes():
    # Same-family but distinct roles + sound => passes (cross-family not hard-required here).
    rej = validate.validate("test-pkg", "update", "status", _launch_payload(_v()), _IN_REVIEW)
    assert rej is None


def test_launch_with_self_judged_verdict_rejected():
    rej = validate.validate("test-pkg", "update", "status",
                            _launch_payload(_v(producer="reviewer", judge="reviewer")), _IN_REVIEW)
    assert rej is not None and rej.rule == "launch-acquits"


def test_launch_with_non_acquitting_verdict_rejected():
    rej = validate.validate("test-pkg", "update", "status",
                            _launch_payload(_v(result="needs-revision")), _IN_REVIEW)
    assert rej is not None and rej.rule == "launch-acquits"


def test_launch_from_implementing_also_gated():
    # Gap 3: the bypass path IMPLEMENTING -> READY_TO_LAUNCH is now gated too.
    rej = validate.validate("test-pkg", "update", "status", _launch_payload(), _IMPLEMENTING)
    assert rej is not None and rej.rule == "launch-needs-verdict"


def test_non_launch_transition_not_gated():
    # Moving to a non-launch status carries no reviewer requirement.
    rej = validate.validate("test-pkg", "update", "status",
                            {"to_status": "IMPLEMENTING"}, _IN_REVIEW)
    assert rej is None


def test_supervised_does_not_relax():
    # Gap 4: even with autonomy_level=supervised, a non-acquitting verdict is still rejected.
    payload = _launch_payload(_v(result="needs-revision"))
    payload["autonomy_level"] = "supervised"
    rej = validate.validate("test-pkg", "update", "status", payload, _IN_REVIEW)
    assert rej is not None and rej.rule == "launch-acquits"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3.13 -m pytest tests/research-op/test_impl_review_gate.py -v`
Expected: FAIL — `test_launch_without_reviewer_verdict_rejected` returns `None` (no such rule yet).

- [ ] **Step 3: Write minimal implementation**

In `skills/research-op/scripts/validate.py`, add these two rules immediately after `rule_acquit_judge_independent` (≈ line 358). `verifier` is already imported at the top of this file; reuse `verifier.ACQUIT_STATES`:

```python
def _entering_launch(op, target, payload, state) -> bool:
    """True iff this op moves status INTO READY_TO_LAUNCH from any other status (destination-keyed)."""
    return (
        target == "status" and op == "update"
        and payload.get("to_status") == "READY_TO_LAUNCH"
        and state.get("status") != "READY_TO_LAUNCH"  # ignore no-op self-transition
    )


def rule_launch_needs_verdict(pkg, op, target, payload, state) -> Reject | None:
    """Entering READY_TO_LAUNCH must carry a reviewer verdict on the implementation (any source status)."""
    if not _entering_launch(op, target, payload, state):
        return None
    if not payload.get("reviewer_verdict"):
        return Reject(
            rule="launch-needs-verdict",
            file=None, anchor=None, field="reviewer_verdict",
            expected="a reviewer verdict on the implementation before entering READY_TO_LAUNCH",
            actual="no reviewer_verdict in payload",
            suggested_fix="Have a separate reviewer sub-agent review the implementation diff and attach "
                          "reviewer_verdict (producer, judge, result, scope_version, artifact_id) "
                          "before moving to READY_TO_LAUNCH. At supervised the human may attest it "
                          "(judge='human').",
        )
    return None


def rule_launch_acquits(pkg, op, target, payload, state) -> Reject | None:
    """The reviewer must be a distinct judge and the verdict must acquit (sound) — autonomy-independent."""
    if not _entering_launch(op, target, payload, state):
        return None
    verdict = payload.get("reviewer_verdict")
    if not verdict:
        return None  # presence is handled by rule_launch_needs_verdict
    producer, judge = verdict.get("producer"), verdict.get("judge")
    if not producer or not judge or producer == judge:
        return Reject(
            rule="launch-acquits",
            file=None, anchor=None, field="reviewer_verdict",
            expected="a verdict whose judge is distinct from the implementer (producer != judge)",
            actual=f"producer={producer!r} judge={judge!r}",
            suggested_fix="Use a separate reviewer (cross-family preferred for the faithfulness check) "
                          "distinct from the coding agent.",
        )
    if verdict.get("result") not in verifier.ACQUIT_STATES:
        return Reject(
            rule="launch-acquits",
            file=None, anchor=None, field="reviewer_verdict",
            expected=f"an acquitting result in {sorted(verifier.ACQUIT_STATES)}",
            actual=f"result={verdict.get('result')!r}",
            suggested_fix="Proceed to launch only on a 'sound' verdict; fix the implementation otherwise.",
        )
    return None
```

Then register both in the `_RULES` list (after the `rule_acquit_judge_independent` entry, ≈ line 584). Both need state (second tuple element `True`):

```python
    (rule_acquit_judge_independent,          True),
    (rule_launch_needs_verdict,              True),
    (rule_launch_acquits,                    True),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3.13 -m pytest tests/research-op/test_impl_review_gate.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Run the full research-op + verifier suites (no regression)**

Run: `python3.13 -m pytest tests/research-op/ tests/verifier/ -v`
Expected: PASS — the new rules fire only on the IMPLEMENTATION_REVIEW→READY_TO_LAUNCH update.

- [ ] **Step 6: Commit**

```bash
git add skills/research-op/scripts/validate.py tests/research-op/test_impl_review_gate.py
git commit -m "feat(research-op): gate entry into READY_TO_LAUNCH on a distinct, acquitting reviewer verdict"
```

---

### Task 5: Consumer 1 — independent-sub-agent fan-out + ranking in `research-ideate`

Prose + frontmatter edit. Generation fans out across independent sub-agents; a separate sub-agent ranks; the banlist stays a mechanical pre-filter.

**Files:**
- Modify: `skills/research-ideate/SKILL.md` (frontmatter `allowed-tools` + Steps 2 and 6)

- [ ] **Step 1: Grant the `Agent` tool (fan-out now happens in the body)**

In the frontmatter `allowed-tools:` line, add `Agent`. The body now spawns independent generator sub-agents and a separate ranking sub-agent, so the grant tracks real usage.

```yaml
allowed-tools: Bash(python3 *), Read, Edit, Write, Grep, Glob, Agent
```

- [ ] **Step 2: Rewrite Step 2 (generation) as independent-sub-agent fan-out**

Replace the body of **Step 2 — Generate N candidate hypotheses** with:

```markdown
**Step 2 — Generate candidates via independent sub-agents (fan-out).**

Do not free-associate in one context. Dispatch **independent generator sub-agents** (Agent tool),
each exploring the direction through a distinct analytic lens and returning candidates as structured
output — this is breadth (firepower), not judgment. Suggested lenses (a floor, not a ceiling):
`method-transfer`, `contradiction`, `untested-assumption`, `scaling-regime`, `diagnostic`. If the
Agent tool is unavailable, enumerate the lenses sequentially in one pass (same result, slower).

Each sub-agent returns:
```json
{"shard_id": "lens:scaling-regime",
 "candidates": [{"id": "hyp-001", "hypothesis": "...", "dedup_key": "<normalized hypothesis>"}]}
```

Merge all shards into one union and assign stable ids (`hyp-001`, ...). Mechanically dedup on
`dedup_key` (exact + near-match) — **never drop a candidate for being "weak"; weakness is the
ranking sub-agent's verdict, not a merge step.** Write nothing to disk yet.
```

- [ ] **Step 3: Insert the ranking step (new Step 6, renumber old Step 6 → Step 7)**

After **Step 5 — Write survivors to candidates.json**, insert:

```markdown
**Step 6 — Rank survivors with a separate independent sub-agent, select top-K.**

The banlist is a *mechanical* filter, not a quality verdict. A **separate** sub-agent (distinct role
from the generators — `generate ≠ judge`) ranks the survivors. Same-family is fine here: a human
ratifies directions and real experiments adjudicate.

```python
import sys
sys.path.insert(0, "<pipeline-root>/lib")
import ranking
```

1. `top_k` defaults to 3 (overridable). Build the request:
   `req = ranking.rank_request(survivor_ids, ["outputs/<pkg>/ideate/candidates.json"],
   "Rank these hypotheses best-first for a top-venue submission under the direction's success
   predicate.", top_k=<k>)`. Dispatch a **fresh ranking sub-agent** (Agent tool) with `req` — it reads
   `candidates.json` itself (paths only; never inline candidate text) and returns the ranking JSON.
2. `parsed = ranking.parse_ranking(reply, survivor_ids)`; then
   `reason = ranking.assess_ranking(parsed["ranking"], survivor_ids,
   producer="ideate-generators", judge="ideate-ranker")`. The `producer`/`judge` are **role ids** —
   distinct because the ranker sub-agent is a different instance than the generators. If `reason` is
   not `None`, **stop and surface it** (do not fall back to "use all"); fix and re-run.
3. `selected = ranking.select_top_k(parsed["ranking"], k)`. Persist the audit record:
   `ranking.write_ranking_verdict("outputs/<pkg>/ideate/verdicts/",
   {"producer": "ideate-generators", "judge": "ideate-ranker", "scope_version": <v>,
   "candidate_set_id": "ideate/candidates.json", "candidate_set": survivor_ids,
   "ranking": parsed["ranking"], "selected": selected, "rationale": parsed["rationale"]})`.
4. Re-write `candidates.json` so it carries the survivor objects plus top-level `"selected": [...ids]`
   and `"ranking_id": "<id>"`. The orchestrator consumes `selected`.
```

Then update old Step 6 (now **Step 7**) "Surface the survivors" so the in-loop branch says the
orchestrator consumes `selected[]` (the ranked top-K), not all survivors.

- [ ] **Step 4: Update Output Contract + Done Condition**

Add to the **Output Contract** table:

```markdown
| Ranking verdict (audit) | `outputs/<pkg>/ideate/verdicts/<ranking_id>.json` | Step 6 via `ranking.write_ranking_verdict` |
```

Note in the `candidates.json` row that it now also carries `selected[]` + `ranking_id`. Update
**Done Condition** to: "`candidates.json` exists, contains the surviving hypotheses, and a non-empty
`selected[]` chosen by a separate ranking sub-agent. Report the selected ids + rationale to the caller."

- [ ] **Step 5: Verify the prose references resolve**

Run:
```bash
grep -n "Agent\|lib/ranking\|rank_request\|assess_ranking\|select_top_k\|write_ranking_verdict\|selected\|shard_id\|dedup_key" skills/research-ideate/SKILL.md
```
Expected: frontmatter grants `Agent`; Step 2 fans out with `shard_id`/`dedup_key`; Step 6 references all four lib functions + `selected`.

- [ ] **Step 6: Commit**

```bash
git add skills/research-ideate/SKILL.md
git commit -m "feat(research-ideate): sub-agent fan-out generation + separate ranking sub-agent selects top-K"
```

---

### Task 6: Consumer 2 — ranking sub-agent in `research-brainstorm`

Prose + frontmatter edit. At N pre-package ideas → 1 ratified Direction, a separate sub-agent ranks
the ideas (`top_k=1`); the human still ratifies (proposer ≠ disposer preserved).

**Files:**
- Modify: `skills/research-brainstorm/SKILL.md`

- [ ] **Step 1: Grant `Agent` and locate the N→1 conversion step**

Add `Agent` to the frontmatter `allowed-tools:` if absent. Then:
```bash
grep -n "allowed-tools\|Direction\|convert\|ratif\|brainstorm.html\|provenance" skills/research-brainstorm/SKILL.md | head -30
```
Read the step that converts brainstorm ideas into a single ratified Direction.

- [ ] **Step 2: Insert the ranking step before ratification**

Immediately before the conversion/ratification step, insert:

```markdown
**Rank the candidate ideas with a separate sub-agent before forming the Direction.**

When more than one pre-package idea is in contention for a single Direction, do not pick by the
generating context's own taste. A **separate** sub-agent ranks them (`generate ≠ judge`), then the
user ratifies the winner (proposer ≠ disposer preserved — the sub-agent *ranks*, the human *ratifies*).

```python
import sys
sys.path.insert(0, "<pipeline-root>/lib")
import ranking
```

1. Write the candidate ideas to `outputs/_brainstorm/<slug>/candidates.json`.
2. `req = ranking.rank_request(idea_ids, ["outputs/_brainstorm/<slug>/candidates.json"],
   "Rank these directions best-first for a publishable research program; the answer should matter
   either way.", top_k=1)`. Dispatch a fresh ranking sub-agent (Agent tool) with `req` (paths only).
3. `parsed = ranking.parse_ranking(reply, idea_ids)`;
   `reason = ranking.assess_ranking(parsed["ranking"], idea_ids,
   producer="brainstorm-ideas", judge="brainstorm-ranker")`. If `reason`, stop and surface it.
4. `winner = ranking.select_top_k(parsed["ranking"], 1)[0]`. Persist
   `ranking.write_ranking_verdict("outputs/_brainstorm/<slug>/verdicts/",
   {"producer": "brainstorm-ideas", "judge": "brainstorm-ranker", "scope_version": <v>,
   "candidate_set_id": "_brainstorm/<slug>/candidates.json", "candidate_set": idea_ids,
   "ranking": parsed["ranking"], "selected": [winner], "rationale": parsed["rationale"]})`.
5. Present `winner` + `parsed["rationale"][winner]` to the user for ratification. Record the rationale
   + `ranking_id` as conversion provenance in the new package's `brainstorm.html`.
```

- [ ] **Step 3: Verify the prose references resolve**

Run:
```bash
grep -n "Agent\|lib/ranking\|rank_request\|assess_ranking\|ratif\|proposer" skills/research-brainstorm/SKILL.md
```
Expected: the new step references the lib functions and keeps the ratification (proposer ≠ disposer) language.

- [ ] **Step 4: Run the brainstorm test suite (no behavior change expected)**

Run: `python3.13 -m pytest tests/research-brainstorm/ -v`
Expected: PASS (prose-only edit; CLI/data behavior unchanged).

- [ ] **Step 5: Commit**

```bash
git add skills/research-brainstorm/SKILL.md
git commit -m "feat(research-brainstorm): separate ranking sub-agent ranks ideas before ratifying the Direction"
```

---

### Task 7: Wire the two-layer implementation reviewer into `research-auto`

Document the IMPLEMENTATION_REVIEW reviewer in the orchestrator: same-family correctness review
(reuse `superpowers:requesting-code-review`) + cross-family faithfulness verdict (Codex), degrade +
flag when no external model is reachable.

**Files:**
- Modify: `skills/research-auto/SKILL.md`

- [ ] **Step 1: Find the implementation-review / transition description**

```bash
grep -n "IMPLEMENTATION_REVIEW\|IMPLEMENTING\|READY_TO_LAUNCH\|reviewer\|verifier\|acquit" skills/research-auto/SKILL.md
```
Read the role/transition section.

- [ ] **Step 2: Add the two-layer reviewer step**

Where the loop moves the package out of `IMPLEMENTATION_REVIEW` toward `READY_TO_LAUNCH`, add:

```markdown
Before leaving **IMPLEMENTATION_REVIEW**, the implementation is reviewed in two layers (the reviewer
sub-agent is always a different instance than the coding agent):

1. **Correctness (same-family, reuse).** Dispatch the `superpowers:requesting-code-review` code-reviewer
   subagent on the local diff (`BASE_SHA..HEAD_SHA`). Treat any Critical/Important finding as blocking —
   fix and re-review.
2. **Faithfulness (cross-family preferred).** Ask "does this code faithfully implement the hypothesis,
   with no fabricated metric, hard-coded result, or skipped condition?" Route this to a **cross-family**
   judge (`mcp__codex__codex`, fresh thread, paths only) when reachable. If no external model is
   reachable, take the same-family answer and set `degraded: true` on the verdict (the T1 human ack is
   the backstop for the deception dimension — 核心问题 #1).

Build `reviewer_verdict = {producer: "impl:<coder-role>", judge: "<reviewer-role-or-codex>",
result: <sound|needs-revision|unsound|...>, scope_version, artifact_id, degraded: <bool>}` and route the
`READY_TO_LAUNCH` status update through `research-op` carrying it. `research-op` rejects **any** entry
into `READY_TO_LAUNCH` (`launch-needs-verdict` / `launch-acquits`) unless the verdict is present, has a
judge distinct from the implementer, and acquits (`sound`). The gate is autonomy-independent — at
`supervised` the human attests the verdict (`judge: "human"`) rather than the gate relaxing. Cross-family
is preferred-and-recorded, not hard-blocked. (No-code-change re-runs that re-enter `READY_TO_LAUNCH`
re-attach the prior verdict.)
```

- [ ] **Step 3: Verify the prose references resolve**

```bash
grep -n "launch-needs-verdict\|launch-acquits\|reviewer_verdict\|requesting-code-review\|mcp__codex__codex\|degraded" skills/research-auto/SKILL.md
```
Expected: the new prose names both gate rules, the same-family reviewer skill, the cross-family Codex route, and the `degraded` flag.

- [ ] **Step 4: Run the full suite**

Run: `python3.13 -m pytest tests/ -q`
Expected: PASS (all prior tests + the new ranking + impl-review-gate tests).

- [ ] **Step 5: Commit**

```bash
git add skills/research-auto/SKILL.md
git commit -m "docs(research-auto): two-layer IMPLEMENTATION_REVIEW reviewer (same-family correctness + cross-family faithfulness)"
```

---

## Self-Review

**Spec coverage:**
- `lib/ranking` (rank_request / parse_ranking / assess_ranking / select_top_k / write+read verdict), self-contained → Tasks 1–3. ✓
- Independence by sub-agent role identity (`producer != judge`), no autonomy/family table → Task 2. ✓
- Generation fan-out via independent sub-agents; separate ranking sub-agent → Tasks 5, 6 (with `Agent` grant). ✓
- Consumer 1 ideate (fan-out → rank → top-K) → Task 5. ✓
- Consumer 2 brainstorm (N → 1 Direction, proposer≠disposer) → Task 6. ✓
- Consumer 3 code implementation: same-family correctness reuse + cross-family faithfulness + degrade/flag; research-op gate enforces presence + distinct judge + acquit → Task 4 (gate) + Task 7 (controller prose). ✓
- Dial governs pause cadence only (unchanged in `lib/verifier`); ranking no longer couples to it → reflected in Architecture + Task 2 (no `autonomy_level`). ✓
- TDD throughout (red→green→commit) → every code task. ✓

**Review gaps addressed (design review round 2):**
- **Gap 1 (not a voting panel):** single independent ranker is intentional (ARIS: same-family voting = correlated blindness); title/wording de-jury-fied → Naming note. ✓
- **Gap 2 (audit write under-validates):** `write_ranking_verdict` now re-checks no-dups + `ranking ⊆ candidate_set` + `selected ⊆ ranking`, and stores `candidate_set` → Task 3 impl + 3 new tests. ✓
- **Gap 3 (bypass path):** gate re-keyed on **entering `READY_TO_LAUNCH`** (destination), closing `IMPLEMENTING → READY_TO_LAUNCH` etc. → Task 4 `_entering_launch` + `test_launch_from_implementing_also_gated`. ✓
- **Gap 4 (supervised ambiguity):** gate is autonomy-independent (always present+distinct+sound; human attests at supervised) — made explicit → Architecture + Task 4 `test_supervised_does_not_relax`. ✓

**Placeholder scan:** No TBD/TODO. Every code step shows complete code. `<pipeline-root>`, `<pkg>`, `<slug>`, `<k>`, `<v>`, `BASE_SHA`/`HEAD_SHA`, role-id strings are runtime substitutions consistent with existing skill conventions (research-ideate already uses `<pipeline-root>` and `outputs/<pkg>/...`).

**Type/name consistency:** `rank_request`, `parse_ranking`, `assess_ranking`, `select_top_k`, `write_ranking_verdict`, `read_ranking_verdict`, `RankingError`, `_RECORD_REQUIRED` identical across tasks. `assess_ranking` signature is `(order, candidate_ids, *, producer, judge)` everywhere (Task 2 impl + Tasks 5/6 callers). Verdict record carries `candidate_set` (Task 3 `_RECORD_REQUIRED` + Tasks 5/6 callers + tests). Gate rules `rule_launch_needs_verdict` / `rule_launch_acquits` and their `rule=` strings (`launch-needs-verdict` / `launch-acquits`) match Task 4 impl + tests + Task 7 prose. `reviewer_verdict` payload key matches the existing `implementation-review` tbody field. `lib/ranking` imports no `verifier`; `validate.py` reuses the already-imported `verifier.ACQUIT_STATES`.

**Scope check:** Single subsystem (one lib + its call sites + one gate). No decomposition needed.
```

