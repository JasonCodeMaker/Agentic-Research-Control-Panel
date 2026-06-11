#!/usr/bin/env node

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

export const workflowSchema = {
  schemaVersion: 1,
  workflowStates: [
    "CONTEXT_LOADED",
    "IMPLEMENTING",
    "IMPLEMENTATION_REVIEW",
    "DECISION_ADJUDICATION",
    "READY_TO_LAUNCH",
    "EXPERIMENT_RUNNING",
    "LIVE_ANALYSIS",
    "RESULT_ANALYSIS",
    "NEXT_ACTION_READY",
    "BLOCKED",
    "STOPPED",
  ],
  runStatus: ["QUEUED", "RUNNING", "COMPLETED", "RUN_FAILED", "RUN_HALTED", "STALE", "SKIPPED"],
  liveAction: ["CONTINUE_RUN", "EARLY_STOP", "REPAIR", "ASK_USER", "ESCALATE"],
  nextRoute: ["RUN_NEXT_EXPERIMENT", "FIX_IMPLEMENTATION", "REVISE_PLAN", "TERMINATE", "ASK_USER"],
  tableSchemas: {
    liveCheck: [
      "Time",
      "Exp ID",
      "Agent",
      "Run State",
      "Last Log",
      "Progress",
      "Latest Metrics",
      "Resource Use",
      "Artifacts",
      "ETA",
      "Live Action",
      "Next Check",
    ],
    resultGate: [
      "Exp ID",
      "Validity",
      "Baseline",
      "PLAN Gate",
      "Observed Metric",
      "Budget/Resource Use",
      "Seed Status",
      "Artifact Completeness",
      "Verdict",
      "Reason",
    ],
  },
} as const;

export type WorkflowState = (typeof workflowSchema.workflowStates)[number];
export type RunStatus = (typeof workflowSchema.runStatus)[number];
export type LiveAction = (typeof workflowSchema.liveAction)[number];
export type NextRoute = (typeof workflowSchema.nextRoute)[number];

export type ExperimentSnapshot = {
  expId: string;
  status: RunStatus | "NOT_STARTED" | string;
};

export type RunSnapshot = {
  runId: string;
  expId: string;
  status: RunStatus | string;
  health?: "OK" | "WARN" | "ERROR" | string;
  runtimeRoot?: string;
  progress?: unknown;
  latestMetrics?: unknown;
  etaSeconds?: number | null;
  eta?: string | null;
  resource?: unknown;
  artifacts?: unknown;
  lastOutputAt?: string | number | null;
  startedAt?: string | number | null;
  heartbeatTimeoutSeconds?: number | null;
  exitCode?: number | null;
  endedAt?: string | number | null;
};

export type ResearchOpEnvelope = {
  op: "insert" | "update" | "delete" | "check" | "scan-events";
  target:
    | "tracker-live-check-row"
    | "tracker-resource-allocation-row"
    | "results-gate-row"
    | "results-block"
    | "experiments-status"
    | "status"
    | "openRuns"
    | "currentBlocker"
    | "lastAction";
  payload: Record<string, unknown>;
};

export type WorkflowSnapshot = {
  pkgId: string;
  packageStatus?: WorkflowState | string;
  nextRoute?: NextRoute | string;
  now?: string | number;
  scanEvents?: Array<Record<string, unknown>>;
  experiments?: ExperimentSnapshot[];
  openRuns?: RunSnapshot[];
  armedReentries?: Record<string, string | number | null | undefined>;
  readiness?: "PASS" | "BLOCKED" | "NOT_RUN" | string;
};

export type PerRunTicket = {
  runId: string;
  expId: string;
  status: RunStatus | string;
  terminal: boolean;
  health: string;
  liveAction: LiveAction;
  runtimeRoot: string;
  nextCheck: string | null;
  statusLine: string;
  requiredMutations: ResearchOpEnvelope[];
  evidence: string[];
};

export type StopGateReport = {
  ok: boolean;
  blockers: string[];
  openRuns: Array<{
    runId: string;
    expId: string;
    status: string;
    nextCheck: string | null;
    reentry: string | null;
    reentryArmed: boolean;
  }>;
  scanEventsPending: number;
};

export type NextAction =
  | { kind: "MONITOR_RUNS"; runIds: string[]; due: string | null }
  | { kind: "LAUNCH_EXPERIMENT"; expId: string }
  | { kind: "ANALYZE_RESULTS"; expIds: string[] }
  | { kind: "ASK_USER"; reason: string }
  | { kind: "REPAIR"; reason: string }
  | { kind: "TERMINATE"; reason: string };

