#!/usr/bin/env python3
"""Read the current learning stores before proposal or execution work.

This is an agent-facing gate. It does not mutate dashboard state; it proves the
agent has loaded the current learnings/rules/gaps surface and fails closed when
the rule registry is malformed.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


RULES_PREFIX = "window.RESEARCH_RULES = "


def _node_eval_packages(root: Path) -> list[dict]:
    data_file = root / "data" / "research-packages.js"
    if not data_file.exists():
        return []
    script = (
        "const fs = require('fs');"
        "global.window = {};"
        f"eval(fs.readFileSync({json.dumps(str(data_file))}, 'utf8'));"
        "process.stdout.write(JSON.stringify(window.RESEARCH_PACKAGES || []));"
    )
    out = subprocess.check_output(["node", "-e", script], text=True)
    payload = json.loads(out)
    return payload if isinstance(payload, list) else []


def _load_rules(root: Path) -> list[dict]:
    path = root / "data" / "rules.js"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8").strip()
    if not text.startswith(RULES_PREFIX):
        raise ValueError(f"rules registry must start with {RULES_PREFIX!r}: {path}")
    payload = json.loads(text[len(RULES_PREFIX):].rstrip(";"))
    if not isinstance(payload, list):
        raise ValueError(f"rules registry must be a JSON array: {path}")
    return payload


def _load_jsonl(root: Path, rel: str) -> list[dict]:
    path = root / "data" / rel
    if not path.exists():
        return []
    out = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_no}: {exc}") from exc
    return out


def build_summary(root: Path) -> dict:
    errors: list[str] = []
    sources = {
        "packages": "missing",
        "rules": "missing",
        "gaps": "missing",
    }
    packages: list[dict] = []
    rules: list[dict] = []
    gaps: list[dict] = []

    try:
        packages = _node_eval_packages(root)
        sources["packages"] = "loaded" if (root / "data" / "research-packages.js").exists() else "missing"
    except Exception as exc:  # pragma: no cover - exact Node errors differ by version
        errors.append(f"packages: {exc}")

    try:
        rules = _load_rules(root)
        sources["rules"] = "loaded" if (root / "data" / "rules.js").exists() else "missing"
    except Exception as exc:
        errors.append(f"rules: {exc}")

    try:
        gaps = _load_jsonl(root, "gaps.jsonl")
        sources["gaps"] = "loaded" if (root / "data" / "gaps.jsonl").exists() else "missing"
    except Exception as exc:
        errors.append(f"gaps: {exc}")

    failed_methods = 0
    unresolved_methods = 0
    adopted_wins = 0
    for pkg in packages:
        methods = pkg.get("methodsTried") if isinstance(pkg, dict) else []
        if not isinstance(methods, list):
            continue
        for row in methods:
            verdict = str((row or {}).get("verdict", "")).upper()
            if verdict == "FAIL":
                failed_methods += 1
            elif verdict == "INCONCLUSIVE":
                unresolved_methods += 1
            elif verdict == "PASS" and str(pkg.get("category", "")).lower() == "success":
                adopted_wins += 1

    active_rules = sum(1 for row in rules if row.get("status") == "ACTIVE")
    open_gaps = sum(1 for row in gaps if row.get("status", "open") == "open")
    return {
        "ok": not errors,
        "root": str(root),
        "sources": sources,
        "counts": {
            "packages": len(packages),
            "active_rules": active_rules,
            "failed_methods": failed_methods,
            "unresolved_methods": unresolved_methods,
            "adopted_wins": adopted_wins,
            "open_gaps": open_gaps,
        },
        "errors": errors,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="research_html", help="dashboard root")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args(argv)

    summary = build_summary(Path(args.root))
    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        print(
            "learning_context "
            f"ok={summary['ok']} "
            f"packages={summary['counts']['packages']} "
            f"active_rules={summary['counts']['active_rules']} "
            f"failed_methods={summary['counts']['failed_methods']} "
            f"adopted_wins={summary['counts']['adopted_wins']} "
            f"open_gaps={summary['counts']['open_gaps']}"
        )
        for err in summary["errors"]:
            print(f"error: {err}")
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
