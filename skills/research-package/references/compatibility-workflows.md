# Pre-run Package revision and compatibility

Read this reference only for a bounded user-requested revision before the first
Run, imported state, or an explicit repair. These paths are not part of initial
Draft refinement or the normal execution and outcome loop.

## Reopen a pre-run Package

Use `reopen_as_draft.py` only when a material design problem is found before
any Run or result exists:

```bash
python3 skills/research-package/scripts/reopen_as_draft.py \
  --workspace <cwd> --package-id <package-id> \
  --reason "<why Scope needs another review>" --actor-id <user-id>
```

The composite event revokes execution authority and detaches bound Experiments
as stale. Any revised Draft needs a fresh Scope Bundle.

For a bounded revision, query the Package, bound Scope, Run and result state,
and exact replacement config in one batch. If the request already resolves the
material choice, it authorizes the reopen and revision but not the unseen
replacement Scope Bundle. Do not ask for a preliminary confirmation or repeat
the full two-phase Draft interview. Ask only when an unresolved choice would
materially change Scope.

Keep the existing Package, Direction, and Experiment ids. Revise only the
affected Research Intent, Experiment spec, Direction gate, and current
proposal. Preserve unrelated reviewed content and historical provenance.
Present one complete revised Scope Bundle, then commit it only after one
explicit user confirmation.

After the commit, verify the transaction in the Package, Direction, and
Experiment histories and verify that the lease contains exactly the reviewed
Experiment ids. Rebuild the Dashboard projection. Run full visual parity only
if Dashboard code or its rendering contract changed.

Do not add or rebuild Result schemas, Implementation Changes, metric contracts,
launch checks, or experiment infrastructure unless the user explicitly asks
for execution readiness or an existing active surface would otherwise remain
inconsistent with the revised intent.

If the latest reopen was a mistake and nothing changed, the user may restore
the exact previous Package and Experiment records:

```bash
python3 skills/research-package/scripts/reactivate_reopened.py \
  --workspace <cwd> --package-id <package-id> --actor-id <user-id>
```

This fails after any Draft, Scope, Experiment, Run, result, or blocker change.

## Correct a pre-run identity

Review, then commit, one exact title and id change with
`rename_package_identity.py`. The transaction updates Package identity and
bound Experiment paths together. It requires a user actor and rejects Packages
with Run or result evidence. Use `review --help` and `commit --help` for the
arguments.

## Activate imported Scope

`create_from_scope.py` supports older workspaces where Direction and
Experiments were already ratified separately. Run `--check --json` first. Every
selected Experiment must be active, confirmed against the current Direction,
and unbound. Activation preserves the accepted Experiment aggregate id and
four-field spec; it adds only Package-local execution metadata.

Pending proposals are not authority. Return to `research-scope` if imported
Scope is incomplete.

## Transfer a legacy Brainstorm

For a Package created before source-document transfer existed:

```bash
python3 skills/research-package/scripts/brainstorm_transfer.py \
  --workspace <cwd> --package-id <package-id> \
  --brainstorm-id <brainstorm-id> --actor-id <user-id>
```

The governed event must give the Package ownership of the same NoteRef before
removing the standalone legacy record. Do not emulate this with separate doc,
archive, and delete commands.

## Manual creation

`create_research_package.py` is restricted to imported state with no Draft. It
does not bypass Scope. Use its `--help` output for current arguments and validate
every bound Experiment against the accepted Direction before committing.

## Repair rule

Never repair Package authority by editing SQLite, JSONL, `current.json`,
generated pages, or run artifacts. If a compatibility command rejects, query
current state, preserve its rule and detail, and choose the matching governed
handoff.
