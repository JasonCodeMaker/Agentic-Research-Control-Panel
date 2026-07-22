# Direction to Experiment decomposition

Use this method when turning one ratified Direction into one or more governed
Experiment proposals. The goal is not to produce a conventional experiment
list. The goal is to partition the Direction into evidence contracts that can
be executed, interpreted, accepted, revised, or stopped without hidden scope
changes.

## Object boundaries

Keep the following boundaries explicit:

| Object | Meaning |
|---|---|
| Direction | The approved research question, comparison space, metric contract, and decision policy. |
| Experiment | The smallest evidence contract that can be governed and interpreted independently. |
| Package | A bounded working unit that groups accepted Experiments. |
| Run | One concrete execution attempt under one Experiment. |
| Arm | A baseline, treatment, ablation, or comparison condition inside an Experiment. |
| Observable | A metric, diagnostic, cost, artifact, or failure count recorded by an Experiment. |
| Task | Setup or implementation work needed to execute an Experiment. It is not a Scope node. |

An Experiment can be described during planning as:

```text
E = <decision, contrast, protocol, observables, admission rule, control mode>
```

This planning tuple is not an additional persisted schema. Translate its
meaning into the four governed fields: `purpose`, `config_ref`, `gate`, and
`control_mode`.

## Decomposition procedure

### 1. Freeze Direction invariants

Extract the approved hypothesis or research question, primary metric contract,
declared baselines, success or completion policy, resource constraints, and
non-negotiable controls. Do not strengthen them while planning Experiments.

In particular, a record-only Direction must remain record-only. Reproduction
agreement, positive improvement, confidence-interval sign, or baseline beating
cannot appear later as a hidden hard gate.

### 2. Build a decision ledger

List every decision the Direction is expected to support. For each decision,
record:

| Field | Question |
|---|---|
| Decision | What can a reviewer decide after seeing this evidence? |
| Contrast | Which arms or conditions answer that decision? |
| Protocol | Which dataset, split, retriever, corpus, budget, and evaluation contract must remain fixed? |
| Observables | Which metrics, diagnostics, costs, and artifacts must be recorded? |
| Admission | What evidence must exist before the result is reviewable? |
| Control | How much autonomy may execution have? |

If an item does not support a distinct decision, it probably belongs inside an
Experiment rather than becoming one.

### 3. Draft evidence contracts

Group ledger rows that share one decision and one evidence-admission rule.
Draft one candidate Experiment for each group. Do not create Scope proposals
yet.

For every candidate, state:

- the decision it supports;
- the arms or contrast it contains;
- the immutable configuration family named by `config_ref`;
- the observables and provenance required for interpretation;
- the completion or scientific decision rule expressed by `gate`;
- the control mode.

### 4. Classify non-Experiment items

Move each item to its correct owner:

- Seeds, retries, and repeated executions become Runs.
- Baselines, treatments, ablations, and prompt variants become arms when they
  share the same protocol and decision.
- Metrics and diagnostics become observables.
- Data download, conversion, environment setup, and checkpoint preparation
  become implementation tasks or Run prerequisites.
- Hyperparameter values become configuration entries. A sweep normally becomes
  multiple Runs unless it answers a separate governed decision.
- Dataset slices remain observables or arms unless they change the protocol or
  create an independently interpretable decision.

### 5. Apply the hard split test

Split two candidate evidence sets when any answer below is yes:

1. Do they support different reviewer decisions?
2. Do they require different dataset, split, retriever, corpus, budget, or
   configuration family?
3. Can one finish, fail, pause, or be revised while the other remains valid?
4. Do they use different evidence-admission or scientific decision rules?
5. Would their artifacts need different provenance or evidence homes?
6. Can one result be interpreted and reported without the other?

These are governance boundaries, not preferences about document organization.

### 6. Apply the merge test

Merge candidates only when all answers below are yes:

1. They support the same decision.
2. They use the same contrast and protocol family.
3. They use the same evidence schema and provenance requirements.
4. They have the same gate semantics and control mode.
5. They share one lifecycle and revision boundary.
6. Partial completion cannot be mistaken for completion of the combined claim.

Sharing a Direction, model, codebase, or final report is not enough to justify
a merge.

### 7. Separate the three kinds of stopping logic

Do not collapse these concepts into one performance threshold:

| Kind | Purpose | Scope treatment |
|---|---|---|
| Evidence admission | Determines whether the record is complete enough to review. | Always express in the Experiment gate. |
| Scientific decision rule | Determines whether evidence supports a stated claim. | Include only when the Direction explicitly requires it. |
| Operational stop | Limits time, cost, failures, or unsafe execution. | Keep in execution control unless it changes research intent. |

For record-only characterization, the gate should require configuration,
coverage, metrics, provenance, logs, and discrepancy notes. It should not
require agreement with a paper or improvement over a baseline.

### 8. Check dependencies

Execution order alone does not create a Scope dependency. Record a dependency
only when upstream evidence changes whether a downstream Experiment is
admissible or interpretable.

Examples:

- No dependency: reproduce a released checkpoint and independently run a new
  dataset baseline. The team may schedule them in either order.
- Real dependency: a calibration Experiment fixes a threshold that the next
  Experiment must use for its result to be defined.

### 9. Prove Direction coverage

Create a compact coverage matrix before submitting proposals:

| Direction obligation | Owning Experiment | Evidence produced | Gate type |
|---|---|---|---|

Every obligation must have one clear owner. Remove duplicate owners unless the
duplication is deliberate and explained. Record any uncovered obligation as a
scope gap rather than inventing an Experiment to make the table look complete.

### 10. Submit semantic Scope reviews

For each final candidate, create a complete Experiment node with exactly:

- `purpose`
- `config_ref`
- `gate`
- `control_mode`

Submit each proposal to Triage and show the Experiment map, coverage, and each
semantic Scope review. Do not auto-accept proposals. A package can be
materialized only after the required Experiments are individually ratified.

## Quality checks

Before submission, verify:

- The number of Experiments follows from evidence boundaries, not a template.
- Each Experiment supports one independently reviewable decision.
- No task, arm, metric, seed, or retry was promoted into Scope by accident.
- Each gate preserves the Direction's actual decision policy.
- No performance threshold was introduced into record-only work.
- Each `config_ref` names one immutable and auditable configuration family.
- A partial result cannot masquerade as completion of a broader claim.
- The coverage matrix has no unexplained gaps or duplicated ownership.
