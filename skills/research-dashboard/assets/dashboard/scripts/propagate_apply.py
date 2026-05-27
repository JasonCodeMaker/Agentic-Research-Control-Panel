#!/usr/bin/env python3
"""Apply event manifests to research-packages.js / results.html / tracker.html.

Reads var/research/<pkg-id>/manifests/*.json that declare an "event" type and
lack a sibling .applied sidecar; dispatches each to its event handler; emits
the deterministic surface edits; marks the manifest applied. Dry-run by
default; --write commits the diff. --auto-derive scans every package and
emits state_derived manifests when narrative fields (currentBlocker /
nextRoute) drift from what experiments[].status implies.

Event types
-----------
verdict_finalized  exp_id, row_anchor, measured, verdict (pass|fail|inconclusive),
                   evidencePath, lastActionPhrase, hypothesis, gate
                   -> registry methodsTried[] append + exp status=completed +
                      results.html row cells + tracker last-action

status_changed     status, [category, lastActionPhrase]
                   -> registry top-level status + optional category lane move

adoption           adoptionPath, [lastActionPhrase]
                   -> status=ADOPTED, category=success, adoptionPath set

supersession       supersededBy, [lastActionPhrase]
                   -> status=SUPERSEDED, supersededBy set

reopen             reopenTrigger, [lastActionPhrase]
                   -> status=ARCHIVED_REOPENABLE, reopenTrigger set

state_derived      [currentBlocker, nextRoute, activeGate, primaryMetricVsGate]
                   -> top-level fields updated (any subset)
                   typically emitted by --auto-derive, but a launcher may
                   write one directly.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import sys
import time
from pathlib import Path


PKG_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}-[A-Za-z0-9_-]+$")
JS_STR = r'"(?:[^"\\]|\\.)*"'

VALID_VERDICTS = {"pass", "fail", "inconclusive"}


class EditError(RuntimeError):
    pass


# ---------- shared registry-edit primitives ----------

def _pkg_slice(text: str, pkg_id: str) -> tuple[int, int]:
    needle = f'id: "{pkg_id}"'
    start = text.find(needle)
    if start == -1:
        raise EditError(f'registry: package id "{pkg_id}" not found')
    end_m = re.search(r"^  \},$", text[start:], re.MULTILINE)
    if not end_m:
        raise EditError(f'registry: end of package block "{pkg_id}" not found')
    obj_start = text.rfind("  {\n", 0, start)
    if obj_start == -1:
        obj_start = start
    return obj_start, start + end_m.end()


def _replace_top_field(obj_text: str, key: str, new_value: str) -> str:
    pat = re.compile(rf"^(    {re.escape(key)}: ){JS_STR}(,)$", re.MULTILINE)
    if not pat.search(obj_text):
        return obj_text  # field absent; silent skip
    return pat.sub(lambda m: m.group(1) + json.dumps(new_value) + m.group(2), obj_text, count=1)


def _read_top_field(obj_text: str, key: str) -> str | None:
    """Return the field's value, or None if the field is absent from the package."""
    pat = re.compile(rf'^    {re.escape(key)}: "((?:[^"\\]|\\.)*)",?$', re.MULTILINE)
    m = pat.search(obj_text)
    return m.group(1) if m else None


def _stamp_last_action(obj_text: str, phrase: str | None) -> str:
    if not phrase:
        return obj_text
    today = time.strftime("%Y-%m-%d")
    return _replace_top_field(obj_text, "lastAction", f"{today} -- {phrase}")


def _stamp_today(obj_text: str) -> str:
    return _replace_top_field(obj_text, "lastUpdated", time.strftime("%Y-%m-%d"))


def _set_experiment_status(obj_text: str, exp_id: str, new_status: str) -> str:
    pat = re.compile(
        rf'(id: "{re.escape(exp_id)}",\n(?:.|\n)*?\n        status: ")[^"]*(")',
    )
    if not pat.search(obj_text):
        raise EditError(f'registry: experiments[].id == "{exp_id}" not found')
    return pat.sub(lambda m: m.group(1) + new_status + m.group(2), obj_text, count=1)


def _parse_experiments(obj_text: str) -> list[dict]:
    m = re.search(r"\n    experiments: \[(.*?)\n    \],", obj_text, re.DOTALL)
    if not m:
        return []
    body = m.group(1)
    out: list[dict] = []
    for em in re.finditer(r'id: "([^"]+)"', body):
        eid = em.group(1)
        tail = body[em.end():]
        # Next status: "..." within this experiment object (before next id: or end)
        next_id = re.search(r'\n      \{', tail)
        scope = tail[: next_id.start()] if next_id else tail
        sm = re.search(r'status: "([^"]+)"', scope)
        if sm:
            out.append({"id": eid, "status": sm.group(1)})
    return out


