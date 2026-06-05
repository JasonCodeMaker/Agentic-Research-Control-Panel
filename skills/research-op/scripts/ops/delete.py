"""Delete handlers for each target in the D-table (spec § 4.3)."""

import os
import re
from datetime import datetime
from pathlib import Path


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


def _remove_inventory_array_entry(pkg: str, array_field: str, entry_pat: str) -> str:
    """Remove one entry matching entry_pat from the named array in the package inventory."""
    p = Path("research_html/data/research-packages.js")
    text = p.read_text()
    # Locate the array block for this package.
    block_pat = re.compile(
        r"(\{[^{}]*?id:\s*['\"]" + re.escape(pkg) + r"['\"][^{}]*?"
        + array_field + r":\s*\[)([^\]]*?)(\])",
        re.DOTALL,
    )
    m = block_pat.search(text)
    if not m:
        raise SystemExit(f"package {pkg} or its {array_field} array not found")
    array_body = m.group(2)
    # Remove the matching entry plus one adjacent comma (before or after).
    entry_re = re.compile(entry_pat, re.DOTALL)
    em = entry_re.search(array_body)
    if not em:
        raise SystemExit(f"entry matching {entry_pat!r} not found in {array_field} for {pkg}")
    start, end = em.start(), em.end()
    # Strip a leading comma+whitespace if present; else a trailing comma+whitespace.
    before = array_body[:start].rstrip()
    after = array_body[end:].lstrip()
    if before.endswith(","):
        new_body = before[:-1] + after
    elif after.startswith(","):
        new_body = before + after[1:]
    else:
        new_body = before + after
    new_text = text[:m.start(2)] + new_body + text[m.end(2):]
    p.write_text(new_text)
    return str(p)


def delete_experiments_row(pkg: str, payload: dict) -> list[str]:
    """Remove the experiments[] entry with the given id from inventory."""
    eid = re.escape(payload["id"])
    entry_pat = r'\{[^{}]*?"id"\s*:\s*"' + eid + r'"[^{}]*?\}'
    return [_remove_inventory_array_entry(pkg, "experiments", entry_pat)]


def delete_tracker_live_check_row(pkg: str, payload: dict) -> list[str]:
    """Remove the <tr> whose second <td> matches exp_id from the live-check tbody."""
    exp_id = re.escape(payload["exp_id"])
    path = Path(f"research_html/packages/{pkg}/tracker.html")
    text = path.read_text()
    # Match a <tr> where the second <td> contains exp_id.
    row_pat = re.compile(
        r'<tr>[^<]*<td>[^<]*</td>\s*<td>' + exp_id + r'</td>.*?</tr>', re.DOTALL,
    )
    new = row_pat.sub("", text, count=1)
    path.write_text(new)
    _bump_last_updated(path)
    return [str(path)]


def delete_tracker_impl_review_row(pkg: str, payload: dict) -> list[str]:
    """Remove the <tr> whose first <td> matches change_id from the implementation-review tbody."""
    cid = re.escape(payload["change_id"])
    path = Path(f"research_html/packages/{pkg}/tracker.html")
    text = path.read_text()
    row_pat = re.compile(
        r'<tr>\s*<td>' + cid + r'</td>.*?</tr>', re.DOTALL,
    )
    new = row_pat.sub("", text, count=1)
    path.write_text(new)
    _bump_last_updated(path)
    return [str(path)]


def delete_methodstried(pkg: str, payload: dict) -> list[str]:
    """Remove the methodsTried[] entry whose evidencePath matches the given value."""
    ep = re.escape(payload["evidencePath"])
    entry_pat = r'\{[^{}]*?"evidencePath"\s*:\s*"' + ep + r'"[^{}]*?\}'
    return [_remove_inventory_array_entry(pkg, "methodsTried", entry_pat)]


def delete_doc_card(pkg: str, payload: dict) -> list[str]:
    """Remove <article data-doc-slug="<slug>">...</article> from docs/index.html."""
    slug = re.escape(payload["slug"])
    path = Path(f"research_html/packages/{pkg}/docs/index.html")
    text = path.read_text()
    article_pat = re.compile(
        r'<article[^>]*data-doc-slug="' + slug + r'"[^>]*>.*?</article>', re.DOTALL,
    )
    new = article_pat.sub("", text, count=1)
    path.write_text(new)
    _bump_last_updated(path)
    return [str(path)]


def delete_doc_file(pkg: str, payload: dict) -> list[str]:
    """Unlink docs/<slug>.html and remove its card from docs/index.html."""
    slug = payload["slug"]
    doc_path = Path(f"research_html/packages/{pkg}/docs/{slug}.html")
    doc_path.unlink()
    card_files = delete_doc_card(pkg, {"slug": slug})
    return [str(doc_path)] + card_files


_DISPATCH = {
    "experiments-row":        delete_experiments_row,
    "tracker-live-check-row": delete_tracker_live_check_row,
    "tracker-impl-review-row": delete_tracker_impl_review_row,
    "methodsTried":           delete_methodstried,
    "doc-file":               delete_doc_file,
    "doc-card":               delete_doc_card,
}


def handle(pkg: str, target: str | None, payload: dict, state: dict) -> tuple[str, list[str]]:
    fn = _DISPATCH.get(target)
    if fn is None:
        raise SystemExit(f"delete target not implemented yet: {target}")
    files = fn(pkg, payload)
    return "passed", files
