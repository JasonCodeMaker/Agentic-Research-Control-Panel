---
name: research-auto
description: "Use when the user invokes /research-auto or asks to run an autonomous research campaign over one Direction toward a measurable gate."
argument-hint: "<direction text or committed direction-id> --gate \"<measurable gate>\" [--dial SUPERVISED|CHECKPOINTED|DEFERRED|AUTONOMOUS] [--max-cycles N]"
allowed-tools: Bash(python3 *), Bash(node *), Read, Edit, Write, Grep, Glob, Agent
disable-model-invocation: false
---

# research-auto (the Direction-campaign conductor)

## Purpose

`/research-auto` turns one **Direction + gate** into a completed research campaign. Where
`/research-run` completes exactly one already-scoped package and stops, `/research-auto` owns the loop
around it: when a package finishes short of the gate, it designs the next experiment from what the last
one taught plus the current Context Pack, routes it through the same scoped surfaces, runs it, and
re-checks the gate — until the Direction's success gate clears with verified evidence, the cycle
budget is exhausted, or a decision surfaces that belongs to the human.

```text
/research-auto  =  campaign over one Direction   (cycles until the gate clears or an honest stop)
   per cycle:   research-brainstorm + ranking     form: grounded, ranked Direction framing
                research-scope (+ Triage)         design: scope formation / milestone revision
                research-package                  design: materialize surfaces from committed scope
                research-run                      run: one package tick to its next terminal outcome
                research-analysis                 harvest: rules + insights worth keeping
                research-op                       every mutation (via the skills above)
```

The conductor itself is deterministic (`scripts/conductor.py`): gate evaluation, the typed cycle
ledger, the route for every tick, and the authority guard are all reproducible from disk — campaign
state never lives in conversational memory.

## Authority (what this skill may never do)

The campaign adds **zero** new mutation paths. All trust contracts hold:

It never disposes Triage, never commits project/direction scope, and never edits package surfaces
directly.

| Decision | Owner | Mechanism |
| --- | --- | --- |
| Project / Direction commits | human | Triage propose → PM dispose → `research-op scope-transition`. The campaign pauses at `AWAIT_RATIFICATION`; it never disposes. |
| Charter (gate, dial, max-cycles) | human | Ratified with the Direction — the gate *is* the Direction's `success_gate`. |
| New / revised milestone Task mid-campaign | dial-keyed | `SUPERVISED`/`CHECKPOINTED`: Triage pause per proposal. `DEFERRED`/`AUTONOMOUS`: self-commit with the SSOT task gate `AGENT_DEFERRED_ACK` **and** a queued `deferred_ack` entry the exit report surfaces. Checked by `conductor.validate_campaign_action` before any commit. |
| Concrete per-cycle experiments | agent | `research-op insert --target experiments-row` under an owning milestone (`sourceTask`) — the existing package contract. |
| Terminal package transitions, adoption | human (T1) | `/research-run`'s existing gates; away dials queue the ack (present-only QA). |
| Campaign exit | conductor routes; human owns acks | `SUCCESS_EXIT` needs a ledgered `gate_eval=PASS` with evidence; every `HALT_*` ends in a typed Triage proposal (extend / revise / archive), never a silent goalpost move. |

The conductor's only writes are the campaign ledger and PACK under `outputs/_auto/<slug>/`. Package
HTML, registry, facts, and the SSOT are mutated only through the delegated skills (hence research-op).

## Resources

`<pipeline-root>` = `/home/uqzzha35/Project/Trustworthy-Research-Pipeline/Trustworthy-Research-Pipeline`

