# Pattern B — write-time validate rules

Every Insert / Update / Delete in `research-op` runs the rules below before any
byte hits disk. Rule ids are the values that appear in the rejection envelope's
`rule` field.

## Per-target rules

### Insert: methodsTried row (I2)
- `methodstried-six-fields`: payload must have exactly `{method, hypothesis, gate, measured, verdict, evidencePath}`. Extra or missing keys reject.
- `methodstried-verdict-enum`: `verdict ∈ {PASS, FAIL, INCONCLUSIVE}`.
- `methodstried-evidence-resolves`: `evidencePath` is either a real file under `outputs/<pkg>/` or `output/`, or an HTML anchor `results.html#<exp-anchor>` that exists on disk.
<!-- planned, not yet implemented: methodstried-source-row-exists — the upstream results.html row at evidencePath exists with a verdict already finalized -->

### Insert: results.html result-gate row (I6)
- `result-gate-ten-cols`: all 10 columns from `workflow.ts` required schema are present.
- `result-gate-validity-enum`: `Validity ∈ {VALID, PARTIAL, RESULT_FAIL, UNMEASURED}`.
- `result-gate-pass-triple-check` *(planned, not yet implemented)* (only if `verdict=pass`): the P5 triple-check passes — hypothesis string-eq frozen contract; metric/dataset/protocol/dedup/cutoff string-eq frozen contract; evidence file's manifest names the canonical eval split.

### Insert: results.html result block (I7)
- `result-block-six-parts`: HTML must contain the 6 anchors — `data-block="title"`, `data-block="summary"` (text ≤ 25 words), `data-block="detail"` (in `<details>` closed), `data-block="main-table"`, `data-block="insight"`, `data-block="ablation"` (or explicit `<!-- no ablation -->` comment).
- `result-block-details-closed`: every `<details>` in the block lacks `open` attr (R-no-details-open).

### Update: results.html verdict cell (U10)
- `verdict-mechanical`: the verdict string MUST equal `predicate(measured)` where `predicate` is the frozen success.predicate from plan.html. Refuse if they differ. The actual measured value is read from `evidencePath`.

### Update: experiments[] row (U4a)
- `experiments-update-payload`: payload must include a non-empty `id` and a full replacement `row` object.
- `experiments-update-id-match`: the replacement row's `id` must equal the row being replaced.

### Update: objectiveContract field (U3)
- `objective-contract-update-payload`: payload must be either `{field, to}` for one field or `{to: {...}}` for whole-object replacement.
- `objective-contract-field-known`: field-level updates are limited to the canonical objective contract fields.

### Update: results.html result-gate row cells (U10a)
- `results-gate-update-payload`: payload must include `exp_id` and a non-empty `cells` object.
- `results-gate-update-fields-known`: cell names must match the known result-gate data-field names.

### Update: status — lane-crossing (U1)
- `lane-t1-ack-present`: the payload must include a non-empty `ack_token` field for any lane-crossing status update (the T1 acknowledgement value).
- `lane-required-fields`: every required field for the destination cell (per `schema.js`) must be present in the inventory entry.
- `lane-edge-legal`: the `(old-category, old-status) -> (new-category, new-status)` edge is a legal cell in the 18-cell state machine (the `STATES` table in `scripts/transitions.py`, documented in [matrix.md](matrix.md) §4.5); terminal-frozen cells (`(success, ADOPTED)`, `(fail, ARCHIVED)`) are never a legal destination.

### Update: status — acquit into the success lane (U1, success-bound)
These fire in addition to the lane-crossing rules above whenever the destination category is `success`.
- `acquit-needs-verdict`: the payload must carry a non-empty `verdict` record (judge, verdict, evidence) for any acquit into the success lane.
- `acquit-judge-independent`: the verdict's judge must satisfy the independence constraint for the task's `autonomy_level` (default `"SUPERVISED"`); at `"AUTONOMOUS"` the judge must be cross-family from the producer. Implemented via `lib/verifier.assess_acquit(verdict, level)` — acquit only on a `SOUND` verdict.

### Insert: doc-file (I9) + paired doc-card
- `doc-file-path-under-package`: file path matches `research_html/packages/<pkg>/docs/<slug>.html`.
- `doc-card-six-parts`: paired card has the 6-part shape (title, tldr, tags, preview, link, last-updated) and 5 `data-doc-*` attrs from the companion HTML-design spec.
- `doc-group-rationale-present`: parent section in `docs/index.html` carries `data-doc-group-rationale`.

### Insert: tracker-live-check-row (I3)
- `live-check-twelve-cols`: all 12 columns from `workflow.ts` required schema are present.
- `live-check-time-local`: `Time` field is local wall-clock (no `Z`, no `+00:00` offset).

### Delete: methodsTried row (D4)
- `methodstried-terminal-frozen`: refuse if `(category, status)` is in `(success/*, fail/*)`.

### Delete: experiments-row (D1)
- `experiments-pre-launch-only`: refuse if any `experiments[].status` for the package is one of `RUNNING`, `COMPLETED`, `RUN_FAILED`.

### rule target (I12 / U14 / D9) — unified rules registry
- `rule-universal-writelock`: any write with `level=universal` is refused — the R/T corpus is a
  read-only mirror of the shipped rule files (every op, both paths).
- `rule-level-routable`: the package path (`--pkg <pkg>`) only mutates `level=package` rows; the
  `_project` path only mutates `level=project` rows. Cross-path attempts are refused with a pointer.
- `rule-kind-mismatch`: rule kind must match the level (`universal=form|trust`,
  `project=constraint`, `package=binding|lesson`).
- `rule-store-malformed`: `data/rules.js` must parse as
  `window.RESEARCH_RULES = <valid JSON array>;` before any rule mutation writes it back.
- `rule-project-needs-ack` (`_project` path): landing/changing a project rule requires a non-empty
  `payload.ack` — the distinct human action (research-apply passes its human token through).
- `rule-required-fields`: insert needs `kind ∈ {binding, lesson}` (package) and the full typed row
  (`slug` kebab-case, `title`, `text`, `rationale`, `addedAt`); update/delete need `payload.id`.
- `rule-origin-reserved`: manual inserts may not set `origin=mirror` or `origin=selfevolve`;
  those rows are regenerated by the universal-rule mirror or self-evolve exporter.
- `rule-text-plain`: `payload.text` must be plain natural-language prose with no HTML tags;
  renderers escape text when painting it into HTML.
- `rule-lesson-needs-result`: `kind=lesson` insert requires ≥ 1 finalized verdict in results.html.
- `rule-lifecycle-fields`: `status=RETIRED` needs `retireReason`; `status=PROMOTED` needs `promotedTo`.
- `rule-origin-immutable`: rows with `origin ∈ {mirror, selfevolve}` are export-owned; hand edits refused.
- `rule-no-hard-delete` (`_project` path): project rules never hard-delete — retire via update.
- `rule-op-supported` (`_project` path): the synthetic project-level rule path only supports
  `check`, `insert`, `update`, and `delete`.
- `retired-target` (universal pre-check): `package-invariant` / `analysis-rule` reject with the
  `--target rule` pointer.

## Universal rules (every op)

- `payload-json-valid`: `--payload` parses as JSON (this fires before the per-target rules above).
- `target-known`: `--target` is a value in `transitions.TARGETS` (this fires before the legality lookup).
- `retired-target`: a target in `transitions.RETIRED_TARGETS` is refused with its replacement pointer.
