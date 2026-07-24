# Resource state schema

The resource registry is the set of Resource aggregates in
`$RESEARCH_ROOT/state/events.jsonl`. `current.json` contains the folded projection; it is not a file
to edit.

## Resource aggregate

The aggregate id is the resource `name`.

| Field | Required | Type or values | Meaning |
| --- | --- | --- | --- |
| `name` | yes | token matching `[A-Za-z0-9._-]` | Unique resource id. |
| `kind` | yes | `local`, `ssh`, or `slurm` | Transport class. |
| `status` | no | `ACTIVE` or `DISABLED` | Disabled resources are not allocated. |
| `control` | no | object | Access path. `path=tmux` requires `tmux_session`. |
| `gpus` | no | list | Declared `{type, count, mem_gb?}` capacity blocks. |
| `slurm` | no | object | Account, partition mapping, QoS, and `max_hours`. |
| `env` | no | object | Working directory and environment details. |
| `tags` | no | list of strings | Capabilities and data locality. |
| `skill` | no | string | Skill that owns remote execution. |
| `presets` | no | list | Stable execution choices exposed during Package review. |
| `start_latency` | no | integer at least 0 | Ranking class. Defaults by `kind`. |
| `notes` | no | string | Non-ranking details. |

Unknown top-level fields are rejected. Registration emits `ResourceRegistered` and replaces the
current aggregate version while preserving event history.

Example logical record:

```json
{
  "name": "bunya",
  "kind": "slurm",
  "status": "ACTIVE",
  "control": {"path": "tmux", "tmux_session": "bunya"},
  "gpus": [
    {"type": "h100-sxm-80gb", "count": 4, "mem_gb": 80},
    {"type": "h100-pcie-80gb", "count": 3, "mem_gb": 80}
  ],
  "presets": [
    {"id": "bunya-sbatch", "label": "Bunya Sbatch", "mode": "sbatch"},
    {
      "id": "bunya-interactive",
      "label": "Bunya Interactive",
      "mode": "interactive"
    }
  ],
  "slurm": {
    "account": "a_eecs_ds",
    "max_hours": 168,
    "gpu_type_map": {
      "h100-sxm-80gb": {
        "partition": "gpu_sxm",
        "qos": "sxm",
        "gres_type": "h100",
        "max_per_node": 4
      },
      "h100-pcie-80gb": {
        "partition": "gpu_cuda",
        "qos": "gpu",
        "gres_type": "h100",
        "max_per_node": 3
      }
    }
  },
  "tags": ["dataset-local"],
  "skill": "bunya-slurm-ops"
}
```

Each preset contains exactly `id`, `label`, and `mode`. Modes are `direct`,
`sbatch`, or `interactive`; scheduler modes require a `slurm` Resource.
Preset ids are unique across the registry. `interactive` has one fixed launch
rule: reuse a valid existing allocation first, and request one only when none
exists.

Presets are stable Package-time choices. Queue state, idle GPUs, and the
allocation actually selected remain short-lived run-time facts.

## Package resource policy

Once the registry exposes active presets, `Package.resourcePolicy` binds each
reviewed Experiment to its allowed preset order and approved capacity fallback
chain:

```json
{
  "experiments": {
    "experiment/videos-r1/P0": {
      "preset_order": ["bunya-interactive"],
      "profiles": [
        {
          "id": "preferred",
          "label": "2 H100 SXM 80GB",
          "gpu_type": "h100-sxm-80gb",
          "gpu_count": 2,
          "min_mem_gb": 80,
          "system_mem_gb": 120,
          "min_hours": 24,
          "config_ref": "configs/resources/p0-h100-sxm2.env"
        }
      ]
    },
    "experiment/videos-r1/P1": {
      "preset_order": ["bunya-interactive", "bunya-sbatch"],
      "profiles": [
        {
          "id": "preferred",
          "label": "2 H100 SXM 80GB",
          "gpu_type": "h100-sxm-80gb",
          "gpu_count": 2,
          "min_mem_gb": 80,
          "system_mem_gb": 120,
          "min_hours": 24,
          "config_ref": "configs/resources/p1-h100-sxm2.env"
        },
        {
          "id": "fallback-h100-pcie",
          "label": "2 H100 PCIe 80GB",
          "gpu_type": "h100-pcie-80gb",
          "gpu_count": 2,
          "min_mem_gb": 80,
          "system_mem_gb": 120,
          "min_hours": 24,
          "config_ref": "configs/resources/p1-h100-pcie2.env"
        }
      ]
    }
  }
}
```

The first profile is preferred; later rows are the only authorized
downgrades. `min_mem_gb` is per GPU and `system_mem_gb` is host RAM. Every
profile carries its own immutable `config_ref`, so a one-GPU fallback cannot
silently reuse an incompatible two-GPU configuration.

At run time, first reuse a compatible open interactive allocation. If none
exists, request the preferred profile. A scheduler rejection must name the
live constraint before selection advances through the reviewed profile and
preset orders. P0 above therefore cannot fall back to batch, PCIe, A100, or a
local GPU; P1 may use only its declared PCIe and batch fallbacks.

The policy must cover exactly the Experiments in the Scope Bundle and reference
active registered presets. It is shown in the single Package review and copied
into the active Package. Legacy roots without presets may omit it. It does not
claim that any profile is currently available.

## ResourceAllocation aggregate

The allocation id is generated by `allocate`. Its lifecycle is:

```text
ResourceAllocationCreated
ResourceAllocationLinked
ResourceAllocationReleased
```

The created record has status `OPEN` and includes the canonical `package_id`,
the accepted Scope `experiment_id`, server, GPU requirement, reason, and
timestamp. A Package-local id may be accepted as CLI input, but it must be
resolved to the canonical Experiment id before the allocation event is
written. A link adds a `run_id` or `job_id`. Release adds the outcome and
changes status to `RELEASED`.

Open allocations are the occupancy authority. Recommendation subtracts them from declared capacity
under the state lock, so two concurrent allocations cannot reserve the same final unit.

Do not reconstruct occupancy from an interface table or a probe snapshot.

## Availability snapshot

Probe output is cached at:

```text
$XDG_RUNTIME_DIR/trustworthy-research/<workspace-hash>/resource_snapshots/<server>.json
```

`ResearchPaths` uses a per-user temporary fallback when `XDG_RUNTIME_DIR` is unset. The snapshot
contains a timestamp and normalized GPU observations. A GPU is marked free when utilization is at
most 10 percent and used memory is at most 10 percent of total memory.

Snapshots expire after 600 seconds. Missing or stale data projects availability as `unknown`. A
snapshot never creates, links, or releases an allocation.

## Interface projection

Any resource information under `$RESEARCH_ROOT/interface/` is generated for people. It may be
deleted and rebuilt from state. Agents must not read it as the registry or write it to record a
decision.
