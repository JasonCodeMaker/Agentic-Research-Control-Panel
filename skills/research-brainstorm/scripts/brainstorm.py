#!/usr/bin/env python3
"""research-brainstorm: the pre-package idea store + the direction-proposal builder.

A brainstorm is a cheap, pre-SSOT, pre-package idea that lives on the dashboard
brainstorm lane (research_html/data/brainstorms.js). Ideas are not gated by
research-op. They touch the SSOT only at conversion, when one or more ideas are
synthesized into a single Direction proposal submitted through the Triage gate.
"""

from __future__ import annotations

import argparse
from html import escape as html_escape
import json
import re
from datetime import datetime, timezone
from pathlib import Path
import sys

PIPELINE_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PIPELINE_ROOT / "lib"))

import scope_ssot  # noqa: E402

DIRECTION_FIELDS = ("hypothesis", "metric", "baselines", "success_gate")


def brainstorms_path(dashboard_root) -> Path:
    """The canonical pre-package idea store, read by the dashboard brainstorm lane."""
    return Path(dashboard_root) / "data" / "brainstorms.js"


def read_brainstorms(dashboard_root) -> list[dict]:
    """Parse window.BRAINSTORMS from the data file (empty list if absent)."""
    path = brainstorms_path(dashboard_root)
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    body = text[text.index("=") + 1:].strip()
    if body.endswith(";"):
        body = body[:-1]
    return json.loads(body)


def write_brainstorms(dashboard_root, items: list[dict]) -> Path:
    """Serialize the idea list back to window.BRAINSTORMS = [...]."""
    path = brainstorms_path(dashboard_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("window.BRAINSTORMS = " + json.dumps(items, indent=2, ensure_ascii=False) + ";\n",
                    encoding="utf-8")
    return path


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "idea"


def _created_date(entry: dict) -> str:
    created_at = str(entry.get("created_at") or "")
    if re.match(r"^\d{4}-\d{2}-\d{2}", created_at):
        return created_at[:10]
    return datetime.now(timezone.utc).date().isoformat()


def brainstorm_detail_path(entry: dict) -> str:
    """Default readable HTML page path for a brainstorm idea."""
    return f"brainstorm/{_created_date(entry)}-{entry['id']}.html"


def render_brainstorm_html(entry: dict, *, language: str = "en") -> str:
    """Render a compact, English-by-default brainstorm page for a pre-package idea."""
    title = html_escape(str(entry.get("title") or entry["id"]))
    idea = html_escape(str(entry.get("idea") or ""))
    rough_metric = html_escape(str(entry.get("rough_metric") or "Not specified yet"))
    created = html_escape(str(entry.get("created_at") or "")[:10])
    idea_id = html_escape(str(entry["id"]))
    refs = entry.get("lit_refs") or []
    if refs:
        refs_html = "\n".join(f"              <li>{html_escape(str(ref))}</li>" for ref in refs)
    else:
        refs_html = '              <li class="muted">No literature grounding recorded yet.</li>'

    return f"""<!doctype html>
<html lang="{html_escape(language or 'en')}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Brainstorm - {title}</title>
  <link rel="stylesheet" href="../assets/research.css">
  <style>
    .callout {{ border-left: 4px solid var(--clay); background: #fbf4ea; padding: 12px 16px; margin: 16px 0; font-size: 14px; }}
    .callout.note {{ border-left-color: #56708e; background: #eef2f8; }}
    .tagline {{ color: var(--g500); font-family: var(--mono); font-size: 11px; letter-spacing: 0.10em; text-transform: uppercase; }}
    .field-grid {{ display: grid; grid-template-columns: 180px minmax(0, 1fr); gap: 12px 18px; margin-top: 16px; }}
    .field-grid dt {{ color: var(--g500); font-family: var(--mono); font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase; }}
    .field-grid dd {{ margin: 0; color: var(--slate); }}
    .muted {{ color: var(--g500); font-style: italic; }}
    @media (max-width: 720px) {{ .field-grid {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body data-page="brainstorm">
  <div class="shell">
    <div class="callout note" style="margin:0 0 18px;">
      <span class="tagline">pre-package idea{(' - ' + created) if created else ''}</span>
      <p style="margin:6px 0 0;">This is an automatically generated brainstorm page. It is readable by default, but it is not a ratified Direction, not a package, and not an SSOT change.</p>
    </div>

    <header class="masthead" data-section="masthead">
      <div class="eyebrow">Brainstorm &middot; pre-package idea</div>
      <h1>{title}</h1>
      <p class="lead">{idea}</p>
      <div class="toolbar">
        <a class="pill" href="../categories/brainstorm/index.html">Brainstorm lane</a>
        <a class="pill" href="../index.html">Dashboard</a>
      </div>
    </header>

    <main>
      <section data-section="idea">
        <article class="module-card">
          <h2>Idea Snapshot</h2>
          <dl class="field-grid">
            <dt>Idea ID</dt>
            <dd><code>{idea_id}</code></dd>
            <dt>Rough metric</dt>
            <dd>{rough_metric}</dd>
            <dt>Grounding</dt>
            <dd>
              <ul style="margin:0; padding-left:18px;">
{refs_html}
              </ul>
            </dd>
            <dt>Next decision</dt>
            <dd>Shape this hunch into a typed spec only when the user is ready: <code>{{hypothesis, metric, baselines, success_gate}}</code>. Submit any Direction through Triage; do not commit the SSOT from this page.</dd>
          </dl>
        </article>
      </section>
    </main>
  </div>
</body>
</html>
"""


def write_brainstorm_html_page(dashboard_root, entry: dict) -> str:
    """Write the default HTML detail page and return the dashboard-relative path."""
    detail_path = entry.get("detailPath") or brainstorm_detail_path(entry)
    entry["detailPath"] = detail_path
    path = Path(dashboard_root) / detail_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_brainstorm_html(entry, language=entry.get("page_language", "en")), encoding="utf-8")
    return detail_path


