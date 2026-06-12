---
name: research-resource
description: "Use when registering the user's predefined compute servers (local workstation, HPC/Slurm clusters, cloud VMs) into the typed resource registry, probing GPU availability, choosing where to run an experiment, or releasing a finished allocation. Triggers: /research-resource, 'register a server', 'where should this run', 'allocate GPUs', 'free the allocation'."
---

# Research Resource

## Purpose

Turn server connection knowledge into structured memory and make experiment placement a typed,
auditable decision. The registry at `outputs/_resources/servers.json` is the single home for
*how to reach and use* each predefined server; the append-only ledger at
`outputs/_resources/allocations.jsonl` makes GPU occupancy a fold over recorded facts, not a
recollection. The objective is experiment-running efficiency: idle capacity gets used first, no
GPU is double-booked, and queue-vs-idle trade-offs are decided from evidence.

## Authority split (the trust boundary)

**The harness recommends, the agent decides, the user predefines.**

- The user predefines servers; the agent never invents one and never edits the registry without
  the user naming the server and confirming its fields.
- `lib/resource_alloc/` only measures, filters, ranks, and records. It never launches work and
  never drives a remote — execution on a remote server belongs to that server's own execution
  skill (the registry's `skill` field names it).
- Allocation facts (which server, which GPUs, since when) come from the ledger, never from
  conversational memory. Capacity claims without a ledger/snapshot citation are violations.
- Availability honesty: a stale or missing snapshot makes a server's availability `unknown` —
  ranked lower, never guessed (same discipline as `est_time=unknown`).

## The toolbox

```bash
python3 lib/resource_alloc/cli.py [--outputs-root outputs] <command>
  register                      # upsert one server (JSON on stdin or --file), reject-before-write
  list                          # print the registry
  snapshot --server X --probe   # local nvidia-smi probe
  snapshot --server X --from-nvidia-smi <file>   # normalize a remote capture
  recommend --pkg P --exp E [--gpu-count N --gpu-type T --min-mem-gb G --min-hours H --tag t]...
  allocate  --server X --pkg P --exp E [...] --reason "why"
  link      --alloc <alloc_id> [--run-id R] [--job-id J]
  release   --alloc <alloc_id> --outcome <RUN_STATUS>
  status                        # occupancy, snapshot ages, open allocations, leaks
```

Every write is reject-before-write: invalid servers, overbooked allocations, double releases, and
unknown ids fail with reasons before any file changes. The library writes only under
`outputs/_resources/` — package surfaces stay research-op-gated.

## Step 1 — Register (once per project, user-led)

For each server the user names, elicit and confirm the typed fields, distilling any existing prose
skill (e.g. a personal Bunya skill) into structure: `name`, `kind` (`local|ssh|slurm`),
`control` (`{path: direct|tmux, tmux_session?, host?}`), `gpus` (`[{type, count, mem_gb}]`),
`slurm` (`{account, partitions, max_hours}`), `env` (workdir, conda env), `tags` (data locality
and capabilities — e.g. which feature sets are staged there), `skill` (the execution skill that
owns running things there), `notes` (overflow only — anything decision-relevant gets a typed
field). See [references/registry-schema.md](references/registry-schema.md) and the three-server
worked example in [references/worked-example.md](references/worked-example.md).

## Step 2 — Probe before deciding

- Local: `snapshot --server local --probe`.
- Remote: capture `nvidia-smi --query-gpu=index,memory.used,memory.total,utilization.gpu
  --format=csv,noheader,nounits` through the server's own control path **under that server's
  skill rules** (serialized tmux panes, no new SSH storms), save the text, then
  `snapshot --server X --from-nvidia-smi <file>`.
- Snapshots expire (default 600 s). Probing is optional — an unprobed server is still allocatable,
  it just ranks as `unknown` behind confirmed-idle capacity.

## Step 3 — Allocate at launch

1. Build the requirement from the task spine / PLAN row (`gpu_count`, `gpu_type`, `min_mem_gb`,
   `min_hours` from the expected-duration class, data-locality `tags`).
2. `recommend` and read the ranked candidates + blocked reasons. Ranking: confirmed-free beats
   unknown, lower start-latency beats queued, best-fit memory keeps big GPUs free.
3. Decide per the task's autonomy dial: autonomous → take the top candidate; otherwise present
   the candidates (with their reasons) to the user.
4. `allocate --reason "<one line>"` and keep the returned `alloc_id`.
5. Launch:
   - **Local runs** — export the assigned GPUs via `CUDA_VISIBLE_DEVICES`, then launch through the
     exp-live wrapper with `--server <name> --alloc <alloc_id>`.
   - **Remote runs** — launch through the server's own execution skill, then bind the Slurm job or
     remote session with `link --alloc <alloc_id> --job-id <id>`.
6. Record the tracker resource-allocation row via research-op as today, citing the `alloc_id` and
   `outputs/_resources/allocations.jsonl` as evidence.

## Step 4 — Release at verified completion

When a run reaches a verified terminal state (exp-live terminal `status.json`, or verified remote
terminal evidence such as `sacct` for a Slurm job — never elapsed time or a quiet log):
`release --alloc <alloc_id> --outcome <RUN_STATUS>`. Before ending a session, run `status`:
a leaked allocation (open allocation whose linked run is already terminal) must be released or
explained — same shape as the open-runs stop gate.

## Failure routing

- `REJECTED: capacity ...` on allocate → re-run `recommend`; another open run holds those GPUs.
  Do not free capacity by editing files — release the finishing allocation first.
- Registry drift (server changed GPUs, new partition policy) → re-`register` the server with the
  user; the upsert replaces its entry and the change is visible in file history.
- `status` shows a stale snapshot for a server you are about to use → re-probe before relying on
  confirmed-free ranking.