| Asset | Path |
| --- | --- |
| Campaign conductor (this skill) | `skills/research-auto/scripts/conductor.py` |
| Admission state machine (reused) | `skills/research-run/scripts/admission.py` |
| Triage CLI | `skills/research-scope/scripts/triage.py` |
| Milestone planner | `skills/research-scope/scripts/plan_milestones.py` |
| Direction→package materializer | `skills/research-package/scripts/create_from_scope.py` |
| Context Pack builder | `lib/context_pack/build.py` |
| research-op CLI | `skills/research-op/scripts/research_op.py` |
| Campaign ledger | `outputs/_auto/<direction-slug>/campaign.jsonl` |
| Campaign PACK | `outputs/_auto/<direction-slug>/_pack.jsonl` |

Conductor CLI:

```bash
python3 skills/research-auto/scripts/conductor.py status --root . --direction-id <dir-id> \
  --max-cycles <N> --dial <DIAL> [--gate "<gate>"] [--no-candidate]
python3 skills/research-auto/scripts/conductor.py gate-eval --measured <x> --gate "<gate>"
python3 skills/research-auto/scripts/conductor.py append-cycle --root . --direction-id <dir-id> --record '<json>'
python3 skills/research-auto/scripts/conductor.py pack --root . --direction-id <dir-id> --bundle '<json>'
```

## The Charter

An invocation carries up to four facts; everything else is derived:

- **direction** — a committed direction node id (`dir/<slug>`), or free text to be shaped.
- **gate** — a measurable gate (`R@1 >= 48`). It becomes the Direction's `success_gate`;
  if the Direction is already committed and the given gate conflicts with its `success_gate`,
  that is a Direction *revise* → Triage proposal, never an in-place edit.
- **dial** — defaults `AUTONOMOUS`. Surfaced at ratification with all four choices.
- **max-cycles** — defaults 5. A cycle = one designed-and-verified experiment outcome.

The human ratifies the charter once, with the Direction, through Triage. That single ratification is
the standing authorization the campaign operates inside.

## Procedure

**0. Admission.** Run the reused front door first — missing prerequisites hand off exactly as
`/research-run` does (`NO_DASHBOARD` → `/research-dashboard`, `NO_PROJECT` → `/research-onboard`):

```python
import sys; sys.path.insert(0, "<pipeline-root>/skills/research-run/scripts"); import admission
state = admission.detect_admission_state(".")          # NO_DASHBOARD | NO_PROJECT | ...
actions = admission.build_admission_actions(state, context, root=".")
```

Surface each action's `next_step` fields verbatim. Unlike `/research-run`, this skill does not stop at
`NO_DIRECTION`/`NO_TASK`/`NO_PACKAGE` — those are campaign work (steps 1–2). A missing dashboard or
Project node still stops the turn: those belong to the user and `/research-onboard`.

**1. Resolve the charter → a committed Direction.** Run `conductor.py status` with the direction id
(or the id the direction text most plausibly maps to; when in doubt list active directions from the
SSOT fold and ask). Route on `action.type`:

- `FORM_DIRECTION` — invoke **`/research-brainstorm`** with the direction text: ground factual
  unknowns against available sources and project evidence, rank competing framings when needed
  (`lib/ranking`), then build the Direction proposal with the charter gate as `success_gate` and
  submit through Triage. Declare the dial and max-cycles in the proposal's `change`/`rationale` so the
  human ratifies the whole charter. **Pause.**
- `AWAIT_RATIFICATION` — show the pending item; **pause**. Never dispose it.
- `ASK_USER` — the gate is not machine-checkable; ask for a comparator-clause restatement. **Pause.**
- anything else — the Direction is committed; continue.

**2. Materialize once per campaign.** When `status` routes `MATERIALIZE_PACKAGE`:

1. Milestones: if the Direction has no active task children, run
   `plan_milestones.py --direction-id <id> --control-mode <dial> --dry-run` to shape them, then
   commit per the dial — at `SUPERVISED`/`CHECKPOINTED` submit through Triage and **pause**; at
   `DEFERRED`/`AUTONOMOUS` commit each node via `research-op --pkg _scope --op scope-transition`
   (`gate=AGENT_DEFERRED_ACK`, payload carrying a non-empty `deferred_ack`), after
   `conductor.validate_campaign_action` clears the action. Record each deferred ack in the ledger turn.
