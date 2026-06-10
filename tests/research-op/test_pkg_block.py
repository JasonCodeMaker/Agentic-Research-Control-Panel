"""Regression tests for _pkg_block — the brace-balanced JS scanner.

Reproduces two prior failure modes:
  1. _append_to_inventory_array failed with "package not found" when the
     package had another array-of-objects field (e.g. methodsTried[{...}])
     after the target array, because [^{}]*? in the bounding regex stopped
     at the first nested brace.
  2. _update_inventory_field silently created a duplicate `status` key
     when an earlier inventory string contained literal '{' / '}' chars
     (e.g. "ann_p4_export_g{0a,0b,1a,1b}" in openRuns) — the [^{}] class
     terminated mid-string, so the field locator's bounding span never
     reached the real `status:` later in the block.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

# Load _pkg_block, insert, update from the skills tree directly.
ROOT = Path(__file__).resolve().parents[2]
SKILL_OPS = ROOT / "skills" / "research-op" / "scripts" / "ops"


# insert.py / update.py import `_pkg_block` via `from . import _pkg_block`, so
# all three modules must be loaded as members of a synthetic `ops` package.
_pkg_pkg = importlib.util.module_from_spec(
    importlib.util.spec_from_loader("ops", loader=None, is_package=True),
)
_pkg_pkg.__path__ = [str(SKILL_OPS)]
sys.modules["ops"] = _pkg_pkg


def _load(name):
    spec = importlib.util.spec_from_file_location(
        f"ops.{name}", SKILL_OPS / f"{name}.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


_pkg_block = _load("_pkg_block")


# A realistic inventory snippet that triggers both prior bugs:
#  - methodsTried[{...}] after experiments[]  (bug 1)
#  - openRuns value contains "g{0a,0b,1a,1b}" literal braces (bug 2)
_INVENTORY = """\
const RESEARCH_PACKAGES = [
  {
    id: "harness-test", lastAction: "noop", openRuns: "ann_p4_export_g{0a,0b,1a,1b} running",
    name: "Harness Test",
    category: "in-progress",
    status: "EXPERIMENT_RUNNING",
    experiments: [
      { id: "E1", status: "COMPLETED" },
      { id: "E2", status: "QUEUED" },
    ],
    methodsTried: [
      { method: "m1", verdict: "pass", evidencePath: "p1" },
    ],
  },
  {
    id: "other-pkg",
    category: "in-progress",
    status: "CONTEXT_LOADED",
  },
];
"""


def test_find_package_block_skips_inline_brace_strings():
    bounds = _pkg_block.find_package_block(_INVENTORY, "harness-test")
    assert bounds is not None
    start, end = bounds
    block = _INVENTORY[start:end]
    assert block.startswith("{")
    assert block.endswith("}")
    # The block must contain the nested experiments/methodsTried arrays.
    assert "experiments" in block
    assert "methodsTried" in block
    # And must not bleed into the next package.
    assert "other-pkg" not in block


def test_find_other_package_is_unaffected():
    bounds = _pkg_block.find_package_block(_INVENTORY, "other-pkg")
    assert bounds is not None
    start, end = bounds
    block = _INVENTORY[start:end]
    assert "harness-test" not in block
    assert 'status: "CONTEXT_LOADED"' in block


def test_find_top_level_field_value_does_not_descend():
    bounds = _pkg_block.find_package_block(_INVENTORY, "harness-test")
    block = _INVENTORY[slice(*bounds)]
    fv = _pkg_block.find_top_level_field_value(block, "status")
    assert fv is not None
    vs, ve = fv
    # Must match the OUTER status (EXPERIMENT_RUNNING), not the nested one.
    assert block[vs:ve] == '"EXPERIMENT_RUNNING"'


def test_find_top_level_field_value_brace_string_value():
    bounds = _pkg_block.find_package_block(_INVENTORY, "harness-test")
    block = _INVENTORY[slice(*bounds)]
    fv = _pkg_block.find_top_level_field_value(block, "openRuns")
    assert fv is not None
    vs, ve = fv
    # The literal value must be captured intact, including the '{...}' inside.
    assert "g{0a,0b,1a,1b}" in block[vs:ve]


def test_find_array_item_by_id():
    bounds = _pkg_block.find_package_block(_INVENTORY, "harness-test")
    block = _INVENTORY[slice(*bounds)]
    fv = _pkg_block.find_top_level_field_value(block, "experiments")
    arr = block[slice(*fv)]
    item = _pkg_block.find_array_item_by_id(arr, "E2")
    assert item is not None
    s, e = item
    assert arr[s:e].startswith("{")
    assert 'id: "E2"' in arr[s:e]
    assert 'status: "QUEUED"' in arr[s:e]


def test_round_trip_insert_after_method_tried_block(tmp_path, monkeypatch):
    """Bug 1 regression: appending an experiments[] row must succeed even
    when the package has methodsTried[{...}] after experiments[]."""
    insert = _load("insert")
    p = tmp_path / "research_html" / "data" / "research-packages.js"
    p.parent.mkdir(parents=True)
    p.write_text(_INVENTORY)
    monkeypatch.chdir(tmp_path)
    insert._append_to_inventory_array(
        "harness-test", "experiments",
        {"id": "E3", "status": "QUEUED"},
    )
    new_text = p.read_text()
    # E3 must land inside the experiments array, not the methodsTried array.
    bounds = _pkg_block.find_package_block(new_text, "harness-test")
    block = new_text[slice(*bounds)]
    exp_fv = _pkg_block.find_top_level_field_value(block, "experiments")
    methods_fv = _pkg_block.find_top_level_field_value(block, "methodsTried")
    exp_inner = block[exp_fv[0]:exp_fv[1]]
    methods_inner = block[methods_fv[0]:methods_fv[1]]
    assert '"id": "E3"' in exp_inner
    assert '"id": "E3"' not in methods_inner
    # And the methodsTried row is still intact.
    assert "m1" in methods_inner


def test_round_trip_update_status_with_brace_string_earlier(tmp_path, monkeypatch):
    """Bug 2 regression: updating status when an earlier field value
    contains literal '{}' chars must rewrite the existing key in place,
    not duplicate it."""
    update = _load("update")
    p = tmp_path / "research_html" / "data" / "research-packages.js"
    p.parent.mkdir(parents=True)
    p.write_text(_INVENTORY)
    monkeypatch.chdir(tmp_path)
    update._update_inventory_field("harness-test", "status", "READY_TO_LAUNCH")
    new_text = p.read_text()
    bounds = _pkg_block.find_package_block(new_text, "harness-test")
    block = new_text[slice(*bounds)]
    # Count of top-level `status:` keys must remain exactly one.
    fv = _pkg_block.find_top_level_field_value(block, "status")
    assert fv is not None
    assert block[fv[0]:fv[1]] == '"READY_TO_LAUNCH"'
    # Sanity: no duplicate key inserted earlier in the block.
    assert block.count("status:") == 1 + 2  # outer + 2 inside experiments[]


def test_round_trip_update_experiments_row_replaces_inline_item(tmp_path, monkeypatch):
    """Updating an experiments[] row must work on inline arrays with nested fields,
    the shape produced by package materialization and later package edits."""
    update = _load("update")
    p = tmp_path / "research_html" / "data" / "research-packages.js"
    p.parent.mkdir(parents=True)
    p.write_text(
        """const RESEARCH_PACKAGES = [
  {
    id: "harness-test",
    category: "in-progress",
    status: "CONTEXT_LOADED",
    experiments: [{"id": "P0", "purpose": "old", "docs": [{"label": "keep", "href": "x"}]}, {"id": "P1", "purpose": "next"}],
    methodsTried: [{"method": "m1", "evidencePath": "p1"}],
  },
];"""
    )
    monkeypatch.chdir(tmp_path)
    update.update_experiments_row(
        "harness-test",
        {
            "id": "P0",
            "row": {
                "id": "P0",
                "purpose": "new",
                "after": [],
                "status": "QUEUED",
                "docs": [{"label": "updated", "href": "docs/x.html"}],
            },
        },
    )
    new_text = p.read_text()
    bounds = _pkg_block.find_package_block(new_text, "harness-test")
    block = new_text[slice(*bounds)]
    exp_fv = _pkg_block.find_top_level_field_value(block, "experiments")
    arr = block[exp_fv[0]:exp_fv[1]]
    p0 = _pkg_block.find_array_item_by_id(arr, "P0")
    p1 = _pkg_block.find_array_item_by_id(arr, "P1")
    assert p0 is not None
    assert p1 is not None
    assert '"purpose": "new"' in arr[p0[0]:p0[1]]
    assert '"label": "updated"' in arr[p0[0]:p0[1]]
    assert '"purpose": "old"' not in arr
    assert '"purpose": "next"' in arr[p1[0]:p1[1]]
    assert "methodsTried" in block


def test_round_trip_update_objective_contract_field(tmp_path, monkeypatch):
    update = _load("update")
    p = tmp_path / "research_html" / "data" / "research-packages.js"
    p.parent.mkdir(parents=True)
    p.write_text(
        """const RESEARCH_PACKAGES = [
  {
    id: "harness-test",
    category: "in-progress",
    status: "CONTEXT_LOADED",
    objectiveContract: { baseline: "old", metric: "keep" },
  },
];"""
    )
    monkeypatch.chdir(tmp_path)
    update.update_objective_contract("harness-test", {"field": "baseline", "to": "new"})
    new_text = p.read_text()
    bounds = _pkg_block.find_package_block(new_text, "harness-test")
    block = new_text[slice(*bounds)]
    obj_fv = _pkg_block.find_top_level_field_value(block, "objectiveContract")
    obj = block[obj_fv[0]:obj_fv[1]]
    baseline = _pkg_block.find_top_level_field_value(obj, "baseline")
    metric = _pkg_block.find_top_level_field_value(obj, "metric")
    assert obj[baseline[0]:baseline[1]] == '"new"'
    assert obj[metric[0]:metric[1]] == '"keep"'


def test_round_trip_update_result_gate_row_cells(tmp_path, monkeypatch):
    update = _load("update")
    path = tmp_path / "research_html" / "packages" / "harness-test" / "results.html"
    path.parent.mkdir(parents=True)
    path.write_text(
        """<html><body>
<table><tbody data-table-body="result-gate">
<tr data-exp-id="P0" id="gate-p0">
  <td data-field="exp-id">P0</td>
  <td data-validity="missing">missing</td>
  <td data-field="baseline">old baseline</td>
  <td data-field="plan-gate">old gate</td>
  <td data-field="artifact-completeness">old artifact</td>
</tr>
</tbody></table>
<time data-field="last-updated">2026-06-01</time>
</body></html>"""
    )
    monkeypatch.chdir(tmp_path)
    update.update_results_gate_row(
        "harness-test",
        {
            "exp_id": "P0",
            "cells": {
                "validity": "missing",
                "baseline": "new baseline",
                "plan-gate": "new gate",
                "artifact-completeness": "new artifact",
            },
        },
    )
    text = path.read_text()
    assert 'data-validity="missing">missing' in text
    assert "new baseline" in text
    assert "new gate" in text
    assert "new artifact" in text
    assert "old baseline" not in text
    assert "2026-06-01" not in text
