# AGENTS.md - Trustworthy Research Pipeline

This is the Codex bootloader for ARC. Keep it small. Do not automatically read
`CLAUDE.md`, `workflow.ts`, every `research-*` skill, or generated interface
files. Load only the skill and reference that own the current request.

## Locate the work

- This toolbox repo is the Git root containing this file, `README.md`,
  `skills/`, and `lib/`.
- A target research project is a consuming repo with a versioned `.research/`
  root and project source, configs, and data.
- Change framework code here. Run research and mutate research state in the
  target project. Do not modify both unless the user asks for an end-to-end
  integration change.

## Authority

Resolve one `RESEARCH_ROOT`, normally `<workspace>/.research`:

1. `state/research.sqlite3` owns governed intent, management history,
   idempotency, and command outcomes.
2. `experiments/<package>/<experiment>/<run>/` owns commands, measurements,
   and evidence for each Run.
3. `state/events.jsonl`, `state/current.json`, and `audit/actions.jsonl` are
   compatibility exports.
4. `interface/` is a disposable, read-only human projection.

Use bounded state queries and the relevant Run files. Never infer authority
from HTML, chat memory, raw terminal scrollback, or a compatibility export.

## Route by use case

Do not load every skill at startup. Select one owner from skill metadata:

- setup, attach, repair: `research-init`;
- first Project charter: `research-onboard`;
- standalone idea discussion: `research-brainstorm`;
- Draft, Scope Bundle, Package outcome or restructuring: `research-package`;
- guarded query or mutation: `research-op`;
- execution and result verification: `research-run`;
- campaign execution: `research-auto`;
- long Run monitoring: `research-exp-live`;
- compute placement: `research-resource`;
- evidence analysis and Rule promotion: `research-analysis`;
- human projection: `research-dashboard`.

Read the selected `SKILL.md`, then only the reference it explicitly routes to
for this case. Use command `--help` for argument details.

## Normal lifecycle

```text
research-init
  -> research-onboard: one Project review and authorization
  -> repeated Package loop:
       Brainstorm discussion
       -> agent materializes one non-executable Draft Package
       -> Draft refinement
       -> one Direction-and-Experiments Scope Bundle review and authorization
       -> execution under the resulting Scope Execution Lease
       -> optional evidence analysis
       -> one evidence-bound SUCCESS or FAIL decision
```

Project, Scope Bundle, and terminal Package outcome are the human authority
boundaries. Brainstorm-to-Draft materialization is not another formal approval.
The normal path creates no Proposal/Triage aggregate and asks for no per-launch
acknowledgement when the current Scope Execution Lease authorizes that
Experiment. Compatibility flows remain available only when a skill routes to
them explicitly.

## Trust kernel

- Scope is `Project -> Direction -> Experiment`; Package is not a Scope level.
- `Experiment.spec` is the only executable intent and owns `purpose`,
  `config_ref`, `gate`, and `control_mode`.
- Validate and reject before write. Use the transaction kernel for a semantic
  operation that changes several aggregates.
- Before writing user-visible prose, invoke `humanizer` and use its final rewrite. Preserve code, paths, IDs, metrics, evidence, citations, equations, logs, and user-authored text; if unavailable, stop.
- Before any codebase design, implementation, refactor, or fix, invoke `ponytail`. Before completion, invoke `ponytail-review` on the resulting diff; if either is unavailable, stop.
- A Run freezes its launch context. Later state changes never rewrite it.
- Results must bind protocol, gate, and hashed evidence. Measurements are not
  verdicts, and producers do not prove their own success.
- Only the user may commit Project intent, a Scope Bundle, or a terminal
  Package outcome.
- Management commands leave the interface stale; Dashboard startup or the next
  static request coalesces changes into one rebuild.

If required intent or evidence is missing, stop at the smallest useful user
decision. Do not invent it or patch a projection.

## Toolbox maintenance

- Preserve unrelated worktree changes.
- A `lib/` helper must have a live skill, CLI, dashboard, install, or test
  caller. Remove or move orphan helpers.
- Put normal-path guidance in a short `SKILL.md`; put compatibility details in
  routed references.
- Run the smallest relevant test layer while iterating: `core`, `integration`,
  `projection` or `release`. Run the full suite before release.
- Report changed surfaces, validation, and any remaining human decision.
