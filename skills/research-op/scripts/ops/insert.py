"""Insert handlers for each target in the I-table (spec § 4.1)."""

import json
import re
from datetime import datetime
from pathlib import Path

from . import _pkg_block


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


def insert_methodstried(pkg: str, payload: dict) -> list[str]:
    return [_append_to_inventory_array(pkg, "methodsTried", payload)]


def insert_experiments_row(pkg: str, payload: dict) -> list[str]:
    return [_append_to_inventory_array(pkg, "experiments", payload)]


def insert_tracker_live_check_row(pkg: str, payload: dict) -> list[str]:
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
    """Append a 6-part result-block <section> to results.html."""
    path = Path(f"research_html/packages/{pkg}/results.html")
    text = path.read_text()
    title = payload.get("title", "untitled")
    summary = payload.get("summary", "")
    detail = payload.get("detail", "")
    main_table_html = payload.get("main_table_html", "")
    insight = payload.get("insight", "")
    ablation_html = payload.get("ablation_html", "") or "<!-- no ablation -->"
    block_html = (
        f'\n    <section class="result-block" data-block="result-block">\n'
        f'      <h3 data-block="title">{title}</h3>\n'
        f'      <p data-block="summary">{summary}</p>\n'
        f'      <details data-block="detail"><summary>Full description</summary><p>{detail}</p></details>\n'
        f'      <div data-block="main-table">{main_table_html}</div>\n'
        f'      <div data-block="insight">{insight}</div>\n'
        f'      <details data-block="ablation"><summary>Ablation</summary>{ablation_html}</details>\n'
        f'    </section>'
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
        f'<li class="card-text" id="rule-{slug}" style="margin-bottom:0.8em;">'
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
        f'<details class="insight-subblock" id="insight-{slug}" '
        f'style="margin-top:0.8em; border:1px solid #d8dde6; border-radius:6px; background:#fafbfd;">'
        f'<summary style="cursor:pointer; padding:10px 14px; font-size:1.05rem; font-weight:600; '
        f'color:#1f2a44; user-select:none; border-radius:6px;">{title}</summary>'
        f'<div class="insight-body-inner" style="padding:4px 14px 14px 14px;">{body}</div>'
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
        f'<article class="doc-card" data-doc-slug="{slug}" data-doc-purpose="{purpose}" '
        f'data-doc-audience="{audience}" data-doc-status="{status}" data-doc-anchor="{slug}.html">'
        f'<h4>{title}</h4><p>{tldr}</p></article>'
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
    """Replace inner HTML of <section data-section="chosen-route"> in tracker.html."""
    path = Path(f"research_html/packages/{pkg}/tracker.html")
    text = path.read_text()
    route = payload.get("route", "")
    reason = payload.get("reason", "")
    next_command = payload.get("next_command", "")
    inner_html = (
        f'<h3>Chosen route</h3>'
        f'<div class="kv-grid">'
        f'<div class="k">Route</div><div>{route}</div>'
        f'<div class="k">Reason</div><div>{reason}</div>'
        f'<div class="k">Next command</div><code>{next_command}</code>'
        f'</div>'
    )
    new = re.sub(
        r'(<section[^>]*data-section="chosen-route"[^>]*>).*?(</section>)',
        rf'\1{inner_html}\2', text, count=1, flags=re.DOTALL,
    )
    path.write_text(new)
    _bump_last_updated(path)
    return [str(path)]


_DISPATCH = {
    "methodsTried":                    insert_methodstried,
    "experiments-row":                 insert_experiments_row,
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
    return "passed", files
