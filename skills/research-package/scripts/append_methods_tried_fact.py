#!/usr/bin/env python3
"""Append a methods_tried.csv row from a source result CSV row."""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

PIPELINE_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PIPELINE_ROOT))

from lib import package_facts  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo-root", default=".")
    p.add_argument("--pkg", required=True)
    p.add_argument("--exp-id", required=True)
    p.add_argument("--source-ref", required=True)
    p.add_argument("--method", required=True)
    p.add_argument("--hypothesis", required=True)
    p.add_argument("--gate", required=True)
    p.add_argument("--row-id", default="")
    return p


def _measured(source_row: dict[str, str]) -> str:
    return f"{source_row.get('metric', '')}={source_row.get('value', '')}{source_row.get('unit', '')}"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.repo_root)
    paths = package_facts.fact_paths(args.pkg, root=root)

    try:
        source_row = package_facts.find_row_by_ref(paths.tables_dir, args.source_ref)
        source_table, source_row_id = package_facts.split_source_ref(args.source_ref)
        verdict = source_row.get("verdict") or "INCONCLUSIVE"
        if source_row.get("source_type", "").lower() == "manual" and verdict == "PASS":
            raise package_facts.FactError("manual PASS source rows cannot be appended to methods_tried.csv")

        row = {
            "row_id": args.row_id or args.source_ref,
            "exp_id": args.exp_id,
            "method": args.method,
            "hypothesis": args.hypothesis,
            "gate": args.gate,
            "measured": _measured(source_row),
            "verdict": verdict,
            "evidencePath": source_row.get("source_artifact", ""),
            "source_table": source_table,
            "source_row": source_row_id,
            "source_artifact": source_row.get("source_artifact", ""),
            "extracted_at": dt.datetime.now(dt.UTC).astimezone().isoformat(timespec="seconds"),
        }
        output_csv = paths.tables_dir / "methods_tried.csv"
        package_facts.upsert_csv_rows(output_csv, package_facts.METHODS_TRIED_COLUMNS, [row])
    except (OSError, package_facts.FactError) as exc:
        print(f"append_methods_tried_fact: {exc}", file=sys.stderr)
        return 2

    print(f"wrote {output_csv.relative_to(root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
