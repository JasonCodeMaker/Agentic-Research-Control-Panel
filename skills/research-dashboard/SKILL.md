---
name: research-dashboard
description: "Set up, repair, or validate the global research_html/ HTML dashboard scaffold for any research project. Use this skill whenever the user types /research-dashboard, asks to create or initialize a research dashboard, repair a broken research_html/ scaffold, install the four lane pages (brainstorm / in-progress / success / fail) before creating research packages, bring a project under the binding HTML rules R1-R18 and Trustworthy Research rules T1-T24, or set up the global research-system protocol for autonomous research agents. Project-agnostic: works in any repository the user opens. The dashboard chrome is overview-only — claims, evidence, and stage transitions live on package pages, not on the dashboard."
argument-hint: "[<root path, defaults to ./research_html>]"
allowed-tools: Bash(*), Read, Edit, Write, Glob, Grep
---

# Research Dashboard

## Purpose

Create or repair the shared `research_html/` dashboard at the working-directory root before any package work begins. The dashboard is the global research-system contract: package lanes, universal rules, optional project profile, Scope SSOT projection, tag-role mapping, and package inventory. It is overview-only — claims and evidence live on package surfaces.

This skill is project-agnostic. The dashboard contract is identical for every project; project specifics belong in `data/research-packages.js` (`window.RESEARCH_PROJECT_PROFILE` plus the package inventory) and the read-only `data/scope-projection.json/js` projection generated from `outputs/_scope/transitions.jsonl`.

## Authority

Authority order, highest first:
1. The user's invocation arguments (e.g. `/research-dashboard ./my_research_html`).
2. Form rules `R1–R18` in `<root>/rules/html-rules.html`.
3. Trustworthy Research rules `T1–T24` in `<root>/rules/trustworthy-research-rules.html`.
4. The contract documented in `references/dashboard-contract.md` (this skill).

This skill installs the rule files into `<root>/rules/` so any project gets them. Do not modify the rule files inside the user's project; if they need to change, update the skill's `assets/` instead.

The scaffold also creates `<root>/data/rules.js` — the **unified rules registry** (one typed row per rule, levels `universal | project | package`). Universal rows are a write-locked mirror of the two rule files above, rebuilt by `ensure_dashboard.py` on every run; project/package rows are mutated only through `research-op --target rule`. The dashboard renders protocol content from its owners (Scope SSOT objective, `schema.js` routes, the rules registry) — it owns none.

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

2. **Detect existing dashboard.** Check whether the root already exists. If it does, treat user edits as authoritative — do not overwrite without `--force`. Required files are listed in [references/dashboard-contract.md](references/dashboard-contract.md). On the **repair** path (root exists but is broken or partial), still run the idempotent script in step 3 — it only writes files that are missing — then read that required-file list and report any file still absent after the run.

3. **Run the bundled script.** The scaffold script lives in the installed `research-dashboard` skill
   directory. It writes a minimal compliant scaffold (idempotent: existing files are preserved) plus
   copies the binding rule files from this skill's `assets/` into `<root>/rules/`. Invoke it as:

   ```bash
   DASHBOARD_SKILL=""
   for dir in "$HOME/.codex/skills/research-dashboard" "$HOME/.claude/skills/research-dashboard"; do
     if [ -f "$dir/scripts/ensure_dashboard.py" ]; then DASHBOARD_SKILL="$dir"; break; fi
   done
   test -n "$DASHBOARD_SKILL"
   python "$DASHBOARD_SKILL/scripts/ensure_dashboard.py" --root <root>
   ```

   Pass `--force` only when the user explicitly asks to overwrite.

4. **Validate.** After scaffolding, run:

   ```bash
   node --check <root>/assets/research.js
   node --check <root>/data/research-packages.js
   ```

   Then grep for the six required content `data-section` anchors (the index also carries `masthead` and `nav` chrome anchors, which the check ignores), the section-level Rule Registry heading/slot, and the two rule-file links rendered by `<root>/assets/research.js`:

   ```bash
   grep -E 'data-section="(snapshot|lanes|packages|protocol|profile|rules)"' <root>/index.html
   grep -E '<h2>Rule Registry</h2>|id="rules-registry-root"' <root>/index.html
   grep -E 'rules/html-rules.html|rules/trustworthy-research-rules.html' <root>/assets/research.js
   ```

   For the autonomous live-run view, verify the server script is valid, then
   **deploy the dashboard server** so the user can open it immediately:

   ```bash
   python -m py_compile <root>/scripts/serve_dashboard.py
   python <root>/scripts/serve_dashboard.py ensure \
     --host 127.0.0.1 --port 8904 --max-port 8904 --json
   ```

   `ensure` is idempotent: it reuses an already-healthy server and otherwise starts
   a fresh background instance, so re-running it — here at init, at every Stop (see
   [`references/stop-fact-propagation-hook.md`](references/stop-fact-propagation-hook.md)),
   or before a tracked `research-exp-live` launch — doubles as an **auto-restart**.
   Surface the printed `url`/`live_url`; over SSH the user reaches it via VSCode
   Remote-SSH port forwarding or `ssh -L 8904:127.0.0.1:8904`. If `ensure` cannot
   bind, report it — the scaffold itself still succeeded.

   If the project has a committed Scope SSOT transition log, render and check the dashboard projection:

   ```bash
   python <root>/scripts/render_scope_projection.py render --transitions outputs/_scope/transitions.jsonl --projection <root>/data/scope-projection.json
   python <root>/scripts/render_scope_projection.py check --transitions outputs/_scope/transitions.jsonl --projection <root>/data/scope-projection.json
   ```

   If `ensure_dashboard.py` raised, confirm the skill is installed under `~/.codex/skills/` or
   `~/.claude/skills/`. If `node --check` exits non-zero, the copied JS is malformed — inspect the
   matching file in this skill's `assets/dashboard/`. If the anchor grep returns nothing, `index.html`
   was not written — re-run step 3 with `--force`.

