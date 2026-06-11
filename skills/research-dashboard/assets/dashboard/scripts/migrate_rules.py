#!/usr/bin/env python3
"""One-shot migration: legacy rule stores → data/rules.js (dry-run default, --write commits).

Lifts four legacy stores into the unified rules registry:
  1. per-package `bindingRules[]` in data/research-packages.js  → level=package, kind=binding
  2. analysis.html Rules `<li>`s                                → level=package, kind=lesson
  3. outputs/_learned/rules.md bullets                          → level=project, kind=constraint
  4. RESEARCH_PROJECT_PROFILE.constraints                       → level=project, kind=constraint
then (--write) strips the migrated sources. The regex stripping is approximate by design —
this is one-shot tooling: dry-run first, and run `learnings_lint.py lint-rules` + `lint-status`
after a --write.
"""

import argparse
import json
import re
from pathlib import Path

PREFIX = "window.RESEARCH_RULES = "
SOURCE = {"binding": "migrated bindingRules[]", "lesson": "migrated analysis.html",
          "learned": "migrated outputs/_learned/rules.md", "constraint": "migrated profile constraints"}


def slugify(text: str) -> str:
    """Kebab slug from rule prose (first 6 words)."""
    words = re.findall(r"[a-z0-9]+", text.lower())[:6]
    return "-".join(words) or "rule"


def load_registry(root: Path) -> list:
    path = root / "data" / "rules.js"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8").strip()
    if not text.startswith(PREFIX):
        raise ValueError(f"{path} must start with {PREFIX!r}")
    rows = json.loads(text[len(PREFIX):].rstrip(";"))
    if not isinstance(rows, list):
        raise ValueError(f"{path} must contain a JSON array")
    return rows


def matching_span(text: str, start: int, open_ch: str, close_ch: str) -> tuple[int, int]:
    """Return the inclusive/exclusive span for a balanced bracket/object."""
    depth = 0
    quote = ""
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if quote:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = ""
            continue
        if ch in ("'", '"'):
            quote = ch
        elif ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return start, i + 1
    raise ValueError(f"unclosed {open_ch}{close_ch} span")


def package_blocks(pkgs_text: str) -> list[tuple[int, int, str]]:
    """Top-level package object spans from window.RESEARCH_PACKAGES."""
    m = re.search(r"RESEARCH_PACKAGES\s*=\s*\[", pkgs_text)
    if not m:
        return []
    arr_start = pkgs_text.index("[", m.start())
    arr_start, arr_end = matching_span(pkgs_text, arr_start, "[", "]")
    body_start = arr_start + 1
    body = pkgs_text[body_start:arr_end - 1]
    spans = []
    i = 0
    while i < len(body):
        if body[i] == "{":
            s, e = matching_span(body, i, "{", "}")
            spans.append((body_start + s, body_start + e, body[s:e]))
            i = e
        else:
            i += 1
    return spans


def top_level_array_value(block: str, field: str) -> str | None:
    """Return a top-level array field value from one object block."""
    depth = 0
    quote = ""
    escape = False
    i = 0
    while i < len(block):
        ch = block[i]
        if quote:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = ""
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
        elif ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
        elif depth == 1 and block.startswith(field, i):
            before = block[i - 1] if i else " "
            after = block[i + len(field)] if i + len(field) < len(block) else ""
            if not (before.isalnum() or before == "_") and after == ":":
                value_start = i + len(field) + 1
                while value_start < len(block) and block[value_start].isspace():
                    value_start += 1
                if value_start < len(block) and block[value_start] == "[":
                    s, e = matching_span(block, value_start, "[", "]")
                    return block[s:e]
        i += 1
    return None


def remove_top_level_array_field(block: str, field: str) -> str:
    """Remove one top-level array field from an object block."""
    pattern = re.compile(rf"\s*{re.escape(field)}\s*:")
    for m in pattern.finditer(block):
        depth = 0
        quote = ""
        escape = False
        for ch in block[:m.start()]:
            if quote:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == quote:
                    quote = ""
            elif ch in ("'", '"'):
                quote = ch
            elif ch in "{[":
                depth += 1
            elif ch in "}]":
                depth -= 1
        if depth != 1:
            continue
        value_start = m.end()
        while value_start < len(block) and block[value_start].isspace():
            value_start += 1
        if value_start >= len(block) or block[value_start] != "[":
            continue
        _, value_end = matching_span(block, value_start, "[", "]")
        end = value_end
        if end < len(block) and block[end] == ",":
            end += 1
        return block[:m.start()] + block[end:]
    return block