# ---------- results.html ----------

def edit_results_html(text: str, manifest: dict) -> str:
    row_id = manifest["row_anchor"]
    measured = manifest.get("measured", {})
    verdict = manifest["verdict"]

    observed = manifest.get("observed_cell_text")
    if observed is None:
        parts = [f"{k}={v}" for k, v in measured.items() if k != "avg_cand"]
        observed = ", ".join(parts) if parts else "measured"

    budget = manifest.get("budget_cell_text")
    if budget is None and "avg_cand" in measured:
        cap_m = re.search(r"avg_cand\s*<=\s*(\d+)", manifest.get("gate", ""))
        cap = cap_m.group(1) if cap_m else "&mdash;"
        budget = f"avg_cand={measured['avg_cand']} / gate {cap}"
    budget = budget or "&mdash;"

    artifact = manifest.get("artifact_cell_text") or manifest.get("best_model", "verified")

    row_pat = re.compile(
        r'(<tr[^>]*\sid="' + re.escape(row_id) + r'"[^>]*>)(.*?)(</tr>)',
        re.DOTALL,
    )
    m = row_pat.search(text)
    if not m:
        raise EditError(f'results.html: no <tr id="{row_id}"> found')

    head, body, tail = m.group(1), m.group(2), m.group(3)

    def replace_cell(body: str, field: str, new_inner: str) -> str:
        cell_pat = re.compile(
            r'(<td[^>]*\sdata-field="' + re.escape(field) + r'"[^>]*>)(.*?)(</td>)',
            re.DOTALL,
        )
        if not cell_pat.search(body):
            return body
        return cell_pat.sub(lambda mm: mm.group(1) + new_inner + mm.group(3), body, count=1)

    body = replace_cell(body, "observed-metric", observed)
    body = replace_cell(body, "budget-use", budget)
    body = replace_cell(body, "artifact-completeness", artifact)
    body = re.sub(
        r'(<td[^>]*\sdata-decision[^>]*>)(.*?)(</td>)',
        lambda mm: mm.group(1) + verdict + mm.group(3),
        body,
        count=1,
        flags=re.DOTALL,
    )
    return text[: m.start()] + head + body + tail + text[m.end() :]


# ---------- tracker.html ----------

def edit_tracker_html(text: str, manifest: dict) -> str:
    phrase = manifest.get("lastActionPhrase")
    if not phrase:
        return text
    new_inner = f"{time.strftime('%Y-%m-%d')} -- {phrase}"
    pat = re.compile(
        r'(<div[^>]*\sdata-field="last-action"[^>]*>)(.*?)(</div>)',
        re.DOTALL,
    )
    if not pat.search(text):
        raise EditError('tracker.html: no <div data-field="last-action"> found')
    return pat.sub(lambda m: m.group(1) + new_inner + m.group(3), text, count=1)


# ---------- event handlers ----------

def _format_methods_row(manifest: dict) -> str:
    measured = manifest.get("measured", {})
    measured_str = ", ".join(f"{k}={v}" for k, v in measured.items())
    return (
        "      {\n"
        f"        method: {json.dumps(manifest['exp_id'])},\n"
        f"        hypothesis: {json.dumps(manifest.get('hypothesis', ''))},\n"
        f"        gate: {json.dumps(manifest.get('gate', ''))},\n"
        f"        measured: {json.dumps(measured_str)},\n"
        f"        verdict: {json.dumps(manifest['verdict'])},\n"
        f"        evidencePath: {json.dumps(manifest.get('evidencePath', ''))},\n"
        "      },\n"
    )


def _append_methods_tried(obj_text: str, row: str) -> str:
    if re.search(r"\n    methodsTried: \[", obj_text):
        close_pat = re.compile(r"(\n    methodsTried: \[(?:.|\n)*?\n)(    \],\n)")
        return close_pat.sub(lambda m: m.group(1) + row + m.group(2), obj_text, count=1)
    block = f"    methodsTried: [\n{row}    ],\n"
    if "    experiments: [" not in obj_text:
        raise EditError("registry: cannot find experiments: [ to anchor a new methodsTried block")
    return obj_text.replace("    experiments: [", block + "    experiments: [", 1)


