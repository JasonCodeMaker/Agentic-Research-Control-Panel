"""Update handlers for each target in the U-table (spec § 4.2)."""

import json
import re
from datetime import datetime
from pathlib import Path

from . import _pkg_block


def _update_inventory_field(pkg: str, field: str, value) -> str:
    """Set `<pkg>.<field> = <value>` in research-packages.js, replacing the existing value."""
    p = Path("research_html/data/research-packages.js")
    text = p.read_text()
    bounds = _pkg_block.find_package_block(text, pkg)
    if bounds is None:
        raise SystemExit(f"package {pkg} not found in inventory")
    pkg_start, pkg_end = bounds
    block = text[pkg_start:pkg_end]
    fv = _pkg_block.find_top_level_field_value(block, field)
    new_val = json.dumps(value)
    if fv is None:
        id_fv = _pkg_block.find_top_level_field_value(block, "id")
        if id_fv is None:
            raise SystemExit(f"package {pkg} has no id field in its block")
        _, id_end = id_fv
        new_block = block[:id_end] + f", {field}: {new_val}" + block[id_end:]
    else:
        value_start, value_end = fv
        new_block = block[:value_start] + new_val + block[value_end:]
    p.write_text(text[:pkg_start] + new_block + text[pkg_end:])
    return str(p)


def update_status(pkg: str, payload: dict) -> list[str]:
    files = [_update_inventory_field(pkg, "status", payload["to"])]
    # Updates that move into success / fail also need terminationMessage etc., but those are
    # separate Update ops the caller must sequence (E3 / E4 / E5 / E6).
    return files


def update_simple_field(pkg: str, payload: dict, field: str) -> list[str]:
    return [_update_inventory_field(pkg, field, payload["to"])]


def update_experiments_status(pkg: str, payload: dict) -> list[str]:
    """Find experiments[] entry by id in inventory and update its status field."""
    exp_id = payload["id"]
    new_status = payload["to"]
    p = Path("research_html/data/research-packages.js")
    text = p.read_text()
    bounds = _pkg_block.find_package_block(text, pkg)
    if bounds is None:
        raise SystemExit(f"package {pkg} not found in inventory")
    pkg_start, pkg_end = bounds
    block = text[pkg_start:pkg_end]
    fv = _pkg_block.find_top_level_field_value(block, "experiments")
    if fv is None:
        raise SystemExit(f"package {pkg} has no experiments array")
    arr_start, arr_end = fv  # at '[' .. one past ']'
    array_text = block[arr_start:arr_end]
    item_bounds = _pkg_block.find_array_item_by_id(array_text, exp_id)
    if item_bounds is None:
        raise SystemExit(f"experiment {exp_id} not found in package {pkg}")
    item_start, item_end = item_bounds
    item_text = array_text[item_start:item_end]
    new_val = json.dumps(new_status)
    status_fv = _pkg_block.find_top_level_field_value(item_text, "status")
    if status_fv is None:
        id_fv = _pkg_block.find_top_level_field_value(item_text, "id")
        if id_fv is None:
            raise SystemExit(f"experiment {exp_id} has no id field?")
        _, id_end = id_fv
        new_item = item_text[:id_end] + f", status: {new_val}" + item_text[id_end:]
    else:
        vs, ve = status_fv
        new_item = item_text[:vs] + new_val + item_text[ve:]
    new_array = array_text[:item_start] + new_item + array_text[item_end:]
    new_block = block[:arr_start] + new_array + block[arr_end:]
    p.write_text(text[:pkg_start] + new_block + text[pkg_end:])
    return [str(p)]


def update_ack_slot(pkg: str, payload: dict) -> list[str]:
    """Set data-ack-value on the matching data-ack element in the named HTML page."""
    page = payload["page"]
    ack_type = payload["ack_type"]
    value = payload["to"]
    path = Path(f"research_html/packages/{pkg}/{page}")
    text = path.read_text()
    new = re.sub(
        r'(data-ack="' + re.escape(ack_type) + r'"\s+data-ack-value=)""',
        rf'\1"{value}"',
        text, count=1,
    )
    iso = datetime.now().date().isoformat()
    new = re.sub(
        r'(<time[^>]*data-field="last-updated"[^>]*>)[^<]*(</time>)',
        rf'\1{iso}\2', new,
    )
    path.write_text(new)
    return [str(path)]


