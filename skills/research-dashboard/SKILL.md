---
name: research-dashboard
description: "Set up, repair, or validate the global research_html/ HTML dashboard scaffold for any research project. Use this skill whenever the user types /research-dashboard, asks to create or initialize a research dashboard, repair a broken research_html/ scaffold, install the four lane pages (brainstorm / in-progress / success / fail) before creating research packages, bring a project under the binding HTML rules R1-R17 and Trustworthy Research rules T1-T24, or set up the global research-system protocol for autonomous research agents. Project-agnostic: works in any repository the user opens. The dashboard chrome is overview-only — claims, evidence, and stage transitions live on package pages, not on the dashboard."
argument-hint: "[<root path, defaults to ./research_html>]"
allowed-tools: Bash(*), Read, Edit, Write, Glob, Grep
---

# Research Dashboard

## Purpose

Create or repair the shared `research_html/` dashboard at the working-directory root before any package work begins. The dashboard is the global research-system contract: package lanes, universal rules, optional project profile, tag-role mapping, and package inventory. It is overview-only — claims and evidence live on package surfaces.

This skill is project-agnostic. The dashboard contract is identical for every project; project specifics belong in `data/research-packages.js` (`window.RESEARCH_PROJECT_PROFILE` plus the package inventory).

## Authority

Authority order, highest first:
1. The user's invocation arguments (e.g. `/research-dashboard ./my_research_html`).
2. Form rules `R1–R17` in `<root>/rules/html-rules.html`.
3. Trustworthy Research rules `T1–T24` in `<root>/rules/trustworthy-research-rules.html`.
4. The contract documented in `references/dashboard-contract.md` (this skill).

This skill installs the rule files into `<root>/rules/` so any project gets them. Do not modify the rule files inside the user's project; if they need to change, update the skill's `assets/` instead.

## Output classification

Every text output this skill emits — intermediate progress lines, the final report, and HTML page content — classifies content by audience:

- **Both audiences** (default): facts, decisions, status, paths, and the concrete fields a human reader needs. Render inline.
- **Human-important only**: prose addressed to the user (questions, recommendations, summaries). Render inline.
- **Agent-important only**: continuity context, internal reasoning, file-map notes, "remember for next turn" pointers that the next agent benefits from but the user does not need on first read. Render collapsed by default:
  - **Chat output** (Claude Code UI): wrap the block in a markdown `>` blockquote; the UI collapses it by default.
  - **HTML pages** (dashboard chrome and lane pages): wrap the block in `<details data-audience="agent"><summary>agent context</summary>…</details>`; the `<details>` element renders closed by default so the human reader sees only the summary.

Both-audience content is written once, inline, without the blockquote or `<details>` wrapper. Do not use the blockquote form for emphasis or aesthetics — it carries audience meaning under this rule. The `data-audience="agent"` attribute and the `^> ` line prefix are stable anchors agents can grep for to recover their private notes.

## Workflow

1. **Resolve the dashboard root.** Default to `<cwd>/research_html`. If the user passes a path argument, honor it. Use absolute paths internally; do not assume the cwd matches the user's intent without confirming when ambiguous.

2. **Detect existing dashboard.** Check whether the root already exists. If it does, treat user edits as authoritative — do not overwrite without `--force`. Required files are listed in [references/dashboard-contract.md](references/dashboard-contract.md).

3. **Run the bundled script.** The scaffold script lives at `~/.claude/skills/research-dashboard/scripts/ensure_dashboard.py`. It writes a minimal compliant scaffold (idempotent: existing files are preserved) plus copies the binding rule files from this skill's `assets/` into `<root>/rules/`. Invoke it as:

   ```bash
   python ~/.claude/skills/research-dashboard/scripts/ensure_dashboard.py --root <root>
   ```

   Pass `--force` only when the user explicitly asks to overwrite.

