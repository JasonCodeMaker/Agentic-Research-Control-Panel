# Package compatibility and repair

Read this reference only for imported state or an explicit repair. These paths
are not part of the normal Brainstorm, Draft, Scope Bundle, execution, and
outcome loop.

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