export type RunTicket = {
  schemaVersion: 1;
  pkgId: string;
  expId: string | null;
  workflowState: WorkflowState;
  route: NextRoute;
  readiness: "PASS" | "BLOCKED" | "NOT_RUN" | string;
  perRun: PerRunTicket[];
  requiredMutations: ResearchOpEnvelope[];
  stopGate: StopGateReport;
  nextAction: NextAction;
  artifactsSeen: Array<Record<string, unknown>>;
  blocker: string | null;
};

const transitionGraph: Record<string, string[]> = {
  START: ["CONTEXT_LOADED"],
  CONTEXT_LOADED: ["IMPLEMENTING", "READY_TO_LAUNCH"],
  IMPLEMENTING: ["IMPLEMENTATION_REVIEW"],
  IMPLEMENTATION_REVIEW: ["IMPLEMENTING", "DECISION_ADJUDICATION", "READY_TO_LAUNCH"],
  DECISION_ADJUDICATION: ["IMPLEMENTING", "IMPLEMENTATION_REVIEW", "READY_TO_LAUNCH", "BLOCKED"],
  READY_TO_LAUNCH: ["EXPERIMENT_RUNNING"],
  EXPERIMENT_RUNNING: ["LIVE_ANALYSIS"],
  LIVE_ANALYSIS: ["EXPERIMENT_RUNNING", "RESULT_ANALYSIS", "IMPLEMENTING"],
  RESULT_ANALYSIS: ["NEXT_ACTION_READY"],
  NEXT_ACTION_READY: ["READY_TO_LAUNCH", "IMPLEMENTING", "BLOCKED", "STOPPED"],
  BLOCKED: [],
  STOPPED: [],
};

const terminalStatuses = new Set(["COMPLETED", "RUN_FAILED", "RUN_HALTED", "SKIPPED"]);
const activeStatuses = new Set(["QUEUED", "RUNNING", "STALE"]);

export function isLegalTransition(from: string, to: string): boolean {
  return (transitionGraph[from] || []).includes(to);
}

export function evaluateWorkflow(snapshot: WorkflowSnapshot): RunTicket {
  const now = parseTime(snapshot.now ?? Date.now());
  const currentState = coerceWorkflowState(snapshot.packageStatus, "CONTEXT_LOADED");
  const runs = normalizeRuns(snapshot.openRuns || [], now);
  const perRun = runs.map((run) => buildPerRunTicket(run, now));
  const nonTerminal = perRun.filter((run) => !run.terminal);
  const terminal = perRun.filter((run) => run.terminal);
  const scanEvents = snapshot.scanEvents || [];
  const stopGate = buildStopGate(perRun, snapshot.armedReentries || {}, scanEvents);
  const nextQueued = findNextQueuedExperiment(snapshot.experiments || []);

  let workflowState: WorkflowState;
  let route: NextRoute;
  let expId: string | null = null;
  let nextAction: NextAction;
  let blocker: string | null = null;

  if (nonTerminal.length > 0) {
    workflowState = "LIVE_ANALYSIS";
    route = "RUN_NEXT_EXPERIMENT";
    expId = nonTerminal[0].expId;
    nextAction = {
      kind: "MONITOR_RUNS",
      runIds: nonTerminal.map((run) => run.runId),
      due: earliest(nonTerminal.map((run) => run.nextCheck).filter(isString)),
    };
  } else if (terminal.length > 0) {
    workflowState = "RESULT_ANALYSIS";
    route = "TERMINATE";
    expId = terminal[0].expId;
    nextAction = { kind: "ANALYZE_RESULTS", expIds: terminal.map((run) => run.expId) };
  } else if (nextQueued) {
    if (canMoveTo(currentState, "READY_TO_LAUNCH")) {
      workflowState = "READY_TO_LAUNCH";
      route = "RUN_NEXT_EXPERIMENT";
      expId = nextQueued.expId;
      nextAction = { kind: "LAUNCH_EXPERIMENT", expId: nextQueued.expId };
    } else {
      workflowState = currentState;
      route = "FIX_IMPLEMENTATION";
      blocker = `${currentState} cannot transition to READY_TO_LAUNCH; finish implementation/review first`;
      nextAction = { kind: "REPAIR", reason: blocker };
    }
  } else if (snapshot.nextRoute === "ASK_USER") {
    workflowState = "BLOCKED";
    route = "ASK_USER";
    nextAction = { kind: "ASK_USER", reason: "package nextRoute asks for a user-level decision" };
    blocker = nextAction.reason;
  } else if (snapshot.nextRoute === "REVISE_PLAN") {
    workflowState = "BLOCKED";
    route = "REVISE_PLAN";
    nextAction = { kind: "ASK_USER", reason: "package nextRoute requests plan revision approval or scope handoff" };
    blocker = nextAction.reason;
  } else if (snapshot.nextRoute === "FIX_IMPLEMENTATION") {
    workflowState = "IMPLEMENTING";
    route = "FIX_IMPLEMENTATION";
    nextAction = { kind: "REPAIR", reason: "package nextRoute requests implementation repair" };
  } else {
    workflowState = coerceWorkflowState(snapshot.packageStatus, "NEXT_ACTION_READY");
    route = coerceNextRoute(snapshot.nextRoute, "TERMINATE");
    nextAction = { kind: "TERMINATE", reason: "no open or queued experiments remain" };
  }

  if (!stopGate.ok && nonTerminal.length === 0 && workflowState !== "READY_TO_LAUNCH") {
    workflowState = "BLOCKED";
    route = "ASK_USER";
    blocker = stopGate.blockers.join("; ");
    nextAction = { kind: "ASK_USER", reason: blocker };
  }

  const requiredMutations = [
    ...mutationsForWorkflowState(snapshot, workflowState, route, nonTerminal, blocker, nextAction),
    ...perRun.flatMap((run) => run.requiredMutations),
  ];

  return {
    schemaVersion: 1,
    pkgId: snapshot.pkgId,
    expId,
    workflowState,
    route,
    readiness: snapshot.readiness || "NOT_RUN",
    perRun,
    requiredMutations,
    stopGate,
    nextAction,
    artifactsSeen: scanEvents,
    blocker,
  };
}

