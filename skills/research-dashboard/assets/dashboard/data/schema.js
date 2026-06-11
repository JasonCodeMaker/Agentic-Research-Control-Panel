// Single source of truth for the (category, status) state machine and the
// required-field rules each (category, status) cell must satisfy. The card
// renderer and the linter both read from this file. Add a new state by
// editing the `states` array and, if applicable, the `required` map.
//
// Two-tier casing convention: LANE = lowercase-kebab (in-progress / success /
// fail) — a coarse grouping facet coupled to HTML data-category attributes, CSS
// selectors, and URL slugs; STATE = SCREAMING_SNAKE (CONTEXT_LOADED, ADOPTED, …)
// — the fine-grained state-machine values. Keep this consistent with
// transitions.py STATES (which owns the legality matrix for the same set).

// Brainstorm is no longer a package category. Pre-package ideas live on the
// dashboard brainstorm lane (data/brainstorms.js, window.BRAINSTORMS) and are not
// in the (category, status) state machine; they become a package only at conversion.
window.RESEARCH_STATUS_SCHEMA = {
  "in-progress": {
    // STOPPED and DECISION_ADJUDICATION are terminal-within-lane / transient
    // active states named in WORKFLOW.md; they live here too so a stopped or
    // adjudicating package is expressible without a schema violation.
    // NEXT_ACTION_READY is transient (a routing handoff, never yielded at).
    states: [
      "CONTEXT_LOADED",
      "IMPLEMENTING",
      "IMPLEMENTATION_REVIEW",
      "READY_TO_LAUNCH",
      "EXPERIMENT_RUNNING",
      "LIVE_ANALYSIS",
      "RESULT_ANALYSIS",
      "NEXT_ACTION_READY",
      "BLOCKED",
      "DECISION_ADJUDICATION",
      "STOPPED",
    ],
    description: "Active packages. Must declare the active gate, primary metric vs gate, and next route at all times (STOPPED is terminal-within-lane and is exempt from that trio).",
    required: {
      // The _all trio applies to every in-progress state EXCEPT STOPPED, which
      // is terminal-within-lane and requires only a terminationMessage.
      _all: ["activeGate", "primaryMetricVsGate", "nextRoute"],
      _all_exempt: ["STOPPED"],
      EXPERIMENT_RUNNING: ["openRuns"],
      LIVE_ANALYSIS: ["openRuns", "lastAction"],
      BLOCKED: ["currentBlocker"],
      NEXT_ACTION_READY: ["lastDecision", "lastDecisionEvidencePath"],
      STOPPED: ["terminationMessage"],
    },
    forbidden: [],
  },
  success: {
    states: ["ADOPTED_UNCONFIRMED", "ADOPTED", "WIN_SUPERSEDED"],
    description: "Packages adopted into the active project. Must carry the structured methodsTried log, termination message, and adoption path.",
    required: {
      _all: ["terminationMessage", "methodsTried", "adoptionPath"],
      WIN_SUPERSEDED: ["supersededBy"],
    },
    forbidden: [],
  },
  fail: {
    states: ["ARCHIVED", "ARCHIVED_CONDITIONAL"],
    description: "Directions judged failed. Must carry the structured methodsTried log and a one-sentence termination message; conditionally-reopenable rows must declare the reopen trigger.",
    required: {
      _all: ["terminationMessage", "methodsTried"],
      ARCHIVED_CONDITIONAL: ["reopenTrigger"],
    },
    forbidden: [],
  },
};

// Allowed values for contributionSpineFlag. Used to group adopted wins and
// failed attempts on learnings.html, and to tag brainstorm directions.
window.RESEARCH_CONTRIBUTION_SPINE = [
  { id: "multi-view-encoder", label: "Multi-view video encoder" },
  { id: "progressive-cotraining", label: "Progressive end-to-end co-training" },
  { id: "contrastive-plus-main", label: "Contrastive pre-train + main stage" },
  { id: "stage1-handoff", label: "Stage-1 to Stage-2 handoff (inference selector)" },
  { id: "evaluation-contract", label: "Evaluation / measurement contract" },
  { id: "none", label: "Outside the contribution spine" },
];

// methodsTried row shape:
//   { method, hypothesis, gate, measured, verdict, evidencePath }
// verdict ∈ EXPERIMENT_VERDICT (the per-experiment gate outcome). Distinct from
// the cross-model trust verdict (verifier/__init__.py VERDICT_STATES).
window.EXPERIMENT_VERDICT = ["PASS", "FAIL", "INCONCLUSIVE", "DIAGNOSTIC"];
// Result-gate Validity column (orthogonal to the Verdict column above): has the
// result row been properly verified and artifact-backed?
window.RESULT_VALIDITY = ["VALID", "PARTIAL", "RESULT_FAIL", "UNMEASURED", "DIAGNOSTIC_ONLY", "MISSING"];
// Allowed nextRoute values (mirrors WORKFLOW.md NEXT_ROUTE; renderer reads this).
window.NEXT_ROUTE = ["RUN_NEXT_EXPERIMENT", "FIX_IMPLEMENTATION", "REVISE_PLAN", "TERMINATE", "ASK_USER"];
// Route semantics live with the enum (single owner); the dashboard renders this map.
window.NEXT_ROUTE_MEANING = {
  RUN_NEXT_EXPERIMENT: "Use when the active plan defines the next run.",
  FIX_IMPLEMENTATION: "Use for concrete code or artifact issues.",
  REVISE_PLAN: "Use when the executable plan changes.",
  TERMINATE: "Use when evidence says the direction should stop or archive.",
  ASK_USER: "Use when a user-level decision blocks progress.",
};
window.RESEARCH_METHODS_TRIED_FIELDS = [
  "method",
  "hypothesis",
  "gate",
  "measured",
  "verdict",
  "evidencePath",
];

// Compact mapping used by the renderer to color the status pill by family.
// Single-word family labels (work/launch/live/analyze/stop/win) are CSS token
// fragments and stay lowercase; multi-word entries use SCREAMING_SNAKE to match
// their corresponding status names.
window.RESEARCH_STATUS_FAMILY = {
  CONTEXT_LOADED: "work",
  IMPLEMENTING: "work",
  IMPLEMENTATION_REVIEW: "work",
  READY_TO_LAUNCH: "launch",
  EXPERIMENT_RUNNING: "live",
  LIVE_ANALYSIS: "live",
  RESULT_ANALYSIS: "analyze",
  NEXT_ACTION_READY: "analyze",
  BLOCKED: "stop",
  DECISION_ADJUDICATION: "analyze",
  STOPPED: "stop",
  ADOPTED_UNCONFIRMED: "WIN_UNCONFIRMED",
  ADOPTED: "win",
  WIN_SUPERSEDED: "WIN_SUPERSEDED",
  ARCHIVED: "stop",
  ARCHIVED_CONDITIONAL: "ARCHIVED_CONDITIONAL",
};