def add_brainstorm(dashboard_root, record: dict) -> str:
    """Append a pre-package idea; assign a unique id (from title) and a timestamp. Returns the id."""
    items = read_brainstorms(dashboard_root)
    existing = {i["id"] for i in items}
    bid = record.get("id") or _slug(record.get("title", "idea"))
    if bid in existing:
        n = 2
        while f"{bid}-{n}" in existing:
            n += 1
        bid = f"{bid}-{n}"
    entry = {**record, "id": bid}
    entry.setdefault("created_at", datetime.now(timezone.utc).isoformat())
    entry.setdefault("page_language", "en")
    write_brainstorm_html_page(dashboard_root, entry)
    items.append(entry)
    write_brainstorms(dashboard_root, items)
    return bid


def remove_brainstorm(dashboard_root, idea_id: str) -> bool:
    """Remove an idea by id. Returns True if one was removed, False if absent (idempotent)."""
    items = read_brainstorms(dashboard_root)
    kept = [i for i in items if i["id"] != idea_id]
    if len(kept) == len(items):
        return False
    write_brainstorms(dashboard_root, kept)
    return True


def consume_brainstorms(dashboard_root, idea_ids: list[str]) -> list[dict]:
    """Return the named idea records (in id order, skipping missing) and remove them from the store."""
    items = read_brainstorms(dashboard_root)
    by_id = {i["id"]: i for i in items}
    taken = [by_id[i] for i in idea_ids if i in by_id]
    remove = set(idea_ids)
    write_brainstorms(dashboard_root, [i for i in items if i["id"] not in remove])
    return taken


def active_project_ids(transitions_path) -> list[str]:
    """Committed active Project node ids — the precondition + parent for a Direction."""
    projection = scope_ssot.fold(scope_ssot.read_log(transitions_path))
    return [nid for nid, n in projection.items()
            if n.get("level") == "project" and n.get("status") == "ACTIVE"]


def active_project_context(transitions_path) -> list[dict]:
    """Committed active Project context that constrains Direction proposals."""
    projection = scope_ssot.fold(scope_ssot.read_log(transitions_path))
    projects = scope_ssot.active_nodes(projection, "project")
    return [
        {
            "id": node["id"],
            "goal": (node.get("spec") or {}).get("goal"),
            "out_of_scope": (node.get("spec") or {}).get("out_of_scope", []),
        }
        for node in projects
    ]


def direction_ready(spec: dict) -> bool:
    """True iff the spec carries all four direction fields, non-empty (the conversion gate)."""
    for field in DIRECTION_FIELDS:
        value = spec.get(field)
        if value is None or value == "" or value == [] or value == {}:
            return False
    return True


