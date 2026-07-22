# Read-only interface contract

The human interface is a projection, not an authority. Its design follows one
rule: a person may use it to understand research state, but an agent must be
able to delete and rebuild it without losing a decision, fact, note, audit
record, run, or experiment output.

## Authority boundary

The default managed root is `<workspace>/.research`. A custom root may be
selected with `--research-root` or `RESEARCH_ROOT`.

| Path | Responsibility | Mutability |
| --- | --- | --- |
| `VERSION` | Managed-root schema version | Written only by initialization |
| `state/research.sqlite3` | Transactional event, current-state, receipt, and audit authority | Written only through management commands |
| `state/events.jsonl` | Compatibility event export | Appended after a database commit and rebuildable from SQLite |
| `state/current.json` | Compatibility current-state export | Rebuildable from SQLite |
| `state/notes/` | Content-addressed source notes | Written through the note store |
| `audit/actions.jsonl` | Compatibility command-audit export | Appended after a database commit and rebuildable from SQLite |
| `experiments/` | Durable run records, logs, checkpoints, metrics, and outputs | Written by experiment controllers |
| `interface/` | Rebuildable human projection | Replaced only by the interface builder |

The interface may contain copies or renderings of authoritative data. Those
copies never become valid inputs to management commands.

## Build contract

`lib.interface.build_interface()` reads the versioned store, creates a complete
staging tree, validates that the tree has no Python execution surface, and
atomically replaces `interface/`.

A successful build returns:

- the generated interface root;
- the source event sequence;
- the source event hash;
- the complete generated file list.

The build is whole-tree and deterministic for the same bundled assets,
authoritative state, notes, and supported experiment records. It must repair a
deleted or damaged projection without consulting prior interface output.

Initialization is allowed only for a genuinely empty managed root. Legacy
markers, a missing version beside existing data, or an unsupported version
produce `upgrade-required`. Automatic migration is unsupported and is never
part of `build_interface()`, `ensure_dashboard.py`, or the server startup path.

## Required global surface

The generated root keeps these human-facing pages:

- `index.html`
- `live.html`
- `scope.html`
- `learnings.html`
- `module.html`
- `categories/brainstorm/index.html`
- `categories/in-progress/index.html`
- `categories/success/index.html`
- `categories/fail/index.html`

Each state-backed Brainstorm also keeps one stable generated route:

- `brainstorm/<created-date>-<brainstorm-id>.html`

That route is a complete document-style page. The renderer combines the shared
`templates/brainstorm-document.html` shell and `assets/brainstorm.css` with the
current content-addressed `document_note` body fragment. Title, Abstract / TLDR,
Idea Snapshot, generated ToC, lifecycle metadata, and revision provenance are
shell responsibilities. Section names and research content remain free-form.
Migrated `detail_note` pages are compatibility overrides, not the authoring
model for new documents.

Each projected package keeps:

- `packages/<package>/plan.html`
- `packages/<package>/implementation.html`
- `packages/<package>/results.html`
- `packages/<package>/analysis.html`
- `packages/<package>/tracker.html`
- `packages/<package>/docs/index.html`

The masthead Hero lead on `packages/<package>/index.html` renders the
state-backed `Package.abstract` as the Package Abstract / TLDR. The renderer
falls back to `problem` only for legacy records without an abstract. It does
not derive this copy from Direction Scope.

`module.html` is part of the frozen surface. Preserve the existing
`module.html?package=<id>&module=<name>` route. Package pages and module routing
must not be collapsed into a single-page application.

### Package status strip

The first viewport of every Package page uses one shared status projection:

- **Current state** renders the lifecycle or active phase. The UI folds a
  blocker into this cell, but authoritative state keeps it separate from the
  resumable canonical `phase`.
- **Current process** describes the work owned by the current lifecycle or
  phase. It never renders the future-facing Package `nextAction`. Live Run ids
  may appear only as supporting evidence in execution phases.
- **Last transition** uses an explicit transition record when one exists. A
  fallback derived from the Scope binding is labelled `INFERRED`.