def update_results_verdict(pkg: str, payload: dict) -> list[str]:
    """Update the verdict cell for a result-gate row identified by data-exp-id."""
    exp_id = payload["exp_id"]
    verdict = payload["to"]
    path = Path(f"research_html/packages/{pkg}/results.html")
    text = path.read_text()
    # Try to find the row by data-exp-id and update data-cell="verdict" inside it.
    row_pat = re.compile(
        r'(<tr[^>]*data-exp-id="' + re.escape(exp_id) + r'"[^>]*>)(.*?)(</tr>)',
        re.DOTALL,
    )
    m = row_pat.search(text)
    if not m:
        raise SystemExit(f"result-gate row for exp_id={exp_id} not found in {path}")
    row_inner = m.group(2)
    verdict_cell_pat = re.compile(
        r'(<td[^>]*data-cell="verdict"[^>]*>)[^<]*(</td>)',
        re.DOTALL,
    )
    vc = verdict_cell_pat.search(row_inner)
    if vc:
        new_inner = row_inner[:vc.start()] + f'{vc.group(1)}{verdict}{vc.group(2)}' + row_inner[vc.end():]
    else:
        # Fall back: replace the 9th <td> (0-indexed 8) — verdict column position.
        cells = list(re.finditer(r'<td[^>]*>.*?</td>', row_inner, re.DOTALL))
        if len(cells) < 9:
            raise SystemExit(f"row for {exp_id} has fewer than 9 cells; cannot locate verdict")
        c = cells[8]
        new_inner = (
            row_inner[:c.start()]
            + re.sub(r'(<td[^>]*>)[^<]*(</td>)', rf'\g<1>{verdict}\g<2>', c.group(), count=1)
            + row_inner[c.end():]
        )
    new_text = text[:m.start(2)] + new_inner + text[m.end(2):]
    iso = datetime.now().date().isoformat()
    new_text = re.sub(
        r'(<time[^>]*data-field="last-updated"[^>]*>)[^<]*(</time>)',
        rf'\1{iso}\2', new_text,
    )
    path.write_text(new_text)
    return [str(path)]


def update_last_updated_time(pkg: str, payload: dict) -> list[str]:
    """Set <time data-field="last-updated"> to today on the named page."""
    page = payload["page"]
    path = Path(f"research_html/packages/{pkg}/{page}")
    text = path.read_text()
    iso = datetime.now().date().isoformat()
    new = re.sub(
        r'(<time[^>]*data-field="last-updated"[^>]*>)[^<]*(</time>)',
        rf'\1{iso}\2', text,
    )
    path.write_text(new)
    return [str(path)]


_DISPATCH = {
    "status":               update_status,
    "activeGate":           lambda p, pl: update_simple_field(p, pl, "activeGate"),
    "primaryMetricVsGate":  lambda p, pl: update_simple_field(p, pl, "primaryMetricVsGate"),
    "lastAction":           lambda p, pl: update_simple_field(p, pl, "lastAction"),
    "lastUpdated":          lambda p, pl: update_simple_field(p, pl, "lastUpdated"),
    "openRuns":             lambda p, pl: update_simple_field(p, pl, "openRuns"),
    "currentBlocker":       lambda p, pl: update_simple_field(p, pl, "currentBlocker"),
    "terminationMessage":   lambda p, pl: update_simple_field(p, pl, "terminationMessage"),
    "adoptionPath":         lambda p, pl: update_simple_field(p, pl, "adoptionPath"),
    "supersededBy":         lambda p, pl: update_simple_field(p, pl, "supersededBy"),
    "reopenTrigger":        lambda p, pl: update_simple_field(p, pl, "reopenTrigger"),
    "experiments-status":   update_experiments_status,
    "ack-slot":             update_ack_slot,
    "results-verdict":      update_results_verdict,
    "last-updated-time":    update_last_updated_time,
}


def handle(pkg: str, target: str | None, payload: dict, state: dict) -> tuple[str, list[str]]:
    fn = _DISPATCH.get(target)
    if fn is None:
        raise SystemExit(f"update target not implemented yet: {target}")
    files = fn(pkg, payload)
    return "passed", files
