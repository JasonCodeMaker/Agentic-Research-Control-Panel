"""Brace-balanced JS scanning helpers for research_html/data/research-packages.js.

Earlier regex-based locators in insert.py / update.py broke on:
  - package blocks whose body contains nested {...} or [...] (the bounding
    [^{}]*? character class silently terminated at the first nested brace),
  - inventory field values containing literal '{' or '}' chars (e.g.
    "ann_p4_export_g{0a,0b,1a,1b}" in openRuns).

These helpers walk the source byte-by-byte, skipping JS strings and comments,
and respect brace/bracket nesting. They are not a full JS parser; they cover
the subset used in research-packages.js (object literals, arrays, single- and
double-quoted strings with backslash escapes, // line + /* block */ comments).
"""

import re


def _skip_string(text, i):
    if i >= len(text):
        return None
    q = text[i]
    if q not in ("'", '"'):
        return None
    j = i + 1
    n = len(text)
    while j < n:
        c = text[j]
        if c == "\\":
            j += 2
            continue
        if c == q:
            return j + 1
        j += 1
    return j


def _skip_comment(text, i):
    if text.startswith("//", i):
        nl = text.find("\n", i)
        return len(text) if nl < 0 else nl + 1
    if text.startswith("/*", i):
        end = text.find("*/", i + 2)
        return len(text) if end < 0 else end + 2
    return None


def find_matching_close(text, open_idx):
    """Return index one past the bracket that matches text[open_idx]."""
    open_ch = text[open_idx]
    close_ch = {"{": "}", "[": "]", "(": ")"}[open_ch]
    depth = 0
    i = open_idx
    n = len(text)
    while i < n:
        c = text[i]
        s_end = _skip_string(text, i)
        if s_end is not None:
            i = s_end
            continue
        c_end = _skip_comment(text, i)
        if c_end is not None:
            i = c_end
            continue
        if c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise ValueError(
        f"unbalanced '{open_ch}' at position {open_idx}: no matching '{close_ch}'"
    )


def find_package_block(text, pkg):
    """Locate the {...} object literal whose first key is `id: '<pkg>'`.

    Returns (start, end) with start at the '{' and end one past the '}', or
    None if the package is absent.
    """
    pat = re.compile(
        r"\{\s*id\s*:\s*['\"]" + re.escape(pkg) + r"['\"]",
        re.DOTALL,
    )
    m = pat.search(text)
    if not m:
        return None
    start = m.start()
    end = find_matching_close(text, start)
    return start, end


def find_top_level_field_value(block_text, field):
    """Find `<field>:` at depth 1 inside an object block (block_text[0]=='{').

    Returns (value_start, value_end) relative to block_text, with value_end
    exclusive. Nested {...} / [...] are skipped without descending, so a key
    of the same name inside a nested experiments[] row is never matched.
    """
    if not block_text or block_text[0] != "{":
        raise ValueError("block_text must begin with '{'")
    n = len(block_text)
    i = 1
    while i < n - 1:
        c = block_text[i]
        s_end = _skip_string(block_text, i)
        if s_end is not None:
            i = s_end
            continue
        c_end = _skip_comment(block_text, i)
        if c_end is not None:
            i = c_end
            continue
        if c == "{" or c == "[":
            i = find_matching_close(block_text, i)
            continue
        m = re.match(r"([A-Za-z_$][A-Za-z0-9_$]*)\s*:", block_text[i:])
        if m and m.group(1) == field:
            j = i + m.end()
            while j < n and block_text[j].isspace():
                j += 1
            value_start = j
            vc = block_text[value_start] if value_start < n else ""
            if vc in "{[":
                value_end = find_matching_close(block_text, value_start)
            else:
                s2 = _skip_string(block_text, value_start)
                if s2 is not None:
                    value_end = s2
                else:
                    k = value_start
                    while k < n and block_text[k] not in ",\n}":
                        k += 1
                    value_end = k
            return value_start, value_end
        i += 1
    return None


def find_array_item_by_id(array_text, target_id):
    """Within an array literal (array_text[0]=='['), find the {...} item whose
    `id` field equals target_id. Returns (start, end) at the item's outer braces,
    relative to array_text, or None.
    """
    if not array_text or array_text[0] != "[":
        raise ValueError("array_text must begin with '['")
    n = len(array_text)
    i = 1
    while i < n - 1:
        c = array_text[i]
        s_end = _skip_string(array_text, i)
        if s_end is not None:
            i = s_end
            continue
        cm_end = _skip_comment(array_text, i)
        if cm_end is not None:
            i = cm_end
            continue
        if c == "{":
            item_end = find_matching_close(array_text, i)
            item = array_text[i:item_end]
            id_bounds = find_top_level_field_value(item, "id")
            if id_bounds is not None:
                vs, ve = id_bounds
                id_lit = item[vs:ve]
                if id_lit.startswith(("'", '"')) and len(id_lit) >= 2:
                    try:
                        inner = bytes(id_lit[1:-1], "utf-8").decode("unicode_escape")
                    except UnicodeDecodeError:
                        inner = id_lit[1:-1]
                    if inner == target_id:
                        return i, item_end
            i = item_end
            continue
        i += 1
    return None