5. **Keep the dashboard project-agnostic.** Project profile prose belongs in `window.RESEARCH_PROJECT_PROFILE` inside `<root>/data/research-packages.js`; project-level *constraints* are registry rows (`data/rules.js`, `level=project`), landed via `research-op --target rule`. Project / Direction / Milestone intent belongs in the Scope SSOT and is rendered into `<root>/data/scope-projection.json/js`; do not hand-edit those projection files or the registry's `origin=mirror|selfevolve` rows.

6. **Check for a committed objective, then recommend the next step.** The dashboard is chrome; a project still needs a ratified objective in the Scope SSOT before any package work. Check whether a Project node is already committed:

   ```bash
   ONBOARD_SKILL=""
   for dir in "$HOME/.codex/skills/research-onboard" "$HOME/.claude/skills/research-onboard"; do
     if [ -f "$dir/scripts/onboard.py" ]; then ONBOARD_SKILL="$dir"; break; fi
   done
   test -n "$ONBOARD_SKILL"
   python "$ONBOARD_SKILL/scripts/onboard.py" has-project-scope --transitions outputs/_scope/transitions.jsonl
   ```

   - If it prints `{"has_project_scope": false}` (the common first-run case), the next step is **`/research-onboard`**, not `/research-package` — onboarding bridges the raw workspace into a pending Project proposal (it scaffolds an empty workspace or analyzes an existing one). Recommend it, and continue into it in the same session unless the user redirects.
   - If it prints `true`, the objective exists; the next step is `/research-scope` (add a Direction) or `/research-package`.

