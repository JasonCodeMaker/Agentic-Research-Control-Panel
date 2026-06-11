#!/usr/bin/env python3
"""Render tracker CSV facts into tracker.html."""

from __future__ import annotations

import argparse
import html
import re
import sys
from datetime import date
from pathlib import Path

PIPELINE_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PIPELINE_ROOT))

from lib import package_facts  # noqa: E402


def esc(value) -> str:
    return html.escape(str(value or ""), quote=True)


def _read_valid_csv(path: Path, columns: list[str]) -> list[dict[str, str]]:
    rows = package_facts.read_csv_rows(path)
    for index, row in enumerate(rows):
        if None in row:
            raise package_facts.FactError(f"malformed CSV row {index + 1} in {path}")
        if not row.get("row_id"):
            raise package_facts.FactError(f"CSV row {index + 1} in {path} has no row_id")
        for col in columns:
            row.setdefault(col, "")
    return rows


def _replace_tbody(text: str, table_body: str, rows_html: str) -> str:
    pat = re.compile(
        r'(<tbody[^>]*data-table-body="' + re.escape(table_body) + r'"[^>]*>)(.*?)(</tbody>)',
        re.DOTALL,
    )
    if not pat.search(text):
        raise package_facts.FactError(f"tracker.html missing {table_body} tbody")
    return pat.sub(lambda m: m.group(1) + "\n" + rows_html + "\n          " + m.group(3), text, count=1)


def _set_attr(tag: str, name: str, value: str) -> str:
    tag = re.sub(r"\s+" + re.escape(name) + r'="[^"]*"', "", tag)
    return tag + f' {name}="{esc(value)}"'


def _mark_table(text: str, data_table: str, source: str, revision: str) -> str:
    pat = re.compile(
        r'(<table\b(?=[^>]*data-table="' + re.escape(data_table) + r'")[^>]*)(>)',
        re.DOTALL,
    )
    if not pat.search(text):
        raise package_facts.FactError(f"tracker.html missing {data_table} table")

    def repl(match: re.Match) -> str:
        tag = _set_attr(match.group(1), "data-source", source)
        tag = _set_attr(tag, "data-fact-revision", revision)
        return tag + match.group(2)

    return pat.sub(repl, text, count=1)


def bump_last_updated(text: str) -> str:
    today = date.today().isoformat()
    new, n = re.subn(
        r'(<time[^>]*data-field="last-updated"[^>]*datetime=")[^"]*("[^>]*>)[^<]*(</time>)',
        rf"\g<1>{today}\g<2>{today}\g<3>",
        text,
        count=1,
    )
    if n:
        return new
    return re.sub(
        r'(<time[^>]*data-field="last-updated"[^>]*>)[^<]*(</time>)',
        rf"\g<1>{today}\g<2>",
        text,
        count=1,
    )


def _live_row(row: dict[str, str]) -> str:
    ref = package_facts.source_ref("live_checks", row["row_id"])
    values = [
        row.get("time", ""),
        row.get("exp_id", ""),
        row.get("agent", ""),
        row.get("run_state", ""),
        row.get("last_log", ""),
        row.get("progress", ""),
        row.get("metrics", ""),
        row.get("resource", ""),
        row.get("artifacts", ""),
        row.get("eta", ""),
        row.get("action", ""),
        row.get("next_check", ""),
    ]
    cells = "".join(f"<td>{esc(value)}</td>" for value in values)
    return f'            <tr data-source-row="{esc(ref)}">{cells}</tr>'


def _resource_row(row: dict[str, str]) -> str:
    ref = package_facts.source_ref("resource_allocation", row["row_id"])
    values = [
        row.get("exp_id", ""),
        row.get("purpose", ""),
        row.get("dependency", ""),
        row.get("target", ""),
        row.get("capacity", ""),
        row.get("assigned", ""),
        row.get("reason", ""),
        row.get("agent", ""),
        row.get("command_cwd_env", ""),
        row.get("session_job", ""),
        row.get("runtime_root", ""),
        row.get("log_path", ""),
        row.get("expected_duration", ""),
        row.get("status", ""),
    ]
    cells = "".join(f"<td>{esc(value)}</td>" for value in values)
    return f'            <tr data-source-row="{esc(ref)}">{cells}</tr>'


def _live_sort_key(row: dict[str, str]) -> tuple[int, str]:
    time = row.get("time", "")
    return (0 if time else 1, time)


def render(pkg: str, root: Path) -> Path:
    paths = package_facts.fact_paths(pkg, root=root)
    tracker_path = root / "research_html" / "packages" / pkg / "tracker.html"
    if not tracker_path.exists():
        raise package_facts.FactError(f"missing tracker.html for {pkg}")

    live_path = paths.tables_dir / "live_checks.csv"
    resource_path = paths.tables_dir / "resource_allocation.csv"
    live_rows = _read_valid_csv(live_path, package_facts.LIVE_CHECK_COLUMNS) if live_path.exists() else []
    resource_rows = _read_valid_csv(resource_path, package_facts.RESOURCE_ALLOCATION_COLUMNS) if resource_path.exists() else []

    sorted_live = sorted(live_rows, key=_live_sort_key, reverse=True)
    latest = sorted_live[:5]
    history = sorted_live[5:]

    text = tracker_path.read_text(encoding="utf-8")
    if live_path.exists():
        revision = package_facts.file_revision(live_path)
        text = _replace_tbody(text, "live-check", "\n".join(_live_row(row) for row in latest))
        text = _replace_tbody(text, "live-check-history", "\n".join(_live_row(row) for row in history))
        text = _mark_table(text, "live-check", "tables/live_checks.csv", revision)
        text = _mark_table(text, "live-check-history", "tables/live_checks.csv", revision)
    if resource_path.exists():
        revision = package_facts.file_revision(resource_path)
        text = _replace_tbody(text, "resource-allocation", "\n".join(_resource_row(row) for row in resource_rows))
        text = _mark_table(text, "resource-allocation", "tables/resource_allocation.csv", revision)
    text = bump_last_updated(text)
    tracker_path.write_text(text, encoding="utf-8")
    return tracker_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--pkg", required=True)
    args = parser.parse_args(argv)
    try:
        path = render(args.pkg, Path(args.repo_root))
    except package_facts.FactError as exc:
        print(f"render_tracker_facts: {exc}", file=sys.stderr)
        return 2
    print(f"rendered {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
