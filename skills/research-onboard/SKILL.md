---
name: research-onboard
description: "The steps 1->3 on-ramp: bridge a raw workspace into the Scope SSOT. Use right after /research-dashboard when no Project node exists yet, or whenever the user types /research-onboard, asks to bootstrap / initialize / set up a research project, or asks the agent to analyze a workspace and propose a project objective. Two cases: an EMPTY workspace gets an in-place deep-learning skeleton plus AGENTS.md / CLAUDE.md stubs, then a goal elicited by dialogue; an EXISTING workspace gets analyzed (README / AGENTS.md / CLAUDE.md / configs / src / data / baselines) into a prior-knowledge artifact plus a drafted objective. Both end by proposing a Project node through Triage for the human to ratify. Project-agnostic. The agent only PROPOSES — it never commits the SSOT and never creates packages."
argument-hint: "[<cwd, defaults to .>]"
allowed-tools: Bash(python3 *), Read, Edit, Write, Grep, Glob
disable-model-invocation: false
---

# research-onboard (the steps 1->3 bridge)

`/research-dashboard` stands up the HTML chrome; `/research-scope` ratifies intent into the Scope SSOT.
Between them is a gap: a raw workspace has no objective yet, and the agent has historically dropped the
user at an empty dashboard with no help. This skill closes that gap. It turns "I opened a repo" into a
**pending Project proposal** the PM can ratify — without ever writing the SSOT itself.

The trust invariant is unchanged: **the agent proposes; the PM disposes.** This skill submits a pending
Triage item through the same `triage.py` gate `research-scope` uses; the human accepts and commits the
`scope-transition`. Onboarding never mutates `transitions.jsonl`.

## Resources

**Pipeline root:** `/home/uqzzha35/Project/Trustworthy-Research-Pipeline/Trustworthy-Research-Pipeline`

| Resource | Path |
|---|---|
| Onboard CLI | `<pipeline-root>/skills/research-onboard/scripts/onboard.py` |
| Scope SSOT lib | `<pipeline-root>/lib/scope_ssot/__init__.py` |
| Triage CLI | `<pipeline-root>/skills/research-scope/scripts/triage.py` |
| Prior-knowledge artifact | `outputs/_scope/prior_knowledge.md` |
| Transition log (SSOT commits) | `outputs/_scope/transitions.jsonl` |
| Triage queue | `outputs/_scope/triage.jsonl` |
| Hand-off skill (commit path) | `research-scope` |

Onboard CLI commands (drive via `Bash(python3 *)`):

```bash
python3 skills/research-onboard/scripts/onboard.py detect --cwd .
python3 skills/research-onboard/scripts/onboard.py scaffold --cwd .
python3 skills/research-onboard/scripts/onboard.py write-prior-knowledge --state-root outputs --content '<markdown>'
python3 skills/research-onboard/scripts/onboard.py build-proposal --node-id project/<slug> --spec '<json>' --source '<files read>'
python3 skills/research-onboard/scripts/onboard.py has-project-scope --transitions outputs/_scope/transitions.jsonl
```

## Precondition

The dashboard must exist (run `/research-dashboard` first). If a Project node is already committed
(`has-project-scope` prints `true`), there is nothing to bootstrap — stop and point the user at
`/research-brainstorm` (vague idea) or `/research-scope` (clear Direction) to add a **Direction** (step 3) instead.

## Procedure

**1. Detect the workspace state.**

```bash
python3 skills/research-onboard/scripts/onboard.py detect --cwd .
```

`"state": "empty"` means nothing but pipeline-managed/noise entries exist. `"existing"` means there is
project content to analyze (listed under `"content"`).

**2a. Empty workspace — scaffold, then elicit.**

Scaffold the in-place deep-learning skeleton (idempotent; writes `AGENTS.md` and `CLAUDE.md` stubs
only if absent):

```bash
python3 skills/research-onboard/scripts/onboard.py scaffold --cwd .
```