function canMoveTo(from: WorkflowState, to: WorkflowState): boolean {
  return from === to || isLegalTransition(from, to);
}

function mutationsForWorkflowState(
  snapshot: WorkflowSnapshot,
  workflowState: WorkflowState,
  route: NextRoute,
  nonTerminal: PerRunTicket[],
  blocker: string | null,
  nextAction: NextAction,
): ResearchOpEnvelope[] {
  const mutations: ResearchOpEnvelope[] = [];
  if (snapshot.packageStatus !== workflowState) {
    mutations.push({
      op: "update",
      target: "status",
      payload: { to: workflowState, to_status: workflowState },
    });
  }

  if ((snapshot.openRuns || []).length > 0 || nonTerminal.length > 0) {
    mutations.push({
      op: "update",
      target: "openRuns",
      payload: {
        to: nonTerminal.length === 0
          ? "none"
          : nonTerminal.map((run) => `${run.runId} (${run.expId} ${run.status}, next=${run.nextCheck ?? "none"})`).join("; "),
      },
    });
  }

  mutations.push({
    op: "update",
    target: "lastAction",
    payload: { to: formatLastAction(workflowState, route, nextAction) },
  });

  if (blocker) {
    mutations.push({
      op: "update",
      target: "currentBlocker",
      payload: { to: blocker },
    });
  }
  return mutations;
}

function normalizeRuns(runs: RunSnapshot[], now: number): RunSnapshot[] {
  return runs.map((run) => {
    const status = String(run.status || "RUNNING");
    if (!activeStatuses.has(status)) {
      return run;
    }
    const ref = run.lastOutputAt ?? run.startedAt;
    const ageSeconds = ref == null ? null : Math.max(0, Math.floor((now - parseTime(ref)) / 1000));
    const heartbeat = run.heartbeatTimeoutSeconds ?? 600;
    if (ageSeconds != null && ageSeconds > heartbeat) {
      return { ...run, status: "STALE" };
    }
    return run;
  });
}

function buildPerRunTicket(run: RunSnapshot, now: number): PerRunTicket {
  const status = String(run.status || "RUNNING");
  const terminal = terminalStatuses.has(status);
  const health = String(run.health || "OK");
  const liveAction = decideLiveAction(status, health);
  const nextCheck = terminal ? null : iso(now + cadenceMillis(run, status, health));
  const runtimeRoot = run.runtimeRoot || `outputs/<pkg>/runs/${run.runId}`;
  const evidence = [
    `${runtimeRoot}/status.json`,
    `${runtimeRoot}/events.jsonl`,
    `${runtimeRoot}/log.txt`,
  ];

  return {
    runId: run.runId,
    expId: run.expId,
    status,
    terminal,
    health,
    liveAction,
    runtimeRoot,
    nextCheck,
    statusLine: formatStatusLine(run, liveAction),
    requiredMutations: mutationsForRun(run, status, terminal, liveAction, nextCheck, now),
    evidence,
  };
}

