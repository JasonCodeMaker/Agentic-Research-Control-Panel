# Server registry schema — `outputs/_resources/servers.json`

One JSON array, order = registration order (used as the final ranking tie-break). Unknown
top-level fields are rejected (`RuleViolation`) — overflow knowledge goes in `notes`, and
anything that turns out to be decision-relevant gets promoted to a typed field.

| Field | Required | Type / values | Meaning |
| --- | --- | --- | --- |
| `name` | yes | token (`[A-Za-z0-9._-]`) | Unique id; upsert key. |
| `kind` | yes | `local` \| `ssh` \| `slurm` | Transport class; sets `start_latency` default (0/1/2). |
| `status` | no (`ACTIVE`) | `ACTIVE` \| `DISABLED` | `DISABLED` servers are never allocated. |
| `control` | no (`{path: direct}`) | `{path: direct\|tmux, tmux_session?, host?, ...}` | How the agent reaches it. `path=tmux` requires `tmux_session`. |
| `gpus` | no (`[]`) | `[{type, count, mem_gb?}]` | Declared GPU capacity blocks. `count >= 1`. |
| `slurm` | no | `{account, partitions: {type: {partition, qos}}, max_hours}` | Slurm submission knowledge; `max_hours` filters long requirements. |
| `env` | no | object | Workdir, conda env/prefix, etc. |
| `tags` | no (`[]`) | list of strings | Capabilities / data locality (e.g. `msrvtt-features`). A requirement's `tags` must all be present. |
| `skill` | no | string | The execution skill that owns running work there. |
| `start_latency` | no (by kind) | int >= 0 | Ranking class: 0 immediate, 1 attached/ssh, 2 queued, 3 needs provisioning. |
| `notes` | no | string | Free-text overflow only. |

## Allocation ledger — `outputs/_resources/allocations.jsonl`

Append-only; never edited. Occupancy = `allocate` lines without a matching `release`.

```json
{"op": "allocate", "alloc_id": "a-1f2e3d4c", "server": "bunya", "pkg": "<pkg>", "exp_id": "P2",
 "gpu_count": 2, "gpu_type": "h100", "gpu_ids": null, "reason": "sweep wave 2", "t": 1781234567.0}
{"op": "link", "alloc_id": "a-1f2e3d4c", "job_id": "9912345", "t": 1781234600.0}
{"op": "release", "alloc_id": "a-1f2e3d4c", "outcome": "COMPLETED", "t": 1781299999.0}
```

## Snapshots — `outputs/_resources/snapshots/<server>.json`

Latest availability evidence per server, written by `cli.py snapshot`. A GPU is `free` when
util <= 10% and used memory <= 10% of total. Snapshots older than 600 s are stale: the server
ranks as `unknown`, never as confirmed-free.
