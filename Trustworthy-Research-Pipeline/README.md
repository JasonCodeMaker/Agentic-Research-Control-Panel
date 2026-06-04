# Trustworthy Auto-Research Pipeline

A research workflow you **manage like a project manager**. You set the goals; an AI agent does the
research; and every claim it makes is gated by machinery — not by trust — so it cannot quietly fabricate
a result, drift off your objective, or rewrite the rules it is judged by.

It exists to solve three failure modes of autonomous research agents:

| Problem | What goes wrong | How this pipeline counters it |
| --- | --- | --- |
| **1. Hallucination → deception** | The agent claims results it never produced. | Typed interfaces + deterministic gates: a citation must resolve to a fetched source, a paper claim must map to a verified artifact, a "success" must clear a metric oracle. Reject-before-write. |
| **2. No model ↔ user alignment** | You can't see what the agent is doing or steer it. | A live HTML dashboard + a user-led objective system (you propose-or-ratify; the agent can only propose). |
| **3. No project self-learning** | The agent repeats the same mistakes. | A reflection loop that proposes new rules from the audit log, landed only with your approval. |

> **Mental model.** *You* are the project manager. *The agent* is a managed worker whose tasks, state,
> evidence, and next actions are made visible and governable. Everything below serves one of seven steps
> you actually perform.

---

## The seven-step journey

This is the whole system. Each step has a skill (or a gate) behind it; nothing else exists.

```
1  Setup          /research-dashboard      → stand up the 4-lane dashboard            (once)
2  Define Project /research-scope          → ratify the north-star objective          (once)
3  Create Dir+Task/research-scope          → a Direction (hypothesis + metric) + dial (per direction)
4  Run            /research-auto           → agent drives the 7 research roles         (the loop)
5  Away modes     (autonomy dial)          → leave it running; review on return
6  Scope change   /research-scope (Triage) → move the goalposts, auditably
7  Self-learning  /research-reflect→apply  → the project gets better at itself
```

> **Worked example used throughout:** *"Beat the ResNet-18 baseline on CIFAR-10 top-1 accuracy."*
> Yardstick → **hypothesis:** mixup augmentation improves top-1 accuracy; **metric:** top-1 accuracy;
> **baseline:** ResNet-18; **success predicate:** `top-1 > baseline + 1.0`.

---

## Setup (once)

### 1. Install the skills — **symlink, do not copy**

The skills' scripts find their shared libraries (`lib/`) relative to their own location in *this repo*.
Symlinks preserve that link; a plain `cp` breaks it for the seven library-backed skills.

```bash
# from this repo's root
for skill in skills/*/; do
  ln -sfn "$(pwd)/$skill" ~/.claude/skills/"$(basename "$skill")"   # ~/.codex/skills/ for Codex
done
```

Restart the agent so it picks up the skills. Verify the install by running the test suite (Python 3.13):

```bash
python3.13 -m pytest -q          # expect: 153 passed
```

### 2. Point a research project at the pipeline

The repo is the **toolbox**; you run the skills from inside whatever **research project** you are
managing. State (`research_html/`, `var/research/`) lands in that project's directory; the skill code
resolves back to this repo automatically.

```bash
cd /path/to/your-research-project
cp /path/to/this-repo/CLAUDE.md ./CLAUDE.md   # then PREPEND your project specifics above the protocols
cp /path/to/this-repo/WORKFLOW.md ./WORKFLOW.md   # if the project doesn't already have one
```

`CLAUDE.md` ships project-agnostic protocols; do not edit them — prepend your project name, objective, and
contribution spine above them. See [CLAUDE.md](CLAUDE.md) → *Per-project customization*.

---

## Step 1 · Setup the dashboard

```
/research-dashboard
```

Scaffolds `research_html/`: an `index.html` + four lane pages (**brainstorm / in-progress / success /
fail**), `learnings.html`, the `(category, status)` state machine in `data/schema.js`, the read-only
Scope-SSOT projection, the binding rule files, and the lint tooling. This is your single pane of glass —
overview-only; claims and evidence live on package pages, never on the dashboard.

## Step 2 · Define the Project (ratify the north-star)

```
/research-scope
```

