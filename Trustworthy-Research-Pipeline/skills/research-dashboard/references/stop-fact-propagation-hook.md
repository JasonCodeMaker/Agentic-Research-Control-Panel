# Stop-hook: auto-apply event manifests at turn end

A Claude Code `Stop` hook that renders/checks the Scope SSOT projection and runs `propagate_apply.py --auto-derive --write` on every Stop, so the dashboard surfaces (`scope-projection.json/js`, `research-packages.js`, `results.html`, `tracker.html`) stay in sync with the manifests landed during the turn — **without prompting the model**.

This is the recommended wiring for any project that uses the `research-dashboard` scaffold and writes event manifests (from launchers, eval drivers, or hand-edited JSON). It is not installed by `ensure_dashboard.py` because it belongs to the project's `.claude/` settings, not the dashboard itself.

## Pre-conditions

- `<root>/scripts/propagate_apply.py` exists (installed by `ensure_dashboard.py`).
- `<root>/scripts/learnings_lint.py` exists.
- `<root>/scripts/render_scope_projection.py` exists (installed by `ensure_dashboard.py`).
- `.claude/settings.json` declares the hook (see "Settings entry" below).
- `jq` is on PATH (used to build the hook's JSON output).

## Files

### `.claude/settings.json`

Add `Stop` (and a `PostToolUse` companion that tracks touched files) to the hooks block. Project-scoped path uses `$CLAUDE_PROJECT_DIR`.

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          { "type": "command", "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/log_touched_file.sh", "timeout": 5 }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/stop_fact_propagation.sh",
            "timeout": 120,
            "statusMessage": "Checking Fact Propagation Contract..."
          }
        ]
      }
    ]
  }
}
```

### `.claude/hooks/log_touched_file.sh`

```bash
#!/usr/bin/env bash
# PostToolUse hook: append edited file paths to a per-session log so the Stop
# hook can derive which research packages were touched in this turn.
INPUT=$(cat)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // "unknown"')
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_response.filePath // empty')
[ -n "$FILE" ] && echo "$FILE" >> "/tmp/claude-touched-${SESSION_ID}.log"
exit 0
```

### `.claude/hooks/stop_fact_propagation.sh`

```bash
#!/usr/bin/env bash
# Stop hook: at every Stop,
#   1) render/check Scope SSOT projection when var/research/_scope changed
#   2) for each touched research package, run its propagate_facts.py (reporter)
#   3) run propagate_apply.py --auto-derive --write (executor) globally
#   4) run learnings_lint.py all (validator)
# Blocks the Stop iff a touched package has un-propagated artifacts. Lint and
# apply errors surface as informational/blocking context per their severity.

INPUT=$(cat)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // "unknown"')
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TOUCH_LOG="/tmp/claude-touched-${SESSION_ID}.log"

if [ ! -f "$TOUCH_LOG" ]; then
    exit 0
fi

if ! grep -qE 'research_html/packages/|research_html/data/research-packages\.js|var/research/' "$TOUCH_LOG"; then
    rm -f "$TOUCH_LOG"
    exit 0
fi

PKG_RE='[0-9]{4}-[0-9]{2}-[0-9]{2}-[A-Za-z0-9_-]+'
PKGS_FROM_HTML=$(grep -oE "research_html/packages/${PKG_RE}" "$TOUCH_LOG" 2>/dev/null \
    | sed 's#research_html/packages/##' | sort -u)
PKGS_FROM_VAR=$(grep -oE "var/research/${PKG_RE}" "$TOUCH_LOG" 2>/dev/null \
    | sed 's#var/research/##' | sort -u)
PACKAGES=$(printf "%s\n%s\n" "$PKGS_FROM_HTML" "$PKGS_FROM_VAR" | sort -u | grep -v '^$')

PROP_REPORT=""
LINT_REPORT=""
APPLY_REPORT=""
SCOPE_REPORT=""
NL=$'\n'

# Scope projection: render the folded SSOT into dashboard data, then check the
# rendered file against the transition log. The render step also writes the
# companion JS file consumed by index.html.
if grep -qE 'var/research/_scope/|research_html/data/scope-projection\.json|research_html/data/scope-projection\.js' "$TOUCH_LOG"; then
    SCOPE_SCRIPT="$REPO_ROOT/research_html/scripts/render_scope_projection.py"
    SCOPE_LOG="$REPO_ROOT/var/research/_scope/transitions.jsonl"
    SCOPE_JSON="$REPO_ROOT/research_html/data/scope-projection.json"
    if [ -f "$SCOPE_SCRIPT" ] && [ -f "$SCOPE_LOG" ]; then
        SCOPE_OUT=$(cd "$REPO_ROOT" && python research_html/scripts/render_scope_projection.py render --transitions var/research/_scope/transitions.jsonl --projection research_html/data/scope-projection.json 2>&1 && python research_html/scripts/render_scope_projection.py check --transitions var/research/_scope/transitions.jsonl --projection research_html/data/scope-projection.json 2>&1)
        SCOPE_STATUS=$?
        if [ $SCOPE_STATUS -ne 0 ]; then
            SCOPE_REPORT="[render_scope_projection: exit ${SCOPE_STATUS}]${NL}$(echo "$SCOPE_OUT" | tail -25)${NL}"
        fi
    fi