2. Package: run the same path as `/research-package from-scope <id>`. First call
   `create_from_scope.py --check --json --direction-id <id>` and stop if it returns a handoff. If
   `materializable` is true, call `create_from_scope.py --direction-id <id>` (committed transitions
   only). If a previous campaign package for this direction went terminal, materialize the next one as
   `--id <YYYY-MM-DD>-<slug>-c<N>` — fresh package, same committed scope; Context Pack and active
   rules carry the history forward.

**3. The campaign cycle.** Every tick starts from disk:

```bash
python3 skills/research-auto/scripts/conductor.py status --root . --direction-id <dir-id> \
  --max-cycles <N> --dial <DIAL>
```

Then act on `action.type`; one tick per route, re-run `status` after each:

- **`RUN_PACKAGE`** — invoke **`/research-run`** on the open package and let it own everything inside
  the package: readiness at the dial, implementation/review (TDD, coder ≠ reviewer),
  launch via **`/research-exp-live`** and **`/research-resource`**, monitoring, `scan-events`
  propagation, result verification, terminal routing. Do not re-implement any of its loop here. Apply
  its model-tiering: light roles on small models, code/analysis on the strong one.
- **`DESIGN_EXPERIMENT`** — the gate is unmet and the spine has nothing executable:
  1. `python3 lib/context_pack/build.py --pkg <pkg> --if-stale` and read the pack (read-only;
     it is project context, not a mutation path). Treat the pack's `global_scope_version`,
     Project, Direction, Tasks, and package provenance as the current agent context. Pending Triage is
     only a collision warning unless the user accepts it into Scope.
  2. Draft the next hypothesis from the pack, verified package facts, and the committed Direction.
     If multiple candidates are plausible, rank them with an independent sub-agent (`lib/ranking`).
  3. Map the selected hypothesis to its owning milestone. Fits an active milestone → add one
     experiments-row through research-op (id `P<n>`, action-verb purpose ≤ 12 words, one gate, one
     output, `sourceTask` = the milestone id):
     ```bash
     python3 skills/research-op/scripts/research_op.py --pkg <pkg> --op insert \
       --target experiments-row --payload '{"id":"P3","purpose":"Evaluate reranker variant",...}'
     ```
     Needs a genuinely new validation objective → shape it with
     `conductor.milestone_task_node(...)` and commit per the dial rule in step 2.1.
  4. At `SUPERVISED`/`CHECKPOINTED`, present the selected hypothesis + designed row and **pause** for
     the pick; at away dials proceed.
- **`SUCCESS_EXIT` / `HALT_BUDGET` / `HALT_NO_CANDIDATE` / `ASK_USER`** — go to step 5.

**4. Harvest every terminal experiment outcome (same turn as the verdict).** When `/research-run`
records a verdict for the cycle's experiment:

1. Read `verdict` + `measured` only from the package's verified facts (the `methodsTried` row /
   result-gate row and its `evidencePath`, themselves written from runtime artifacts). Never from chat.
2. Gate-check: `conductor.py gate-eval --measured <x> --gate "<gate>"`.
3. On `FAIL`, make the failure visible in the package facts and cycle ledger so future designs do not
   repeat it without explicit justification.
4. When the cycle taught a mechanism-level lesson, record it via **`/research-analysis`**
   (Insight, optionally distilled to a Rule).
5. Close the cycle in the ledger — a cycle without a ledger record may not close:
   ```bash
   python3 skills/research-auto/scripts/conductor.py append-cycle --root . --direction-id <dir-id> \
     --record '{"cycle":<n>,"direction_id":"<dir-id>","pkg_id":"<pkg>","exp_id":"P3",
                "hypothesis":"...","verdict":"FAIL","measured":"46.1","gate_eval":"FAIL",
                "evidence":"outputs/<pkg>/P3/result.json","next_action":"DESIGN_EXPERIMENT"}'
   ```