def handle_verdict_finalized(manifest: dict, pkg_id: str) -> dict:
    for key in ("exp_id", "row_anchor", "measured", "verdict"):
        if key not in manifest:
            raise EditError(f"verdict_finalized: required key missing: {key}")
    if manifest["verdict"] not in VALID_VERDICTS:
        raise EditError(f"verdict_finalized: invalid verdict: {manifest['verdict']}")

    exp_id = manifest["exp_id"]
    phrase = manifest.get("lastActionPhrase", f"{exp_id} verdict={manifest['verdict']}")
    pm = manifest.get("primaryMetricVsGate")
    ag = manifest.get("activeGate")

    def edit_registry(text: str) -> str:
        obj_start, obj_end = _pkg_slice(text, pkg_id)
        obj = text[obj_start:obj_end]
        obj = _stamp_last_action(obj, phrase)
        obj = _stamp_today(obj)
        if pm is not None:
            obj = _replace_top_field(obj, "primaryMetricVsGate", pm)
        if ag is not None:
            obj = _replace_top_field(obj, "activeGate", ag)
        obj = _set_experiment_status(obj, exp_id, "completed")
        obj = _append_methods_tried(obj, _format_methods_row(manifest))
        return text[:obj_start] + obj + text[obj_end:]

    return {
        "research_html/data/research-packages.js": edit_registry,
        f"research_html/packages/{pkg_id}/results.html": lambda t: edit_results_html(t, manifest),
        f"research_html/packages/{pkg_id}/tracker.html": lambda t: edit_tracker_html(t, manifest),
    }


def _pkg_state_edit(pkg_id: str, fields: dict, phrase: str | None) -> "callable":
    """Build a registry editor that writes the given top-level fields + bumps
    lastAction/lastUpdated only when at least one field actually changes."""
    def edit(text: str) -> str:
        obj_start, obj_end = _pkg_slice(text, pkg_id)
        obj = text[obj_start:obj_end]
        before = obj
        for key, value in fields.items():
            obj = _replace_top_field(obj, key, value)
        if obj != before:
            obj = _stamp_last_action(obj, phrase)
            obj = _stamp_today(obj)
        return text[:obj_start] + obj + text[obj_end:]
    return edit


def handle_status_changed(manifest: dict, pkg_id: str) -> dict:
    if "status" not in manifest:
        raise EditError("status_changed: 'status' required")
    fields = {"status": manifest["status"]}
    if "category" in manifest:
        fields["category"] = manifest["category"]
    targets = {
        "research_html/data/research-packages.js": _pkg_state_edit(pkg_id, fields, manifest.get("lastActionPhrase")),
    }
    if manifest.get("lastActionPhrase"):
        targets[f"research_html/packages/{pkg_id}/tracker.html"] = lambda t: edit_tracker_html(t, manifest)
    return targets


def handle_adoption(manifest: dict, pkg_id: str) -> dict:
    if "adoptionPath" not in manifest:
        raise EditError("adoption: 'adoptionPath' required")
    fields = {
        "status": "ADOPTED",
        "category": "success",
        "adoptionPath": manifest["adoptionPath"],
    }
    targets = {
        "research_html/data/research-packages.js": _pkg_state_edit(pkg_id, fields, manifest.get("lastActionPhrase")),
    }
    if manifest.get("lastActionPhrase"):
        targets[f"research_html/packages/{pkg_id}/tracker.html"] = lambda t: edit_tracker_html(t, manifest)
    return targets


def handle_supersession(manifest: dict, pkg_id: str) -> dict:
    if "supersededBy" not in manifest:
        raise EditError("supersession: 'supersededBy' required")
    fields = {
        "status": "SUPERSEDED",
        "supersededBy": manifest["supersededBy"],
    }
    targets = {
        "research_html/data/research-packages.js": _pkg_state_edit(pkg_id, fields, manifest.get("lastActionPhrase")),
    }
    if manifest.get("lastActionPhrase"):
        targets[f"research_html/packages/{pkg_id}/tracker.html"] = lambda t: edit_tracker_html(t, manifest)
    return targets


def handle_reopen(manifest: dict, pkg_id: str) -> dict:
    if "reopenTrigger" not in manifest:
        raise EditError("reopen: 'reopenTrigger' required")
    fields = {
        "status": "ARCHIVED_REOPENABLE",
        "reopenTrigger": manifest["reopenTrigger"],
    }
    targets = {
        "research_html/data/research-packages.js": _pkg_state_edit(pkg_id, fields, manifest.get("lastActionPhrase")),
    }
    if manifest.get("lastActionPhrase"):
        targets[f"research_html/packages/{pkg_id}/tracker.html"] = lambda t: edit_tracker_html(t, manifest)
    return targets


