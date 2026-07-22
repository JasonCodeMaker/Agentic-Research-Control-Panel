# Compatibility Scope and Triage

Read this only for an independent Scope revision, an imported workspace, or a
repair that cannot use the normal Project or Scope Bundle transaction.

The formal hierarchy remains:

```text
Project -> Direction -> Experiment
```

Proposal and Triage records are not committed intent. A user accepts one exact
proposal hash, then the gateway writes semantic Scope events bound to that
accepted proposal snapshot.

## Combined compatibility acceptance

```bash
python3 skills/research-op/scripts/research_op.py \
  --workspace <workspace> --pkg _scope --op scope-accept \
  --from-triage <proposal-id> \
  --proposal-hash <proposal-hash> \
  --actor-type user --actor-id <stable-user-id>
```

This rechecks the pending hash, user actor, accepted snapshot, causation,
version, and idempotency. A `package_finalization` proposal cannot use ordinary
`scope-accept`; normal Package finalization belongs to `commit-scope`.

## Already accepted proposals

For repair or a separately governed caller:

```bash
python3 skills/research-op/scripts/research_op.py \
  --workspace <workspace> --pkg _scope --op scope-transition \
  --from-triage <proposal-id>
```

The gateway reloads the accepted Proposal, recomputes its content hash, checks
the `ProposalAccepted` event, and uses it as causation. Missing, rejected,
stale, ambiguous, or hash-mismatched records fail closed.

The explicit payload form is reserved for separately governed structured
callers. It cannot substitute for or bypass the accepted snapshot. Measured
values, verdicts, and Run status never belong in `Experiment.spec`.

## Direction effects

A committed Direction revision may mark older bound Experiments stale. Reopen,
dial-revert, and other explicit effects remain bound to the accepted proposal.
Do not patch affected Experiment records separately or infer a new gate.
