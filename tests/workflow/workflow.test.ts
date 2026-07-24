import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  evaluateWorkflow,
  isLegalTransition,
  workflowSchema,
} from "../../workflow.ts";

const baseSnapshot = {
  pkgId: "2026-06-11-demo",
  packageStatus: "EXPERIMENT_RUNNING",
  nextRoute: "RUN_NEXT_EXPERIMENT",
  now: "2026-06-11T00:00:00.000Z",
  scanEvents: [],
  experiments: [
    { expId: "P1", status: "RUNNING" },
    { expId: "P2", status: "QUEUED" },
  ],
};

test("keeps a Draft Package in governed refinement instead of execution", () => {
  const ticket = evaluateWorkflow({
    pkgId: "draft-package",
    packageLifecycle: "DRAFT",
    packagePhase: null,
    packageBlocker: null,
    experiments: [],
    openRuns: [],
  });

  assert.equal(ticket.packageLifecycle, "DRAFT");
  assert.equal(ticket.packagePhase, null);
  assert.equal(ticket.workflowState, "DRAFT");
  assert.equal(ticket.route, "ASK_USER");
  assert.equal(ticket.nextAction.kind, "ASK_USER");
  assert.match(ticket.nextAction.reason || "", /atomically finalized/);
});

test("tracks a long wrapper run with adaptive next check and stop-gate reentry proof", () => {
  const ticket = evaluateWorkflow({
    ...baseSnapshot,
    openRuns: [
      {
        runId: "P1-r1",
        expId: "P1",
        status: "RUNNING",
        health: "OK",
        runtimeRoot: "outputs/2026-06-11-demo/runs/P1-r1",
        progress: "step 1000/100000",
        latestMetrics: "loss=0.42",
        etaSeconds: 8 * 60 * 60,
        resource: "gpu0 71%",
        lastOutputAt: "2026-06-10T23:59:30.000Z",
        heartbeatTimeoutSeconds: 600,
      },
    ],
    armedReentries: {
      "P1-r1": "2026-06-11T00:55:00.000Z",
    },
  });

  assert.equal(ticket.workflowState, "LIVE_ANALYSIS");
  assert.equal(ticket.route, "RUN_NEXT_EXPERIMENT");
  assert.equal(ticket.perRun.length, 1);
  assert.equal(ticket.perRun[0].liveAction, "CONTINUE_RUN");
  assert.equal(ticket.perRun[0].nextCheck, "2026-06-11T01:00:00.000Z");
  assert.deepEqual(ticket.requiredMutations.map((m) => m.target).slice(0, 3), [
    "status",
    "openRuns",
    "lastAction",
  ]);
  assert.deepEqual(ticket.requiredMutations[0].payload, {
    to: "LIVE_ANALYSIS",
  });
  assert.deepEqual(ticket.perRun[0].requiredMutations, []);
  assert.deepEqual(ticket.stopGate.ok, true);
  assert.equal(ticket.stopGate.openRuns[0].reentryArmed, true);
});

test("records the launch phase before entering live analysis", () => {
  const ticket = evaluateWorkflow({
    ...baseSnapshot,
    packageStatus: "READY_TO_LAUNCH",
    openRuns: [
      {
        runId: "P1-r1",
        expId: "P1",
        status: "RUNNING",
        health: "OK",
        runtimeRoot: "outputs/2026-06-11-demo/runs/P1-r1",
      },
    ],
    armedReentries: {
      "P1-r1": "2026-06-11T00:05:00.000Z",
    },
  });

  assert.equal(ticket.workflowState, "EXPERIMENT_RUNNING");
  assert.deepEqual(ticket.requiredMutations[0], {
    op: "update",
    target: "status",
    payload: { to: "EXPERIMENT_RUNNING" },
  });
});

test("blocks stop gate when an open run lacks reentry or scan-events has pending facts", () => {
  const ticket = evaluateWorkflow({
    ...baseSnapshot,
    scanEvents: [{ event: "CHECKPOINT_SAVED", artifact: "outputs/demo/best.pt" }],
    openRuns: [
      {
        runId: "P1-r1",
        expId: "P1",
        status: "RUNNING",
        health: "OK",
        runtimeRoot: "outputs/2026-06-11-demo/runs/P1-r1",
        heartbeatTimeoutSeconds: 600,
      },
    ],
    armedReentries: {},
  });

  assert.equal(ticket.stopGate.ok, false);
  assert.match(ticket.stopGate.blockers.join("\n"), /scan-events has 1 pending event/);
  assert.match(ticket.stopGate.blockers.join("\n"), /P1-r1 has no armed re-entry/);
});