4. **Validate.** After scaffolding, run:

   ```bash
   node --check <root>/assets/research.js
   node --check <root>/data/research-packages.js
   ```

   Then grep for the eight required `data-section` anchors and the two rule-file links in `<root>/index.html`:

   ```bash
   grep -E 'data-section="(snapshot|lanes|packages|protocol|profile|rules)"' <root>/index.html
   grep -E 'rules/html-rules.html|rules/trustworthy-research-rules.html' <root>/index.html
   ```

5. **Keep the dashboard project-agnostic.** Project objective, success rule, and cautions belong in `window.RESEARCH_PROJECT_PROFILE` inside `<root>/data/research-packages.js`. Do not edit the universal protocol cards in the same file; those are shared chrome.

6. **Report back.** State the resolved root, files written (or "preserved, no changes"), and the next suggested step (typically `/research-package` to create the first package). Apply the [Output classification](#output-classification) rule on the report itself.

## Scope (what this skill does NOT do)

- Does not create research packages — use `/research-package` for that.
- Does not edit per-package content — package surfaces own claims and evidence.
- Does not change the universal protocol or rule files in user projects — the rule files are bundled with this skill and copied as-is.

## State model and learnings tooling

The dashboard ships a `(category, status)` state machine. Every package carries a `status` field whose legal values depend on its lane:

| category | legal `status` values |
|---|---|
| brainstorm | `EXPLORING`, `PILOT_READY`, `PROMOTED`, `ABANDONED` |
| in-progress | `CONTEXT_LOADED`, `IMPLEMENTING`, `IMPLEMENTATION_REVIEW`, `READY_TO_LAUNCH`, `EXPERIMENT_RUNNING`, `LIVE_ANALYSIS`, `RESULT_ANALYSIS`, `NEXT_ACTION_READY`, `BLOCKED` |
| success | `ADOPTED_PENDING_ACK`, `ADOPTED`, `SUPERSEDED` |
| fail | `ARCHIVED`, `ARCHIVED_REOPENABLE` |

Required field sets per `(category, status)` and the structured `methodsTried` row shape are declared in `<root>/data/schema.js` — that file is the single source of truth and is bundled by this skill. The card renderer and the lint tool both import from it.

Terminal-state packages (success / fail / brainstorm-`ABANDONED`) must carry a `terminationMessage` and a `methodsTried[]` array of structured rows (`{method, hypothesis, gate, measured, verdict, evidencePath}`, verdict in `{pass, fail, inconclusive}`). The learnings page (`<root>/learnings.html`, also bundled) is a derived view over `data/research-packages.js` that re-organizes those rows by contribution spine.

The dashboard-wide consistency tool is `<root>/scripts/learnings_lint.py` (Python; reads the JS data files via the bundled `dump_packages.js` node helper):

```bash
python <root>/scripts/learnings_lint.py lint-status     # schema + cross-ref lint
python <root>/scripts/learnings_lint.py lint-evidence   # evidencePath resolution
python <root>/scripts/learnings_lint.py scan-events     # 3 draft writers (E1/E3/E4)
python <root>/scripts/learnings_lint.py all             # all three at once
```

The Stop Gate of any learnings-relevant turn requires `learnings_lint.py all` to exit 0.

## Event-manifest applier (auto-propagation)

`<root>/scripts/propagate_apply.py` is the dashboard-wide executor for inventory events. Read event manifests from `var/research/<pkg-id>/manifests/*.json`, apply the deterministic surface edits to `data/research-packages.js`, the package's `results.html`, and the package's `tracker.html`, then mark each manifest `.applied`. Dry-run by default; `--write` commits.

Supported events (filenames are conventional, not enforced — the `event` key inside the JSON drives dispatch):

| Event key | Payload (required + optional) | Surfaces written |
| --- | --- | --- |
| `verdict_finalized` | `exp_id, row_anchor, measured, verdict, evidencePath, gate, hypothesis, lastActionPhrase` | registry `methodsTried[]` append + `experiments[i].status=completed` + results-row cells + tracker Last action |
| `status_changed` | `status, [category, lastActionPhrase]` | registry `status` (+ optional `category` lane move) |
| `adoption` | `adoptionPath, [lastActionPhrase]` | registry `status=ADOPTED, category=success, adoptionPath` |
| `supersession` | `supersededBy, [lastActionPhrase]` | registry `status=SUPERSEDED, supersededBy` |
| `reopen` | `reopenTrigger, [lastActionPhrase]` | registry `status=ARCHIVED_REOPENABLE, reopenTrigger` |
| `state_derived` | any of `currentBlocker, nextRoute, activeGate, primaryMetricVsGate` | registry top-level fields (subset that's provided) |

```bash
python <root>/scripts/propagate_apply.py --auto-derive --write
```

`--auto-derive` is the passive change detector. Before/after applying pending manifests, it scans every package's `experiments[].status` and writes a `_auto_state_<sha>.json` draft into that package's `manifests/` dir if the derived `currentBlocker` / `nextRoute` differs from the registry. **Conservative policy**: only overrides a field when it is currently **blank** in the registry. Non-blank values are treated as human-curated and stay untouched — overwrite them with an explicit `state_derived` manifest if you need to.

Derivation rules (computed from `experiments[].status` + `category`):

| Package state | Derived `currentBlocker` | Derived `nextRoute` |
| --- | --- | --- |
| `category in {success, fail}` | `""` | `archive_or_stop` |
| any experiment `failed` | `experiments[] failed: <ids>` | `archive_or_stop` |
| any experiment `blocked` | `experiments[] blocked: <ids>` | `run_next_experiment_from_step4` |
| any experiment `running` | `""` | `run_next_experiment_from_step4` |
| all experiments terminal | `""` | `archive_or_stop` |
| any experiment `pending` / `queued` | `""` | `run_next_experiment_from_step4` |

Each manifest is idempotent: a sibling `.applied` sidecar (`<manifest>.applied`) is touched on successful `--write`, and discovery skips manifests with that sidecar. Re-running `--auto-derive --write` after the registry catches up produces zero diff and zero new drafts.

A companion helper `<root>/scripts/emit_verdict_manifest.py` parses a trainer chain log (`Candidate-expanded retrieval: {...}` dict line) and writes a `verdict_finalized` JSON shaped for `propagate_apply.py`. Call it from a launcher's chain-done block.

For zero-prompt auto-apply at every Stop, wire the Claude Code Stop hook documented in [`references/stop-fact-propagation-hook.md`](references/stop-fact-propagation-hook.md).

## Bundled resources

- `scripts/ensure_dashboard.py` — idempotent scaffold for the dashboard chrome plus rule-file copy.
- `references/dashboard-contract.md` — required dashboard sections, anchors, and rule citations.
- `references/stop-fact-propagation-hook.md` — Claude Code `Stop` hook recipe that wires `propagate_apply.py --auto-derive --write` + `learnings_lint.py all` at every turn end.
- `assets/html-rules.html`, `assets/trustworthy-research-rules.html` — the binding rule files copied into every project's `<root>/rules/` so package surfaces can link them with no further setup.
- `assets/dashboard/data/schema.js` — the `(category, status)` state machine and required-field rules; copied to `<root>/data/schema.js`.
- `assets/dashboard/learnings.html` — cross-package learnings view (derived; do not edit directly).
- `assets/dashboard/scripts/learnings_lint.py` + `dump_packages.js` — the dashboard-wide lint and draft tool.
- `assets/dashboard/scripts/propagate_apply.py` — event-manifest executor (`verdict_finalized`, `status_changed`, `adoption`, `supersession`, `reopen`, `state_derived`) with `--auto-derive` drift scanner.
- `assets/dashboard/scripts/emit_verdict_manifest.py` — launcher-side helper that parses a trainer log into a `verdict_finalized` manifest.