function decideLiveAction(status: string, health: string): LiveAction {
  if (status === "RUN_FAILED" || status === "RUN_HALTED" || health === "ERROR") {
    return "REPAIR";
  }
  if (status === "STALE" || health === "WARN") {
    return "ESCALATE";
  }
  return "CONTINUE_RUN";
}

function cadenceMillis(run: RunSnapshot, status: string, health: string): number {
  const minute = 60 * 1000;
  if (status === "STALE" || health === "ERROR") {
    return 0;
  }
  if (health === "WARN") {
    return 5 * minute;
  }
  const eta = typeof run.etaSeconds === "number" && Number.isFinite(run.etaSeconds) ? run.etaSeconds : null;
  if (eta == null) {
    return 10 * minute;
  }
  if (eta <= 15 * 60) {
    return 5 * minute;
  }
  if (eta <= 60 * 60) {
    return 10 * minute;
  }
  if (eta <= 6 * 60 * 60) {
    return 30 * minute;
  }
  return 60 * minute;
}

function mutationsForRun(
  run: RunSnapshot,
  status: string,
  terminal: boolean,
  liveAction: LiveAction,
  nextCheck: string | null,
  now: number,
): ResearchOpEnvelope[] {
  const runtimeRoot = run.runtimeRoot || `outputs/<pkg>/runs/${run.runId}`;
  const liveCheck: ResearchOpEnvelope = {
    op: "insert",
    target: "tracker-live-check-row",
    payload: {
      time: localIso(now),
      run_id: run.runId,
      exp_id: run.expId,
      agent: "workflow.ts",
      run_state: status,
      last_log: run.lastOutputAt ?? "unmeasured",
      progress: stringifyField(run.progress),
      metrics: stringifyField(run.latestMetrics),
      resource: stringifyField(run.resource),
      artifacts: stringifyField(run.artifacts),
      eta: run.eta ?? (run.etaSeconds == null ? "unknown" : `${run.etaSeconds}s`),
      action: liveAction,
      next_check: nextCheck ?? "none",
      source_artifact: `${runtimeRoot}/status.json`,
    },
  };
  if (!terminal) {
    return [liveCheck];
  }
  return [
    liveCheck,
    {
      op: "insert",
      target: "results-gate-row",
      payload: {
        exp_id: run.expId,
        run_id: run.runId,
        validity: status === "COMPLETED" ? "UNMEASURED" : "RESULT_FAIL",
        baseline: "unmeasured",
        plan_gate: "unmeasured",
        observed_metric: "unmeasured",
        budget_use: stringifyField(run.resource),
        seed_status: "unmeasured",
        artifact_completeness: stringifyField(run.artifacts),
        verdict: status === "COMPLETED" ? "INCONCLUSIVE" : "FAIL",
        reason: `${run.runId} ended with ${status}; verify metric artifacts before final verdict`,
        status,
        runtime_root: runtimeRoot,
        exit_code: run.exitCode ?? "unmeasured",
        ended_at: run.endedAt ?? "unmeasured",
        source_artifact: `${runtimeRoot}/status.json`,
      },
    },
    {
      op: "update",
      target: "experiments-status",
      payload: {
        id: run.expId,
        to: status,
      },
    },
  ];
}

function buildStopGate(
  perRun: PerRunTicket[],
  armedReentries: Record<string, string | number | null | undefined>,
  scanEvents: Array<Record<string, unknown>>,
): StopGateReport {
  const blockers: string[] = [];
  if (scanEvents.length > 0) {
    blockers.push(`scan-events has ${scanEvents.length} pending event(s)`);
  }

  const openRuns = perRun
    .filter((run) => !run.terminal)
    .map((run) => {
      const reentry = armedReentries[run.runId] ?? null;
      const reentryArmed = reentry != null && run.nextCheck != null && parseTime(reentry) <= parseTime(run.nextCheck);
      if (!reentryArmed) {
        blockers.push(
          reentry == null
            ? `${run.runId} has no armed re-entry`
            : `${run.runId} re-entry is after Next Check`,
        );
      }
      return {
        runId: run.runId,
        expId: run.expId,
        status: run.status,
        nextCheck: run.nextCheck,
        reentry: reentry == null ? null : iso(parseTime(reentry)),
        reentryArmed,
      };
    });

  return {
    ok: blockers.length === 0,
    blockers,
    openRuns,
    scanEventsPending: scanEvents.length,
  };
}