The agent **proposes** a Project node — north-star objective, contribution spine, non-goals. The Project
gate is **mandatory user ratification**: nothing proceeds under an objective you didn't sign off on. The
objective cascade is PM-write-only — the agent can never edit it on its own.

## Step 3 · Create a Direction + Task

`/research-scope` proposes a **Direction** carrying a typed *yardstick* (`hypothesis / metric / baselines /
success_predicate`) and you pick its **autonomy level** (the dial — see Step 5). A scope change is never a
direct write; it flows through **Triage** (agent proposes → you dispose):

```bash
# agent proposes; you inspect
python3 skills/research-scope/scripts/triage.py propose --log var/research/_scope/triage.jsonl --item '<json>'
python3 skills/research-scope/scripts/triage.py pending --log var/research/_scope/triage.jsonl

# you accept, then commit the versioned SSOT transition (this is the only thing that writes intent)
python3 skills/research-scope/scripts/triage.py dispose --log var/research/_scope/triage.jsonl --id <id> --decision accept
python3 skills/research-op/scripts/research_op.py --pkg <pkg> --op scope-transition --payload '{
  "id":"dir-cifar10-mixup","level":"direction","parents":[],"version":1,"status":"active",
  "yardstick":{"hypothesis":"mixup augmentation improves top-1 accuracy","metric":"top-1 accuracy",
               "baselines":["ResNet-18"],"success_predicate":"top-1 > baseline + 1.0"},
  "provenance":"...","op":"create","gate":"user+xmodel-audit"}'
```

Then materialize the Direction into a research package (it reads only the committed SSOT, never pending
proposals):

```bash
python3 skills/research-scope/scripts/plan_milestones.py   --direction-id dir-cifar10-mixup   # propose milestones
python3 skills/research-package/scripts/create_from_scope.py --direction-id dir-cifar10-mixup --id 2026-06-04-cifar10-mixup
```

The package gets `overview / plan / implementation / results / analysis / next-action / tracker /
brainstorm` pages with provenance links back to the Direction and its milestones.

## Step 4 · Run the loop

```
/research-auto
```

The orchestrator drives one direction's `idea → paper` loop through **seven roles**, pulling every
yardstick from the Scope SSOT and routing every write through the trust gates:

| Role | Skill / home | Trust guarantee |
| --- | --- | --- |
| **R1** scope | `research-scope` | acts only under a ratified SSOT node |
| **R2** search/read | `research-lit` | **fetch-don't-fabricate** — a citation must resolve to a fetched source (`lib/cite_check`) |
| **R3** ideate | `research-ideate` | won't re-try an idea the current scope already failed (scope-conditional banlist) |
| **R4** experiment | `WORKFLOW.md` | the 7-step experiment controller; long runs in `tmux` |
| **R5** verify | `lib/verifier` | a cross-model jury; **producer ≠ judge**; 6-state verdict |
| **R6** write | `research-write` | **grounded-only** — a paper claim must map to a verified artifact (`lib/cite_check`) |
| **R7** remember | memory + acquit gate | a direction is "acquitted" only if the metric oracle clears the SSOT success predicate |

Watch it live by tailing the audit log; find where it got stuck by grepping for rejections:

```bash
tail -f var/research/<pkg>/_actions.jsonl
grep '"validation": "rejected"' var/research/<pkg>/_actions.jsonl | tail
```

## Step 5 · Away modes (the autonomy dial)

You choose, per task, how much the agent may do unattended. Higher levels still obey every trust gate —
the dial controls *acknowledgement*, never *correctness*.

| Level | Agent pauses for you at… | On your return |
| --- | --- | --- |
| `supervised` | every gate | — |
| `checkpoints` | terminal gates only | — |
| `async` | nothing | a **PACK**'d dashboard narrative |
| `autonomous` | nothing | PACK narrative; acquit additionally requires a **different model family** in the verifier |

The agent never self-acquits and never edits the objective while away. On return you **UNPACK** the
narrative, dispose any Triage items, and T1-ack terminal transitions.

## Step 6 · Scope change (move the goalposts, auditably)

