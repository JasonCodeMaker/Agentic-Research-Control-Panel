---
name: research-dashboard
description: "Use when building, serving, repairing, or validating the read-only .research/interface projection."
---

# Research Dashboard

Build and serve the human research interface without turning HTML into a second
state store. The interface is a disposable projection of the managed research
root. It must remain useful to people while staying irrelevant to agent
authority.

Read [references/dashboard-contract.md](references/dashboard-contract.md)
before changing the projection or its tests.

## Boundary

Resolve one `ResearchPaths` instance from:

1. `--research-root`, when supplied.
2. `RESEARCH_ROOT`, when set.
3. `<workspace>/.research`, otherwise.

The managed root has four distinct responsibilities:

```text
.research/
├── VERSION
├── state/          # authoritative management state and content-addressed notes
├── audit/          # authoritative command audit
├── experiments/    # durable experiment runs and outputs
└── interface/      # generated, read-only human projection
```

Treat `.research/state/` and `.research/experiments/` as inputs.
Treat `.research/interface/` as output. Agents must never recover facts from the
interface, edit it as state, or place experiment outputs inside it. Deleting the
entire interface must be safe because a build can recreate it from authority.

The projection contains HTML, CSS, JavaScript, and generated data files. It
must not contain Python files or a `scripts/` directory.

## Build

From the pipeline checkout, rebuild an existing versioned store:

```bash
python3 skills/research-dashboard/scripts/ensure_dashboard.py \
  --workspace . \
  build
```

Pass `--research-root <path>` when the managed root is not
`<workspace>/.research`. The command prints the interface root, source event
sequence, source hash, file count, and every generated file.

The builder creates the complete projection in a staging directory and swaps it
into place. A rebuild therefore repairs missing files and removes stale files.
Do not patch generated files to repair drift. Rebuild them.

`build` never initializes or migrates managed state. A missing, legacy,
unversioned, or unsupported root must stop with a handoff to `research-init`.

## Serve

The server document root is exactly `.research/interface`. It adds only
read-only health and live-run endpoints:

- `/api/health`
- `/api/live/runs`
- `/api/live/status/<run-id>`
- `/api/live/log/<run-id>`

Run a foreground server when the process should remain attached:

```bash
python3 -m lib.interface.serve \
  --workspace . \
  serve \
  --host 127.0.0.1 \
  --port 8904
```

Build and start a background server, or reuse a healthy one:

```bash
python3 -m lib.interface.serve \
  --workspace . \
  ensure \
  --host 127.0.0.1 \
  --port 8904 \
  --json
```

Check the recorded server:

```bash
python3 -m lib.interface.serve \
  --workspace . \
  status \
  --json
```

Stop only the healthy server recorded for this workspace:

```bash
python3 -m lib.interface.serve \
  --workspace . \
  stop \
  --json
```

`ensure` requires a versioned root and performs a full rebuild before checking
or starting the server.
`serve` builds only when the interface directory is absent. Use `build` or
`ensure` when state has changed and a fresh projection is required.

Server PID metadata and logs are volatile runtime state. They live below
`$XDG_RUNTIME_DIR/trustworthy-research/<workspace-hash>/` when
`XDG_RUNTIME_DIR` is set, or below the per-user temporary fallback otherwise.
They must not be written into `.research/interface`.

For a remote workspace, keep the server bound to loopback and forward it:

```bash
ssh -L 8904:127.0.0.1:8904 <host>
```

Then open `http://127.0.0.1:8904/index.html`.

## Human interface contract

Keep the current human layout and navigation:

- Global pages remain `index.html`, `live.html`, `scope.html`, and
  `learnings.html`.
- The four category pages remain separate pages.
- Each Brainstorm detail route is a full document assembled from the shared
  `templates/brainstorm-document.html` shell, `assets/brainstorm.css`, and an
  optional state-backed `document_note` HTML fragment.
- Each package keeps its own plan, implementation, results, analysis, tracker,
  and docs pages.
- `module.html` remains available. Preserve the existing
  `module.html?package=<id>&module=<name>` route.
- `live.html` keeps its own API poller. Other pages may use
  `assets/live-data.js` to refresh projected data in place.

Do not consolidate these pages into a single-page application. Do not remove
the module route. Do not redesign the UI as part of a storage or authority
change.

Brainstorm `detail_note` remains a compatibility override for migrated
self-contained pages. New and revised Brainstorms use `document_note`; do not
copy the outer page, navigation, ToC, scripts, or CSS into that fragment.

The DOM hierarchy, contract-bearing attributes, CSS bytes, viewport, browser
major, and screenshot baselines are frozen by
`assets/interface-contract.json`. State-source paths and narrowly necessary
serve guidance may change, but IDs, classes, navigation, page layout, and
visual styling require explicit user approval.

## Validation

After a dashboard change:

```bash
python3 skills/research-dashboard/scripts/ensure_dashboard.py \
  --workspace . \
  build
python3 -m lib.interface.parity check
```

Use `python3 -m lib.interface.parity check --no-visual` only as a fast
intermediate DOM and CSS check. Final interface validation includes the visual
pages and their bounded perceptual hash comparison.

Also verify:

1. `.research/interface` contains no `scripts/` directory or Python files.
2. All global, category, module, and package URLs load from the interface root.
3. `/api/*` endpoints remain read-only.
4. Rebuilding after deleting `.research/interface` recreates the same human
   surface from state and experiment authority.
5. Server metadata and logs remain outside the managed projection.

The dashboard can show that Project Scope is absent, but it does not define or
ratify Project intent. Check that boundary through the onboarding query:

```bash
python3 skills/research-onboard/scripts/onboard.py \
  --workspace . \
  has-project-scope
```

If managed state is absent, hand off to `research-init`. If no Project exists
in a valid setup, hand the next decision to `research-onboard`. Do not invent
Project, Direction, or Experiment intent in dashboard data.

## Report

Report the resolved research root, generated interface root, source sequence and
hash, server URL and stop command when started, parity result, and whether a
committed Project exists. If setup is missing or invalid, report the
`research-init` handoff and that no initialization, migration, or overwrite was
attempted.
