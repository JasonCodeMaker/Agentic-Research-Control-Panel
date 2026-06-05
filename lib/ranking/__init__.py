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


def select_top_k(order, k):
    """Return the first k ids of the ranking (mechanical, judgment-free)."""
    return list(order)[:k]


_RECORD_REQUIRED = ("producer", "judge", "scope_version", "candidate_set_id",
                    "candidate_set", "ranking", "selected")


def _missing_fields(record):
    """Required fields that are absent or empty. Int fields (scope_version) are valid at 0 — only None
    and empty str/list/dict count as missing; do not simplify to `not value`."""
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
