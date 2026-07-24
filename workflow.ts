#!/usr/bin/env node

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

type ResearchStateSchema = {
  schema_version: number;
  enums: {
    package_lifecycle: string[];
    package_phase: string[];
    experiment_status: string[];
    run_status: string[];
    run_status_compat: string[];
    live_action: string[];
    decision_route: string[];
  };
  compatibility: {
    run_status: Record<string, string>;
    experiment_status: Record<string, string>;
    package_terminal_status: Record<string, string>;
  };
  transitions: {
    package_phase: Record<string, string[]>;
  };
  status_groups: {
    run: {
      active: string[];
      terminal: string[];
    };
  };
};

const researchStateSchema = JSON.parse(
  readFileSync(
    fileURLToPath(new URL("./lib/research_state/schema.json", import.meta.url)),
    "utf-8",
  ),
) as ResearchStateSchema;

export const workflowSchema = {
  schemaVersion: researchStateSchema.schema_version,
  packageLifecycle: Object.freeze([...researchStateSchema.enums.package_lifecycle]),
  workflowStates: Object.freeze([...researchStateSchema.enums.package_phase]),
  experimentStatus: Object.freeze([...researchStateSchema.enums.experiment_status]),
  runStatus: Object.freeze([...researchStateSchema.enums.run_status]),
  liveAction: Object.freeze([...researchStateSchema.enums.live_action]),
  nextRoute: Object.freeze([...researchStateSchema.enums.decision_route]),
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
};

export type PackageLifecycle = string;
export type WorkflowState = string;
export type ExperimentStatus = string;
export type RunStatus = string;
export type LiveAction = string;
export type NextRoute = string;

