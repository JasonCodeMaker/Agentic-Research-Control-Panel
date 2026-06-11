"""Insert handlers for each target in the I-table (spec § 4.1)."""

import csv
import io
import json
import re
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from . import _pkg_block

PIPELINE_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PIPELINE_ROOT))
sys.path.insert(0, str(PIPELINE_ROOT / "skills" / "research-package" / "scripts"))
from fact_transaction import FactTransaction  # noqa: E402
from lib import package_facts  # noqa: E402
from render_tracker_facts import render as render_tracker_facts  # noqa: E402
from sync_methods_tried_projection import sync_methods_tried_projection  # noqa: E402
from task_spine import derive_task_blocks  # noqa: E402

def _bump_last_updated(path: Path) -> None:
    """Update the <time data-field='last-updated'> on a touched HTML file."""
    text = path.read_text()
    iso = datetime.now().date().isoformat()
    new = re.sub(
        r'(<time[^>]*data-field="last-updated"[^>]*>)[^<]*(</time>)',
        rf'\1{iso}\2', text,
    )
    if new != text:
        path.write_text(new)


def _append_to_inventory_array(pkg: str, array_field: str, entry: dict) -> str:
    """Append `entry` to the named array in the package's inventory entry. Returns the file path edited."""
    p = Path("research_html/data/research-packages.js")
    text = p.read_text()
    bounds = _pkg_block.find_package_block(text, pkg)
    if bounds is None:
        raise SystemExit(f"package {pkg} not found in inventory")
    pkg_start, pkg_end = bounds
    block = text[pkg_start:pkg_end]
    fv = _pkg_block.find_top_level_field_value(block, array_field)
    if fv is None:
        # Array absent — add it as a new top-level field just before the closing '}'.
        insert_at = pkg_end - 1
        while insert_at > pkg_start and text[insert_at - 1] in " \t":
            insert_at -= 1
        insertion = f"\n    {array_field}: [{json.dumps(entry)}],\n  "
        new_text = text[:insert_at] + insertion + text[insert_at:]
    else:
        value_start, value_end = fv  # value_start at '[', value_end one past ']'
        inner = block[value_start + 1:value_end - 1]
        stripped = inner.strip()
        if stripped:
            new_inner = inner.rstrip()
            if not new_inner.endswith(","):
                new_inner += ","
            new_inner += "\n      " + json.dumps(entry) + "\n    "
        else:
            new_inner = json.dumps(entry)
        new_block = block[:value_start + 1] + new_inner + block[value_end - 1:]
        new_text = text[:pkg_start] + new_block + text[pkg_end:]
    p.write_text(new_text)
    return str(p)


def _is_fact_backed(pkg: str) -> bool:
    return (Path("research_html") / "data" / "packages" / pkg).exists()


def _csv_text_after_upsert(path: Path, columns: list[str], rows: list[dict]) -> str:
    existing = package_facts.read_csv_rows(path)
    by_id = {str(row.get("row_id", "")): row for row in existing if row.get("row_id")}
    order = [str(row.get("row_id")) for row in existing if row.get("row_id")]
    for raw in rows:
        row_id = str(raw.get("row_id", "")).strip()
        if not row_id:
            raise package_facts.FactError("CSV fact row requires non-empty row_id")
        row = {col: str(raw.get(col, "")) for col in columns}
        row["row_id"] = row_id
        if row_id not in by_id:
            order.append(row_id)
        by_id[row_id] = row

    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row_id in order:
        writer.writerow({col: by_id[row_id].get(col, "") for col in columns})
    return out.getvalue()


def _copy_if_exists(src: Path, dest: Path) -> None:
    if src.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)


def _render_tracker_candidate(pkg: str, csv_path: Path, csv_text: str) -> str:
    root = Path(".")
    tracker_rel = Path("research_html") / "packages" / pkg / "tracker.html"
    live_paths = package_facts.fact_paths(pkg)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        tmp_paths = package_facts.fact_paths(pkg, root=tmp_root)
        _copy_if_exists(root / tracker_rel, tmp_root / tracker_rel)
        _copy_if_exists(live_paths.tables_dir / "live_checks.csv", tmp_paths.tables_dir / "live_checks.csv")
        _copy_if_exists(
            live_paths.tables_dir / "resource_allocation.csv",
            tmp_paths.tables_dir / "resource_allocation.csv",
        )
        target_csv = tmp_root / csv_path
        target_csv.parent.mkdir(parents=True, exist_ok=True)
        target_csv.write_text(csv_text, encoding="utf-8")
        render_tracker_facts(pkg, tmp_root)
        return (tmp_root / tracker_rel).read_text(encoding="utf-8")


