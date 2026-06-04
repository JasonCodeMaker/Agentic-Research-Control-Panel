"""I/O loader + CLI for the Context Pack.

Reads the pipeline's existing stores (read-only) and writes two artifacts:
  outputs/<pkg>/context_pack.{md,json}   — full per-direction pack (agent working context)
  research_html/data/context-core.js     — durable, direction-independent project core
                                            (drives the human surface + cross-package reflect)

research-packages.js is read through the canonical node dumper; every other source
degrades gracefully (missing → that section is simply absent from the pack).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # lib/ on path for scope_ssot
import scope_ssot  # noqa: E402

from context_pack import assemble, render_md, render_json, is_stale  # noqa: E402

_RULE_RE = re.compile(r'<li[^>]*id="rule-([a-z0-9-]+)"[^>]*>(.*?)</li>', re.DOTALL | re.IGNORECASE)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _strip_html(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"&amp;", "&", s)
    s = re.sub(r"&[a-z]+;", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def load_packages(root: str) -> list:
    """Read research-packages.js via the canonical node dumper. Graceful: [] on any failure."""
    dump = Path(root) / "scripts" / "dump_packages.js"
    if not dump.exists():
        return []
    try:
        out = subprocess.check_output(["node", str(dump)], text=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        return []
    try:
        return json.loads(out).get("packages", []) or []
    except (json.JSONDecodeError, AttributeError):
        return []


def load_learned_rules(path: str) -> list:
    p = Path(path)
    if not p.exists():
        return []
    rules = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(("- ", "* ")):
            rules.append(line[2:].strip())
    return rules


def load_analysis_rules(root: str, packages: list) -> list:
    out = []
    for pkg in packages:
        pid = pkg.get("id")
        if not pid:
            continue
        f = Path(root) / "packages" / pid / "analysis.html"
        if not f.exists():
            continue
        for slug, body in _RULE_RE.findall(f.read_text(encoding="utf-8")):
            prose = _strip_html(body)
            if prose and "No rules recorded yet" not in prose:
                out.append({"pkg": pid, "slug": slug, "prose": prose})
    return out


def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default
    return data if isinstance(data, type(default)) else default


def load_registry(root: str, name: str) -> list:
    """Read a project-level knowledge registry JSONL (papers/edges/gaps). [] if absent."""
    path = Path(root) / "data" / name
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def load_banlist(pkg_id: str) -> list:
    return _load_json(Path("outputs") / pkg_id / "ideate" / "banlist.json", [])


def load_sources(pkg_id: str) -> dict:
    return _load_json(Path("outputs") / pkg_id / "lit" / "sources.json", {})


def resolve_direction(packages: list, pkg_id: str, transitions_path: str):
    """Active direction node + its scope_version for a package (None, 0 if unresolved)."""
    node_id = next((p.get("sourceScopeNode") for p in packages if p.get("id") == pkg_id), None)
    if not node_id:
        return None, 0
    node = scope_ssot.fold(scope_ssot.read_log(transitions_path)).get(node_id)
    if node is None:
        return None, 0
    return node, node.get("version", 0)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build(root: str, pkg_id: str, *, transitions_path: str = "outputs/_scope/transitions.jsonl",
          learned_path: str = "outputs/_learned/rules.md", budget_chars: int = 8000,
          generated_at: str | None = None):
    """Load stores → assemble full + core packs → write the three artifacts."""
    generated_at = generated_at or _now_iso()
    packages = load_packages(root)
    learned_rules = load_learned_rules(learned_path)
    analysis_rules = load_analysis_rules(root, packages)
    direction_node, scope_version = resolve_direction(packages, pkg_id, transitions_path)
    # Project-level knowledge registries (cross-package → belong in both full + core).
    papers_registry = load_registry(root, "papers.jsonl")
    edges = load_registry(root, "edges.jsonl")
    gaps = load_registry(root, "gaps.jsonl")

    full = assemble({
        "direction_node": direction_node, "active_pkg": pkg_id, "scope_version": scope_version,
        "generated_at": generated_at, "packages": packages, "learned_rules": learned_rules,
        "analysis_rules": analysis_rules, "banlist": load_banlist(pkg_id),
        "papers": load_sources(pkg_id),
        "papers_registry": papers_registry, "edges": edges, "gaps": gaps,
    }, budget_chars=budget_chars)

    # Durable core: direction-independent cross-package knowledge only (no per-direction overlay).
    core = assemble({
        "direction_node": None, "active_pkg": None, "scope_version": scope_version,
        "generated_at": generated_at, "packages": packages, "learned_rules": learned_rules,
        "analysis_rules": analysis_rules, "banlist": [], "papers": {},
        "papers_registry": papers_registry, "edges": edges, "gaps": gaps,
    }, budget_chars=budget_chars)

    _write(Path("outputs") / pkg_id / "context_pack.md", render_md(full))
    _write(Path("outputs") / pkg_id / "context_pack.json",
           json.dumps(render_json(full), indent=2, ensure_ascii=False) + "\n")
    _write(Path(root) / "data" / "context-core.js",
           "window.RESEARCH_CONTEXT_CORE = "
           + json.dumps(render_json(core), indent=2, ensure_ascii=False) + ";\n")
    return full, core


def ensure_fresh(root: str, pkg_id: str, *, transitions_path: str = "outputs/_scope/transitions.jsonl",
                 learned_path: str = "outputs/_learned/rules.md", budget_chars: int = 8000,
                 generated_at: str | None = None) -> bool:
    """Rebuild the pack iff it is missing or stale (scope advanced). Returns True if it rebuilt.

    This is the staleness + backfill contract a consumer runs before reading the pack.
    """
    pack_json = Path("outputs") / pkg_id / "context_pack.json"
    if pack_json.exists():
        try:
            pj = json.loads(pack_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pj = None
        if pj is not None:
            _, ver = resolve_direction(load_packages(root), pkg_id, transitions_path)
            if not is_stale(pj, ver):
                return False
    build(root, pkg_id, transitions_path=transitions_path, learned_path=learned_path,
          budget_chars=budget_chars, generated_at=generated_at)
    return True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build the Context Pack for a package.")
    ap.add_argument("--pkg", required=True)
    ap.add_argument("--root", default="research_html")
    ap.add_argument("--transitions", default="outputs/_scope/transitions.jsonl")
    ap.add_argument("--learned", default="outputs/_learned/rules.md")
    ap.add_argument("--budget-chars", type=int, default=8000)
    ap.add_argument("--if-stale", action="store_true",
                    help="rebuild only when the pack is missing or the scope version advanced")
    args = ap.parse_args(argv)
    if args.if_stale:
        rebuilt = ensure_fresh(args.root, args.pkg, transitions_path=args.transitions,
                               learned_path=args.learned, budget_chars=args.budget_chars)
        print(f"context_pack {'rebuilt' if rebuilt else 'already fresh'} for {args.pkg}")
        return 0
    full, _ = build(args.root, args.pkg, transitions_path=args.transitions,
                    learned_path=args.learned, budget_chars=args.budget_chars)
    print(f"context_pack → outputs/{args.pkg}/context_pack.md "
          f"({len(full.sections)} sections); core → {args.root}/data/context-core.js")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
