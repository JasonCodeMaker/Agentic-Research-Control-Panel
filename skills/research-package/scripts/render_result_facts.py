#!/usr/bin/env python3
"""Render package result CSV facts into results.html."""

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


def render_gate_rows(rows: list[dict]) -> str:
    out = []
    for row in rows:
        exp_id = row.get("exp_id", "")
        ref = package_facts.source_ref("result_gate", row["row_id"])
        out.append(
            '            <tr id="gate-{low}" data-exp-id="{exp}" data-source-row="{ref}" data-ack="result-pass" data-ack-value="">'
            '<td data-field="exp-id">{exp}</td>'
            '<td data-validity="{validity}">{validity}</td>'
            '<td data-field="baseline">{baseline}</td>'
            '<td data-field="plan-gate">{metric}</td>'
            '<td data-field="observed-metric">{metric}={value}{unit}</td>'
            '<td data-field="budget-use">unmeasured</td>'
            '<td data-field="seed-status">{split}</td>'
            '<td data-field="artifact-completeness"><code>{artifact}</code></td>'
            '<td data-decision data-field="verdict">{verdict}</td>'
            '<td data-field="reason">fact-backed row {row_id}</td></tr>'.format(
                low=esc(exp_id.lower()),
                exp=esc(exp_id),
                ref=esc(ref),
                validity=esc(row.get("validity") or "UNMEASURED"),
                baseline=esc(row.get("baseline") or "unmeasured"),
                metric=esc(row.get("metric") or "unmeasured"),
                value=esc(row.get("value") or "unmeasured"),
                unit=esc(row.get("unit") or ""),
                split=esc(row.get("split") or "unmeasured"),
                artifact=esc(row.get("source_artifact") or "unmeasured"),
                verdict=esc(row.get("verdict") or "INCONCLUSIVE"),
                row_id=esc(row.get("row_id") or ""),
            )
        )
    return "\n".join(out)


def render_result_article(table_path: Path, rows: list[dict]) -> str:
    table_id = table_path.stem
    revision = package_facts.file_revision(table_path)
    body_rows = []
    for row in rows:
        ref = package_facts.source_ref(table_id, row["row_id"])
        body_rows.append(
            '              <tr data-source-row="{ref}">'
            "<td>{split}</td><td>{metric}</td><td>{value}{unit}</td><td><code>{artifact}</code></td>"
            "</tr>".format(
                ref=esc(ref),
                split=esc(row.get("split") or "unmeasured"),
                metric=esc(row.get("metric") or "unmeasured"),
                value=esc(row.get("value") or "unmeasured"),
                unit=esc(row.get("unit") or ""),
                artifact=esc(row.get("source_artifact") or "unmeasured"),
            )
        )
    exp_id = rows[0].get("exp_id", table_id.replace("result_table_", "")) if rows else table_id
    return """        <article class="result-block" id="result-slot-{low}" data-result-block data-exp-id="{exp}" data-phase-id="{exp}" data-source="tables/{name}" data-fact-revision="{revision}">
          <h2>{exp} &mdash; fact-backed result table</h2>
          <p class="block-summary">Rendered from <code>tables/{name}</code>.</p>
          <table class="data-table block-main-table" data-table="{table_id}" data-exp-id="{exp}">
            <thead><tr><th>Split</th><th>Metric</th><th>Value</th><th>Artifact</th></tr></thead>
            <tbody data-table-body="{table_id}">
{rows}
            </tbody>
          </table>
        </article>""".format(
        low=esc(str(exp_id).lower()),
        exp=esc(exp_id),
        name=esc(table_path.name),
        revision=esc(revision),
        table_id=esc(table_id),
        rows="\n".join(body_rows),
    )


def replace_result_gate(text: str, rows_html: str) -> str:
    pat = re.compile(r'(<tbody[^>]*data-table-body="result-gate"[^>]*>)(.*?)(</tbody>)', re.DOTALL)
    if not pat.search(text):
        raise package_facts.FactError("results.html missing result-gate tbody")
    return pat.sub(lambda m: m.group(1) + "\n" + rows_html + "\n          " + m.group(3), text, count=1)


def replace_result_blocks(text: str, articles_html: str) -> str:
    pat = re.compile(r'(<section[^>]*data-list="result-blocks"[^>]*>)(.*?)(</section>)', re.DOTALL)
    if not pat.search(text):
        raise package_facts.FactError("results.html missing data-list=result-blocks section")
    return pat.sub(lambda m: m.group(1) + "\n" + articles_html + "\n      " + m.group(3), text, count=1)


def bump_last_updated(text: str) -> str:
    today = date.today().isoformat()
    return re.sub(
        r'(<time[^>]*data-field="last-updated"[^>]*datetime=")[^"]*("[^>]*>)[^<]*(</time>)',
        rf"\g<1>{today}\g<2>{today}\g<3>",
        text,
        count=1,
    )


def render(pkg: str, root: Path) -> Path:
    paths = package_facts.fact_paths(pkg, root=root)
    results_path = root / "research_html" / "packages" / pkg / "results.html"
    if not results_path.exists():
        raise package_facts.FactError(f"missing results.html for {pkg}")
    gate_rows = package_facts.read_csv_rows(paths.tables_dir / "result_gate.csv")
    table_paths = sorted(paths.tables_dir.glob("result_table_*.csv"))
    articles = [render_result_article(p, package_facts.read_csv_rows(p)) for p in table_paths]
    text = results_path.read_text(encoding="utf-8")
    if gate_rows:
        text = replace_result_gate(text, render_gate_rows(gate_rows))
    if articles:
        text = replace_result_blocks(text, "\n".join(articles))
    text = bump_last_updated(text)
    results_path.write_text(text, encoding="utf-8")
    return results_path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo-root", default=".")
    p.add_argument("--pkg", required=True)
    args = p.parse_args(argv)
    try:
        path = render(args.pkg, Path(args.repo_root))
    except package_facts.FactError as exc:
        print(f"render_result_facts: {exc}", file=sys.stderr)
        return 2
    print(f"rendered {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