def _commit_fact_projection(files: dict[Path, str]) -> None:
    tx = FactTransaction()
    try:
        for path, text in files.items():
            tx.stage_text(path, text)
        tx.commit()
    finally:
        tx.cleanup()


def _measured(source_row: dict[str, str]) -> str:
    return f"{source_row.get('metric', '')}={source_row.get('value', '')}{source_row.get('unit', '')}"


def _build_methods_row(pkg: str, payload: dict) -> dict[str, str]:
    paths = package_facts.fact_paths(pkg)
    source_row = package_facts.find_row_by_ref(paths.tables_dir, payload["source_ref"])
    source_table, source_row_id = package_facts.split_source_ref(payload["source_ref"])
    exp_id = str(payload.get("exp_id") or source_row.get("exp_id") or "")
    if not exp_id:
        raise SystemExit("fact-backed methodsTried source_ref requires exp_id")
    verdict = source_row.get("verdict") or "INCONCLUSIVE"
    if source_row.get("source_type", "").lower() == "manual" and verdict == "PASS":
        raise package_facts.FactError("manual PASS source rows cannot be appended to methods_tried.csv")
    return {
        "row_id": str(payload.get("row_id") or payload["source_ref"]),
        "exp_id": exp_id,
        "method": str(payload["method"]),
        "hypothesis": str(payload["hypothesis"]),
        "gate": str(payload["gate"]),
        "measured": _measured(source_row),
        "verdict": verdict,
        "evidencePath": source_row.get("source_artifact", ""),
        "source_table": source_table,
        "source_row": source_row_id,
        "source_artifact": source_row.get("source_artifact", ""),
        "extracted_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def _sync_methods_candidate(pkg: str, csv_path: Path, csv_text: str) -> str:
    registry_rel = Path("research_html") / "data" / "research-packages.js"
    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        _copy_if_exists(Path(registry_rel), tmp_root / registry_rel)
        tmp_csv = tmp_root / csv_path
        tmp_csv.parent.mkdir(parents=True, exist_ok=True)
        tmp_csv.write_text(csv_text, encoding="utf-8")
        sync_methods_tried_projection(pkg, tmp_root)
        return (tmp_root / registry_rel).read_text(encoding="utf-8")


def _tracker_row_id(payload: dict) -> str:
    if payload.get("row_id"):
        return str(payload["row_id"])
    exp_id = str(payload.get("exp_id", "")).strip()
    suffix = str(payload.get("run_id") or payload.get("time") or "latest").strip()
    if not exp_id:
        raise SystemExit("fact-backed tracker row requires exp_id")
    return f"{exp_id}:{suffix}"


def _tracker_files(pkg: str, csv_path: Path) -> list[str]:
    return [str(csv_path), f"research_html/packages/{pkg}/tracker.html"]


def insert_methodstried(pkg: str, payload: dict) -> list[str]:
    if _is_fact_backed(pkg) and payload.get("source_ref"):
        paths = package_facts.fact_paths(pkg)
        csv_path = paths.tables_dir / "methods_tried.csv"
        csv_text = _csv_text_after_upsert(
            csv_path,
            package_facts.METHODS_TRIED_COLUMNS,
            [_build_methods_row(pkg, payload)],
        )
        registry_text = _sync_methods_candidate(pkg, csv_path, csv_text)
        registry_path = Path("research_html") / "data" / "research-packages.js"
        _commit_fact_projection({csv_path: csv_text, registry_path: registry_text})
        return [str(csv_path), str(registry_path)]
    return [_append_to_inventory_array(pkg, "methodsTried", payload)]


def insert_experiments_row(pkg: str, payload: dict) -> list[str]:
    files = [_append_to_inventory_array(pkg, "experiments", payload)]
    files.extend(derive_task_blocks(Path(f"research_html/packages/{pkg}"), [payload]))
    return files


def insert_package_invariant(pkg: str, payload: dict) -> list[str]:
    """Append a binding directive {rule, rationale, addedAt} to the package's bindingRules[] — the typed,
    audited home for a user-added rule (e.g. one-notebook-per-figure)."""
    entry = {k: payload[k] for k in ("rule", "rationale", "addedAt") if k in payload}
    return [_append_to_inventory_array(pkg, "bindingRules", entry)]


def insert_tracker_live_check_row(pkg: str, payload: dict) -> list[str]:
    if _is_fact_backed(pkg):
        csv_path = package_facts.table_csv_path(pkg, "live_checks")
        row = {col: str(payload.get(col, "")) for col in package_facts.LIVE_CHECK_COLUMNS}
        row["row_id"] = _tracker_row_id(payload)
        csv_text = _csv_text_after_upsert(csv_path, package_facts.LIVE_CHECK_COLUMNS, [row])
        tracker_text = _render_tracker_candidate(pkg, csv_path, csv_text)
        tracker_path = Path("research_html") / "packages" / pkg / "tracker.html"
        _commit_fact_projection({csv_path: csv_text, tracker_path: tracker_text})
        return _tracker_files(pkg, csv_path)

    path = Path(f"research_html/packages/{pkg}/tracker.html")
    text = path.read_text()
    # Append into <tbody data-table-body="live-check">.
    row_html = (
        "<tr>"
        + "".join(f"<td>{payload.get(c, 'unmeasured')}</td>" for c in (
            "time", "exp_id", "agent", "run_state", "last_log", "progress",
            "metrics", "resource", "artifacts", "eta", "action", "next_check"
        ))
        + "</tr>"
    )
    # If a row for this exp_id exists, REPLACE; otherwise APPEND.
    exp_id = payload.get("exp_id", "")
    existing_row = re.compile(
        rf'<tr>[^<]*<td>[^<]*</td>\s*<td>{re.escape(exp_id)}</td>.*?</tr>', re.DOTALL,
    )
    if existing_row.search(text):
        new = existing_row.sub(row_html, text, count=1)
    else:
        new = re.sub(
            r'(<tbody[^>]*data-table-body="live-check"[^>]*>)',
            rf"\1\n      {row_html}", text, count=1,
        )
    path.write_text(new)
    _bump_last_updated(path)
    return [str(path)]


def insert_tracker_resource_allocation_row(pkg: str, payload: dict) -> list[str]:
    """Append a <tr> into <tbody data-table-body="resource-allocation"> in tracker.html."""
    if _is_fact_backed(pkg):
        csv_path = package_facts.table_csv_path(pkg, "resource_allocation")
        row = {col: str(payload.get(col, "")) for col in package_facts.RESOURCE_ALLOCATION_COLUMNS}
        row["row_id"] = _tracker_row_id(payload)
        csv_text = _csv_text_after_upsert(csv_path, package_facts.RESOURCE_ALLOCATION_COLUMNS, [row])
        tracker_text = _render_tracker_candidate(pkg, csv_path, csv_text)
        tracker_path = Path("research_html") / "packages" / pkg / "tracker.html"
        _commit_fact_projection({csv_path: csv_text, tracker_path: tracker_text})
        return _tracker_files(pkg, csv_path)

    path = Path(f"research_html/packages/{pkg}/tracker.html")
    text = path.read_text()
    cols = (
        "exp_id", "purpose", "dependency", "target", "capacity", "assigned",
        "reason", "agent", "command_cwd_env", "session_job", "runtime_root",
        "log_path", "expected_duration", "status",
    )
    row_html = (
        "<tr>"
        + "".join(f"<td>{payload.get(c, 'unmeasured')}</td>" for c in cols)
        + "</tr>"
    )
    new = re.sub(
        r'(<tbody[^>]*data-table-body="resource-allocation"[^>]*>)',
        rf"\1\n      {row_html}", text, count=1,
    )
    path.write_text(new)
    _bump_last_updated(path)
    return [str(path)]


def insert_tracker_impl_review_row(pkg: str, payload: dict) -> list[str]:
    """Append a <tr> into <tbody data-table-body="implementation-review"> in tracker.html."""
    path = Path(f"research_html/packages/{pkg}/tracker.html")
    text = path.read_text()
    cols = (
        "change_id", "purpose", "unit", "owned_files", "scope",
        "no_change_boundary", "reviewer_verdict", "finding_class",
        "required_fix", "main_decision", "style_minimal", "complexity",
        "oos_check", "validation", "integration_verdict",
    )
    row_html = (
        "<tr>"
        + "".join(f"<td>{payload.get(c, 'unmeasured')}</td>" for c in cols)
        + "</tr>"
    )
    new = re.sub(
        r'(<tbody[^>]*data-table-body="implementation-review"[^>]*>)',
        rf"\1\n      {row_html}", text, count=1,
    )
    path.write_text(new)
    _bump_last_updated(path)
    return [str(path)]


def insert_results_gate_row(pkg: str, payload: dict) -> list[str]:
    """Append a <tr> into <tbody data-table-body="result-gate"> in results.html."""
    path = Path(f"research_html/packages/{pkg}/results.html")
    text = path.read_text()
    cols = (
        "exp_id", "validity", "baseline", "plan_gate", "observed_metric",
        "budget_use", "seed_status", "artifact_completeness", "verdict", "reason",
    )
    row_html = (
        "<tr>"
        + "".join(f"<td>{payload.get(c, 'unmeasured')}</td>" for c in cols)
        + "</tr>"
    )
    new = re.sub(
        r'(<tbody[^>]*data-table-body="result-gate"[^>]*>)',
        rf"\1\n      {row_html}", text, count=1,
    )
    path.write_text(new)
    _bump_last_updated(path)
    return [str(path)]


def insert_results_block(pkg: str, payload: dict) -> list[str]:
    """Append a 6-part result-block <article> to results.html."""
    path = Path(f"research_html/packages/{pkg}/results.html")
    text = path.read_text()
    title = payload.get("title", "untitled")
    summary = payload.get("summary", "")
    detail = payload.get("detail", "")
    main_table_html = payload.get("main_table_html", "")
    insight = payload.get("insight", "")
    ablation_html = payload.get("ablation_html", "") or "<!-- no ablation -->"
    block_html = (
        f'\n    <article class="result-block" data-result-block data-block="result-block">\n'
        f'      <h2 data-block="title">{title}</h2>\n'
        f'      <p class="block-summary" data-block="summary">{summary}</p>\n'
        f'      <details class="block-detail" data-block="detail"><summary>Full description</summary><p>{detail}</p></details>\n'
        f'      <div class="block-main-table" data-block="main-table">{main_table_html}</div>\n'
        f'      <section class="block-insight" data-block="insight">{insight}</section>\n'
        f'      <details class="block-ablation" data-block="ablation"><summary>Ablation</summary>{ablation_html}</details>\n'
        f'    </article>'
    )
    # Insert before </main> if present, otherwise before </body>.
    if "</main>" in text:
        new = text.replace("</main>", block_html + "\n  </main>", 1)
    else:
        new = text.replace("</body>", block_html + "\n</body>", 1)
    path.write_text(new)
    _bump_last_updated(path)
    return [str(path)]


def insert_analysis_rule(pkg: str, payload: dict) -> list[str]:
    """Append a rule <li> into <ol class="rules-list"> in analysis.html."""
    path = Path(f"research_html/packages/{pkg}/analysis.html")
    text = path.read_text()
    slug = payload.get("slug", "")
    prose = payload.get("prose", "")
    evidence_slug = payload.get("evidence_slug", "")
    li_html = (
        f'<li class="card-text" id="rule-{slug}">'
        f'{prose} Evidence: <a href="#insight-{evidence_slug}">see insight</a>.'
        f'</li>'
    )
    # Strip the placeholder if present.
    text = re.sub(
        r'<li[^>]*><em>No rules recorded yet\.</em></li>\s*',
        '', text,
    )
    new = re.sub(
        r'(<ol[^>]*class="rules-list"[^>]*>)',
        rf"\1\n          {li_html}", text, count=1,
    )
    path.write_text(new)
    _bump_last_updated(path)
    return [str(path)]


def insert_analysis_insight(pkg: str, payload: dict) -> list[str]:
    """Append an insight <details> subblock into <div class="insight-body"> in analysis.html."""
    path = Path(f"research_html/packages/{pkg}/analysis.html")
    text = path.read_text()
    slug = payload.get("slug", "")
    title = payload.get("title", "")
    body = payload.get("body", "")
    details_html = (
        f'<details class="insight-subblock" id="insight-{slug}">'
        f'<summary>{title}</summary>'
        f'<div class="insight-subblock-body">{body}</div>'
        f'</details>'
    )
    # Strip the placeholder if present.
    text = re.sub(
        r'<p[^>]*><em>No insight content yet\.</em></p>\s*',
        '', text,
    )
    new = re.sub(
        r'(<div[^>]*class="insight-body"[^>]*data-block="insight-body"[^>]*>|'
        r'<div[^>]*data-block="insight-body"[^>]*class="insight-body"[^>]*>)',
        rf"\1\n          {details_html}", text, count=1,
    )
    path.write_text(new)
    _bump_last_updated(path)
    return [str(path)]


def insert_doc_card(pkg: str, payload: dict) -> list[str]:
    """Append a doc <article> card into the matching docs-group section in docs/index.html."""
    path = Path(f"research_html/packages/{pkg}/docs/index.html")
    text = path.read_text()
    slug = payload.get("slug", "")
    title = payload.get("title", "")
    purpose = payload.get("purpose", "")
    audience = payload.get("audience", "")
    status = payload.get("status", "")
    tldr = payload.get("tldr", "")
    group = payload.get("group", "")
    card_html = (
        f'<article class="module-card doc-card" data-doc-slug="{slug}" data-doc-purpose="{purpose}" '
        f'data-doc-audience="{audience}" data-doc-status="{status}" data-doc-anchor="{slug}.html">'
        f'<header class="doc-card-header"><h3>{title}</h3></header>'
        f'<p class="doc-tldr">{tldr}</p></article>'
    )
    # Try to insert into the matching group section; fall back to appending before </body>.
    group_pat = re.compile(
        r'(<[^>]*data-doc-group-kind="' + re.escape(group) + r'"[^>]*>)',
        re.DOTALL,
    )
    m = group_pat.search(text)
    if m:
        new = text[:m.end()] + f"\n      {card_html}" + text[m.end():]
    else:
        new = text.replace("</body>", f"      {card_html}\n</body>", 1)
    path.write_text(new)
    _bump_last_updated(path)
    return [str(path)]


def insert_doc_file(pkg: str, payload: dict) -> list[str]:
    """Create docs/<slug>.html with payload['html'] then insert the paired doc card."""
    slug = payload.get("slug", "")
    doc_path = Path(f"research_html/packages/{pkg}/docs/{slug}.html")
    doc_path.write_text(payload.get("html", ""))
    card_files = insert_doc_card(pkg, payload)
    return [str(doc_path)] + card_files


def insert_tracker_chosen_route(pkg: str, payload: dict) -> list[str]:
    """Update the chosen-route fields in tracker.html in place. Targeted field
    writes only — never overwrite the section — so the two-article structure
    (chosen-route-card + considered-routes-card) and every data-* anchor that
    renderChosenRoutePanel() targets are preserved (R6, T24)."""
    path = Path(f"research_html/packages/{pkg}/tracker.html")
    text = path.read_text()
    route = payload.get("route", "")
    reason = payload.get("reason", "")
    next_command = payload.get("next_command", "")

    def set_field(html: str, field: str, content: str) -> str:
        """Replace the inner HTML of the first element carrying data-field="<field>"."""
        pat = re.compile(
            r'(<(\w+)\b[^>]*\bdata-field="' + re.escape(field) + r'"[^>]*>).*?(</\2>)',
            re.DOTALL,
        )
        return pat.sub(lambda m: m.group(1) + content + m.group(3), html, count=1)

    text = set_field(text, "chosen-route", route)
    text = set_field(text, "chosen-route-reason", reason)
    if next_command:
        # Append a Next-command row after the (unique) reason row, inside the
        # chosen-route-card kv-grid — additive, never destructive.
        text = re.sub(
            r'(<div[^>]*data-field="chosen-route-reason"[^>]*>.*?</div>)',
            lambda m: m.group(1)
            + '<div class="k">Next command</div><code>' + next_command + '</code>',
            text, count=1, flags=re.DOTALL,
        )
    path.write_text(text)
    _bump_last_updated(path)
    return [str(path)]


_DISPATCH = {
    "methodsTried":                    insert_methodstried,
    "experiments-row":                 insert_experiments_row,
    "package-invariant":               insert_package_invariant,
    "tracker-live-check-row":          insert_tracker_live_check_row,
    "tracker-resource-allocation-row": insert_tracker_resource_allocation_row,
    "tracker-impl-review-row":         insert_tracker_impl_review_row,
    "results-gate-row":                insert_results_gate_row,
    "results-block":                   insert_results_block,
    "analysis-rule":                   insert_analysis_rule,
    "analysis-insight":                insert_analysis_insight,
    "doc-file":                        insert_doc_file,
    "doc-card":                        insert_doc_card,
    "tracker-chosen-route":            insert_tracker_chosen_route,
}


def handle(pkg: str, target: str | None, payload: dict, state: dict) -> tuple[str, list[str]]:
    fn = _DISPATCH.get(target)
    if fn is None:
        raise SystemExit(f"insert target not implemented yet: {target}")
    files = fn(pkg, payload)
    return "PASSED", files
