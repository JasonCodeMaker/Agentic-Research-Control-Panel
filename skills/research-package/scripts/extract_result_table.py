#!/usr/bin/env python3
"""Extract one result-table CSV row from a real JSON experiment artifact."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

PIPELINE_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PIPELINE_ROOT))

from lib import package_facts  # noqa: E402


def _nested_get(data: dict, dotted: str):
    current = data
    for part in dotted.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            raise package_facts.FactError(f"missing key path: {dotted}")
    return current


def _optional_nested_get(data: dict, dotted: str | None) -> str:
    if not dotted:
        return ""
    try:
        value = _nested_get(data, dotted)
    except package_facts.FactError:
        return ""
    return str(value)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo-root", default=".")
    p.add_argument("--pkg", required=True)
    p.add_argument("--exp-id", required=True)
    p.add_argument("--input", required=True, dest="input_path")
    p.add_argument("--metric", required=True)
    p.add_argument("--value-key", required=True)
    p.add_argument("--row-id", required=True)
    p.add_argument("--unit", default="")
    p.add_argument("--split", default="")
    p.add_argument("--split-key", default="")
    p.add_argument("--baseline", default="")
    p.add_argument("--validity", default="VALID", choices=sorted(package_facts.VALID_RESULT_VALIDITY))
    p.add_argument("--verdict", default="INCONCLUSIVE", choices=sorted(v for v in package_facts.VALID_EXPERIMENT_VERDICT if v))
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.repo_root)
    input_rel = Path(args.input_path)
    input_abs = root / input_rel
    try:
        data = json.loads(input_abs.read_text(encoding="utf-8"))
        value = _nested_get(data, args.value_key)
    except (OSError, json.JSONDecodeError, package_facts.FactError) as exc:
        print(f"extract_result_table: {exc}", file=sys.stderr)
        return 2

    paths = package_facts.fact_paths(args.pkg, root=root)
    output_csv = paths.tables_dir / f"result_table_{args.exp_id}.csv"
    source_mtime = dt.datetime.fromtimestamp(input_abs.stat().st_mtime, dt.UTC).isoformat()
    extracted_at = dt.datetime.now(dt.UTC).astimezone().isoformat(timespec="seconds")
    split = args.split or _optional_nested_get(data, args.split_key)
    row = {
        "row_id": args.row_id,
        "exp_id": args.exp_id,
        "metric": args.metric,
        "value": str(value),
        "unit": args.unit,
        "split": split,
        "baseline": args.baseline,
        "verdict": args.verdict,
        "validity": args.validity,
        "source_artifact": str(input_rel),
        "source_mtime": source_mtime,
        "extractor": "extract_result_table.py",
        "extracted_at": extracted_at,
    }
    package_facts.upsert_csv_rows(output_csv, package_facts.RESULT_COLUMNS, [row])

    manifest = {
        "exp_id": args.exp_id,
        "inputs": [str(input_rel)],
        "extractor": "extract_result_table.py",
        "output_csv": str(output_csv.relative_to(root)),
        "generated_at": extracted_at,
    }
    paths.extractors_dir.mkdir(parents=True, exist_ok=True)
    (paths.extractors_dir / f"{args.exp_id}.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {output_csv.relative_to(root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
