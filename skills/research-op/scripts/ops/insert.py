"""Insert handlers for each target in the I-table (spec § 4.1)."""

import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from . import _pkg_block

PIPELINE_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PIPELINE_ROOT))
sys.path.insert(0, str(PIPELINE_ROOT / "skills" / "research-package" / "scripts"))
from lib import package_facts  # noqa: E402
from task_spine import derive_task_blocks  # noqa: E402

RENDER_TRACKER = PIPELINE_ROOT / "skills" / "research-package" / "scripts" / "render_tracker_facts.py"
APPEND_METHODS = PIPELINE_ROOT / "skills" / "research-package" / "scripts" / "append_methods_tried_fact.py"
SYNC_METHODS = PIPELINE_ROOT / "skills" / "research-package" / "scripts" / "sync_methods_tried_projection.py"


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


def _run_script(script: Path, *args: str) -> None:
    result = subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(result.stderr or result.stdout)


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
        source_row = package_facts.find_row_by_ref(paths.tables_dir, payload["source_ref"])
        exp_id = str(payload.get("exp_id") or source_row.get("exp_id") or "")
        if not exp_id:
            raise SystemExit("fact-backed methodsTried source_ref requires exp_id")
        args = [
            "--repo-root", ".",
            "--pkg", pkg,
            "--exp-id", exp_id,
            "--source-ref", str(payload["source_ref"]),
            "--method", str(payload["method"]),
            "--hypothesis", str(payload["hypothesis"]),
            "--gate", str(payload["gate"]),
        ]
        if payload.get("row_id"):
            args.extend(["--row-id", str(payload["row_id"])])
        _run_script(APPEND_METHODS, *args)
        _run_script(SYNC_METHODS, "--repo-root", ".", "--pkg", pkg)
        return [str(paths.tables_dir / "methods_tried.csv"), "research_html/data/research-packages.js"]
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
        package_facts.upsert_csv_rows(csv_path, package_facts.LIVE_CHECK_COLUMNS, [row])
        _run_script(RENDER_TRACKER, "--repo-root", ".", "--pkg", pkg)
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
        package_facts.upsert_csv_rows(csv_path, package_facts.RESOURCE_ALLOCATION_COLUMNS, [row])
        _run_script(RENDER_TRACKER, "--repo-root", ".", "--pkg", pkg)
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