function findNextQueuedExperiment(experiments: ExperimentSnapshot[]): ExperimentSnapshot | null {
  return experiments.find((exp) => ["QUEUED", "NOT_STARTED", ""].includes(String(exp.status || ""))) || null;
}

function formatStatusLine(run: RunSnapshot, liveAction: LiveAction): string {
  const progress = stringifyField(run.progress, "pending(first_progress)");
  const performance = stringifyField(run.latestMetrics, "pending(first_eval)");
  const eta = run.eta ?? (run.etaSeconds == null ? "unknown" : `${run.etaSeconds}s`);
  return `${run.expId}: progress=${progress}; performance=${performance}; est_time=${eta}; action=${liveAction}`;
}

function formatLastAction(workflowState: WorkflowState, route: NextRoute, nextAction: NextAction): string {
  if ("reason" in nextAction) {
    return `workflow.ts routed state=${workflowState} route=${route}; next=${nextAction.kind}; reason=${nextAction.reason}`;
  }
  return `workflow.ts routed state=${workflowState} route=${route}; next=${nextAction.kind}`;
}

function coerceWorkflowState(value: unknown, fallback: WorkflowState): WorkflowState {
  return workflowSchema.workflowStates.includes(value as WorkflowState) ? (value as WorkflowState) : fallback;
}

function coerceNextRoute(value: unknown, fallback: NextRoute): NextRoute {
  return workflowSchema.nextRoute.includes(value as NextRoute) ? (value as NextRoute) : fallback;
}

function stringifyField(value: unknown, fallback = "unmeasured"): string {
  if (value == null || value === "") {
    return fallback;
  }
  if (typeof value === "string") {
    return value;
  }
  return JSON.stringify(value);
}

function parseTime(value: string | number | Date): number {
  if (value instanceof Date) {
    return value.getTime();
  }
  if (typeof value === "number") {
    return value > 10_000_000_000 ? value : value * 1000;
  }
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) {
    throw new Error(`invalid timestamp: ${value}`);
  }
  return parsed;
}

function iso(ms: number): string {
  return new Date(ms).toISOString();
}

function localIso(ms: number): string {
  const date = new Date(ms);
  const offsetMinutes = -date.getTimezoneOffset();
  const sign = offsetMinutes >= 0 ? "+" : "-";
  const absOffset = Math.abs(offsetMinutes);
  const offset = `${sign}${pad(Math.floor(absOffset / 60))}:${pad(absOffset % 60)}`;
  return [
    date.getFullYear(),
    "-",
    pad(date.getMonth() + 1),
    "-",
    pad(date.getDate()),
    "T",
    pad(date.getHours()),
    ":",
    pad(date.getMinutes()),
    ":",
    pad(date.getSeconds()),
    offset,
  ].join("");
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

function earliest(values: string[]): string | null {
  if (values.length === 0) {
    return null;
  }
  return iso(Math.min(...values.map((value) => parseTime(value))));
}

function isString(value: unknown): value is string {
  return typeof value === "string";
}

function readSnapshotFromArgs(argv: string[]): WorkflowSnapshot {
  const jsonIndex = argv.indexOf("--json");
  if (jsonIndex >= 0) {
    const raw = argv[jsonIndex + 1];
    if (!raw) {
      throw new Error("--json requires a JSON payload");
    }
    return JSON.parse(raw) as WorkflowSnapshot;
  }
  const inputIndex = argv.indexOf("--input");
  if (inputIndex >= 0) {
    const file = argv[inputIndex + 1];
    if (!file) {
      throw new Error("--input requires a file path");
    }
    return JSON.parse(readFileSync(resolve(file), "utf-8")) as WorkflowSnapshot;
  }
  throw new Error("expected --json '<snapshot>' or --input <snapshot.json>");
}

function main(argv: string[]): number {
  const [command, ...rest] = argv;
  if (command === "next") {
    process.stdout.write(`${JSON.stringify(evaluateWorkflow(readSnapshotFromArgs(rest)), null, 2)}\n`);
    return 0;
  }
  if (command === "schema") {
    process.stdout.write(`${JSON.stringify(workflowSchema, null, 2)}\n`);
    return 0;
  }
  process.stderr.write("usage: node workflow.ts next (--json '<snapshot>' | --input snapshot.json)\n");
  process.stderr.write("       node workflow.ts schema\n");
  return 2;
}

const isMain = process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1]);
if (isMain) {
  process.exitCode = main(process.argv.slice(2));
}
