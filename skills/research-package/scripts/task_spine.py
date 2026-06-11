"""Task-spine block derivation shared by scaffolders and research-op.

The inventory experiments[] row is the source of truth. This module only derives
structural placeholders keyed by data-exp-id; it does not author measured values.
"""

from __future__ import annotations

import html
import re
from pathlib import Path


PLACEHOLDERS = {"", "unmeasured", "file:function", "tbd", "n/a", "none"}


def _esc(value) -> str:
    return html.escape(str(value), quote=True)


def _filled(value) -> bool:
    return str(value or "").strip().lower() not in PLACEHOLDERS


def _exp_id(exp: dict) -> str:
    return str(exp.get("id") or "").strip()


def _measures(exp: dict) -> bool:
    return bool(exp.get("measures", True))


def _has_result_table(text: str, eid: str) -> bool:
    escaped = _esc(eid)
    return (
        f'data-table="result-slot-{escaped}"' in text
        or f'data-table="result_table_{escaped}"' in text
        or f'data-source="tables/result_table_{escaped}.csv"' in text
    )


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


def _tbody_insert(text: str, table_body: str, rows: list[str]) -> str:
    if not rows:
        return text
    pat = re.compile(
        r'(<tbody[^>]*data-table-body="' + re.escape(table_body) + r'"[^>]*>)(.*?)(</tbody>)',
        re.DOTALL,
    )
    m = pat.search(text)
    if not m:
        return text
    body = m.group(2)
    # Remove the generic scaffold row when adding typed rows. Authored rows with
    # real exp ids are preserved.
    body = re.sub(
        r'\s*<tr[^>]*>\s*<td[^>]*data-field="exp-id"[^>]*>\s*unmeasured\s*</td>.*?</tr>',
        "",
        body,
        flags=re.DOTALL | re.IGNORECASE,
    )
    insertion = body.rstrip() + "\n" + "\n".join(rows) + "\n          "
    return text[:m.start(2)] + insertion + text[m.end(2):]


def _derive_results(package_root: Path, experiments: list[dict]) -> Path | None:
    path = package_root / "results.html"
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    original = text
    gate_rows = []
    result_slots = []
    for exp in experiments:
        eid = _exp_id(exp)
        if not eid or not _measures(exp):
            continue
        if f'data-exp-id="{_esc(eid)}"' not in text and f'data-field="exp-id">{_esc(eid)}<' not in text:
            gate = _esc(exp.get("gate") or "unmeasured")
            gate_rows.append(
                '            <tr id="gate-{low}" data-exp-id="{eid}" data-ack="result-pass" data-ack-value="">'
                '<td data-field="exp-id">{eid}</td>'
                '<td data-validity="missing">missing</td>'
                '<td data-field="baseline">unmeasured</td>'
                '<td data-field="plan-gate">{gate}</td>'
                '<td data-field="observed-metric">unmeasured</td>'
                '<td data-field="budget-use">unmeasured</td>'
                '<td data-field="seed-status">unmeasured</td>'
                '<td data-field="artifact-completeness">unmeasured</td>'
                '<td data-decision data-field="verdict">unmeasured</td>'
                '<td data-field="reason">unmeasured</td></tr>'.format(eid=_esc(eid), low=_esc(eid.lower()), gate=gate)
            )
        if not _has_result_table(text, eid):
            result_slots.append(
                '\n        <article class="result-block" id="result-slot-{low}" data-result-block data-exp-id="{eid}" data-phase-id="{eid}">\n'
                '          <h2>{eid} &mdash; result slot</h2>\n'
                '          <p class="block-summary"><em>unmeasured</em> &mdash; predefined home for this task\'s readings.</p>\n'
                '          <table class="data-table block-main-table" data-table="result-slot-{eid}" data-exp-id="{eid}">\n'
                '            <thead><tr><th>Metric</th><th>Value</th><th>Artifact</th></tr></thead>\n'
                '            <tbody data-table-body="result-slot-{eid}">\n'
                '              <tr><td>unmeasured</td><td>unmeasured</td><td>unmeasured</td></tr>\n'
                '            </tbody>\n'
                '          </table>\n'
                '        </article>'.format(eid=_esc(eid), low=_esc(eid.lower()))
            )
    text = _tbody_insert(text, "result-gate", gate_rows)
    if result_slots:
        bounds = _section_content_bounds(text, 'data-list="result-blocks"')
        if bounds:
            _, content_end = bounds
            text = text[:content_end].rstrip() + "".join(result_slots) + "\n      " + text[content_end:]
    if text != original:
        path.write_text(text, encoding="utf-8")
        return path
    return None


