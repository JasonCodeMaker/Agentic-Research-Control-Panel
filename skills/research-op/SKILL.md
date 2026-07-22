---
name: research-op
description: "Use when a governed research-state query, package mutation, Scope commit, knowledge registration, run reconciliation, or self-evolve transition is required."
allowed-tools: Bash(python3 *), Read, Edit, Write, Grep, Glob
context: fork
---

# Research operation gateway

`research-op` is the only management-state command gateway. It validates a
command, appends one domain event, folds current state, and records the attempt
in `.research/audit/actions.jsonl`.

`BrainstormCreated` and `BrainstormRevised` govern the standalone idea stage.
After explicit user approval, `PackageDraftCreated` atomically consumes the
exact Brainstorm and creates the non-executable proposal Package.
`PackageActivated` can then finalize that exact Draft, accept one full Scope
proposal, create its Direction and Experiments, and bind them to the same
ACTIVE Package in one composite event. It must preserve the reviewed proposal
NoteRef and path.

`PackageMaterialized` remains the compatibility event for older flows that had
no Draft Package; it may also consume legacy standalone Brainstorms after their
exact NoteRefs transfer into Package docs. Repairing an older Package uses one
`PackageMutationApplied` event with the same ownership checks. Do not emulate
these transitions with direct state edits or separate archive/delete
operations.

`PackageReopenedAsDraft` is the guarded pre-launch inverse of activation. It is
one composite Package event that preserves the proposal document, revokes
execution authority, and detaches every bound Experiment as stale. It requires
an explicit user actor and is forbidden after any Run or result exists.

It does not write run telemetry. The experiment harness may write only inside
its assigned `.research/experiments/<package>/<experiment>/<run>/` directory.
After a successful management commit, the gateway rebuilds
`.research/interface/` from canonical state.

## Authority

```text
user or research skill
  -> research-op
  -> schema + policy + expected-version check
  -> .research/state/events.jsonl
  -> .research/state/current.json
  -> .research/audit/actions.jsonl
```

Rejected commands change no domain state, but they still receive an audit
outcome. Never work around a rejection by editing `events.jsonl`,
`current.json`, generated JS, or HTML.

`RESEARCH_ROOT` defaults to `.research`. Use `--research-root` for the only
supported override.

## Bounded queries

These commands return typed data with `source_seq` and `source_hash`:

```bash
python3 skills/research-op/scripts/research_op.py \
  show package <package-id> --workspace <workspace>

python3 skills/research-op/scripts/research_op.py \
  context <package-id> --workspace <workspace>

python3 skills/research-op/scripts/research_op.py \
  history package/<package-id> --workspace <workspace>

python3 skills/research-op/scripts/research_op.py \
  audit <command-id> --workspace <workspace>
```

Prefer `context` for agent work. Do not load the complete `current.json` or
read `.research/interface/` to infer package state.

For a Draft Package, `context` returns the exact hash-verified proposal
fragment, project boundary, and pending Scope binding with
`execution_authorized=false`. For an ACTIVE Package, pass `--phase` when the
caller must assert a specific workflow phase.

## Package mutations

The structured shape is:

```bash
python3 skills/research-op/scripts/research_op.py \
  --workspace <workspace> \
  --pkg <package-id> \
  --op <insert|update|delete|check> \
  --target <typed-target> \
  --payload '<json-object>' \
  --idempotency-key <stable-key> \
  --expected-version <aggregate-version>
```

Common targets include:

- `experiments-row`, which only binds an accepted Scope Experiment to a
  Package, and `experiments-status`, which changes execution status;
- `tracker-impl-review-row`, which also records a Change;
- `tracker-chosen-route`, which also records a Decision;
- `approval-ack-slot`, which records an immutable acknowledgement;
- `analysis-insight`, which records a Learning;
- `results-gate-row`, `result-block`, `methodsTried`, and package metadata;
- `doc-file`, whose content is stored as a content-addressed NoteRef;
- `rule`, with the governed Rule lifecycle.