test("surfaces dashboard server repair without blocking live monitoring", () => {
  const ticket = evaluateWorkflow({
    ...baseSnapshot,
    dashboardServer: {
      ok: false,
      repair_required: true,
      error: "port unavailable",
    },
    openRuns: [
      {
        runId: "P1-r1",
        expId: "P1",
        status: "RUNNING",
        health: "OK",
        runtimeRoot: "outputs/2026-06-11-demo/runs/P1-r1",
        heartbeatTimeoutSeconds: 600,
      },
    ],
    armedReentries: {
      "P1-r1": "2026-06-11T00:10:00.000Z",
    },
  });

  assert.equal(ticket.workflowState, "LIVE_ANALYSIS");
  assert.equal(ticket.nextAction.kind, "MONITOR_RUNS");
  assert.equal(ticket.stopGate.ok, true);
  assert.equal(ticket.dashboardServer.requiredAction, "ENSURE_DASHBOARD_SERVER");
  assert.match(ticket.dashboardServer.warning || "", /port unavailable/);
});

test("keeps monitoring other experiments while routing terminal runs to result evidence", () => {
  const ticket = evaluateWorkflow({
    ...baseSnapshot,
    openRuns: [
      {
        runId: "P1-r1",
        expId: "P1",
        status: "COMPLETED",
        health: "OK",
        runtimeRoot: "outputs/2026-06-11-demo/runs/P1-r1",
        exitCode: 0,
        endedAt: "2026-06-11T00:00:00.000Z",
      },
      {
        runId: "P2-r1",
        expId: "P2",
        status: "RUNNING",
        health: "WARN",
        runtimeRoot: "outputs/2026-06-11-demo/runs/P2-r1",
        progress: "epoch 2/20",
        heartbeatTimeoutSeconds: 600,
      },
    ],
    armedReentries: {
      "P2-r1": "2026-06-11T00:05:00.000Z",
    },
  });

  assert.equal(ticket.workflowState, "LIVE_ANALYSIS");
  assert.equal(ticket.route, "RUN_NEXT_EXPERIMENT");
  assert.equal(ticket.perRun.find((r) => r.runId === "P1-r1")?.liveAction, "CONTINUE_RUN");
  assert.deepEqual(
    ticket.perRun.find((r) => r.runId === "P1-r1")?.requiredMutations.map((m) => m.target),
    ["results-gate-row", "experiments-status"],
  );
  assert.deepEqual(
    ticket.perRun.find((r) => r.runId === "P1-r1")?.requiredMutations.find((m) => m.target === "experiments-status")?.payload,
    { id: "P1", to: "COMPLETE" },
  );
  assert.equal(ticket.perRun.find((r) => r.runId === "P2-r1")?.liveAction, "ESCALATE");
});

test("selects the next queued experiment after all open runs are terminal", () => {
  const ticket = evaluateWorkflow({
    ...baseSnapshot,
    packageStatus: "NEXT_ACTION_READY",
    openRuns: [],
    experiments: [
      { expId: "P1", status: "COMPLETED" },
      { expId: "P2", status: "QUEUED" },
    ],
    armedReentries: {},
  });

  assert.equal(ticket.workflowState, "READY_TO_LAUNCH");
  assert.equal(ticket.expId, "P2");
  assert.equal(ticket.nextAction.kind, "LAUNCH_EXPERIMENT");
  assert.equal(ticket.nextAction.expId, "P2");
});

test("keeps an implementation-incomplete experiment out of launch", () => {
  const ticket = evaluateWorkflow({
    ...baseSnapshot,
    packageStatus: "CONTEXT_LOADED",
    openRuns: [],
    experiments: [
      {
        expId: "P0",
        status: "QUEUED",
        implementationReadiness: "BLOCKED",
        currentChangeId: "p0-integration",
      },
    ],
    armedReentries: {},
  });

  assert.equal(ticket.workflowState, "IMPLEMENTING");
  assert.equal(ticket.route, "FIX_IMPLEMENTATION");
  assert.equal(ticket.readiness, "BLOCKED");
  assert.equal(ticket.expId, "P0");
  assert.equal(ticket.packageBlocker, null);
  assert.equal(ticket.nextAction.kind, "REPAIR");
  assert.match(ticket.nextAction.reason, /p0-integration/);
});

test("routes one reviewed Experiment through the canonical launch mutation", () => {
  const ticket = evaluateWorkflow({
    pkgId: "pkg",
    packageLifecycle: "ACTIVE",
    packagePhase: "CONTEXT_LOADED",
    packageBlocker: null,
    packageVersion: 4,
    openRuns: [],
    experiments: [{
      expId: "P0",
      status: "READY",
      implementationReadiness: "PASS",
      reviewChangeId: "p0-review",
    }],
  });

  assert.equal(ticket.nextAction.kind, "LAUNCH_EXPERIMENT");
  assert.deepEqual(ticket.requiredMutations[0], {
    op: "update",
    target: "status",
    payload: {
      to: "READY_TO_LAUNCH",
      experiment_id: "P0",
      review_change_id: "p0-review",
      expected_version: 4,
    },
  });
});

test("does not launch a completed implementation before independent review", () => {
  const ticket = evaluateWorkflow({
    pkgId: "pkg",
    packageLifecycle: "ACTIVE",
    packagePhase: "CONTEXT_LOADED",
    packageBlocker: null,
    openRuns: [],
    experiments: [{
      expId: "P0",
      status: "READY",
      implementationReadiness: "PASS",
      reviewChangeId: null,
    }],
  });

  assert.equal(ticket.packagePhase, "CONTEXT_LOADED");
  assert.equal(ticket.route, "FIX_IMPLEMENTATION");
  assert.equal(ticket.nextAction.kind, "REPAIR");
  assert.match(ticket.nextAction.reason, /independent review/);
});

