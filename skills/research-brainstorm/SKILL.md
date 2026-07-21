---
name: research-brainstorm
description: "Use when the user has a vague research idea and needs to shape it into a typed Direction proposal before package creation."
argument-hint: "[--workspace <path>] [--research-root <path>]"
allowed-tools: Bash(python3 *), Read, Edit, Write, Grep, Glob, Agent
disable-model-invocation: false
---

# Research brainstorm

Use this skill before a Direction exists. A Brainstorm is a cheap, reversible
idea; it is not a committed Direction and cannot authorize an experiment.

The authority flow is:

```text
Brainstorm state
  -> typed Direction proposal
  -> human Triage disposition
  -> committed Direction
  -> governed Experiment.spec
  -> Package materialization
```

The Brainstorm CLI writes typed events through the research-op management
gateway. It does not write HTML or JavaScript. Human-readable cards and detail
pages appear only after the interface renderer rebuilds
`.research/interface/`.

## Inputs

Start with:

- the user's rough idea;
- the active Project goal and out-of-scope boundary;
- any factual sources needed to check prior work, baselines, or metrics;
- related Learnings and Rules returned by the state query.

Resolve all workspace data through `ResearchPaths`. `RESEARCH_ROOT` defaults to
`.research`; `--research-root` is the only path override.

## Check the Project boundary

```bash
python3 skills/research-brainstorm/scripts/brainstorm.py check-project \
  --workspace <workspace>
```

If `active_project_ids` is empty, stop and use `research-onboard` or
`research-scope`. A Direction must be a child of an accepted Project. Compare
every candidate with the returned Project goal and `out_of_scope` list.

Load relevant governed context separately:

```bash
python3 skills/research-op/scripts/research_op.py \
  show project --workspace <workspace>
```

Do not read `.research/interface/` as context.

## Shape and store ideas

Ask one useful question at a time. When several framings are plausible, present
their trade-offs and record distinct candidates separately.

```bash
python3 skills/research-brainstorm/scripts/brainstorm.py add \
  --workspace <workspace> \
  --title "Candidate-pool audit" \
  --idea "Measure first-stage visibility before changing the reranker" \
  --rough-metric "CanHit@100" \
  --lit-refs '["paper:example"]'
```

Other state operations:

```bash
python3 skills/research-brainstorm/scripts/brainstorm.py list \
  --workspace <workspace>

python3 skills/research-brainstorm/scripts/brainstorm.py revise \
  --workspace <workspace> --id <idea-id> \
  --patch '{"rough_metric":"CanHit@100 and R@10"}'

python3 skills/research-brainstorm/scripts/brainstorm.py remove \
  --workspace <workspace> --id <idea-id> \
  --reason "superseded by a more testable framing"
```

`remove` archives the aggregate; it does not erase history. The stored
`detailPath` is projection metadata, not a file written by this skill.

When a framing depends on a factual unknown, inspect reliable sources before
putting the claim into shared context. Do not invent novelty, baseline, or
state-of-the-art claims.

## Form a Direction

A conversion-ready Direction has exactly:

```json
{
  "hypothesis": "A testable statement",
  "metric": {"name": "primary metric", "direction": "higher"},
  "baselines": ["A concrete comparison"],
  "success_gate": "A measurable condition"
}
```

Check completeness:

```bash
python3 skills/research-brainstorm/scripts/brainstorm.py direction-ready \
  --spec '<direction-spec-json>'
```

Then build, submit, and display the hash-bound proposal:

```bash
PROPOSAL=$(python3 skills/research-brainstorm/scripts/brainstorm.py build-proposal \
  --node-id direction/<slug> \
  --parent-project-id <project-id> \
  --spec '<direction-spec-json>' \
  --source 'brainstorms:<idea-id>,<idea-id>' \
  --source-brainstorms '["<idea-id>","<idea-id>"]')

python3 skills/research-scope/scripts/triage.py propose \
  --workspace <workspace> --item "$PROPOSAL"

python3 skills/research-scope/scripts/triage.py pending \
  --workspace <workspace>
```

Stop at this boundary. The agent may prepare and explain a proposal, but only
the user's matching `ACCEPT <proposal-id> <proposal-hash>` can authorize its
disposition and subsequent Scope commit.

## Optional interface rebuild

After state has changed:

```bash
python3 skills/research-dashboard/scripts/ensure_dashboard.py build \
  --workspace <workspace>
```

This generates the existing brainstorm lane and detail-page layout under
`.research/interface/`. A failed or missing interface build does not invalidate
the Brainstorm event or proposal.

## Boundaries

- Do not create a Package directly from a Brainstorm.
- Do not commit Project or Direction Scope without accepted Triage.
- Do not create old Task records; validation work is an `Experiment.spec`.
- Do not store candidate files, ranking ledgers, or verdicts in ad hoc
  workspace directories. Durable judgments belong in Decision state with
  evidence.
- Do not edit state logs, `current.json`, generated JS, or generated HTML by
  hand.

## Done condition

The relevant Brainstorm records exist in state. If the user chose a direction,
a complete Direction proposal is pending with its proposal hash and
`source_brainstorms`; it is not yet treated as committed. The human interface
may be rebuilt independently without changing that authority.
