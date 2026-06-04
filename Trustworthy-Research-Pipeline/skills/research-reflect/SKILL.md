---
name: research-reflect
description: "S2/S3 self-learning PROPOSER — read-only. Use to reflect over what the pipeline emits (the _actions.jsonl audit log, scope transitions) and surface recurring failure: doom-loops (N identical failures) and scope-thrash (a node revised over and over). Stages rule proposals under a pending/ area; it NEVER lands a change to the live corpus. Landing is a separate, human-gated skill (research-apply) — the proposer is never the applier. The learnable corpus is project-level rules only, not universal protocols/skills/validators. Never invokes git. Never lands a change — for landing a staged proposal, use research-apply."
allowed-tools: Bash(python3 *), Read, Grep, Glob
context: fork
disable-model-invocation: false
---

# research-reflect (S2/S3 · observe + reflect + propose)

The proposer is never the applier. This skill has no Edit/Write permission by design — it can only read
logs and run `reflect.py`. A finding becomes a staged proposal; landing that proposal into the live corpus
requires the separate, human-gated `research-apply`. This privilege split prevents the self-learning loop
from silently modifying the rules it is judged by.

## Resources

Pipeline root: `/home/uqzzha35/Project/Trustworthy-Research-Pipeline/Trustworthy-Research-Pipeline`

Bundled script:
```
python3 skills/research-reflect/scripts/reflect.py \
  [--actions outputs/<pkg>/_actions.jsonl] \
  [--transitions outputs/_scope/transitions.jsonl] \
  [--context-pack outputs/<pkg>/context_pack.json] \
  --pending-dir outputs/<pkg>/pending \
  [--threshold 3]
```

Only `--pending-dir` is required. Omitting `--actions` skips doom-loop detection; omitting
`--transitions` skips scope-thrash detection; omitting `--context-pack` skips cross-package dead-end
detection.

Inputs consumed (read-only):
- `outputs/<pkg>/_actions.jsonl` — per-package audit log written by every `research-op` call.
- `outputs/_scope/transitions.jsonl` — scope transition log written by `research-op --op scope-transition`.
- `outputs/<pkg>/context_pack.json` — the compiled Context Pack (`lib/context_pack/build.py`); its
  `facts.cross_package_failures` block carries the cross-package view a single audit log cannot see.

## Procedure

**1. Locate the input logs.**

Read the two log paths. Confirm `_actions.jsonl` exists for the target package; `transitions.jsonl` is
optional (scope-thrash detection is skipped if absent).

```bash
# confirm audit log exists
ls outputs/<pkg>/_actions.jsonl
# confirm transitions log if you expect scope-thrash checks
ls outputs/_scope/transitions.jsonl
```

**2. Run reflect.py.**

```bash
python3 skills/research-reflect/scripts/reflect.py \
  --actions outputs/<pkg>/_actions.jsonl \
  --transitions outputs/_scope/transitions.jsonl \
  --pending-dir outputs/<pkg>/pending \
  --threshold 3
```

The script runs three detectors internally:
- `detect_doom_loop(actions, threshold)` — flags N consecutive identical failures in the audit log.
- `detect_scope_thrash(transitions, threshold)` — flags a node revised >= threshold times.
- `detect_cross_package_dead_end(cross_failures, threshold)` — flags a method whose verdict is `fail`
  across >= threshold distinct packages (read from the Context Pack's `facts.cross_package_failures`).
  This widens self-learning from intra-package to cross-package: a method that is a dead-end
  project-wide should not be re-proposed without a materially different approach.

For each finding it calls `propose(pending_dir, finding, suggested_diff)`, which writes one proposal
file and returns a proposal id (`pid`).

Output is JSON on stdout (each `pid` is `p-` + the first 10 hex of a sha256 of `json.dumps(finding, sort_keys=True)`):
```json
{"findings": [...], "staged": ["p-a9cd94330b", "p-c3e81f7d22"]}
```

**3. Report staged proposals.**

For each `pid` in `staged`, report to the user:
- The pid and its path: `outputs/<pkg>/pending/<pid>/proposal.json`
- A one-line summary of the finding (doom-loop vs scope-thrash, which node/op, count).

Example:
> Staged 2 proposals:
> - `p-a9cd94330b` at `outputs/2026-06-03-grdr/pending/p-a9cd94330b/proposal.json` — doom-loop,
>   signature `op="update" target="result-gate" rule=None` (threshold 3 reached)
> - `p-c3e81f7d22` at `outputs/2026-06-03-grdr/pending/p-c3e81f7d22/proposal.json` — scope-thrash on
>   node `direction/grdr-v2` (4 revisions, threshold 3)

**4. Handle the no-findings case.**

If `staged` is empty, say explicitly: "no findings at threshold 3" (substituting the actual threshold).
Do not silently succeed — an empty result is information the user needs to see.

## Output contract

Each staged proposal is written to:
```
outputs/<pkg>/pending/<pid>/proposal.json
```
with shape (`finding` is the detector's dict, not a string):
```json
{
  "finding": {"kind": "doom-loop", "signature": ["<op>", "<target>", "<rule>"], "count": 3},
  "suggested_diff": "...",
  "status": "staged"
}
```
A scope-thrash finding instead looks like `{"kind": "scope-thrash", "node_id": "<id>", "count": 4}`.
A cross-package dead-end finding looks like `{"kind": "cross-package-dead-end", "method": "<name>", "packages": ["<id>", ...], "count": 3}`.

The learnable corpus is **project-level rules only** — never the universal protocols, skills, or
validators. A proposal's `suggested_diff` must target project-level config (e.g. a rule in the
project's `CLAUDE.md` preamble), not the pipeline's own SKILL.md or WORKFLOW.md bodies.

## Done condition

`reflect.py` exits 0 and all staged pids are reported to the user. The proposals sit in `pending/`
awaiting human review via `research-apply`.

## Error path

| Symptom | Meaning | Next step |
|---|---|---|
| `_actions.jsonl` not found | No `research-op` calls have been made for this package yet | Run at least one `research-op` op first, then re-invoke |
| `reflect.py` exits non-zero | Parse error or malformed log line | Read the stderr output; fix the offending log entry or report the bug |
| `staged` empty | No pattern reached threshold | Lower `--threshold` or wait for more pipeline activity; report "no findings" to user |
| Proposal `status` is not `staged` | A prior reflect run left a proposal in a different state | Check `pending/` for existing proposals; `research-apply` owns state transitions past `staged` |
