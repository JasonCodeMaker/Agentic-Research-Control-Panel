#!/usr/bin/env python3
"""Audit package migration state for JS/CSV fact-backed projections."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace


def _load_package_facts_module():
    parents = Path(__file__).resolve().parents
    candidates = [
        parents[5] if len(parents) > 5 else None,  # source tree
        parents[2] if len(parents) > 2 else None,  # installed dashboard
        Path.cwd(),
    ]
    for root in candidates:
        if root is not None and (root / "lib" / "package_facts").exists():
            sys.path.insert(0, str(root))
            from lib import package_facts
            return package_facts

    class _PackageFactsFallback:
        @staticmethod
        def fact_paths(pkg: str, root: Path | str = Path(".")):
            root = Path(root)
            base = root / "research_html" / "data" / "packages"
            package_data_dir = base / pkg
            return SimpleNamespace(
                root=root,
                pkg=pkg,
                package_data_dir=package_data_dir,
                facts_js=base / f"{pkg}.facts.js",
                tables_dir=package_data_dir / "tables",
                extractors_dir=package_data_dir / "extractors",
            )

    return _PackageFactsFallback


package_facts = _load_package_facts_module()


STATES = ("legacy", "partial", "fact-backed", "stale")


def _node_dump_script(root: Path) -> str:
    data_dir = root / "research_html" / "data"
    return f"""
const fs = require('fs');
global.window = {{}};
global.document = {{ addEventListener: () => {{}} }};
eval(fs.readFileSync({json.dumps(str(data_dir / "schema.js"))}, 'utf8'));
eval(fs.readFileSync({json.dumps(str(data_dir / "research-packages.js"))}, 'utf8'));
process.stdout.write(JSON.stringify({{
  packages: window.RESEARCH_PACKAGES || [],
}}, null, 2));
"""


def load_packages(root: Path) -> list[dict]:
    dump_script = root / "research_html" / "scripts" / "dump_packages.js"
    cmd = ["node", str(dump_script)] if dump_script.exists() else ["node", "-e", _node_dump_script(root)]
    try:
        return json.loads(subprocess.check_output(cmd, text=True)).get("packages") or []
    except (FileNotFoundError, subprocess.CalledProcessError, json.JSONDecodeError):
        path = root / "research_html" / "data" / "research-packages.js"
        text = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
        return [{"id": match.group(1)} for match in re.finditer(r"\bid\s*:\s*['\"]([^'\"]+)['\"]", text)]


def _tables(paths) -> dict[str, bool]:
    return {
        "result": (paths.tables_dir / "result_gate.csv").exists()
        or bool(list(paths.tables_dir.glob("result_table_*.csv"))),
        "tracker": (paths.tables_dir / "live_checks.csv").exists()
        or (paths.tables_dir / "resource_allocation.csv").exists(),
        "methods": (paths.tables_dir / "methods_tried.csv").exists(),
    }


def _required_pages(tables: dict[str, bool]) -> list[str]:
    pages = []
    if tables["result"]:
        pages.append("results.html")
    if tables["tracker"]:
        pages.append("tracker.html")
    return pages


def package_migration_state(pkg_id: str, root: Path) -> dict:
    paths = package_facts.fact_paths(pkg_id, root=root)
    if not paths.package_data_dir.exists():
        return {
            "id": pkg_id,
            "state": "legacy",
            "tables": {"result": False, "tracker": False, "methods": False},
            "requiredPages": [],
            "stale": [],
        }

    tables = _tables(paths)
    required_pages = _required_pages(tables)
    stale = []
    for page in required_pages:
        try:
            package_facts.assert_page_projection_fresh(pkg_id, page, root=root)
        except package_facts.FactError as exc:
            stale.append(f"{page}: {exc}")

    if stale:
        state = "stale"
    elif all(tables.values()):
        state = "fact-backed"
    else:
        state = "partial"

    return {
        "id": pkg_id,
        "state": state,
        "tables": tables,
        "requiredPages": required_pages,
        "stale": stale,
    }


def audit_packages(root: Path, pkg_filter: str | None = None) -> dict:
    packages = load_packages(root)
    rows = []
    for pkg in packages:
        pkg_id = pkg.get("id")
        if not pkg_id or (pkg_filter and pkg_id != pkg_filter):
            continue
        rows.append(package_migration_state(pkg_id, root))
    counts = {state: 0 for state in STATES}
    for row in rows:
        counts[row["state"]] += 1
    return {"counts": counts, "packages": rows}


def render_text(report: dict) -> str:
    lines = ["=== fact-migration audit ==="]
    for row in report["packages"]:
        flags = ", ".join(name for name, present in row["tables"].items() if present) or "no fact tables"
        lines.append(f"[{row['state']}] {row['id']} ({flags})")
        for stale in row["stale"]:
            lines.append(f"  stale: {stale}")
    counts = " ".join(f"{state}={report['counts'][state]}" for state in STATES)
    lines.append(f"--- {counts}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--pkg")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = audit_packages(args.repo_root, pkg_filter=args.pkg)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