When evidence says the goal should change, the agent files a Triage proposal showing the lineage
(`from → to / trigger / cause / delta / invalidates / reopens`). You ratify or reject. On ratify: a
**versioned** SSOT transition; propagation carries/invalidates/reopens downstream nodes; affected tasks'
dials **auto-revert to supervised**; and a failed idea whose failure condition no longer holds is
**reopened** in the banlist — failure is never permanent across a goalpost move.

## Step 7 · Self-learning (human-gated)

```
/research-reflect      # read-only proposer
/research-apply        # privileged, human-gated lander
```

`research-reflect` reads the audit logs and surfaces recurring failure — **doom-loops** (N identical
failures) and **scope-thrash** (a node revised over and over) — and stages a rule proposal. It can never
write to the live corpus. `research-apply` lands a staged proposal **only** when given both a distinct
human approval token *and* a clearing jury verdict. **Proposer ≠ applier, structurally** — this is what
stops the loop from rewriting away its own constraints. Learning is scoped to *project rules*, never the
universal protocols, skills, or validators.

---

## Why you can trust the record

Every guarantee is mechanical (a passing test, a resolved path) rather than a promise:

- **Reject-before-write.** `research-op` is the single mutation surface; an out-of-contract write is
  refused before any byte hits disk, and every op (success or reject) appends one line to
  `var/research/<pkg>/_actions.jsonl`.
- **No fabricated citations / claims.** `lib/cite_check` blocks a cite whose source wasn't fetched (R2)
  and a claim with no verified artifact (R6).
- **No self-graded success.** The metric oracle reads the success predicate back from the SSOT; the
  cross-model verifier keeps producer ≠ judge.
- **No silent goalpost moves.** Intent lives only in the versioned Scope SSOT; the agent can propose, only
  you commit.

## Project maturity

- **Solid (153 tests):** the trust substrate (`lib/scope_ssot`, `lib/verifier`, `lib/cite_check`), the
  dashboard/package/analysis surfaces, and `research-op`'s gates.
- **Walking skeleton:** the `/research-auto` Run loop composes end-to-end at the `supervised` level, but
  several roles are still thin/stub (`skills/research-auto/scripts/skeleton.py`). The dial, cross-model
  verifier, and PACK ship as tested utilities being wired into the main loop.

---

## Reference

### Skills & libraries

| Component | Role |
| --- | --- |
| `skills/research-dashboard/` | Project-level HTML dashboard scaffold (Step 1). |
| `skills/research-scope/` | Objective/Task SSOT + Triage admission gate (Steps 2, 3, 6). |
| `skills/research-package/` | Per-direction multi-page package scaffold (Step 3). |
| `skills/research-auto/` | Orchestrator: drives R1→R7 (Step 4). |
| `skills/research-lit/` · `research-ideate/` · `research-write/` | Roles R2 · R3 · R6 (Step 4). |
| `skills/research-analysis/` | Per-package Rules + Insight page. |
| `skills/research-op/` | The single mutation surface; reject-before-write + audit log + scope-transition commit. |
| `skills/research-reflect/` · `research-apply/` | Self-learning proposer → human-gated applier (Step 7). |
| `lib/scope_ssot/` | Versioned home for intent (Project→Direction→Task). Passive. |
| `lib/verifier/` | Cross-model jury: independence table, 6-state verdict. Passive. |
| `lib/cite_check/` | Fetch-don't-fabricate + grounded-only gates (R2/R6). Passive. |

### State model

Each package's legal `status` values depend on its lane (`brainstorm / in-progress / success / fail`),
declared with the required-field rules in `research_html/data/schema.js`. The
`(category, status, op, target)` legality matrix that `research-op` enforces lives in
[skills/research-op/references/matrix.md](skills/research-op/references/matrix.md). Full state contract:
[CLAUDE.md](CLAUDE.md).

### The per-package controller

When the agent works *inside* a package (role R4), it follows the seven-step controller in
[WORKFLOW.md](WORKFLOW.md) and the binding **Mutation Rule** — every package-surface edit routes through
`research-op`; direct `Edit`/`Write` is a workflow violation.

### Design docs

The architecture, decision audit, and build order live under `plan/` (in the parent design repo) and
[docs/superpowers/](docs/superpowers/).