- **Next state conditions** render every legal outgoing phase as an ordered
  `IF transition condition → next state` pair. They come from the central
  package-phase graph and remain visually neutral: the interface must not
  predict or highlight a branch before its condition is verified and the
  transition is recorded.

Active gates and metric-versus-gate values do not belong in this universal
strip. Their authoritative detail remains in Scope and Plan, while observed
measurements and gate verdicts remain in Results.

On the Package Overview, the masthead is an identity summary rather than a
marketing hero. It stays compact enough to keep the whole status strip in the
first viewport. Current State is the primary visual anchor. Current Process and
Last Transition are supporting context, and every legal next-state branch uses
the same neutral treatment until the transition is recorded. Empty optional
headline content stays hidden, while declared experiments render in the
Experiment queue.

The Research Intent card renders exactly four state-backed rows in causal
order: **Problem**, **Motivation**, **Objective**, and **Hypothesis**. Problem
states the known or high-probability research gap; Motivation gives its value
and high-level solution rationale; Objective gives the verifiable target for
judging that rationale; Hypothesis is the falsifiable natural-language
synthesis of Motivation and Objective. The renderer never hides a row because
its text duplicates another field and never invents `*Tldr` alternatives.
Missing or duplicated content is an upstream Package/Scope validation error,
not a presentation rule.

## Required generated data

The data directory exposes browser-safe projections such as:

- `schema.js`
- `research-packages.js`
- `brainstorms.js`
- `rules.js`
- `scope-projection.json` and `scope-projection.js`
- `scope-transitions.jsonl` and `scope-triage.jsonl`
- `live-runs.jsonl` and `live-acknowledged.json`
- `self-evolution.json` and `self-evolution.js`

The exact population depends on current state, but the browser globals and file
names consumed by the frozen pages must remain available. Scope JSONL files are
generated views of state events. Live files are generated indexes of
experiment state. Rules and learnings are state-backed projections. None is a
write surface.

The generated tree must contain no `scripts/` directory, `.py` file, server
state, or server log.

## Server contract

`lib.interface.serve` serves only the resolved `interface/` directory. It may
read authority to answer these endpoints:

- `GET /api/health`
- `GET /api/live/runs`
- `GET /api/live/status/<run-id>`
- `GET /api/live/log/<run-id>`

No write endpoint is allowed. Path validation must prevent a run reference from
escaping the managed `experiments/` root.

`ensure` checks the projection marker, rebuilds only when absent or stale,
reuses a healthy matching server when possible, or starts one. `serve` performs
the same currentness check before running in the foreground. Each static-page
request rechecks the marker and coalesces intervening management commits into
one rebuild. `status` reads the recorded runtime state and checks health.

Volatile server metadata and logs live under:

```text
$XDG_RUNTIME_DIR/trustworthy-research/<workspace-hash>/
```

When `XDG_RUNTIME_DIR` is absent, use the per-user temporary fallback selected
by `ResearchPaths.runtime`. Runtime state never belongs in the managed
interface tree.

## Frozen human contract

Storage simplification must not alter the human layout. The following are
regression-protected:

- DOM hierarchy and contract-bearing `id`, `class`, `href`, `src`, `name`,
  `type`, and `role` attributes;
- `assets/research.css` and `assets/toc.css`;
- the shared Brainstorm document shell and `assets/brainstorm.css`;
- the fixed viewport and Chromium major;
- screenshot perceptual hashes for the global, module, and representative
  package pages.

The checked baseline is
`skills/research-dashboard/assets/interface-contract.json`. Validate it with:

```bash
python3 -m lib.interface.parity check
```

The exact protected page counts are recorded by the parity fixture and checked
against `lib.interface.parity`. `--no-visual` is an intermediate check only. Do
not update the baseline to hide an accidental UI change.

State plumbing and narrowly necessary path or serve guidance may change without
a redesign. Any change to page composition, navigation, module routing, DOM
anchors, CSS, or visual layout requires explicit user approval.
