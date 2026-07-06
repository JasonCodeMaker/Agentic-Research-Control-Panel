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


def _read_valid_result_rows(path: Path, schema: dict | None = None) -> list[dict[str, str]]:
    rows = package_facts.read_csv_rows(path)
    columns = package_facts.RESULT_CELL_COLUMNS if schema or path.stem.startswith("result_table_") else package_facts.RESULT_COLUMNS
    for index, row in enumerate(rows):
        if None in row:
            raise package_facts.FactError(f"malformed CSV row {index + 1} in {path}")
        if not row.get("row_id"):
            raise package_facts.FactError(f"CSV row {index + 1} in {path} has no row_id")
        for col in columns:
            row.setdefault(col, "")
        package_facts.validate_csv_fact_row(columns, row)
    return rows


def _set_attr(tag: str, name: str, value: str) -> str:
    tag = re.sub(r"\s+" + re.escape(name) + r'="[^"]*"', "", tag)
    return tag + f' {name}="{esc(value)}"'


def mark_result_gate_table(text: str, source: str, revision: str) -> str:
    pat = re.compile(
        r'(<table\b(?=[^>]*data-table="result-gate")[^>]*)(>)',
        re.DOTALL,
    )
    if not pat.search(text):
        raise package_facts.FactError("results.html missing result-gate table")

    def repl(match: re.Match) -> str:
        tag = _set_attr(match.group(1), "data-fact-projection", "results")
        tag = _set_attr(tag, "data-source", source)
        tag = _set_attr(tag, "data-fact-revision", revision)
        return tag + match.group(2)

    return pat.sub(repl, text, count=1)


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


def _headline_fact_ref(pkg: str, root: Path) -> str:
    facts = package_facts.load_facts_js(pkg, root=root)
    return str((((facts.get("pages") or {}).get("results") or {}).get("headlineFact") or "")).strip()


def render_headline_card(ref: str, row: dict[str, str]) -> str:
    metric = row.get("metric") or "metric"
    value = f"{row.get('value', '')}{row.get('unit', '')}"
    baseline = row.get("baseline") or "unmeasured"
    verdict = row.get("verdict") or "INCONCLUSIVE"
    artifact = row.get("source_artifact") or "unmeasured"
    return """      <section data-section="headline" id="headline" aria-label="Headline result" data-fact-projection="results">
        <article class="module-card" data-card="headline" data-source-row="{ref}">
          <h2>Headline result</h2>
          <div class="metric-strip">
            <div class="metric-card">
              <div class="k">{metric}</div>
              <div class="v" data-field="headline-new" data-source-row="{ref}">{value}</div>
              <p class="card-text">Current best from <code>{artifact}</code>.</p>
            </div>
            <div class="metric-card">
              <div class="k">Baseline</div>
              <div class="v" data-field="headline-baseline" data-source-row="{ref}">{baseline}</div>
              <p class="card-text">Reference value for the same row id.</p>
            </div>
            <div class="metric-card">
              <div class="k">Verdict</div>
              <div class="v" data-field="headline-verdict" data-source-row="{ref}">{verdict}</div>
              <p class="card-text">Rendered from the headline CSV row.</p>
            </div>
          </div>
        </article>
      </section>""".format(
        ref=esc(ref),
        metric=esc(metric),
        value=esc(value),
        baseline=esc(baseline),
        verdict=esc(verdict),
        artifact=esc(artifact),
    )


def replace_or_insert_headline(text: str, headline_html: str) -> str:
    pat = re.compile(
        r'\s*<section\b(?=[^>]*data-section="headline")[^>]*>.*?</section>',
        re.DOTALL,
    )
    if pat.search(text):
        return pat.sub("\n" + headline_html, text, count=1)
    marker = re.search(r'\s*<section\b[^>]*data-list="result-blocks"[^>]*>', text, re.DOTALL)
    if marker:
        return text[:marker.start()] + "\n" + headline_html + text[marker.start():]
    return text.replace("</body>", headline_html + "\n</body>", 1)


def _schemas_by_table(pkg: str, root: Path) -> dict[str, dict]:
    facts = package_facts.load_facts_js(pkg, root=root)
    schemas = facts.get("resultSchemas") or {}
    if isinstance(schemas, list):
        return {str(item.get("tableId") or ""): item for item in schemas if isinstance(item, dict)}
    if isinstance(schemas, dict):
        return {str(item.get("tableId") or ""): item for item in schemas.values() if isinstance(item, dict)}
    return {}


def _result_table_paths(paths: package_facts.FactPaths, schemas: dict[str, dict]) -> list[Path]:
    by_name = {path.name: path for path in sorted(paths.tables_dir.glob("result_table_*.csv"))}
    for table_id in schemas:
        if not table_id:
            continue
        path = paths.tables_dir / f"{table_id}.csv"
        by_name.setdefault(path.name, path)
    return [path for path in sorted(by_name.values(), key=lambda item: item.name) if path.exists()]


def _cell_by_axis(rows: list[dict]) -> dict[tuple[str, str], dict]:
    out = {}
    for row in rows:
        row_key = str(row.get("row_key") or "").strip()
        column_key = str(row.get("column_key") or "").strip()
        if row_key and column_key:
            out[(row_key, column_key)] = row
    return out