def _derive_implementation(package_root: Path, experiments: list[dict]) -> Path | None:
    path = package_root / "implementation.html"
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    original = text
    items = []
    for exp in experiments:
        eid = _exp_id(exp)
        if not eid or not exp.get("requiresCode"):
            continue
        if re.search(r'data-field="validating-exp"[^>]*>\s*' + re.escape(eid) + r'\s*<', text):
            continue
        items.append(
            '          <li data-exp-id="{eid}">\n'
            '            <strong data-field="change-id">change-{low}</strong>\n'
            '            <div class="kv-grid">\n'
            '              <div class="k">Code anchor</div><code data-field="code-anchor">file:function</code>\n'
            '              <div class="k">Expected sign</div><div data-field="expected-sign">unmeasured</div>\n'
            '              <div class="k">Magnitude band</div><div data-field="expected-magnitude">unmeasured</div>\n'
            '              <div class="k">Validating exps</div><div data-field="validating-exp">{eid}</div>\n'
            '            </div>\n'
            '          </li>'.format(eid=_esc(eid), low=_esc(eid.lower()))
        )
    if items:
        text = re.sub(
            r'\s*<li>\s*<strong[^>]*data-field="change-id"[^>]*>change-1</strong>.*?'
            r'<div[^>]*data-field="validating-exp"[^>]*>\s*unmeasured\s*</div>.*?</li>',
            "",
            text,
            count=1,
            flags=re.DOTALL | re.IGNORECASE,
        )
        text = re.sub(
            r'(data-list="changes-agent-detail"[^>]*>)(.*?)(</ul>)',
            lambda m: m.group(1) + m.group(2).rstrip() + "\n" + "\n".join(items) + "\n        " + m.group(3),
            text,
            count=1,
            flags=re.DOTALL,
        )
    if text != original:
        path.write_text(text, encoding="utf-8")
        return path
    return None


def _pipeline_doc_shell(package_root: Path) -> str:
    pkg = package_root.name
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'  <title>{_esc(pkg)} - Pipeline contract</title>\n'
        '  <link rel="stylesheet" href="../../../assets/research.css">\n</head>\n'
        f'<body data-page="docs" data-package-id="{_esc(pkg)}">\n  <div class="shell">\n'
        '    <header class="masthead" data-section="masthead">\n'
        '      <div class="eyebrow">pipeline contract</div>\n'
        '      <h1>Pipeline contract</h1>\n'
        '      <p class="lead">Per-task HOW blocks derived from inventory experiments[].</p>\n'
        '      <div class="toolbar"><a class="pill" href="../plan.html#experiments">Plan</a></div>\n'
        '      <div class="status-strip" data-status-strip aria-label="Package status (T2)"></div>\n'
        '    </header>\n'
        '    <nav class="package-nav" data-package-nav aria-label="Package pages"></nav>\n'
        '    <section data-section="task-spine" id="task-spine" aria-label="Task-spine blocks">\n'
        '    </section>\n'
        '  </div>\n'
        f'  <script>window.RESEARCH_PACKAGE_ID = "{_esc(pkg)}"; window.RESEARCH_ROOT_PREFIX = "../../../";</script>\n'
        '  <script src="../../../data/research-packages.js"></script>\n'
        '  <script src="../../../assets/research.js"></script>\n'
        '</body>\n</html>\n'
    )


