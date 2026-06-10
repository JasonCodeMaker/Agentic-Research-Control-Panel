---
name: research-apply
description: "S4 self-learning APPLIER — human-gated. Use only when a human chooses to land a staged research-reflect proposal. Landing requires BOTH a distinct human action (a non-empty human token) AND a clearing jury verdict (sound); an ungated/auto invocation is refused. The proposer (research-reflect) is never the applier — this is the privilege split that stops the loop from rewriting away its own constraints. Edits the project rules only, never the universal protocols/skills/validators. Never invokes git. Trigger phrases: 'land the proposal', 'apply the staged rule', 'approve and apply' — any human-approval phrase paired with a pending proposal under outputs/.../pending/."
allowed-tools: Bash(python3 *), Read, Edit, Write, Grep, Glob
context: fork
disable-model-invocation: false
---

# research-apply (S4 · human apply-gate)

The privileged half of the self-learning loop, deliberately separate from the proposer (research-reflect).
Because producer != applier and the apply-gate is human, an ungated reflection loop can never silently
rewrite its own constraints.

## Resources

Pipeline root: `/home/uqzzha35/Project/Trustworthy-Research-Pipeline/Trustworthy-Research-Pipeline`

| Resource | Path |
|---|---|
| Bundled CLI | `<pipeline-root>/skills/research-apply/scripts/apply.py` |
| Verifier lib | `<pipeline-root>/lib/verifier/__init__.py` |
| Pending proposals | `outputs/<pkg>/pending/<pid>/` |
| Learned rules file | `outputs/_learned/rules.md` (or user-designated path) |

Import pattern for the verifier:
```python
import sys
sys.path.insert(0, "<pipeline-root>/lib")
import verifier
# verifier.ACQUIT_STATES == {"SOUND"}
# verifier.VERDICT_STATES == ("SOUND", "UNSOUND", "INCONCLUSIVE", "NEEDS_REVISION", "INSUFFICIENT_EVIDENCE", "ABSTAIN")
```

Full CLI invocation:
```bash
python3 skills/research-apply/scripts/apply.py \
  --proposal-dir outputs/<pkg>/pending/<pid>/ \
  --human-token "<verbatim approval text>" \
  --jury-verdict SOUND \
  --rules-path outputs/_learned/rules.md
```

## Procedure

**1. Confirm a distinct human approval turn exists.**

The human token is the literal text of the user's approval message in this conversation turn (e.g. "Approved — land it"). It must be non-empty. If the current turn contains no explicit approval, stop and ask. Do not infer or synthesize one.

**2. Locate the pending proposal.**

Find the proposal directory at `outputs/<pkg>/pending/<pid>/`. If none exists, report "no pending proposal found" and stop.

**3. Obtain and validate the jury verdict.**

Read the jury verdict produced by `lib/verifier` (from a prior `verifier.jury_request` →
`verifier.interpret` pass). It clears only if it is in `verifier.ACQUIT_STATES`:

```python
import sys; sys.path.insert(0, "<pipeline-root>/lib"); import verifier
verdict = "<one of verifier.VERDICT_STATES>"
clears = verdict in verifier.ACQUIT_STATES   # True only for "SOUND"
```

If `clears` is False the verdict is not clearing — stop here (see Error path). `apply.py` re-checks this
itself and raises `ValueError` on a non-clearing verdict, so nothing can land on a bad verdict.

**4. Run apply.py.**

```bash
python3 skills/research-apply/scripts/apply.py \
  --proposal-dir outputs/<pkg>/pending/<pid>/ \
  --human-token "<verbatim approval text>" \
  --jury-verdict SOUND \
  --rules-path outputs/_learned/rules.md
```

`apply.py` appends the proposal's `suggested_diff` as a bullet to `rules-path`, then marks the proposal `status=LANDED` and records `landed_by=<human token>` **inside `proposal.json`** (it does not write a separate status file or audit log).

Example for package `2026-06-03-self-learning`, proposal `p001`:
```bash
python3 skills/research-apply/scripts/apply.py \
  --proposal-dir outputs/2026-06-03-self-learning/pending/p001/ \
  --human-token "Approved — land it" \
  --jury-verdict SOUND \
  --rules-path outputs/_learned/rules.md
```

**5. Report the result.**

After a successful run, report:
- Updated `rules_path` (show the file path)
- Proposal `status=LANDED`
- `landed_by`: the human token text

## Output contract

| What | Where |
|---|---|
| Updated project rules | `outputs/_learned/rules.md` (or user-designated `--rules-path`) — one appended bullet |
| Proposal status + approver | `status=LANDED` and `landed_by=<human token>`, both written inside `outputs/<pkg>/pending/<pid>/proposal.json` |

No package surface HTML is written by this skill. If the landed rule should be reflected in a package surface, route that separately through research-op.

## Done condition

apply.py exits 0, the rules file gained the new bullet, and `proposal.json` now has `status=LANDED` + `landed_by`. Report the rules path and the proposal id to the user.

## Error path

| Condition | Exception | Action |
|---|---|---|
| Human token is absent or empty | `PermissionError` | Report "no human approval token — landing refused" and stop. Nothing writes. |
| Jury verdict not in `verifier.ACQUIT_STATES` | `ValueError` | Report "verdict `<value>` is not clearing (need 'SOUND') — landing refused" and stop. Nothing writes. |
| Proposal directory missing | `FileNotFoundError` | Report the missing path and stop. |

In all refusal cases, zero bytes are written to the rules file or the audit log. Ask the user to supply the missing gate (approval or a re-run of the jury) before retrying.