def handle_state_derived(manifest: dict, pkg_id: str) -> dict:
    fields = {}
    for key in ("currentBlocker", "nextRoute", "activeGate", "primaryMetricVsGate"):
        if key in manifest:
            fields[key] = manifest[key]
    if not fields:
        raise EditError("state_derived: at least one of currentBlocker/nextRoute/activeGate/primaryMetricVsGate required")
    return {
        "research_html/data/research-packages.js": _pkg_state_edit(pkg_id, fields, manifest.get("lastActionPhrase")),
    }


EVENT_DISPATCH = {
    "verdict_finalized": handle_verdict_finalized,
    "status_changed": handle_status_changed,
    "adoption": handle_adoption,
    "supersession": handle_supersession,
    "reopen": handle_reopen,
    "state_derived": handle_state_derived,
}


# ---------- auto-derive ----------

def derive_state(category: str, experiments: list[dict]) -> dict:
    """Return derived currentBlocker / nextRoute from experiment statuses.

    Rules are conservative; an empty string means 'no rule fired, do not override'.
    """
    statuses = [e["status"] for e in experiments]
    failed = [e["id"] for e in experiments if e["status"] == "failed"]
    blocked = [e["id"] for e in experiments if e["status"] == "blocked"]
    running = [e["id"] for e in experiments if e["status"] == "running"]
    pending = [e["id"] for e in experiments if e["status"] in {"pending", "queued"}]
    all_terminal = bool(experiments) and all(s in {"completed", "skipped"} for s in statuses)

    if category in {"success", "fail"}:
        return {"currentBlocker": "", "nextRoute": "archive_or_stop"}
    if failed:
        return {
            "currentBlocker": f"experiments[] failed: {', '.join(failed)}",
            "nextRoute": "archive_or_stop",
        }
    if blocked:
        return {
            "currentBlocker": f"experiments[] blocked: {', '.join(blocked)}",
            "nextRoute": "run_next_experiment_from_step4",
        }
    if running:
        return {
            "currentBlocker": "",
            "nextRoute": "run_next_experiment_from_step4",
        }
    if all_terminal:
        return {"currentBlocker": "", "nextRoute": "archive_or_stop"}
    if pending:
        return {"currentBlocker": "", "nextRoute": "run_next_experiment_from_step4"}
    return {"currentBlocker": "", "nextRoute": ""}


def auto_derive(repo_root: Path) -> list[Path]:
    """Scan every package; write _auto_state_<sha>.json under each package whose
    derived currentBlocker / nextRoute drifts from the registry's current value."""
    registry_path = repo_root / "research_html" / "data" / "research-packages.js"
    if not registry_path.exists():
        return []
    text = registry_path.read_text()

    written: list[Path] = []
    var_root = repo_root / "var" / "research"
    if not var_root.exists():
        return written

    for pkg_dir in sorted(var_root.iterdir()):
        if not (pkg_dir.is_dir() and PKG_RE.match(pkg_dir.name)):
            continue
        pkg_id = pkg_dir.name
        try:
            obj_start, obj_end = _pkg_slice(text, pkg_id)
        except EditError:
            continue
        obj = text[obj_start:obj_end]
        category = _read_top_field(obj, "category")
        experiments = _parse_experiments(obj)
        if not experiments:
            continue

        derived = derive_state(category or "", experiments)
        drift = {}
        for key in ("currentBlocker", "nextRoute"):
            current = _read_top_field(obj, key)
            # Conservative auto-fill: only override when (a) the field is
            # present in the registry, (b) it is currently blank, and (c) the
            # derived value is non-empty. Non-blank values are human-curated
            # and stay untouched — verdict_finalized / status_changed events
            # are the way to overwrite them.
            if current is None or current != "":
                continue
            if derived[key]:
                drift[key] = derived[key]
        if not drift:
            continue

        payload = {"event": "state_derived", **drift}
        sha = hashlib.sha1(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:8]
        manifests_dir = pkg_dir / "manifests"
        manifests_dir.mkdir(parents=True, exist_ok=True)
        out = manifests_dir / f"_auto_state_{sha}.json"
        # Idempotent: skip if this exact derived payload was already applied.
        if Path(str(out) + ".applied").exists():
            continue
        if out.exists() and out.read_text().strip() == json.dumps(payload, indent=2):
            continue
        out.write_text(json.dumps(payload, indent=2) + "\n")
        written.append(out)
    return written


# ---------- driver ----------

def repo_root_from(script_path: Path) -> Path:
    return script_path.parent.parent.parent


def unified(before: str, after: str, path: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            n=2,
        )
    )


