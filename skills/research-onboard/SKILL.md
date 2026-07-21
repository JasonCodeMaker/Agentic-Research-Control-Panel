---
name: research-onboard
description: "Use when turning a new or existing workspace into a PM-ratifiable Project proposal."
---

# research-onboard

Onboarding turns a setup-ready workspace into a pending Project proposal. It
does not initialize ARC, attach protocols, commit Project intent, or create a
Package.

The agent proposes; the PM decides. Show the exact objective before asking for
confirmation, then submit it through the same hash-bound Triage gate used by
`research-scope`.

## Authority

Trustworthy-managed state lives under `.research`:

- Project, proposal, and disposition state is event-backed.
- Prior knowledge is a content-addressed NoteRef under
  `.research/state/notes`.
- `.research/interface` is a disposable projection. Onboarding never reads it
  as authority.

The skill does not edit state JSON, event logs, audit rows, HTML, JavaScript,
or CSV. Note and proposal writes call the typed `research-op` management
gateway.

Every CLI accepts `--research-root`; omit it for the default `.research` root.

```bash
python3 skills/research-onboard/scripts/onboard.py --workspace . detect
python3 skills/research-onboard/scripts/onboard.py --workspace . has-project-scope
python3 skills/research-onboard/scripts/onboard.py --workspace . scaffold
python3 skills/research-onboard/scripts/onboard.py --workspace . \
  write-prior-knowledge --content '<markdown>'
python3 skills/research-onboard/scripts/onboard.py --workspace . \
  build-proposal \
  --node-id project/<slug> \
  --spec '<json>' \
  --source '<user dialogue or files read>' \
  --prior-knowledge '<note-ref-json>'
```

The setup gate is fail closed. If the workspace lacks a current versioned root,
contains legacy managed data, or has an unsupported version, stop and use
`research-init`. Do not initialize or migrate from onboarding.

## Procedure

### 1. Detect and check existing intent

Run:

```bash
python3 skills/research-onboard/scripts/onboard.py --workspace . detect
python3 skills/research-onboard/scripts/onboard.py --workspace . has-project-scope
```

`empty` means the workspace contains no project files beyond ignored noise and
the managed research root. `existing` means the command found project content
to inspect.

If an active Project already exists, onboarding is complete. Use
`/research-brainstorm` when the next Direction is vague, or
`/research-scope` when it is already clear.

### 2. Empty workspace

After `research-init` reports `READY_NO_PROJECT`, create the optional
source-side deep-learning skeleton:

```bash
python3 skills/research-onboard/scripts/onboard.py --workspace . scaffold
```

The command creates source, configuration, data-reference, baseline, and figure
directories. It does not initialize `.research` or write protocol files. Run
output does not get a second source-side folder; the experiment harness owns it
under `.research/experiments`.

Ask for the Project goal, contributions, and out-of-scope boundary one
question at a time. Do not invent them. Use
`user-dialogue:onboarding` as the source.

### 3. Existing workspace

Read the files reported by `detect`. Usually this includes `README.md`,
`AGENTS.md`, `CLAUDE.md`, source and configuration trees, dataset references,
baseline code, and documented commands.

Write a compact prior-knowledge digest containing:

- dataset and baseline inventory;
- the relevant source and configuration map;
- known train and evaluation commands;
- clearly labelled observed readings, if any.

Store it:

```bash
python3 skills/research-onboard/scripts/onboard.py --workspace . \
  write-prior-knowledge --content '<markdown>'
```

The command returns a NoteRef with `uri`, `sha256`, `mime`, and `title`.
Preserve that exact JSON for the Project proposal. The NoteRef is included in
the proposal hash and is attached to the Project only after acceptance.

Draft Project intent from the workspace:

- `goal`: 3 to 100 words;
- `contributions`: a non-empty list, 5 to 50 words per item;
- `out_of_scope`: a non-empty list, 5 to 50 words per item.

Readings can appear in the prior-knowledge note, but never inside the Project
spec. List the files read in `source`, for example
`read:README.md,CLAUDE.md,configs/train.yaml`.

### 4. Build and review the candidate

Build the proposal with `build-proposal`. For an existing workspace, pass the
NoteRef returned in step 3 through `--prior-knowledge`. The command validates
the complete Project node but does not submit it.

Show:

```markdown
**Project Scope Review**
- Status: Candidate, not yet submitted
- Level: project
- Node: project/<slug>
- Objective / Goal: <exact proposed text>
- Contributions: <each exact list item>
- Out of Scope: <each exact list item>
- Prior Knowledge: <NoteRef, or none for user-dialogue onboarding>
- Source: <user dialogue and/or files read>
- Next Step: CONFIRM to submit, REVISE with changes, or REJECT the draft
```

If the user supplied exact wording, show it verbatim. Keep any agent
interpretation outside the proposed spec. Do not submit until the PM confirms
the displayed content.

### 5. Submit and stop

Submit the confirmed JSON:

```bash
python3 skills/research-scope/scripts/triage.py --workspace . propose \
  --item '<proposal-json>'
python3 skills/research-scope/scripts/triage.py --workspace . pending
```

Show the same Project Scope Review again with:

- `Status: Pending Triage, not yet committed`
- the Triage item id;
- the proposal hash;
- the exact next decision syntax.

The next decision must be one of:

- `ACCEPT <item-id> <proposal-hash>`
- `REVISE <item-id> <proposal-hash>` with requested changes
- `REJECT <item-id> <proposal-hash>`

Stop after showing the pending review. `research-scope` owns the hash check,
disposition, and accepted `scope-transition`.

## Boundaries

Onboarding does not:

- install skills, attach protocols, initialize state, or migrate legacy data;
- commit a Project, Direction, or Experiment;
- create a Package or launch a Run;
- read or mutate the interface projection;
- treat a NoteRef as accepted Project intent before proposal acceptance.

## Done condition

For an empty workspace, the source skeleton and versioned research root exist.
For an existing workspace, prior knowledge has a stable NoteRef. In both
cases, a validated Project proposal is pending and the PM has seen its exact
content, item id, proposal hash, and next decision syntax.

The Project becomes active only after a matching PM acceptance and the gated
`research-op --pkg _scope --op scope-transition --from-triage <item-id>`
command succeed.