7. **Report back.** State the resolved root, files written (or "preserved, no changes"), and the next suggested step chosen in step 6. Apply the [Output classification](#output-classification) rule on the report itself.

## Scope (what this skill does NOT do)

- Does not create research packages — use `/research-package` for that.
- Does not edit per-package content — package surfaces own claims and evidence.
- Does not change the universal protocol or rule files in user projects — the rule files are bundled with this skill and copied as-is.

## State model and learnings tooling

The dashboard ships a `(category, status)` state machine. Every package carries a `status` field whose legal values depend on its lane (brainstorm is **not** a package category — the brainstorm lane holds pre-package ideas from `data/brainstorms.js`):

| category | legal `status` values |
|---|---|
| in-progress | `CONTEXT_LOADED`, `IMPLEMENTING`, `IMPLEMENTATION_REVIEW`, `READY_TO_LAUNCH`, `EXPERIMENT_RUNNING`, `LIVE_ANALYSIS`, `RESULT_ANALYSIS`, `NEXT_ACTION_READY`, `BLOCKED` |
| success | `ADOPTED_UNCONFIRMED`, `ADOPTED`, `WIN_SUPERSEDED` |
| fail | `ARCHIVED`, `ARCHIVED_CONDITIONAL` |

Required field sets per `(category, status)` and the structured `methodsTried` row shape are declared in `<root>/data/schema.js` — that file is the single source of truth and is bundled by this skill. The card renderer and the lint tool both import from it.

Terminal-state `success` packages must carry a `terminationMessage`, a `methodsTried[]` array of structured rows (`{method, hypothesis, gate, measured, verdict, evidencePath}`, verdict in `{PASS, FAIL, INCONCLUSIVE, DIAGNOSTIC}`), and an `adoptionPath`; `fail` packages require the `terminationMessage` and `methodsTried[]`. The learnings page (`<root>/learnings.html`, also bundled) is a derived view over `data/research-packages.js` that re-organizes those rows by contribution spine.
It also renders the action-facing decision strip for each package: reuse, do-not-repeat, reopen condition,
promoted package rule, and Scope impact. It reads `data/rules.js` and `data/scope-projection.js` as
read-only context and owns none of those stores.

Before brainstorm conversion, Scope proposal, package materialization, or package execution, agents run:

```bash
python <root>/scripts/learning_context_gate.py --root <root> --json
```

This is the project-level read gate. It counts active rules, failed methods, unresolved methods, adopted
wins, and open gaps. It fails closed on malformed rule/package/gap sources; zero counts are allowed only
after the stores were loaded successfully.

The Context Pack is agent-facing only: `lib/context_pack/build.py` writes
`outputs/<pkg>/context_pack.md` and `outputs/<pkg>/context_pack.json` at
context-load. The pack freshness stamp includes package inventory, rules, knowledge registries,
fact-backed `methods_tried.csv` files, and the self-evolve rule transition log, so package learning
changes rebuild context even when Scope does not move. The retired global `context.html` / `data/context-core.js`
dashboard surface must not be reintroduced as a second project-memory interface;
inspect the package-local Context Pack artifact when agent working context needs
auditing.

The dashboard-wide consistency tool is `<root>/scripts/learnings_lint.py` (Python; reads the JS data files via the bundled `dump_packages.js` node helper):

```bash
python <root>/scripts/learnings_lint.py lint-status     # schema + cross-ref lint
python <root>/scripts/learnings_lint.py lint-evidence   # evidencePath resolution
python <root>/scripts/learnings_lint.py lint-rules      # rules-registry schema + mirror sync
python <root>/scripts/learnings_lint.py scan-events     # 3 draft writers (VERDICT_FINALIZED/TERMINAL_TRANSITION/ADOPTION)
python <root>/scripts/learnings_lint.py alignment       # task-spine structural lint
python <root>/scripts/learnings_lint.py all             # status + evidence + scan + alignment + rules
```

The Stop Gate of any learnings-relevant turn requires `learnings_lint.py all` to exit 0. For Scope-materialized packages, `lint-status` also checks that `sourceDirection`, `sourceTasks`, and `experiments[].sourceTask` still point to active Scope SSOT nodes; `alignment` checks each typed task's result/implementation/docs/tracker thread.

## Event-manifest applier (auto-propagation)

`<root>/scripts/propagate_apply.py` is the dashboard-wide executor for inventory events. Read event manifests from `outputs/<pkg-id>/manifests/*.json`, apply the deterministic surface edits to `data/research-packages.js`, the package's `results.html`, and the package's `tracker.html`, then mark each manifest `.applied`. Dry-run by default; `--write` commits.

Supported events (filenames are conventional, not enforced — the `event` key inside the JSON drives dispatch):

| Event key | Payload (required + optional) | Surfaces written |
| --- | --- | --- |
| `VERDICT_FINALIZED` | `exp_id, row_anchor, measured, verdict, [evidencePath, gate, hypothesis, lastActionPhrase]` | registry `methodsTried[]` append + `experiments[i].status=COMPLETED` + results-row cells + tracker Last action |
| `STATUS_CHANGED` | `status, [category, lastActionPhrase]` | registry `status` (+ optional `category` lane move) |
| `ADOPTION` | `adoptionPath, [lastActionPhrase]` | registry `status=ADOPTED, category=success, adoptionPath` |
| `SUPERSESSION` | `supersededBy, [lastActionPhrase]` | registry `status=WIN_SUPERSEDED, supersededBy` |
| `REOPEN` | `reopenTrigger, [lastActionPhrase]` | registry `status=ARCHIVED_CONDITIONAL, reopenTrigger` |
| `state_derived` | any of `currentBlocker, nextRoute, activeGate, primaryMetricVsGate` | registry top-level fields (subset that's provided) |

```bash
python <root>/scripts/propagate_apply.py --auto-derive --write
```

`--auto-derive` is the passive change detector. Before/after applying pending manifests, it scans every package's `experiments[].status` and writes a `_auto_state_<sha>.json` draft into that package's `manifests/` dir if the derived `currentBlocker` / `nextRoute` differs from the registry. **Conservative policy**: only overrides a field when it is currently **blank** in the registry. Non-blank values are treated as human-curated and stay untouched — overwrite them with an explicit `state_derived` manifest if you need to.

Derivation rules (computed from `experiments[].status` + `category`):

| Package state | Derived `currentBlocker` | Derived `nextRoute` |
| --- | --- | --- |
| `category in {success, fail}` | `""` | `TERMINATE` |
| any experiment `RUN_FAILED` | `experiments[] failed: <ids>` | `TERMINATE` |
| any experiment `RUN_HALTED` | `experiments[] blocked: <ids>` | `RUN_NEXT_EXPERIMENT` |
| any experiment `RUNNING` | `""` | `RUN_NEXT_EXPERIMENT` |
| all experiments terminal | `""` | `TERMINATE` |
| any experiment `QUEUED` | `""` | `RUN_NEXT_EXPERIMENT` |

Each manifest is idempotent: a sibling `.applied` sidecar (`<manifest>.applied`) is touched on successful `--write`, and discovery skips manifests with that sidecar. Re-running `--auto-derive --write` after the registry catches up produces zero diff and zero new drafts.

A companion helper `<root>/scripts/emit_verdict_manifest.py` parses a trainer chain log (`Candidate-expanded retrieval: {...}` dict line) and writes a `verdict_finalized` JSON shaped for `propagate_apply.py`. Call it from a launcher's chain-done block.

For zero-prompt auto-apply at every Stop, wire the Claude Code Stop hook documented in [`references/stop-fact-propagation-hook.md`](references/stop-fact-propagation-hook.md). That hook also renders/checks `scope-projection.json/js` when `outputs/_scope/` changes.

## Viewing the dashboard (served, not file-watched)

The dashboard is meant to be read through its own HTTP server, never through a live-reload preview
extension. A file-watching previewer reloads the entire page whenever the agent writes a data file;
`serve_dashboard.py` injects no reload, and every surface self-refreshes in place via `assets/live-data.js`
(a 3 s `fetch`+hash+diff poll that re-evaluates only changed `data/*.js` files and re-invokes the renderers
registered on `window.__researchRenderers`).

Start (or reuse) the server on the workstation and reach it over SSH:

    python research_html/scripts/serve_dashboard.py ensure \
      --host 127.0.0.1 --port 8904 --max-port 8904 --json

Passing equal `--port`/`--max-port` pins the port so the SSH forward is stable. The server binds localhost
on the workstation; access it from your machine via VSCode Remote-SSH automatic port forwarding, or an
explicit tunnel:

    ssh -L 8904:127.0.0.1:8904 <user>@<workstation>

Then open `http://127.0.0.1:8904/research_html/index.html`.

**Upgrading an already-scaffolded project:** `live-data.js` is a new file and is written by a normal
`ensure_dashboard.py` run. The edited chrome HTML templates are existing files, so re-scaffold them
explicitly (use the skill's refresh path; do **not** blanket `--force`, which can overwrite
`data/research-packages.js`).

## Bundled resources

- `scripts/ensure_dashboard.py` — idempotent scaffold. Mirrors this skill's entire `assets/dashboard/` tree into `<root>/` — `index.html`, `learnings.html`, `live.html`, `module.html`, `package-template.html`, the four `categories/<lane>/index.html` lane pages, `assets/research.css` + `assets/research.js` + `assets/live-data.js`, `data/schema.js`, and `scripts/*` — writes empty `data/scope-projection.json/js`, installs `scripts/render_scope_projection.py`, copies the rule files, and removes retired global reference surfaces (`context.html`, `data/context-core.js`, and `templates/module-library.html`) if an older scaffold left them behind. The agent does not manage these chrome files individually; they are installed and refreshed automatically.
- `references/dashboard-contract.md` — required dashboard sections, anchors, and rule citations.
- `references/stop-fact-propagation-hook.md` — Claude Code `Stop` hook recipe that wires `propagate_apply.py --auto-derive --write` + `learnings_lint.py all` at every turn end.
- `assets/html-rules.html`, `assets/trustworthy-research-rules.html` — the binding rule files copied into every project's `<root>/rules/` so package surfaces can link them with no further setup.
- `assets/dashboard/data/schema.js` — the `(category, status)` state machine and required-field rules; copied to `<root>/data/schema.js`.
- `assets/dashboard/learnings.html` — cross-package learnings view (derived; do not edit directly).
- `assets/dashboard/live.html` + `assets/dashboard/scripts/serve_dashboard.py` — API-first live-run view and local read-only API server. The server serves static `research_html/` and exposes `/api/live/*` by reading `outputs/_live/runs.jsonl` and `status.json`; volatile runtime writes stay out of the static page reload path.
- `assets/dashboard/scripts/learnings_lint.py` + `dump_packages.js` — the dashboard-wide lint and draft tool, including Scope/package provenance drift checks.
- `assets/dashboard/scripts/learning_context_gate.py` — project-level agent read gate over current Learnings, Rules, and open gaps.
- `scripts/render_scope_projection.py` — renders/checks `research_html/data/scope-projection.json` and the JS companion consumed by the dashboard homepage.
- `assets/dashboard/scripts/propagate_apply.py` — event-manifest executor (`verdict_finalized`, `status_changed`, `adoption`, `supersession`, `reopen`, `state_derived`) with `--auto-derive` drift scanner.
- `assets/dashboard/scripts/emit_verdict_manifest.py` — launcher-side helper that parses a trainer log into a `verdict_finalized` manifest.