def _is_event_manifest(path: Path) -> bool:
    """Return True iff the file is a dict JSON with a recognized event key.

    Other JSON files (launcher artifacts, output manifests, sweep configs) that
    happen to live in manifests/ are silently ignored.
    """
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return False
    return isinstance(data, dict) and data.get("event") in EVENT_DISPATCH


def discover_manifests(repo_root: Path, pkg_filter: str | None) -> list[Path]:
    root = repo_root / "var" / "research"
    if not root.exists():
        return []
    pkgs = (
        [pkg_filter]
        if pkg_filter
        else [p.name for p in root.iterdir() if p.is_dir() and PKG_RE.match(p.name)]
    )
    out: list[Path] = []
    for pkg in pkgs:
        d = root / pkg / "manifests"
        if not d.exists():
            continue
        for m in sorted(d.glob("*.json")):
            if m.name.endswith(".applied"):
                continue
            if Path(str(m) + ".applied").exists():
                continue
            if not _is_event_manifest(m):
                continue
            out.append(m)
    return out


def apply_one(manifest_path: Path, repo_root: Path, write: bool) -> dict:
    manifest = json.loads(manifest_path.read_text())
    if not isinstance(manifest, dict):
        raise EditError(f"{manifest_path.name}: manifest must be a JSON object, not {type(manifest).__name__}")
    pkg_id = manifest_path.parents[1].name
    if not PKG_RE.match(pkg_id):
        raise EditError(f'invalid package id derived from path: "{pkg_id}"')

    event = manifest.get("event")
    if event not in EVENT_DISPATCH:
        raise EditError(f"{manifest_path.name}: unsupported event: {event}")

    targets = EVENT_DISPATCH[event](manifest, pkg_id)

    diffs: dict[str, str] = {}
    new_texts: dict[str, str] = {}
    for rel, fn in targets.items():
        path = repo_root / rel
        if not path.exists():
            raise EditError(f"missing surface: {rel}")
        before = path.read_text()
        after = fn(before)
        if before != after:
            diffs[rel] = unified(before, after, rel)
            new_texts[rel] = after

    if write:
        for rel, after in new_texts.items():
            (repo_root / rel).write_text(after)
        Path(str(manifest_path) + ".applied").touch()

    return {"manifest": str(manifest_path), "pkg": pkg_id, "event": event, "diffs": diffs}


def run_apply_phase(repo_root: Path, pkg_filter: str | None, write: bool, manifest: Path | None = None) -> bool:
    manifests = [manifest] if manifest else discover_manifests(repo_root, pkg_filter)
    if not manifests:
        return False
    any_changes = False
    for mp in manifests:
        try:
            result = apply_one(mp, repo_root, write)
        except EditError as e:
            print(f"[error] {mp}: {e}", file=sys.stderr)
            continue
        if not result["diffs"]:
            print(f"[noop] {mp.name}: no surface changes")
            continue
        any_changes = True
        mode = "WRITE" if write else "DRY-RUN"
        rel = mp.relative_to(repo_root) if mp.is_absolute() and repo_root in mp.parents else mp
        print(f"\n=== {mode}: {rel} -> {result['pkg']} [{result['event']}] ===")
        for diff in result["diffs"].values():
            print(diff)
    return any_changes


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--pkg", help="restrict to one package id")
    ap.add_argument("--manifest", type=Path, help="apply one explicit manifest path")
    ap.add_argument("--write", action="store_true", help="commit edits (default: dry-run)")
    ap.add_argument(
        "--auto-derive",
        action="store_true",
        help="before/after apply, scan packages and emit state_derived manifests for drifted narrative fields",
    )
    ap.add_argument("--repo-root", type=Path, default=None)
    args = ap.parse_args()

    repo_root = (args.repo_root or repo_root_from(Path(__file__).resolve())).resolve()

    if args.auto_derive:
        # Phase 1: apply pre-existing manifests so registry reflects current state.
        any_pre = run_apply_phase(repo_root, args.pkg, args.write, args.manifest)
        # Phase 2: scan for narrative-field drift; write _auto_state_*.json manifests.
        written = auto_derive(repo_root)
        if written:
            print(f"\n[auto-derive] wrote {len(written)} state_derived draft(s):", file=sys.stderr)
            for p in written:
                print(f"  - {p.relative_to(repo_root)}", file=sys.stderr)
        # Phase 3: apply the new drafts (and any other late-arriving manifests).
        any_post = run_apply_phase(repo_root, args.pkg, args.write, None)
        any_changes = any_pre or any_post
    else:
        any_changes = run_apply_phase(repo_root, args.pkg, args.write, args.manifest)

    if not args.write and any_changes:
        print(
            "\n(dry-run only; pass --write to commit and mark manifests .applied)",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