Legality is evaluated from the full
`(lifecycle, phase, blocker, operation, target)` tuple. A blocker uses the
restricted blocked policy even when a phase remains present. Terminal
lifecycle records stay frozen except for explicitly allowed transitions.

Entering `READY_TO_LAUNCH` requires `review_change_id` for a committed Change
whose review has distinct `producer` and `judge` identities and
`result=SOUND`. The Package event records that Change event as its causation.

Before a success transition, record a verifier Decision over one finalized Run:

```bash
python3 skills/research-op/scripts/research_op.py \
  --workspace <workspace> --pkg <package-id> \
  --op update --target results-verdict \
  --payload '{
    "run_id":"<run-id>",
    "verdict":{"producer":"<producer>","judge":"<judge>","result":"SOUND"}
  }'
```

Before success, fail, or STOPPED, record a user acknowledgement:

```bash
python3 skills/research-op/scripts/research_op.py \
  --workspace <workspace> --pkg <package-id> \
  --op update --target approval-ack-slot \
  --actor-type user --actor-id <user-id> \
  --payload '{
    "ack_type":"TERMINAL_ACK",
    "to":"ACKNOWLEDGED",
    "target_status":"<terminal-status>"
  }'
```

The status command then references `terminal_decision_id`; success additionally
references `verifier_decision_id` and supplies `terminationMessage` plus
`adoptionPath`. A free-form `ack` string has no authority.

For natural-language requests, translate intent into this structured shape and
show the semantic change in plain language. Keep CLI, ids, hashes, and payloads
internal unless the user requests audit details. `--nl` deliberately does not
parse prose; it exits with a translation prompt.

Never use a Package mutation to create or revise `Experiment.spec`.
`experiments-row insert` accepts `scope_experiment_id`, `local_id`, and
execution metadata only. Spec revisions, archives, and supersession go through
a hash-bound Scope proposal.

## Scope and Triage

The formal hierarchy is:

```text
Project -> Direction -> Experiment.spec
```

Project, Direction, and Experiment changes retain their distinct gates. A
normal new Package presents Direction and all selected Experiments in one
`package_finalization` proposal. Its approval must use this atomic command:

```bash
python3 skills/research-op/scripts/research_op.py \
  --workspace <workspace> \
  --pkg <package-id> \
  --op package-finalize \
  --from-triage <proposal-id> \
  --proposal-hash <proposal-hash> \
  --actor-type user \
  --actor-id <stable-user-id>
```

One `PackageActivated` event records the exact Draft as `SCOPE_READY` in its
payload, accepts the proposal, commits the Direction and Experiments, and
leaves the same Package `ACTIVE / CONTEXT_LOADED`. The reducer tracks that one
event in every participant's history. A stale Draft, hash mismatch, partial
Scope collision, or non-user actor rejects the entire command before append.

For Project onboarding or an independent Scope revision that is not coupled
to Package activation, use one call that records the user decision and commits
the exact bound snapshot:

```bash
python3 skills/research-op/scripts/research_op.py \
  --workspace <workspace> \
  --pkg _scope \
  --op scope-accept \
  --from-triage <proposal-id> \
  --proposal-hash <proposal-hash> \
  --actor-type user \
  --actor-id <stable-user-id>
```

`scope-accept` preserves separate `ProposalAccepted` and semantic Scope events.
It rechecks the pending hash, user actor, accepted snapshot, causation, Scope
version, and idempotency. Retrying the same accepted proposal is safe and does
not require another user decision. It rejects `package_finalization` proposals
so the normal Package lifecycle cannot partially commit.

The lower-level compatibility path commits a proposal whose disposition was
already recorded:

```bash
python3 skills/research-op/scripts/research_op.py \
  --workspace <workspace> \
  --pkg _scope \
  --op scope-transition \
  --from-triage <proposal-id>
```

This command reloads the accepted proposal, recomputes its content hash, checks
the recorded `ProposalAccepted` event, and uses that event as causation.
Missing, rejected, stale, ambiguous, or hash-mismatched proposals fail closed.