def collect(root: Path, outputs: Path) -> tuple[list, dict]:
    """Gather migration rows + the source-stripping actions, without writing."""
    rows, actions = [], {}
    pkgs_path = root / "data" / "research-packages.js"
    pkgs_text = pkgs_path.read_text(encoding="utf-8") if pkgs_path.exists() else ""
    # 1. bindingRules[] per package
    for _start, _end, block in package_blocks(pkgs_text):
        m_id = re.search(r'id:\s*["\']([^"\']+)["\']', block)
        rules_block = top_level_array_value(block, "bindingRules")
        if not m_id or rules_block is None:
            continue
        pkg_id = m_id.group(1)
        for m in re.finditer(r'\{[^{}]*\}', block):
            if m.start() < block.find(rules_block) or m.end() > block.find(rules_block) + len(rules_block):
                continue
            entry = dict(re.findall(r'(\w+):\s*["\']([^"\']*)["\']', m.group(0)))
            if entry.get("rule"):
                rows.append({"id": f"{pkg_id}#{slugify(entry['rule'])}", "level": "package",
                             "pkg": pkg_id, "kind": "binding", "title": entry["rule"][:60],
                             "text": entry["rule"], "rationale": entry.get("rationale", "migrated"),
                             "source": SOURCE["binding"], "origin": "migration",
                             "status": "ACTIVE", "addedAt": entry.get("addedAt", "migrated")})
    # 2. analysis.html rule <li>s
    for analysis in sorted(root.glob("packages/*/analysis.html")):
        pkg_id = analysis.parent.name
        for slug, body in re.findall(r'<li[^>]*id="rule-([^"]+)"[^>]*>([\s\S]*?)</li>',
                                     analysis.read_text(encoding="utf-8")):
            prose = re.sub(r"<[^>]+>", "", body).strip()
            if prose and "No rules recorded" not in prose:
                rows.append({"id": f"{pkg_id}#{slug}", "level": "package", "pkg": pkg_id,
                             "kind": "lesson", "title": prose[:60], "text": prose,
                             "rationale": "migrated analysis rule", "source": SOURCE["lesson"],
                             "origin": "migration", "status": "ACTIVE", "addedAt": "migrated"})
    # 3. learned rules.md bullets
    learned = outputs / "_learned" / "rules.md"
    if learned.exists():
        for line in learned.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith(("- ", "* ")):
                prose = line.strip()[2:].strip()
                rows.append({"id": f"PRJ-{slugify(prose)}", "level": "project", "kind": "constraint",
                             "title": prose[:60], "text": prose, "rationale": "migrated learned rule",
                             "source": SOURCE["learned"], "origin": "migration",
                             "status": "ACTIVE", "addedAt": "migrated"})
        actions["delete_learned"] = learned
    # 4. profile constraints
    m = re.search(r'constraints:\s*\[([\s\S]*?)\]', pkgs_text)
    if m:
        for prose in re.findall(r'["\']([^"\']+)["\']', m.group(1)):
            rows.append({"id": f"PRJ-{slugify(prose)}", "level": "project", "kind": "constraint",
                         "title": prose[:60], "text": prose, "rationale": "migrated profile constraint",
                         "source": SOURCE["constraint"], "origin": "migration",
                         "status": "ACTIVE", "addedAt": "migrated"})
    actions["pkgs_path"] = pkgs_path
    return rows, actions


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default="research_html")
    ap.add_argument("--outputs", default="outputs")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    root, outputs = Path(args.root), Path(args.outputs)
    existing = load_registry(root)
    have = {r["id"] for r in existing}
    rows, actions = collect(root, outputs)
    rows = [r for r in rows if r["id"] not in have]
    print(f"migrate_rules: {len(rows)} rows to add ({'write' if args.write else 'dry-run'})")
    for r in rows:
        print(f"  + {r['id']}  [{r['level']}/{r['kind']}]")
    if not args.write:
        return 0
    if rows:
        (root / "data" / "rules.js").write_text(
            PREFIX + json.dumps(existing + rows, indent=2, ensure_ascii=False) + ";\n",
            encoding="utf-8")
    pkgs_path = actions["pkgs_path"]
    if pkgs_path.exists():
        text = pkgs_path.read_text(encoding="utf-8")
        blocks = package_blocks(text)
        rebuilt = []
        cursor = 0
        for start, end, block in blocks:
            rebuilt.append(text[cursor:start])
            rebuilt.append(remove_top_level_array_field(block, "bindingRules"))
            cursor = end
        rebuilt.append(text[cursor:])
        text = "".join(rebuilt)
        text = re.sub(r'(RESEARCH_PROJECT_PROFILE\s*=\s*\{[\s\S]*?)\s*constraints:\s*\[[\s\S]*?\],?',
                      r'\1', text, count=1)
        pkgs_path.write_text(text, encoding="utf-8")
    if "delete_learned" in actions:
        actions["delete_learned"].unlink()
    print("sources stripped: bindingRules[], constraints, rules.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