def render_schema_result_article(table_path: Path, rows: list[dict], schema: dict) -> str:
    table_id = table_path.stem
    revision = package_facts.file_revision(table_path)
    schema_id = str(schema.get("id") or "")
    exp_id = str(schema.get("expId") or table_id.replace("result_table_", ""))
    row_axis = schema.get("rowAxis") if isinstance(schema.get("rowAxis"), dict) else {}
    row_axis_label = str(row_axis.get("label") or row_axis.get("key") or "Row")
    planned_rows = row_axis.get("plannedRows") if isinstance(row_axis.get("plannedRows"), list) else []
    columns = schema.get("columns") if isinstance(schema.get("columns"), list) else []
    cells = _cell_by_axis(rows)
    header_cells = "".join(
        "<th>{label}</th>".format(label=esc(column.get("label") or column.get("key") or "Metric"))
        for column in columns
    )
    body_rows = []
    for row_item in planned_rows:
        row_key = str(row_item.get("key") or "")
        row_label = str(row_item.get("label") or row_key or "unmeasured")
        values = []
        for column in columns:
            column_key = str(column.get("key") or "")
            cell = cells.get((row_key, column_key))
            if cell:
                ref = package_facts.source_ref(table_id, cell["row_id"])
                value = f"{cell.get('value') or 'unmeasured'}{cell.get('unit') or ''}"
                values.append(
                    '<td data-source-row="{ref}" data-validity="{validity}">{value}</td>'.format(
                        ref=esc(ref),
                        validity=esc(cell.get("validity") or "UNMEASURED"),
                        value=esc(value),
                    )
                )
            else:
                values.append('<td data-validity="MISSING">missing</td>')
        body_rows.append(
            '              <tr data-row-key="{row_key}"><th>{row_label}</th>{values}</tr>'.format(
                row_key=esc(row_key),
                row_label=esc(row_label),
                values="".join(values),
            )
        )
    return """        <article class="result-block" id="result-slot-{low}" data-result-block data-fact-projection="results" data-exp-id="{exp}" data-phase-id="{exp}" data-source="tables/{name}" data-fact-revision="{revision}" data-result-schema="{schema_id}">
          <h2>{exp} &mdash; {kind}</h2>
          <p class="block-summary">{question}</p>
          <table class="data-table block-main-table" data-table="{table_id}" data-exp-id="{exp}">
            <thead><tr><th>{row_axis_label}</th>{header_cells}</tr></thead>
            <tbody data-table-body="{table_id}">
{rows}
            </tbody>
          </table>
        </article>""".format(
        low=esc(exp_id.lower()),
        exp=esc(exp_id),
        name=esc(table_path.name),
        revision=esc(revision),
        schema_id=esc(schema_id),
        kind=esc(schema.get("kind") or "result table"),
        question=esc(schema.get("decisionQuestion") or "Task-specific result table."),
        table_id=esc(table_id),
        row_axis_label=esc(row_axis_label),
        header_cells=header_cells,
        rows="\n".join(body_rows),
    )


def render_result_article(table_path: Path, rows: list[dict], schema: dict | None = None) -> str:
    if schema:
        return render_schema_result_article(table_path, rows, schema)
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
    return """        <article class="result-block" id="result-slot-{low}" data-result-block data-fact-projection="results" data-exp-id="{exp}" data-phase-id="{exp}" data-source="tables/{name}" data-fact-revision="{revision}">
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


def _section_content_bounds(text: str, attr: str) -> tuple[int, int] | None:
    start = re.search(r'<section\b(?=[^>]*' + re.escape(attr) + r')[^>]*>', text, re.DOTALL)
    if not start:
        return None
    depth = 0
    for tag in re.finditer(r'</?section\b[^>]*>', text[start.start():], re.IGNORECASE | re.DOTALL):
        absolute_start = start.start() + tag.start()
        if tag.group(0).startswith("</"):
            depth -= 1
            if depth == 0:
                return start.end(), absolute_start
        else:
            depth += 1
    return None


def replace_result_blocks(text: str, articles_html: str) -> str:
    bounds = _section_content_bounds(text, 'data-list="result-blocks"')
    if not bounds:
        raise package_facts.FactError("results.html missing data-list=result-blocks section")
    content_start, content_end = bounds
    return text[:content_start] + "\n" + articles_html + "\n      " + text[content_end:]


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
    gate_path = paths.tables_dir / "result_gate.csv"
    gate_rows = _read_valid_result_rows(gate_path) if gate_path.exists() else []
    schemas = _schemas_by_table(pkg, root)
    table_paths = _result_table_paths(paths, schemas)
    articles = [
        render_result_article(p, _read_valid_result_rows(p, schemas.get(p.stem)), schemas.get(p.stem))
        for p in table_paths
    ]
    text = results_path.read_text(encoding="utf-8")
    headline_ref = _headline_fact_ref(pkg, root)
    if headline_ref:
        headline_row = package_facts.find_row_by_ref(paths.tables_dir, headline_ref)
        text = replace_or_insert_headline(text, render_headline_card(headline_ref, headline_row))
    if gate_rows:
        text = replace_result_gate(text, render_gate_rows(gate_rows))
        text = mark_result_gate_table(text, "tables/result_gate.csv", package_facts.file_revision(gate_path))
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
