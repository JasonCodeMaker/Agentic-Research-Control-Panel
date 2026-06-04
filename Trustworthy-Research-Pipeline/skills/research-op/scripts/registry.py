"""Project-level knowledge registries (papers / edges / gaps) for research-op.

These are cross-package stores, not package surfaces — like the Scope SSOT transition log they
bypass the (category, status) state-gate. Each `--op registry-add` validates (reject-before-write),
dedups, and appends one JSONL line under research_html/data/<store>.jsonl. The Context Pack
(lib/context_pack/build.py) reads these stores and surfaces them on context.html.
"""

import json
from pathlib import Path

# Edge types we build (each has a consumer in our loop). `supersedes` is already expressed by the
# package supersededBy field; `tested_by`/`supports` duplicate evidencePath — intentionally omitted.
EDGE_TYPES = {"extends", "contradicts", "addresses_gap", "invalidates"}

STORES = {"paper": "papers.jsonl", "edge": "edges.jsonl", "gap": "gaps.jsonl"}


class RegistryReject(Exception):
    """Reject-before-write: a registry payload broke an invariant; nothing is written."""

    def __init__(self, rule: str, detail: str):
        self.rule = rule
        self.detail = detail
        super().__init__(detail)


def store_path(target: str, root: str = "research_html") -> Path:
    return Path(root) / "data" / STORES[target]


def _read(path: Path) -> list:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _paper_key(rec: dict) -> str:
    return rec.get("id") or rec.get("arxiv") or rec.get("source_id") or ""


def _validate(target: str, payload: dict, existing: list):
    """Return the normalized record to append, or None if it is a duplicate (idempotent skip)."""
    if target == "paper":
        key = payload.get("id") or payload.get("arxiv") or payload.get("source_id")
        if not key:
            raise RegistryReject("paper-id-required", "paper needs id (or arxiv/source_id)")
        if not payload.get("title"):
            raise RegistryReject("paper-title-required", "paper needs a title")
        rec = {"id": key, "title": payload["title"], "url": payload.get("url", ""),
               "arxiv": payload.get("arxiv", ""), "source_id": payload.get("source_id", ""),
               "pkg": payload.get("pkg", "")}
        return None if any(_paper_key(e) == key for e in existing) else rec

    if target == "edge":
        frm, to, typ = payload.get("from"), payload.get("to"), payload.get("type")
        if not frm or not to:
            raise RegistryReject("edge-endpoints-required", "edge needs both from and to")
        if typ not in EDGE_TYPES:
            raise RegistryReject("edge-type-unknown", f"edge type must be one of {sorted(EDGE_TYPES)}")
        rec = {"from": frm, "to": to, "type": typ, "evidence": payload.get("evidence", "")}
        dup = any(e.get("from") == frm and e.get("to") == to and e.get("type") == typ for e in existing)
        return None if dup else rec

    if target == "gap":
        gid = payload.get("id")
        if not gid:
            raise RegistryReject("gap-id-required", "gap needs an id")
        if not payload.get("summary"):
            raise RegistryReject("gap-summary-required", "gap needs a summary")
        rec = {"id": gid, "summary": payload["summary"], "status": payload.get("status", "open")}
        return None if any(e.get("id") == gid for e in existing) else rec

    raise RegistryReject("unknown-target", f"unknown registry target {target!r}")


def add(target: str, payload: dict, *, root: str = "research_html"):
    """Validate + dedup + append. Returns (status, record|None, path); status ∈ {added, duplicate}."""
    if target not in STORES:
        raise RegistryReject("unknown-target", f"unknown registry target {target!r}")
    path = store_path(target, root)
    record = _validate(target, payload, _read(path))
    if record is None:
        return "duplicate", None, path
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return "added", record, path
