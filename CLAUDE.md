# CLAUDE.md - Trustworthy Research Pipeline

This is the Claude bootloader for ARC. It is independently sufficient and does
not require reading `AGENTS.md` or `workflow.ts`. Load one owning skill and only
the references needed for the current use case.

## Purpose and authority

ARC makes autonomous research auditable, steerable, and project-specific. Its
claim rests on typed intent, narrow mutation surfaces, immutable Run context,
evidence-bound results, governed learning, and a read-only human interface.

Under `RESEARCH_ROOT`, normally `<workspace>/.research`:

1. `state/research.sqlite3` owns governed intent, events, current state,
   idempotency receipts, and command outcomes.
2. `experiments/<package>/<experiment>/<run>/` owns executed commands,
   measurements, and evidence.
3. JSONL and `current.json` are compatibility exports.
4. `interface/` is a rebuildable human projection and never agent authority.

Query typed state. Read only the relevant Run directory for runtime facts.
Never use interface files, chat summaries, or raw scrollback as a writer or
source of research truth.

## Research model and lifecycle

Scope is:

```text
Project -> Direction -> Experiment
```

`Experiment.spec` is the only executable intent. It owns `purpose`,
`config_ref`, `gate`, and `control_mode`. Brainstorm is a standalone idea
document. Package is the governed work unit, not a Scope level. Run is one
immutable execution attempt.

The normal lifecycle is:

```text
one Project review and authorization
  -> Brainstorm discussion
  -> agent materializes a non-executable Draft Package
  -> Draft refinement
  -> one complete Scope Bundle review and authorization
  -> Package execution under its Scope Execution Lease
  -> optional analysis
  -> one evidence-bound SUCCESS or FAIL decision
```

The Scope Bundle transaction binds the exact Draft revision and document hash,
then writes the Package, Direction, and selected Experiments atomically.
Project, Scope Bundle, and terminal outcome are user decisions. Materializing a
Brainstorm as Draft is not a separate formal approval. Proposal/Triage and
launch-ack flows are compatibility paths, not the normal loop.

## Trust rules

- Validate and reject before write. Never hand-edit SQLite, compatibility
  exports, audit rows, or generated interface files.
- A Run freezes current governed context into its `context.json`; later Scope
  changes apply only to later Runs.
- Every result binds its declared gate and protocol to hashed evidence.
- Checkpoints, metrics, terminal markers, and logs are observations until the
  result contract and verifier admit them.
- Producers do not independently establish their own success.
- The user owns changes to ratified intent, Package adoption, and archival.
- Evidence-backed Learnings and Rules must resolve to their witness.
- When intent or evidence is missing, surface the gap and stop at the smallest
  required decision.

## Skill routing

Use skill metadata to choose one owner:

- `research-init`: setup, attach, migration, repair;
- `research-onboard`: first Project charter;
- `research-brainstorm`: idea creation and refinement;
- `research-package`: Draft, Scope Bundle, Package decision, restructuring;
- `research-op`: bounded queries and governed mutations;
- `research-run` or `research-auto`: execution;
- `research-exp-live`: long Run monitoring;
- `research-resource`: compute placement;
- `research-analysis`: evidence analysis and Rule promotion;
- `research-dashboard`: read-only interface build and serve.

Use `research-op context` for bounded agent context. The launcher independently
freezes full authority context for the Run. Detailed schema, migration, and
compatibility commands belong in skill references or command help.

## Runtime and interface

Long experiments use `research-exp-live` when it is available.
Structured status is the routine source; bounded logs are a debug fallback.
Keep long training, preprocessing, downloads, syncs, and remote jobs observable through
the supported named runner.

Management commits do not render HTML. Dashboard startup and static-page reads
compare a source marker with current state and rebuild once when stale. A
projection failure cannot roll back or redefine committed research state.

## Per-project profile

A consuming project may prepend its purpose, datasets, primary metric, budget,
contribution spine, current best result, and project-specific constraints.
Those sections are user-owned. They may narrow this protocol but must not
silently weaken the authority, evidence, or human-decision boundaries above.