def build_direction_proposal(node_id: str, spec: dict, *, parent_project_id: str,
                             source: str, source_brainstorms: list[str] | None = None,
                             item_id: str | None = None, change: str | None = None,
                             rationale: str | None = None) -> dict:
    """Build a validated level=direction Triage item. Raises RuleViolation on a bad spec."""
    node = {
        "id": node_id, "level": "direction", "parents": [parent_project_id], "version": 1,
        "status": "ACTIVE", "spec": spec, "source": source,
    }
    scope_ssot.validate_node(node)  # reject-before-propose: direction-legal spec only
    return {
        "id": item_id or f"direction-{_slug(node_id.rsplit('/', 1)[-1])}",
        "level": "direction",
        "node_id": node_id,
        "op": "create",
        "gate": scope_ssot.REQUIRED_GATE["direction"],
        "change": change or f"Create direction {node_id} from brainstormed idea(s)",
        "rationale": rationale or "Brainstormed idea(s) converged into a testable direction; PM must ratify.",
        "proposed_spec": spec,
        "proposed_node": node,
        "source_brainstorms": list(source_brainstorms or []),
        "post_accept_actions": [],
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    pa = sub.add_parser("add", help="append a pre-package idea to brainstorms.js")
    pa.add_argument("--root", default="research_html")
    pa.add_argument("--title", required=True)
    pa.add_argument("--idea", required=True)
    pa.add_argument("--id", default=None)
    pa.add_argument("--rough-metric", default=None)
    pa.add_argument("--lit-refs", default=None, help="JSON list of source refs")
    pa.add_argument("--page-language", default="en", help="HTML page language; default is English")

    pl = sub.add_parser("list", help="print window.BRAINSTORMS as JSON")
    pl.add_argument("--root", default="research_html")

    pr = sub.add_parser("remove", help="remove an idea by id")
    pr.add_argument("--root", default="research_html")
    pr.add_argument("--id", required=True)

    pc = sub.add_parser("check-project", help="list committed active Project node ids")
    pc.add_argument("--transitions", default="outputs/_scope/transitions.jsonl")

    pd = sub.add_parser("direction-ready", help="check a spec is conversion-ready")
    pd.add_argument("--spec", required=True)

    pb = sub.add_parser("build-proposal", help="build a validated direction Triage item")
    pb.add_argument("--node-id", required=True)
    pb.add_argument("--parent-project-id", required=True)
    pb.add_argument("--spec", required=True, help="JSON: hypothesis, metric, baselines, success_gate")
    pb.add_argument("--source", required=True)
    pb.add_argument("--source-brainstorms", default="[]", help="JSON list of idea ids")
    pb.add_argument("--item-id", default=None)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "add":
        record = {"title": args.title, "idea": args.idea}
        if args.id:
            record["id"] = args.id
        if args.rough_metric:
            record["rough_metric"] = args.rough_metric
        if args.lit_refs:
            record["lit_refs"] = json.loads(args.lit_refs)
        record["page_language"] = args.page_language
        bid = add_brainstorm(args.root, record)
        item = next(i for i in read_brainstorms(args.root) if i["id"] == bid)
        print(json.dumps({"id": bid, "detailPath": item.get("detailPath")}, ensure_ascii=False))
    elif args.cmd == "list":
        print(json.dumps(read_brainstorms(args.root), ensure_ascii=False))
    elif args.cmd == "remove":
        print(json.dumps({"removed": remove_brainstorm(args.root, args.id)}, ensure_ascii=False))
    elif args.cmd == "check-project":
        projects = active_project_context(args.transitions)
        print(json.dumps({
            "active_project_ids": [p["id"] for p in projects],
            "active_projects": projects,
        }, ensure_ascii=False))
    elif args.cmd == "direction-ready":
        print(json.dumps({"ready": direction_ready(json.loads(args.spec))}, ensure_ascii=False))
    elif args.cmd == "build-proposal":
        item = build_direction_proposal(
            args.node_id, json.loads(args.spec), parent_project_id=args.parent_project_id,
            source=args.source, source_brainstorms=json.loads(args.source_brainstorms),
            item_id=args.item_id)
        print(json.dumps(item, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