test("does not skip implementation review to launch a queued experiment", () => {
  const ticket = evaluateWorkflow({
    ...baseSnapshot,
    packageStatus: "IMPLEMENTING",
    openRuns: [],
    experiments: [{ expId: "P1", status: "QUEUED" }],
    armedReentries: {},
  });

  assert.equal(ticket.workflowState, "IMPLEMENTING");
  assert.equal(ticket.route, "FIX_IMPLEMENTATION");
  assert.equal(ticket.nextAction.kind, "REPAIR");
  assert.match(ticket.nextAction.reason, /cannot transition to READY_TO_LAUNCH/);
});

test("routes plan revision explicitly instead of terminating", () => {
  const ticket = evaluateWorkflow({
    ...baseSnapshot,
    packageStatus: "NEXT_ACTION_READY",
    nextRoute: "REVISE_PLAN",
    openRuns: [],
    experiments: [],
    armedReentries: {},
  });

  assert.equal(ticket.workflowState, "NEXT_ACTION_READY");
  assert.equal(ticket.packagePhase, "NEXT_ACTION_READY");
  assert.equal(ticket.packageBlocker?.code, "PLAN_REVISION_REQUIRED");
  assert.equal(ticket.route, "REVISE_PLAN");
  assert.equal(ticket.nextAction.kind, "ASK_USER");
  assert.match(ticket.nextAction.reason, /plan revision/);
  assert.equal(ticket.blocker, ticket.nextAction.reason);
});

test("keeps blocker orthogonal and rejects ambiguous legacy BLOCKED input", () => {
  assert.throws(
    () => evaluateWorkflow({
      ...baseSnapshot,
      packageStatus: "BLOCKED",
      openRuns: [],
      experiments: [],
    }),
    /requires packagePhase/,
  );

  const ticket = evaluateWorkflow({
    ...baseSnapshot,
    packageStatus: undefined,
    packageLifecycle: "ACTIVE",
    packagePhase: "IMPLEMENTING",
    packageBlocker: {
      code: "MISSING_DATASET",
      summary: "Dataset is unavailable",
    },
    openRuns: [],
    experiments: [{ expId: "P1", status: "READY" }],
  });
  assert.equal(ticket.packagePhase, "IMPLEMENTING");
  assert.equal(ticket.workflowState, "IMPLEMENTING");
  assert.equal(ticket.packageBlocker?.code, "MISSING_DATASET");
  assert.equal(ticket.nextAction.kind, "ASK_USER");
});

test("uses canonical experiment hierarchy for inferred run evidence paths", () => {
  const ticket = evaluateWorkflow({
    ...baseSnapshot,
    openRuns: [{
      runId: "run-1",
      expId: "P1",
      status: "RUNNING",
      lastOutputAt: "2026-06-11T00:00:00.000Z",
    }],
    armedReentries: { "run-1": "2026-06-11T00:10:00.000Z" },
  });
  assert.equal(
    ticket.perRun[0].runtimeRoot,
    ".research/experiments/2026-06-11-demo/P1/run-1",
  );
  assert.match(ticket.perRun[0].evidence[0], /^\.research\/experiments\//);
});

test("exposes legal transition graph and CLI JSON ticket", () => {
  assert.equal(isLegalTransition("EXPERIMENT_RUNNING", "LIVE_ANALYSIS"), true);
  assert.equal(isLegalTransition("EXPERIMENT_RUNNING", "STOPPED"), false);
  assert.deepEqual(workflowSchema.nextRoute, [
    "RUN_NEXT_EXPERIMENT",
    "FIX_IMPLEMENTATION",
    "REVISE_PLAN",
    "TERMINATE",
    "ASK_USER",
  ]);

  const stdout = execFileSync(
    process.execPath,
    ["workflow.ts", "next", "--json", JSON.stringify({ ...baseSnapshot, openRuns: [], armedReentries: {} })],
    { encoding: "utf-8" },
  );
  const ticket = JSON.parse(stdout);
  assert.equal(ticket.pkgId, "2026-06-11-demo");
  assert.equal(ticket.schemaVersion, 1);
});

test("loads workflow enums from the central research-state schema", () => {
  const stateSchema = JSON.parse(
    readFileSync("lib/research_state/schema.json", "utf-8"),
  );
  assert.deepEqual(workflowSchema.nextRoute, stateSchema.enums.decision_route);
  assert.deepEqual(workflowSchema.workflowStates, stateSchema.enums.package_phase);
  assert.deepEqual(workflowSchema.runStatus, stateSchema.enums.run_status);
  assert.equal(workflowSchema.workflowStates.includes("BLOCKED"), false);
  assert.equal(workflowSchema.workflowStates.includes("STOPPED"), false);
});
