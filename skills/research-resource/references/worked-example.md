# Worked example with local, Bunya, and Nectar

The user has defined a local workstation, a Slurm cluster reached through an existing tmux gateway,
and a cloud VM.

```bash
export RESEARCH_ROOT="${RESEARCH_ROOT:-.research}"
```

## Register

```bash
python3 lib/resource_alloc/cli.py --research-root "$RESEARCH_ROOT" register <<'EOF'
{"name":"local","kind":"local",
 "gpus":[{"type":"a6000","count":2,"mem_gb":48}],
 "tags":["msrvtt-features","internet"],
 "env":{"workdir":"/home/user/Project","conda":"python3.13"}}
EOF

python3 lib/resource_alloc/cli.py --research-root "$RESEARCH_ROOT" register <<'EOF'
{"name":"bunya","kind":"slurm",
 "control":{"path":"tmux","tmux_session":"bunya"},
 "gpus":[{"type":"h100","count":3,"mem_gb":80},
         {"type":"a100","count":4,"mem_gb":80}],
 "slurm":{"account":"a_eecs_ds",
          "partitions":{"h100":{"partition":"gpu_sxm","qos":"sxm"}},
          "max_hours":168},
 "env":{"workdir":"/scratch/user/<user>/Project"},
 "tags":["msrvtt-features"],
 "skill":"bunya-slurm-ops",
 "notes":"Reuse the existing tmux gateway; probe with bash ~/idle_gpus.sh."}
EOF

python3 lib/resource_alloc/cli.py --research-root "$RESEARCH_ROOT" register <<'EOF'
{"name":"nectar","kind":"ssh",
 "control":{"path":"direct","host":"203.0.113.7","user":"ubuntu"},
 "gpus":[{"type":"a100","count":1,"mem_gb":40}],
 "tags":["internet"]}
EOF
```

These commands commit Resource aggregates. They do not create a separate registry file.

## Probe and recommend

Probe the local resource:

```bash
python3 lib/resource_alloc/cli.py --research-root "$RESEARCH_ROOT" \
  snapshot --server local --probe
```

Collect Bunya's GPU output through its existing tmux gateway, save it as `/tmp/bunya-smi.txt`, then
normalize it:

```bash
python3 lib/resource_alloc/cli.py --research-root "$RESEARCH_ROOT" \
  snapshot --server bunya --from-nvidia-smi /tmp/bunya-smi.txt
```

The snapshot is a short-lived XDG runtime projection. It is not allocation state.

Recommend a single-GPU evaluation that needs local MSRVTT features:

```bash
python3 lib/resource_alloc/cli.py --research-root "$RESEARCH_ROOT" \
  recommend --pkg 2026-06-12-demo --exp P1 \
  --gpu-count 1 --min-mem-gb 30 --tag msrvtt-features
```

The result ranks confirmed free capacity first. Nectar is blocked because it lacks the required tag.

## Allocate and launch

```bash
python3 lib/resource_alloc/cli.py --research-root "$RESEARCH_ROOT" \
  allocate --server local --pkg 2026-06-12-demo --exp P1 \
  --gpu-count 1 --min-mem-gb 30 --tag msrvtt-features \
  --gpu-ids 1 --reason "evaluation on idle GPU 1"
```

Use the returned allocation id:

```bash
CUDA_VISIBLE_DEVICES=1 python3 -m lib.experiments.launch \
  --workspace . \
  --research-root "$RESEARCH_ROOT" \
  --pkg 2026-06-12-demo \
  --exp P1 \
  --server local \
  --alloc <allocation-id> \
  --tmux-session demo-p1 \
  -- bash scripts/run_eval.sh
```

The Run lives below:

```text
$RESEARCH_ROOT/experiments/2026-06-12-demo/P1/<run-id>/
```

For a remote alternative, submit through the registered execution skill and bind the scheduler id:

```bash
python3 lib/resource_alloc/cli.py --research-root "$RESEARCH_ROOT" \
  link --alloc <allocation-id> --job-id 9912345
```

## Release

After verified terminal evidence:

```bash
python3 lib/resource_alloc/cli.py --research-root "$RESEARCH_ROOT" \
  release --alloc <allocation-id> --outcome COMPLETED

python3 lib/resource_alloc/cli.py --research-root "$RESEARCH_ROOT" status
```

`status` should report no leaked allocation for the completed Run.
