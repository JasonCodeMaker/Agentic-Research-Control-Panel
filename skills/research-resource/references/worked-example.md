# Worked example — three predefined servers (Local + Bunya + Nectar)

The user predefines a local workstation, a Slurm HPC cluster reached through an existing tmux
login session, and a cloud VM. Adapt names/values to the actual project; the registry lives in
the managed project's `outputs/_resources/`, not in this toolbox repo.

## 1. Register

```bash
python3 lib/resource_alloc/cli.py register <<'EOF'
{"name": "local", "kind": "local",
 "gpus": [{"type": "a6000", "count": 2, "mem_gb": 48}],
 "tags": ["msrvtt-features", "internet"],
 "env": {"workdir": "/home/user/Project", "conda": "python3.13"}}
EOF

python3 lib/resource_alloc/cli.py register <<'EOF'
{"name": "bunya", "kind": "slurm",
 "control": {"path": "tmux", "tmux_session": "bunya"},
 "gpus": [{"type": "h100", "count": 3, "mem_gb": 80}, {"type": "a100", "count": 4, "mem_gb": 80}],
 "slurm": {"account": "a_eecs_ds",
           "partitions": {"h100": {"partition": "gpu_sxm", "qos": "sxm"}},
           "max_hours": 168},
 "env": {"workdir": "/scratch/user/<user>/Project"},
 "tags": ["msrvtt-features"],
 "skill": "bunya-slurm-ops",
 "notes": "Duo on new SSH connections - reuse the tmux session; idle GPUs via ~/idle_gpus.sh"}
EOF

python3 lib/resource_alloc/cli.py register <<'EOF'
{"name": "nectar", "kind": "ssh",
 "control": {"path": "direct", "host": "203.0.113.7", "user": "ubuntu"},
 "gpus": [{"type": "a100", "count": 1, "mem_gb": 40}],
 "tags": ["internet"],
 "notes": "ARDC Nectar VM - always-on, no queue"}
EOF
```

(`control.user` style extras live inside `control` — it is an open object once `path` is valid.)

## 2. Probe, recommend, allocate, launch, release

```bash
# local probe + a remote capture (taken via the bunya tmux pane, saved to a file)
python3 lib/resource_alloc/cli.py snapshot --server local --probe
python3 lib/resource_alloc/cli.py snapshot --server bunya --from-nvidia-smi /tmp/bunya-smi.txt

# 1×GPU eval that needs the MSRVTT features staged
python3 lib/resource_alloc/cli.py recommend --pkg 2026-06-12-demo --exp P1 \
  --gpu-count 1 --min-mem-gb 30 --tag msrvtt-features
# -> local confirmed-free first; bunya unknown/queued second; nectar blocked (missing tag)

python3 lib/resource_alloc/cli.py allocate --server local --pkg 2026-06-12-demo --exp P1 \
  --gpu-count 1 --min-mem-gb 30 --tag msrvtt-features --gpu-ids 1 --reason "eval, GPU1 idle"
# -> {"alloc_id": "a-..."}

CUDA_VISIBLE_DEVICES=1 python3 lib/exp_live/launch.py --pkg 2026-06-12-demo --exp P1 \
  --server local --alloc a-... --tmux-session demo-p1 -- bash scripts/run_eval.sh

# remote alternative: submit via the server's own skill, then bind the job id
python3 lib/resource_alloc/cli.py link --alloc a-... --job-id 9912345

# at verified completion (terminal status.json / sacct evidence)
python3 lib/resource_alloc/cli.py release --alloc a-... --outcome COMPLETED
python3 lib/resource_alloc/cli.py status   # leaks must be empty before session end
```