fi

# Per-package reporter (optional legacy path)
for pkg in $PACKAGES; do
    SCRIPT="$REPO_ROOT/research_html/packages/$pkg/scripts/propagate_facts.py"
    if [ -f "$SCRIPT" ]; then
        OUT=$(cd "$REPO_ROOT" && python "$SCRIPT" 2>&1)
        if echo "$OUT" | grep -qiE 'unpropagated|new artifacts|locked fact'; then
            PROP_REPORT="${PROP_REPORT}[propagate_facts: ${pkg}]${NL}$(echo "$OUT" | head -30)${NL}${NL}"
        fi
    fi
done

# Global executor: apply unapplied manifests across all packages, derive
# narrative drift, apply newly-derived state manifests.
APPLY_SCRIPT="$REPO_ROOT/research_html/scripts/propagate_apply.py"
if [ -f "$APPLY_SCRIPT" ]; then
    APPLY_OUT=$(cd "$REPO_ROOT" && python research_html/scripts/propagate_apply.py --auto-derive --write 2>&1)
    APPLY_STATUS=$?
    if [ $APPLY_STATUS -ne 0 ]; then
        APPLY_REPORT="[propagate_apply: exit ${APPLY_STATUS}]${NL}$(echo "$APPLY_OUT" | tail -25)${NL}"
    fi
fi

# Validator
LINT_SCRIPT="$REPO_ROOT/research_html/scripts/learnings_lint.py"
if [ -f "$LINT_SCRIPT" ]; then
    LINT_OUT=$(cd "$REPO_ROOT" && python research_html/scripts/learnings_lint.py all 2>&1)
    LINT_STATUS=$?
    if [ $LINT_STATUS -ne 0 ]; then
        LINT_REPORT="[learnings_lint: exit ${LINT_STATUS}]${NL}$(echo "$LINT_OUT" | tail -25)${NL}"
    fi
fi

rm -f "$TOUCH_LOG"

if [ -z "$PROP_REPORT" ] && [ -z "$LINT_REPORT" ] && [ -z "$APPLY_REPORT" ] && [ -z "$SCOPE_REPORT" ]; then
    exit 0
fi

# Block the Stop when there are actionable unpropagated artifacts OR an apply
# failure. Lint state may be pre-existing, so it's informational only when
# alone.
if [ -n "$PROP_REPORT" ] || [ -n "$APPLY_REPORT" ] || [ -n "$SCOPE_REPORT" ]; then
    REASON="Fact Propagation Stop hook: address unpropagated artifacts before ending the turn.${NL}${NL}${PROP_REPORT}"
    if [ -n "$SCOPE_REPORT" ]; then
        REASON="${REASON}${NL}--- scope projection errors ---${NL}${SCOPE_REPORT}"
    fi
    if [ -n "$APPLY_REPORT" ]; then
        REASON="${REASON}${NL}--- propagate_apply errors ---${NL}${APPLY_REPORT}"
    fi
    if [ -n "$LINT_REPORT" ]; then
        REASON="${REASON}${NL}--- learnings_lint (informational) ---${NL}${LINT_REPORT}"
    fi
    jq -n --arg reason "$REASON" '{
        "decision": "block",
        "reason": $reason,
        "systemMessage": "Fact Propagation Stop hook: unpropagated artifacts detected for a touched package."
    }'
else
    # Lint-only — surface as informational, do not block.
    REASON="learnings_lint reported issues (informational, not blocking).${NL}${NL}${LINT_REPORT}"
    jq -n --arg reason "$REASON" '{
        "systemMessage": $reason
    }'
fi
exit 0
```

### Permissions

Mark both scripts executable: `chmod +x .claude/hooks/*.sh`.

## Schema notes

The Stop hook's JSON output must conform to Claude Code's hook schema:

- top-level allowed keys: `continue`, `suppressOutput`, `stopReason`, `decision`, `reason`, `systemMessage`, `terminalSequence`, `permissionDecision`
- `hookSpecificOutput.hookEventName` is **only** valid for `PreToolUse` / `UserPromptSubmit` / `PostToolUse` / `PostToolBatch` — never for `Stop`. Adding it to a `Stop` payload triggers an `Invalid input` validation error.

The recipe above uses only the allowed top-level keys.

## What this gives you

- Every event manifest emitted by a launcher (or hand-written by the user) is auto-applied to the three dashboard surfaces at turn end. No prompt, no model tokens.
- Scope transition commits automatically refresh `research_html/data/scope-projection.json` and its JS companion used by the dashboard homepage.
- `--auto-derive` scans every package and fills **blank** `currentBlocker` / `nextRoute` fields based on `experiments[].status`. Non-blank fields are treated as human-curated and never overwritten passively.
- Lint runs after the apply, so any schema violation introduced by an event manifest is caught in the same turn it lands.