def _derive_docs(package_root: Path, experiments: list[dict]) -> Path | None:
    complex_exps = [exp for exp in experiments if _exp_id(exp) and exp.get("complex")]
    if not complex_exps:
        return None
    path = package_root / "docs" / "pipeline.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_text(encoding="utf-8") if path.exists() else _pipeline_doc_shell(package_root)
    original = text
    blocks = []
    for exp in complex_exps:
        eid = _exp_id(exp)
        anchor = str(exp.get("docsAnchor") or f"docs/pipeline.html#{eid.lower()}").partition("#")[2] or eid.lower()
        if f'id="{_esc(anchor)}"' in text:
            continue
        blocks.append(
            '      <article class="module-card" data-exp-id="{eid}">\n'
            '        <h3 id="{anchor}" data-exp-id="{eid}">{eid}</h3>\n'
            '        <p class="card-text">{eid} &mdash; see <a href="../plan.html#experiments">plan.html#experiments</a> for purpose and gate.</p>\n'
            '        <div class="kv-grid">\n'
            '          <div class="k">Input schema</div><div>unmeasured</div>\n'
            '          <div class="k">Output schema</div><div>unmeasured</div>\n'
            '          <div class="k">Code anchors</div><code>file:function</code>\n'
            '        </div>\n'
            '      </article>'.format(eid=_esc(eid), anchor=_esc(anchor))
        )
    if blocks:
        text = text.replace("</section>", "\n".join(blocks) + "\n    </section>", 1)
    if text != original:
        path.write_text(text, encoding="utf-8")
        return path
    return None


def _derive_tracker(package_root: Path, experiments: list[dict]) -> Path | None:
    path = package_root / "tracker.html"
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    original = text
    items = []
    for exp in experiments:
        eid = _exp_id(exp)
        if not eid:
            continue
        if f'data-exp-id="{_esc(eid)}"' in text:
            continue
        purpose = _esc(exp.get("purpose") or "run task")
        items.append(
            '          <li data-exp-id="{eid}"><label><input type="checkbox"> {purpose}</label> '
            '&mdash; <a href="plan.html#experiments">{eid}</a></li>'.format(eid=_esc(eid), purpose=purpose)
        )
    if items:
        text = re.sub(
            r'\s*<li>\s*<label><input type="checkbox">\s*unmeasured\s*</label>.*?</li>',
            "",
            text,
            count=1,
            flags=re.DOTALL | re.IGNORECASE,
        )
        text = re.sub(
            r'(data-field="todo-list"[^>]*>)(.*?)(</ul>)',
            lambda m: m.group(1) + m.group(2).rstrip() + "\n" + "\n".join(items) + "\n        " + m.group(3),
            text,
            count=1,
            flags=re.DOTALL,
        )
    if text != original:
        path.write_text(text, encoding="utf-8")
        return path
    return None


def derive_task_blocks(package_root: Path, experiments: list[dict]) -> list[str]:
    """Derive missing placeholder blocks for a package experiments[] spine."""
    touched = []
    for path in (
        _derive_results(package_root, experiments),
        _derive_implementation(package_root, experiments),
        _derive_docs(package_root, experiments),
        _derive_tracker(package_root, experiments),
    ):
        if path is not None:
            touched.append(str(path))
    return touched


def has_authored_content_for_exp(package_root: Path, exp_id: str) -> list[str]:
    """Return derived blocks for exp_id that appear to contain authored content."""
    hits: list[str] = []
    eid = re.escape(exp_id)
    for rel in ("results.html", "implementation.html", "tracker.html", "docs/pipeline.html"):
        path = package_root / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for block in re.findall(
            r'<(?:tr|li|article|table)\b[^>]*data-exp-id="' + eid + r'"[^>]*>.*?</(?:tr|li|article|table)>',
            text,
            flags=re.DOTALL,
        ):
            fields = {
                k: re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", v)).strip()
                for k, v in re.findall(r'data-field="([^"]+)"[^>]*>(.*?)<', block, re.DOTALL)
            }
            if rel == "implementation.html":
                authored = (
                    _filled(fields.get("code-anchor")) and fields.get("code-anchor") != "file:function"
                ) or _filled(fields.get("expected-sign")) or _filled(fields.get("expected-magnitude"))
            elif rel == "results.html":
                authored = any(_filled(fields.get(k)) for k in (
                    "observed-metric", "budget-use", "seed-status", "artifact-completeness", "verdict", "reason"
                ))
            elif rel == "docs/pipeline.html":
                authored = "file:function" not in block or block.lower().count("unmeasured") < 2
            else:
                authored = "checked" in block
            if authored:
                hits.append(rel)
                break
    return sorted(set(hits))
