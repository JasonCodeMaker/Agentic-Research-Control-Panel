# Research init setup contract

## Contents

1. State classification
2. Write ownership
3. User gates
4. Completion states
5. Recovery rules

## State classification

Classify ARC state independently from project content:

| ARC state | Meaning | Legal next operation |
| --- | --- | --- |
| `ABSENT` | No versioned or legacy managed data | `setup` |
| `LEGACY` | `research_html/` or `outputs/` exists without `VERSION` | inventory, backup confirmation, `migrate` |
| `MIGRATION_STAGED` | A migration manifest exists without finalized `VERSION` | resume `migrate` or inspect `check` blockers |
| `CURRENT` | `VERSION` matches this toolbox | `setup` reconciliation or `check` |
| `INVALID` | Unknown version or unexplained unversioned root | stop |

`EMPTY` and `EXISTING` describe project content. They do not authorize or
block `.research` initialization by themselves.

## Write ownership

`research-init` may create repository-backed skill symlinks and managed
protocol blocks. It delegates all other writes:

| Write | Owner |
| --- | --- |
| `.research` layout and `VERSION` | `lib.research_state.EventStore.initialize` |
| Legacy import and migration manifest | `lib.research_state.migration` |
| Interface projection | `lib.interface.build` |
| Dashboard process and runtime metadata | `lib.interface.serve` |
| Project proposal | `research-onboard` |
| Scope disposition and commit | `research-scope` and `research-op` |

Never call a lower-level writer to bypass the owner. Setup must not produce a
Project, Direction, Experiment, Package, Decision, Learning, Rule, or Run.

## User gates

Require explicit confirmation for:

- merging a managed protocol block into an existing unmarked file;
- using a `RESEARCH_ROOT` outside the target workspace;
- starting migration after the inventory and recoverable backup review;
- running without the default Dashboard Server.

Do not replace a real directory or file in an agent skill root. Missing,
broken, or wrong symlinks may be created or repaired because their source is
the verified toolbox skill tree.

## Completion states

`READY_NO_PROJECT` requires:

- valid current `VERSION`;
- state replay without projection drift;
- current managed protocol blocks;
- current skill links for the selected agent;
- generated interface;
- a healthy Dashboard Server unless the user explicitly selected
  `--no-serve`;
- no active Project.

`READY_WITH_PROJECT` has the same setup requirements and an active Project.
`REPAIR_REQUIRED` means setup is incomplete even when the state store itself is
healthy.

Always state whether the Server was started or reused. Report its URL and
health. For a remote workspace, report the returned SSH forwarding command.
Also report the returned stop command so a default-started Server has a clear
shutdown path.

## Recovery rules

- `inspect` is read-only and may be repeated without cleanup.
- `setup` is idempotent. Managed protocol blocks and correct symlinks remain
  unchanged on the second run.
- `migrate` is idempotent through the official migration manifest. Never
  invent migration completion from directory presence.
- Do not delete or archive legacy roots. The user may archive them only after
  `check` returns `ok: true` and they have inspected the new interface.
- An unhealthy Server does not corrupt state. Report `REPAIR_REQUIRED` and
  preserve the healthy state and interface for repair.