6. At `DEFERRED`/`AUTONOMOUS`, also write the campaign PACK bundle (`conductor.py pack`) — attempted /
   found / hypothesis-state / next-action / blocking-decision, so an absent reader never meets a gap.
7. If a lesson should become durable project memory, route it through the governed Rule Store or
   `research-op` registry path with explicit acknowledgement.

Then loop to step 3.

**5. Exit.** Every exit produces the **campaign report** from the ledger: cycles used, per-cycle
`hypothesis → verdict (measured vs gate)` with evidence paths, queued deferred acks, staged
learning actions, and the route's `next_step` copy. Then:

- **`SUCCESS_EXIT`** — the gate cleared (`gate_eval=PASS`, verdict `PASS`, evidence resolves). Let
  `/research-run` route the terminal success transition with its T1 ack — live dials collect the ack
  now; away dials queue it and say so in the report. Adoption (`ADOPTED`) remains a human decision.
- **`HALT_BUDGET`** — report, then propose through Triage: extend max-cycles, revise the
  metric/scope, or archive. **Pause.**
- **`HALT_NO_CANDIDATE`** — no legal next experiment remains under the current scope; propose a scope
  revise, add constraints/evidence, or archive through Triage. **Pause.**
- **`ASK_USER`** — ask the single blocking question.

## Directive changes mid-campaign

A user instruction that changes the campaign's constraints (new rule, different metric/baseline,
redesigned experiment) is a locked fact (`DIRECTIVE_CHANGE`): propagate it through research-op to its
typed home in the same turn, re-run `conductor.py status`, and re-route. A direction-level change is a
Triage proposal + pause — the campaign never rewrites its own charter. If a scope transition carries
`dial_revert`, affected Tasks revert to `SUPERVISED` and lock until re-grounded (existing dial rule).

## Output contract

| Output | Location | Written by |
| --- | --- | --- |
| Campaign ledger (typed cycle records) | `outputs/_auto/<slug>/campaign.jsonl` | `conductor.py append-cycle` (reject-before-write) |
| Campaign PACK bundles | `outputs/_auto/<slug>/_pack.jsonl` | `conductor.py pack` (away dials) |
| Direction/milestone proposals | `outputs/_scope/triage.jsonl` | `triage.py propose` via the formation skills |
| Committed scope, packages, runs, facts, verdicts | their existing homes | the delegated skills, all through research-op |

## Done condition

The campaign is done when the ledger shows an evidence-backed `gate_eval=PASS` cycle and the terminal
success routing (with its T1 ack, collected or queued) has been applied through `/research-run` — or
when a `HALT_*`/`ASK_USER` exit has been reported with its Triage proposal or blocking question in the
user's hands. A long wait is never a stop: open runs stay armed via `/research-run`'s stop gate, and
away-mode ticks always leave a fresh PACK bundle.

## Error path

| Symptom | Meaning | Action |
| --- | --- | --- |
| `GateUnparseable` from status/gate-eval | The gate has no comparator clause | Route `ASK_USER`; never self-judge an unmeasurable gate |
| `validate_campaign_action` returns rejected | The planned action smuggles authority (disposal, direction commit, gateless task commit) | Drop the action; take the Triage-pause path instead |
| `append-cycle` raises ValueError | Cycle record incomplete or verdict/gate_eval illegal | Fill the missing field from facts; an unproven verdict cannot clear the gate |
| `create_from_scope --check` reports a handoff | Direction or validation Tasks are missing or pending | Stop and surface the returned `nextSkill` and `nextAction` |
| `create_from_scope` rejects | Pending-only scope or duplicate package id | Wait for ratification, or materialize with the `-c<N>` id |
| research-op rejects an envelope | A package-state invariant fired | Read the structured rejection, repair the payload, retry; never patch files directly |
| No legal next experiment | The scope's design space is exhausted | `HALT_NO_CANDIDATE` → propose metric/scope revise or archive through Triage |