The explicit payload form is reserved for separately governed callers:

```bash
python3 skills/research-op/scripts/research_op.py \
  --workspace <workspace> \
  --pkg _scope \
  --op scope-transition \
  --payload '{
    "id":"experiment/retrieval/p1",
    "level":"experiment",
    "parents":["direction/retrieval"],
    "version":1,
    "status":"ACTIVE",
    "spec":{
      "purpose":"Measure the frozen retrieval hypothesis under the declared protocol.",
      "config_ref":"configs/p1.yaml",
      "gate":"Recall@1 >= 48",
      "control_mode":"CHECKPOINTED"
    },
    "source":"accepted-proposal",
    "op":"create",
    "gate":"AGENT_DEFERRED_ACK"
  }'
```

Measured values and verdicts never belong in `Experiment.spec`.

## Knowledge registry

Paper, KnowledgeEdge, and KnowledgeGap records live in state:

```bash
python3 skills/research-op/scripts/research_op.py \
  --workspace <workspace> --pkg <package-id> \
  --op registry-add --target paper \
  --payload '{"id":"dpr2020","title":"Dense Passage Retrieval","url":"https://arxiv.org/abs/2004.04906"}'

python3 skills/research-op/scripts/research_op.py \
  --workspace <workspace> --pkg <package-id> \
  --op registry-add --target gap \
  --payload '{"id":"gap-zero-shot","summary":"No verified zero-shot comparison exists.","status":"open"}'

python3 skills/research-op/scripts/research_op.py \
  --workspace <workspace> --pkg <package-id> \
  --op registry-add --target edge \
  --payload '{"from":"paper:dpr2020","to":"gap:gap-zero-shot","type":"ADDRESSES_GAP","evidence":"evidence ref or note"}'
```

An edge is accepted only when both typed endpoints already exist. Context
queries read this state, never browser projection files.

## Rules and Learnings

Package Rules use `level=package, kind=binding`. Project Rules use
`level=project, kind=constraint` and require the governed human acknowledgement.
Universal rules are write-locked mirrors. The general Rule path cannot alter
`origin=selfevolve` records.

A Learning must contain verified evidence. Promoting it to a Rule requires an
admitted Decision over that same Learning. Retirement requires a lifecycle
Decision over the exact Rule version.

## Run reconciliation and result ingest

Use:

```bash
python3 skills/research-op/scripts/research_op.py \
  --workspace <workspace> --pkg <package-id> --op scan-events

python3 skills/research-op/scripts/research_op.py \
  --workspace <workspace> --pkg <package-id> \
  --event RUN_RESULT_FINALIZED --payload '{"run_id":"<run-id>"}'
```

Reconciliation can restore a missing `RunLaunched` callback before submitting
`RunTerminal`, but only from immutable `run.json` and terminal run-local
evidence. Result ingest verifies identity, status, EvidenceRef hashes, and
package policy before updating Package and Experiment summaries. Simple numeric
gates are checked mechanically at `RunResultFinalized`; compound or
natural-language gates are resolved by the governed verifier Decision without
rewriting `Experiment.spec.gate`.

Checkpoint, sentinel, phase-marker, and candidate-submission composite events
are observations, not scientific verdicts.

## Concurrency and retry

- Supply a stable idempotency key for retriable commands.
- Supply `--expected-version` when acting on a previously read aggregate.
- An identical idempotency replay returns the original event.
- Reusing a key with different content or submitting a stale version is a
  conflict, not a retry signal to bypass.
- State lock timeouts are bounded; retry only after re-querying current state.

## After a commit

Mutation responses report `interface_written`, `interface_root`, and the source
sequence used for the rebuild. The rebuild runs after the canonical event is
durable and after the state lock is released. If it fails, the command records
`PROJECTION_FAILED` in the audit log and reports `interface_error`; the accepted
event remains committed. Fix the projection error, then retry the same
idempotent command or run the dashboard build command.
