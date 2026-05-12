// Single source of truth for the (category, status) state machine and the
// required-field rules each (category, status) cell must satisfy. The card
// renderer and the linter both read from this file. Add a new state by
// editing the `states` array and, if applicable, the `required` map.

window.RESEARCH_STATUS_SCHEMA = {
  brainstorm: {
    states: ["EXPLORING", "PILOT_READY", "PROMOTED", "ABANDONED"],
    description: "Idea or audit packages. Holds direction and which contribution spine the idea touches; no metric/gate fields.",
    required: {
      _all: ["direction", "contributionSpineFlag"],
      PILOT_READY: ["hypothesis", "noChangeBoundary"],
      PROMOTED: ["promotedTo"],
      ABANDONED: ["terminationMessage"],
    },
    forbidden: ["activeGate", "primaryMetricVsGate", "methodsTried", "openRuns"],
  },
  "in-progress": {
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
    ],
    description: "Active packages. Must declare the active gate, primary metric vs gate, and next route at all times.",
    required: {
      _all: ["activeGate", "primaryMetricVsGate", "nextRoute"],
      EXPERIMENT_RUNNING: ["openRuns"],
      LIVE_ANALYSIS: ["openRuns", "lastAction"],
      BLOCKED: ["currentBlocker"],
      NEXT_ACTION_READY: ["lastDecision", "lastDecisionEvidencePath"],
    },
    forbidden: [],
  },
  success: {
    states: ["ADOPTED_PENDING_ACK", "ADOPTED", "SUPERSEDED"],
    description: "Packages adopted into the active project. Must carry the structured methodsTried log, termination message, and adoption path.",
    required: {
      _all: ["terminationMessage", "methodsTried", "adoptionPath"],
      SUPERSEDED: ["supersededBy"],
    },
    forbidden: [],
  },
  fail: {
    states: ["ARCHIVED", "ARCHIVED_REOPENABLE"],
    description: "Directions judged failed. Must carry the structured methodsTried log and a one-sentence termination message; reopenable rows must declare the reopen trigger.",
    required: {
      _all: ["terminationMessage", "methodsTried"],
      ARCHIVED_REOPENABLE: ["reopenTrigger"],
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
// verdict ∈ { "pass", "fail", "inconclusive" }
window.RESEARCH_METHODS_TRIED_FIELDS = [
  "method",
  "hypothesis",
  "gate",
  "measured",
  "verdict",
  "evidencePath",
];

// Compact mapping used by the renderer to color the status pill by family.
window.RESEARCH_STATUS_FAMILY = {
  EXPLORING: "idea",
  PILOT_READY: "idea-ready",
  PROMOTED: "idea-done",
  ABANDONED: "idea-stop",
  CONTEXT_LOADED: "work",
  IMPLEMENTING: "work",
  IMPLEMENTATION_REVIEW: "work",
  READY_TO_LAUNCH: "launch",
  EXPERIMENT_RUNNING: "live",
  LIVE_ANALYSIS: "live",
  RESULT_ANALYSIS: "analyze",
  NEXT_ACTION_READY: "analyze",
  BLOCKED: "stop",
  ADOPTED_PENDING_ACK: "win-pending",
  ADOPTED: "win",
  SUPERSEDED: "win-old",
  ARCHIVED: "stop",
  ARCHIVED_REOPENABLE: "stop-reopen",
};