There is no repo to mine, so **elicit** the objective from the user in plain dialogue, one question at a
time: the goal, the core contributions, and what is out of scope. Do not invent these. Source for the
proposal is `user-dialogue:onboarding`.

**2b. Existing workspace — analyze, then draft.**

Read the content entries `detect` reported — typically `README.md`, any `AGENTS.md` / `CLAUDE.md`,
`configs/`, the `src/` tree, dataset locations, and existing `baselines/` or reported metrics. From them, draft:

- **prior knowledge** — a human-readable digest the later roles (R2 lit, R3 ideate, R4 experiment) read:
  dataset inventory, existing baselines and any current-best metric, the key file map, training/eval
  commands. Write it (this is content, not an SSOT write):

  ```bash
  python3 skills/research-onboard/scripts/onboard.py write-prior-knowledge --state-root outputs --content '<markdown>'
  ```

- **a candidate objective** — `goal`, `contributions`, `out_of_scope` inferred from what you read.
  Keep these as *intent*, never readings (no measured values inside the spec). Provenance lists the
  files you read, e.g. `read:README.md,AGENTS.md,CLAUDE.md,configs/train.yaml`.
  `goal` is a 20-100 word string; `contributions` and `out_of_scope` are non-empty lists where each
  item is 5-50 words.

Confirm the drafted objective with the user before proposing — they may correct the goal. This is the
HCI-alignment moment (核心问题 #2): the agent shows its inferred understanding and the user steers it.

**3. Build the validated Project proposal.**

```bash
python3 skills/research-onboard/scripts/onboard.py build-proposal \
    --node-id project/<slug> \
    --spec '{"goal":"<20-100 word project goal>","contributions":["<5-50 word contribution>"],"out_of_scope":["<5-50 word boundary>"]}' \
    --source '<dialogue or files read>'
```

`build-proposal` validates the spec against the SSOT schema (reject-before-propose): a reading or a
non-project field is refused before anything is written. Fix the spec if it raises.

**4. Submit through the Triage gate and STOP.**

Pipe the proposal into the same gate `research-scope` uses:

```bash
python3 skills/research-scope/scripts/triage.py propose --log outputs/_scope/triage.jsonl --item '<proposal json>'
python3 skills/research-scope/scripts/triage.py pending --log outputs/_scope/triage.jsonl
```

Show the pending item and stop. Onboarding is done — committing the objective is the PM's decision.

## Hand-off (PM action, not agent)

This mirrors `research-scope`'s human-accept path. The PM:

1. `triage.py dispose --decision accept`.
2. Commits the Project node with `research-op --op scope-transition` and `gate=USER_ONLY` (the project gate).
3. Once the Project is committed, the journey advances to **step 3** — forming a Direction under the
   ratified Project. If the user only has a vague idea, route through **`/research-brainstorm`** (shape it,
   ground uncertainties, converge to a Direction proposal). If they already have a
   clear Direction (`hypothesis / metric / baselines / success_gate`), `/research-scope` proposes it
   directly.

## Scope (what this skill does NOT do)

- Does not commit the SSOT — only proposes a pending Triage item.
- Does not create Directions, Tasks, milestones, or research packages — those are `/research-scope` and
  `/research-package`, after the Project is ratified.
- Does not edit the dashboard chrome or rule files.

## Output contract

| Path | Written by | Contents |
|---|---|---|
| `<cwd>/src`, `configs/`, … + `AGENTS.md` / `CLAUDE.md` stubs | this skill (empty case only) | in-place DL skeleton |
| `outputs/_scope/prior_knowledge.md` | this skill (existing case) | analysis digest for later roles |
| `outputs/_scope/triage.jsonl` | `triage.py propose` | one pending Project item |
| `outputs/_scope/transitions.jsonl` | PM only (via research-op) | committed Project node — never this skill |

## Done condition

A pending **project**-level Triage item is visible in `triage.jsonl` and has been shown to the user;
for an empty workspace the skeleton is scaffolded; for an existing one `prior_knowledge.md` is written.
The objective is not yet in effect — it takes effect only after PM acceptance and the
`research-op --op scope-transition` commit.
