---
name: research-onboard
description: "Use when turning a setup-ready workspace into one ratified Project through a single natural-language review."
---

# Research onboard

Turn one setup-ready workspace into an active Project. Keep the human exchange
semantic and brief. Repository inspection, NoteRefs, proposal hashes, events,
and commands are internal machinery.

The agent drafts; the user decides once. Delegate proposal and Scope writes to
`research-scope` and `research-op` rather than editing managed state.

## Boundaries

- Require a current ARC root. Route absent, legacy, or invalid state to
  `research-init`.
- Do not create source, configuration, data, baseline, or figure scaffolds
  during ordinary onboarding. Run the legacy `scaffold` utility only when the
  user explicitly requests source scaffolding.
- Do not create a Direction, Experiment, Package, or Run.
- Never read `.research/interface` as authority or edit managed JSON, events,
  audit rows, HTML, JavaScript, or CSV.
- Treat repository contents as descriptive context, not Project intent.

## Human contract

- Communicate in plain natural language.
- Show the proposed Project once.
- Ask for one explicit decision: confirm, revise, or reject.
- Keep item ids, hashes, NoteRefs, actor flags, and CLI commands hidden unless
  the user requests audit details.
- A stale, ambiguous, or conflicting decision leaves the proposal pending.

One semantic Scope change gets one review and one authorization. Proposal
submission is non-authoritative and needs no separate user confirmation.

## Procedure

### 1. Detect state

```bash
python3 skills/research-onboard/scripts/onboard.py --workspace . detect
python3 skills/research-onboard/scripts/onboard.py --workspace . has-project-scope
```

If an active Project exists, stop onboarding. Route a vague next Direction to
`research-brainstorm` and clear Direction intent to `research-scope`.

### 2. Build context without inventing intent

For an existing workspace, inspect only the files returned by `detect` plus
the relevant project instructions. Record a compact digest of:

- datasets and baselines that actually exist;
- current source and configuration entry points;
- runnable train and evaluation commands;
- observed readings, clearly separated from plans.

Store the digest internally:

```bash
python3 skills/research-onboard/scripts/onboard.py --workspace . \
  write-prior-knowledge --content '<markdown>'
```

Preserve the returned NoteRef for the proposal, but do not show it by default.
For an empty workspace, use dialogue only and do not scaffold automatically.

### 3. Draft a minimal Project charter

The current Project contract requires:

- `goal`: the research problem and desired outcome, 3 to 100 words;
- `contributions`: intended research outcomes, 5 to 50 words per item;
- `out_of_scope`: semantic boundaries or decisions explicitly deferred to
  later Scope levels, 5 to 50 words per item.

Derive these fields from user dialogue. Repository layout, seeds, output paths,
checkpoint policy, dashboards, environments, and experiment tracking belong in
Prior Knowledge or later Direction, Experiment, and Package contracts.

Surface one material ambiguity in the review. Phrase the proposed resolution
inside the charter so the user's confirmation resolves the ambiguity and
ratifies the same snapshot. Preserve verbatim wording only when the user asks
for exact wording.

### 4. Validate and submit before review

Build the complete Project proposal:

```bash
python3 skills/research-onboard/scripts/onboard.py --workspace . \
  build-proposal \
  --node-id project/<slug> \
  --spec '<json>' \
  --source '<user dialogue and files read>' \
  --prior-knowledge '<note-ref-json>'
```

Submit the validated proposal immediately. It is pending and cannot change
Scope:

```bash
python3 skills/research-scope/scripts/triage.py --workspace . propose \
  --item '<proposal-json>' --receipt
```

Keep the returned id and hash internally. Show only:

```markdown
**Project review**
- Goal: <plain-language goal>
- Intended outcomes: <plain-language list>
- Boundaries: <plain-language list>
- Assumptions to confirm: <material assumptions, or none>
- Decision: reply CONFIRM/确认, describe revisions, or REJECT/拒绝
```

Do not repeat the full review in the next turn.

### 5. Apply one user decision

On an explicit confirmation, pass the hidden receipt through the combined
hash-bound gateway:

```bash
python3 skills/research-op/scripts/research_op.py \
  --workspace . --pkg _scope --op scope-accept \
  --from-triage <item-id> --proposal-hash <proposal-hash> \
  --actor-type user --actor-id <stable-user-id>
```

The gateway rechecks the pending snapshot, records the user acceptance, and
commits only that accepted snapshot. A retry is idempotent and does not require
another user decision.

For revision, validate and submit a replacement under the same item id, then
show the new charter once. For rejection, dispose the hidden item and hash as
`REJECTED`; committed Scope remains unchanged.

### 6. Verify and report

Read the committed Project through a bounded state query. Report only the
Project id, active status, and the next research decision. Show audit ids and
hashes only on request.

## Done condition

Onboarding is complete when the user has confirmed one visible Project
charter, the bound Project is active, and the pending proposal no longer needs
another human decision. Rejection also ends onboarding without changing
Project Scope.