export type ExperimentSnapshot = {
  expId: string;
  status: RunStatus | "NOT_STARTED" | string;
  implementationReadiness?: "PASS" | "BLOCKED" | "NOT_REQUIRED" | string;
  currentChangeId?: string | null;
  reviewChangeId?: string | null;
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

export type DashboardServerSnapshot = {
  ok?: boolean;
  repairRequired?: boolean;
  repair_required?: boolean;
  status?: string | null;
  error?: string | null;
  liveUrl?: string | null;
  live_url?: string | null;
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
  packageLifecycle?: PackageLifecycle | string;
  packagePhase?: WorkflowState | string | null;
  packageBlocker?: Blocker | null;
  packageVersion?: number;
  /** One-version compatibility input. Prefer packageLifecycle/packagePhase. */
  packageStatus?: WorkflowState | string;
  nextRoute?: NextRoute | string;
  now?: string | number;
  scanEvents?: Array<Record<string, unknown>>;
  experiments?: ExperimentSnapshot[];
  openRuns?: RunSnapshot[];
  dashboardServer?: DashboardServerSnapshot | null;
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

export type Blocker = {
  code: string;
  summary: string;
  evidence?: Record<string, unknown> | null;
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
  schemaVersion: number;
  pkgId: string;
  expId: string | null;
  packageLifecycle: PackageLifecycle;
  packagePhase: WorkflowState | null;
  packageBlocker: Blocker | null;
  /** Compatibility projection for existing callers; never an authority field. */
  workflowState: WorkflowState;
  route: NextRoute;
  readiness: "PASS" | "BLOCKED" | "NOT_RUN" | string;
  perRun: PerRunTicket[];
  requiredMutations: ResearchOpEnvelope[];
  stopGate: StopGateReport;
  dashboardServer: {
    ok: boolean;
    repairRequired: boolean;
    liveUrl: string | null;
    warning: string | null;
    requiredAction: "NONE" | "ENSURE_DASHBOARD_SERVER";
  };
  nextAction: NextAction;
  artifactsSeen: Array<Record<string, unknown>>;
  blocker: string | null;
};

const transitionGraph: Record<string, string[]> = researchStateSchema.transitions.package_phase;
const terminalStatuses = new Set(researchStateSchema.status_groups.run.terminal);
const activeStatuses = new Set(researchStateSchema.status_groups.run.active);

export function isLegalTransition(from: string, to: string): boolean {
  if (from === "START") {
    return to === "CONTEXT_LOADED";
  }
  return (transitionGraph[from] || []).includes(to);
}

export function evaluateWorkflow(snapshot: WorkflowSnapshot): RunTicket {
  const now = parseTime(snapshot.now ?? Date.now());
  const packageState = normalizePackageState(snapshot);
  const currentState = packageState.phase ?? "CONTEXT_LOADED";
  const runs = normalizeRuns(snapshot.openRuns || [], now);
  const perRun = runs.map((run) => buildPerRunTicket(run, now, snapshot.pkgId));
  const nonTerminal = perRun.filter((run) => !run.terminal);
  const terminal = perRun.filter((run) => run.terminal);
  const scanEvents = snapshot.scanEvents || [];
  const stopGate = buildStopGate(perRun, snapshot.armedReentries || {}, scanEvents);
  const dashboardServer = evaluateDashboardServer(snapshot.dashboardServer || null);
  const nextQueued = findNextQueuedExperiment(snapshot.experiments || []);

  let packagePhase: WorkflowState | null;
  let route: NextRoute;
  let expId: string | null = null;
  let nextAction: NextAction;
  let packageBlocker = packageState.blocker;
  let readiness = snapshot.readiness || "NOT_RUN";

  if (packageState.lifecycle === "DRAFT") {
    packagePhase = null;
    route = "ASK_USER";
    nextAction = {
      kind: "ASK_USER",
      reason: "Draft Package must be refined, reviewed as one Scope bundle, and atomically finalized before execution",
    };
  } else if (packageState.lifecycle !== "ACTIVE") {
    packagePhase = packageState.phase;
    route = "TERMINATE";
    nextAction = {
      kind: "TERMINATE",
      reason: `package lifecycle is ${packageState.lifecycle}`,
    };
  } else if (nonTerminal.length > 0) {
    packagePhase = "LIVE_ANALYSIS";
    route = "RUN_NEXT_EXPERIMENT";
    expId = nonTerminal[0].expId;
    nextAction = {
      kind: "MONITOR_RUNS",
      runIds: nonTerminal.map((run) => run.runId),
      due: earliest(nonTerminal.map((run) => run.nextCheck).filter(isString)),
    };
  } else if (terminal.length > 0) {
    packagePhase = "RESULT_ANALYSIS";
    route = "TERMINATE";
    expId = terminal[0].expId;
    nextAction = { kind: "ANALYZE_RESULTS", expIds: terminal.map((run) => run.expId) };
  } else if (packageBlocker) {
    packagePhase = currentState;
    route = "ASK_USER";
    nextAction = { kind: "ASK_USER", reason: packageBlocker.summary };
  } else if (nextQueued) {
    readiness = nextQueued.implementationReadiness || "NOT_REQUIRED";
    if (!["PASS", "NOT_REQUIRED"].includes(readiness)) {
      packagePhase = canMoveTo(currentState, "IMPLEMENTING")
        ? "IMPLEMENTING"
        : currentState;
      route = "FIX_IMPLEMENTATION";
      expId = nextQueued.expId;
      const currentChange = nextQueued.currentChangeId
        ? `; continue Change ${nextQueued.currentChangeId}`
        : "; declare and complete its implementation Change";
      nextAction = {
        kind: "REPAIR",
        reason: `${nextQueued.expId} implementation is incomplete${currentChange}`,
      };
    } else if (readiness === "PASS" && !nextQueued.reviewChangeId) {
      packagePhase = currentState;
      route = "FIX_IMPLEMENTATION";
      expId = nextQueued.expId;
      nextAction = {
        kind: "REPAIR",
        reason: `${nextQueued.expId} implementation requires an independent review`,
      };
    } else if (canMoveTo(currentState, "READY_TO_LAUNCH")) {
      packagePhase = "READY_TO_LAUNCH";
      route = "RUN_NEXT_EXPERIMENT";
      expId = nextQueued.expId;
      nextAction = { kind: "LAUNCH_EXPERIMENT", expId: nextQueued.expId };
    } else {
      packagePhase = currentState;
      route = "FIX_IMPLEMENTATION";
      packageBlocker = {
        code: "PHASE_TRANSITION_REQUIRED",
        summary: `${currentState} cannot transition to READY_TO_LAUNCH; finish implementation/review first`,
      };
      nextAction = { kind: "REPAIR", reason: packageBlocker.summary };
    }
  } else if (snapshot.nextRoute === "ASK_USER") {
    packagePhase = currentState;
    route = "ASK_USER";
    nextAction = { kind: "ASK_USER", reason: "package nextRoute asks for a user-level decision" };
    packageBlocker = { code: "USER_DECISION_REQUIRED", summary: nextAction.reason };
  } else if (snapshot.nextRoute === "REVISE_PLAN") {
    packagePhase = currentState;
    route = "REVISE_PLAN";
    nextAction = { kind: "ASK_USER", reason: "package nextRoute requests plan revision approval or scope handoff" };
    packageBlocker = { code: "PLAN_REVISION_REQUIRED", summary: nextAction.reason };
  } else if (snapshot.nextRoute === "FIX_IMPLEMENTATION") {
    packagePhase = "IMPLEMENTING";
    route = "FIX_IMPLEMENTATION";
    nextAction = { kind: "REPAIR", reason: "package nextRoute requests implementation repair" };
  } else {
    packagePhase = packageState.phase ?? "NEXT_ACTION_READY";
    route = coerceNextRoute(snapshot.nextRoute, "TERMINATE");
    nextAction = { kind: "TERMINATE", reason: "no open or queued experiments remain" };
  }

  if (!stopGate.ok && nonTerminal.length === 0 && packagePhase !== "READY_TO_LAUNCH") {
    route = "ASK_USER";
    packageBlocker = {
      code: "STOP_GATE_BLOCKED",
      summary: stopGate.blockers.join("; "),
    };
    nextAction = { kind: "ASK_USER", reason: packageBlocker.summary };
  }

  const requiredMutations = [
    ...mutationsForWorkflowState(
      snapshot,
      packageState.lifecycle,
      packagePhase,
      packageBlocker,
      route,
      nonTerminal,
      nextAction,
    ),
    ...perRun.flatMap((run) => run.requiredMutations),
  ];
  const workflowState = packagePhase ?? packageState.lifecycle;

  return {
    schemaVersion: researchStateSchema.schema_version,
    pkgId: snapshot.pkgId,
    expId,
    packageLifecycle: packageState.lifecycle,
    packagePhase,
    packageBlocker,
    workflowState,
    route,
    readiness,
    perRun,
    requiredMutations,
    stopGate,
    dashboardServer,
    nextAction,
    artifactsSeen: scanEvents,
    blocker: packageBlocker?.summary ?? null,
  };
}

function evaluateDashboardServer(snapshot: DashboardServerSnapshot | null): RunTicket["dashboardServer"] {
  if (!snapshot) {
    return {
      ok: false,
      repairRequired: true,
      liveUrl: null,
      warning: "dashboard server state is missing",
      requiredAction: "ENSURE_DASHBOARD_SERVER",
    };
  }
  const repairRequired = Boolean(snapshot.repairRequired ?? snapshot.repair_required);
  const ok = Boolean(snapshot.ok) && !repairRequired;
  return {
    ok,
    repairRequired: !ok,
    liveUrl: snapshot.liveUrl ?? snapshot.live_url ?? null,
    warning: ok ? null : String(snapshot.error || snapshot.status || "dashboard server unhealthy"),
    requiredAction: ok ? "NONE" : "ENSURE_DASHBOARD_SERVER",
  };
}

function canMoveTo(from: WorkflowState, to: WorkflowState): boolean {
  return from === to || isLegalTransition(from, to);
}

function mutationsForWorkflowState(
  snapshot: WorkflowSnapshot,
  lifecycle: PackageLifecycle,
  phase: WorkflowState | null,
  packageBlocker: Blocker | null,
  route: NextRoute,
  nonTerminal: PerRunTicket[],
  nextAction: NextAction,
): ResearchOpEnvelope[] {
  const mutations: ResearchOpEnvelope[] = [];
  const current = normalizePackageState(snapshot);
  if (
    current.lifecycle !== lifecycle
    || current.phase !== phase
    || JSON.stringify(current.blocker) !== JSON.stringify(packageBlocker)
  ) {
    const payload: Record<string, unknown> = { to: phase ?? lifecycle };
    if (phase === "READY_TO_LAUNCH" && nextAction.kind === "LAUNCH_EXPERIMENT") {
      const experiment = (snapshot.experiments || []).find(
        (row) => row.expId === nextAction.expId,
      );
      payload.experiment_id = nextAction.expId;
      if (experiment?.reviewChangeId) {
        payload.review_change_id = experiment.reviewChangeId;
      }
    }
    if (snapshot.packageVersion !== undefined) {
      payload.expected_version = snapshot.packageVersion;
    }
    mutations.push({
      op: "update",
      target: "status",
      payload,
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
    payload: { to: formatLastAction(phase ?? lifecycle, route, nextAction) },
  });

  if (packageBlocker) {
    mutations.push({
      op: "update",
      target: "currentBlocker",
      payload: { to: packageBlocker.summary },
    });
  }
  return mutations;
}

function normalizeRuns(runs: RunSnapshot[], now: number): RunSnapshot[] {
  return runs.map((run) => {
    const status = normalizeRunStatus(run.status || "RUNNING");
    if (!activeStatuses.has(status)) {
      return { ...run, status };
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

function buildPerRunTicket(run: RunSnapshot, now: number, pkgId: string): PerRunTicket {
  const status = normalizeRunStatus(run.status || "RUNNING");
  const terminal = terminalStatuses.has(status);
  const health = String(run.health || "OK");
  const liveAction = decideLiveAction(status, health);
  const nextCheck = terminal ? null : iso(now + cadenceMillis(run, status, health));
  const runtimeRoot = run.runtimeRoot || `.research/experiments/${pkgId}/${run.expId}/${run.runId}`;
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
    requiredMutations: mutationsForRun(run, status, terminal, liveAction, nextCheck, now, pkgId),
    evidence,
  };
}

function decideLiveAction(status: string, health: string): LiveAction {
  if (status === "FAILED" || status === "HALTED" || health === "ERROR") {
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
  pkgId: string,
): ResearchOpEnvelope[] {
  const runtimeRoot = run.runtimeRoot || `.research/experiments/${pkgId}/${run.expId}/${run.runId}`;
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
        to: experimentStatusFromRun(status),
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
  return experiments.find((exp) =>
    ["PLANNED", "READY"].includes(normalizeExperimentStatus(exp.status || "PLANNED"))
  ) || null;
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

function normalizePackageState(snapshot: WorkflowSnapshot): {
  lifecycle: PackageLifecycle;
  phase: WorkflowState | null;
  blocker: Blocker | null;
} {
  const legacyStatus = snapshot.packageStatus == null ? null : String(snapshot.packageStatus);
  const inferredLifecycle = legacyStatus == null
    ? "ACTIVE"
    : researchStateSchema.compatibility.package_terminal_status[legacyStatus] ?? "ACTIVE";
  const lifecycle = String(snapshot.packageLifecycle ?? inferredLifecycle);
  if (!workflowSchema.packageLifecycle.includes(lifecycle)) {
    throw new Error(`unknown package lifecycle: ${lifecycle}`);
  }

  let phase: WorkflowState | null;
  if (snapshot.packagePhase !== undefined) {
    phase = snapshot.packagePhase == null ? null : String(snapshot.packagePhase);
  } else if (legacyStatus && workflowSchema.workflowStates.includes(legacyStatus)) {
    phase = legacyStatus;
  } else if (lifecycle === "ACTIVE" && legacyStatus !== "BLOCKED") {
    phase = "CONTEXT_LOADED";
  } else {
    phase = null;
  }
  if (phase !== null && !workflowSchema.workflowStates.includes(phase)) {
    throw new Error(`unknown package phase: ${phase}`);
  }
  if (lifecycle === "ACTIVE" && phase === null) {
    throw new Error(
      legacyStatus === "BLOCKED"
        ? "legacy BLOCKED input requires packagePhase; BLOCKED is now a blocker, not a phase"
        : "ACTIVE package requires packagePhase",
    );
  }
  if (lifecycle !== "ACTIVE" && phase !== null) {
    throw new Error(`${lifecycle} package must not carry an active packagePhase`);
  }

  const blocker = snapshot.packageBlocker ?? null;
  if (
    blocker !== null
    && (
      typeof blocker !== "object"
      || typeof blocker.code !== "string"
      || !blocker.code
      || typeof blocker.summary !== "string"
      || !blocker.summary
    )
  ) {
    throw new Error("packageBlocker requires non-empty code and summary");
  }
  return { lifecycle, phase, blocker };
}

function normalizeRunStatus(value: unknown): RunStatus {
  const raw = String(value);
  const canonical = researchStateSchema.compatibility.run_status[raw] ?? raw;
  if (!workflowSchema.runStatus.includes(canonical)) {
    throw new Error(`unknown run status: ${raw}`);
  }
  return canonical;
}

function normalizeExperimentStatus(value: unknown): ExperimentStatus {
  const raw = String(value);
  const canonical = researchStateSchema.compatibility.experiment_status[raw] ?? raw;
  if (!workflowSchema.experimentStatus.includes(canonical)) {
    throw new Error(`unknown experiment status: ${raw}`);
  }
  return canonical;
}

function experimentStatusFromRun(status: RunStatus): ExperimentStatus {
  const mapping: Record<string, string> = {
    QUEUED: "READY",
    RUNNING: "ACTIVE",
    STALE: "ACTIVE",
    COMPLETED: "COMPLETE",
    FAILED: "FAILED",
    HALTED: "FAILED",
    SKIPPED: "SKIPPED",
  };
  return normalizeExperimentStatus(mapping[status]);
}

function coerceNextRoute(value: unknown, fallback: NextRoute): NextRoute {
  if (value == null || value === "") {
    return fallback;
  }
  const route = String(value);
  if (!workflowSchema.nextRoute.includes(route)) {
    throw new Error(`unknown decision route: ${route}`);
  }
  return route;
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
