# /research-auto maturation — wiring the walking skeleton into a real autonomous scientist

**Date:** 2026-06-05 · **Status:** PLAN (not implemented). Supersedes the "later stages" stub in `skills/research-auto/SKILL.md` §263–270 with a concrete, TDD-first build order.
**Refinement note:** optimized after review to prioritize the production-loop contract and real code/run spine before wiring the L2 jury, so the verifier judges real runtime artifacts rather than the toy skeleton path.

> **One-line framing.** Today `/research-auto` is a *validated trust skeleton*: the gates fire in the right order and block the right things, but every intelligence role is a stub. This plan first defines the production dispatch contract, then wires the missing **code + run + review** spine, and only then attaches the already-built deterministic gates (`lib/verifier`, `dial.py`, `pack.py`, `lib/cite_check`, the split role-skills) so the seven autonomous-scientist capabilities become real one stage at a time without weakening any existing gate.

Connects to `[[auto-research-harness-first-strategy]]`, `[[multi-agent-ranking-jury-design]]`, `[[workflow-model-tiering]]`, `[[wiki-context-pack-integration]]`, `[[self-evolving-self-learning-design]]`.

---

## 1. Where we actually are (grounded audit, 2026-06-05)

`skills/research-auto/scripts/skeleton.py::run` proves the **trust wiring** composes end-to-end at Supervised/L1. Every *intelligence* role is thin or faked:

| Role | Real (keep) | Faked (replace) |
| --- | --- | --- |
| R1 scope | gated SSOT write `propose_transition` | hypothesis hard-coded in `scope()` |
| R2 search | L1 cite-exists partition | "search" = `Path.exists()`; no fetch/synthesis |
| R3 ideate | — | returns the hypothesis verbatim |
| R4 experiment | artifact-on-disk discipline | `measured` is **passed in by the caller**; no code written/run |
| R5 verify | L1 metric oracle reads number from disk | scalar `>=` compare, not the L2 jury |
| R6 write | grounded-only structure | string template |
| R7 acquit | research-op `acquit-needs-verdict` gate | — |

**Built but unwired into the loop:** `lib/verifier` (L2 cross-model jury, 130 LoC, tested), `dial.py` (auto-revert), `pack.py` (PACK continuity), the split skills `research-lit` / `research-ideate` / `research-write` (each has its SKILL.md + deterministic helper but `skeleton.run` calls its own internal stub instead). `research-reflect` / `research-apply` (self-learning) exist, gated, unwired.

**Missing entirely:** a **code-writing + IMPLEMENTATION_REVIEW + run** role. R1–R7 has no place where real experiment code is authored, reviewed, and executed. The two-layer review is well-specified *prose* in SKILL.md §240–261 but nothing executes it. This is the single biggest hole and the one 核心问题 #1 (TDD-as-anti-deception) most needs.

**The three feedback points are accurate and match the system's own self-description** (SKILL.md §46–49, §263–270). This is the ratified harness-first order, not an accident — the deliverable is *trustworthiness*, so faking the scientist while hardening the gates is the correct sequence. The only failure would be to stop here and call it "done."

## 2. The structural decision (ratified: agent-driven loop)

**Move the orchestration locus from `skeleton.run` (a Python function calling stubs) to an agent-driven dispatch loop** — the SKILL.md "Procedure" §142–207 already drafts it. Python libs stay as *deterministic gates*; Claude sub-agents perform the *heavy roles*.

- **Production loop** = a typed agent-driven tick: Claude reads scope → compiles Context Pack → dispatches role sub-agents (per `[[workflow-model-tiering]]`: Haiku/Sonnet for thin roles, Opus for code+analysis) → receives typed role returns → routes every write through research-op → writes PACK / next-state. The dispatch contract is testable without a real model call by using fake role adapters.
- **`skeleton.run`** is demoted to the **L1 reference path / test fixture**: it stays green as the deterministic proof that the gate ordering composes, and as the contract every heavy role must satisfy. It is *not* the thing that runs in production.

Rationale: dial-revert needs real Tasks to revert and PACK needs real tick content — a stub loop has neither, so "wire dial.py in" is literally impossible until the locus moves. Keeping `skeleton.run` as the fixture preserves the 58-test substrate.

**Non-negotiable invariants (all stages):** single mutation surface (research-op); proposer ≠ disposer / coder ≠ reviewer / reflect ≠ apply; cite-exists + grounded-only before any paper byte; acquit blocked unless the metric oracle/jury clears the SSOT predicate; every gate that is green today stays green (additive only).

## 3. Capability → gap → stage map

| # | Autonomous-scientist capability | Today | Lands in |
| --- | --- | --- | --- |
| 1 | Auto find + synthesize literature | cite gate only | Stage 5 (R2 → `research-lit`) |
| 2 | Auto propose high-quality ideas | banlist only | Stage 5 (R3 → `research-ideate` + `lib/ranking`) |
| 3 | Auto write + review **real code** | **absent** | **Stage 1 (new code role)** |
| 4 | Auto schedule long experiments | none | Stage 2 + Stage 4 (real run + unattended driver) |
| 5 | Auto analyze complex results | scalar compare | Stage 3 (L2 jury) + Stage 5 (heavy R5/result analysis) |
| 6 | Auto write trustworthy paper | template | Stage 5 (R6 → `research-write`) |
| 7 | Reliably advance unattended + deliver PACK | pack.py unwired | Stage 4 (PACK + driver-lite) |

## 4. Build order (each stage TDD-first, additive, full suite stays green)

Run tests with conda `python3.13`. Every stage: write the failing test against the gate first, then wire.

> **Build outcome (2026-06-05).** Stages 0-6 trust-wiring shipped TDD-first; full suite **440 passed**
> (400 baseline → +10 `test_driver.py` → +19 `test_roles.py`, additive, 0 regressions). Stage 0 =
> `driver.py` (dispatch seam). Stages 1-6 = `roles.py` helpers, each emitting a research-op envelope
> proven against the *real* gate (`validate.py`) and the verifier — see the table in SKILL.md §"Build
> stages". What remains is **live dispatch**: swapping fake role adapters for real model-tiered
> sub-agent calls. The deterministic trust contract those adapters must satisfy is now fixed and tested.
> Not committed (awaiting user).

### Stage 0 — production-loop contract *(make orchestration testable before adding intelligence)* — **DONE 2026-06-05 (TDD, +10 green, full suite 410)**
Built: `skills/research-auto/scripts/driver.py` (`validate_role_return`, `validate_mutation`, `run_tick`) + `tests/research-auto/test_driver.py`. SKILL.md §"Stage 0" documents the seam. `skeleton.run` kept green as the L1 fixture.

Create a minimal `research-auto` driver contract that can be tested with fake role adapters and no live model calls. This is the seam that makes "agent-driven" executable rather than prose.
- **Tasks:** (a) Define typed role-return schemas for `scope`, `lit`, `ideate`, `implement`, `review`, `run`, `verify`, `write`, `remember` with `agent_role`, `assigned_scope`, `status`, `evidence`, `blockers`, `recommended_next_action`. (b) Add a dry-run driver/tick that reads package state + Scope node, compiles Context Pack, calls fake adapters, emits proposed research-op mutations, and writes a PACK candidate without touching package HTML directly. (c) Test: the driver rejects a role return missing evidence; refuses direct file writes; routes all mutations through a research-op envelope; keeps `skeleton.run` green as the L1 fixture.
- **Closes:** no scientist capability directly; unlocks every later stage by giving them a common executable seam.

### Stage 0.5 — front-door admission layer *(make /research-auto the post-init front door)* — **DONE 2026-06-05 (TDD)**
Built: `skills/research-auto/scripts/admission.py` (`detect_admission_state` A-G, `build_admission_actions`, `validate_admission_action`, `run_front_door`, default-autonomy handling) + `tests/research-auto/test_admission.py`. Detailed design in `plan/2026-06-05-research-auto-front-door-intake.md`. `/research-auto` now discovers missing Step-3 formation, runs the R1-R3 roles up to the human gates, and stops — proposing through Triage but never ratifying or materializing from pending state. New Task proposals default to `autonomous`, surface all four dial choices before the user accepts, and reject invalid or internally inconsistent autonomy values. SKILL.md §"Stage 0.5" documents the state machine + the simplified `init → /research-auto → accept/reject` user story.

### Stage 1 — the missing **code role** (R3.5/R4 authoring + IMPLEMENTATION_REVIEW)
Insert author-code → two-layer IMPLEMENTATION_REVIEW, executing the prose at SKILL.md §240–261 before any run can launch.
- **Tasks:** (a) Code sub-agent (Opus tier) writes the experiment under TDD — failing test first (核心问题 #1). (b) **Correctness** review: dispatch the existing code-review path on `BASE_SHA..HEAD_SHA`; Critical/Important = blocking. (c) **Faithfulness** review: ask a distinct judge "does this code faithfully implement the hypothesis with no fabricated metric / hard-coded result / skipped condition?"; cross-family preferred, `degraded:true` only records reduced assurance and never upgrades a bad verdict. (d) Build `reviewer_verdict{producer, judge, result, scope_version, artifact_id, degraded}` and route `READY_TO_LAUNCH` through research-op — the existing `launch-needs-verdict` / `launch-acquits` gate rejects entry without a distinct-judge `sound` verdict. (e) Test: `IMPLEMENTING -> READY_TO_LAUNCH` without reviewer verdict is rejected; self-reviewed code is rejected; non-`sound` review is rejected; a hard-coded metric implementation is caught by faithfulness review and cannot launch.
- **Closes:** capability #3. This is the highest-value stage because every downstream claim needs real code first.

### Stage 2 — real run + artifact protocol *(replace prompt-supplied measured values)*
Wire R4 to execute the reviewed implementation, not `skeleton.experiment(measured=...)`.
- **Tasks:** (a) Launch the reviewed command in a named tmux session with cwd/env/runtime root recorded in tracker/resource allocation rows. (b) Require the run to write a typed metric artifact under `outputs/<pkg>/...`; the measured value is read only from that artifact. (c) Add an artifact scanner/adapter that converts completed runtime artifacts into result-gate payloads through research-op. (d) Test: prompt-supplied `measured` is ignored/rejected; missing artifact cannot verify or acquit; tampered artifact changes the verdict; runtime facts propagate atomically.
- **Closes:** capability #4 partial and unlocks capability #5 on real evidence.

### Stage 3 — real R5: L2 verifier over runtime artifacts
Replace the production loop's L1-only scalar verdict with `verifier.jury_request` + `verifier.assess_acquit` over the Stage-2 runtime artifacts. The lib is already tested; this stage is wiring + dispatch.
- **Tasks:** (a) Build file-paths-only jury requests over code diff, runtime artifact, result summary, and Scope yardstick. (b) Persist structured verdicts with `producer`, `judge`, `scope_version`, `artifact_id`, `result`; feed them to the existing `acquit-needs-verdict` / `acquit-judge-independent` gate. (c) At `autonomous`, if no cross-family judge is reachable, pause/fail-closed; do not terminal-acquit with `degraded:true`. (d) Test: fabricated/hard-coded metrics are refuted by the jury; non-`sound` verdict blocks success; autonomous same-family verdict blocks terminal acquit.
- **Closes:** capability #5 partial. Keeps `skeleton.run` as the L1 fixture, not the production path.

### Stage 4 — `dial.py` + `pack.py` + unattended driver-lite
Turn "runs once when called" into "can advance a reviewed run while the human is away."
- **Tasks:** (a) PACK tick: at Async/Autonomous, call `pack.write_pack` on every loop iteration — the blank-field reject is the no-silent-gap guarantee. (b) Driver-lite: monitor tmux/job state, detect completed/failed/stale runs, run artifact scanner, route next state through research-op, stop on acquit/archive/blocker. (c) Dial-revert: when a scope transition carries `dial_revert`, call `dial.revert_on_scope_change(tasks, transition)` and push reverted Tasks through research-op. (d) Readiness preflight gates loop entry by dial horizon. (e) Present-only QA: questions are recorded and acked but never block an absent reader. (f) Test: PACK missing field rejects; vanished run becomes BLOCKED with evidence; completed run routes to RESULT_ANALYSIS; scope transition reverts affected tasks to supervised.
- **Closes:** capabilities #4 and #7.

### Stage 5 — heavy R2 / R3 / R6 via the split skills
Make the loop *delegate* to `research-lit` / `research-ideate` / `research-write` instead of `skeleton`'s internal stubs.
- **R2 → research-lit:** real fetch (WebFetch/WebSearch) + synthesis; `lib/cite_check.unresolved_citations` still the hard gate; injection-scan banner treated as DATA.
- **R3 → research-ideate:** real hypothesis generation; scope-conditional `banlist`; **ranking jury** per `[[multi-agent-ranking-jury-design]]` (`lib/ranking`, independent sub-agent ids; already implemented and tested) selects top-K before adopting one.
- **R6 → research-write:** IMRAD from verified artifacts only; `lib/cite_check.ungrounded_claims` blocks any claim with no backing artifact id.
- **Tasks:** Procedure steps 1b/3/6 dispatch the skills with the Context Pack as compiled context; each returns a typed result the loop routes through research-op. Tests assert: unresolved cite rejected; banned idea not re-proposed; ungrounded claim blocked.
- **Closes:** capabilities #1, #2, #5 (full), #6.

### Stage 6 — self-learning loop
Wire `research-reflect` (read-only proposer: doom-loop / scope-thrash detectors) → `research-apply` (human-gated lander). Proposer ≠ applier is already enforced. Optionally fold in the two-store self-evolving design from `[[self-evolving-self-learning-design]]`.

## 5. Minimum credible "autonomous scientist on one direction"

**Cut line: Stage 0 + Stage 1 + Stage 2 + Stage 3 + Stage 4 driver-lite.** That yields a loop that: has a testable production dispatch seam → writes real code TDD-first → gets it correctness- and faithfulness-reviewed by a distinct judge → launches and monitors the reviewed code in tmux → reads measured values only from runtime artifacts → verifies the result with the L2 jury against the SSOT predicate → never leaves an absent reader with a silent gap. That is the minimum *honest* version for one already-scoped direction; Stage 5 and Stage 6 raise quality (literature, idea ranking, paper, self-learning) on top of the trustworthy spine.

## 6. Risks / open decisions

- **Cross-family availability.** `mcp__codex__codex` may be absent in headless/cron runs. Policy: for terminal acquit at `autonomous`, no reachable cross-family judge means **pause/fail-closed**; `degraded:true` may be recorded as diagnostic evidence, but it cannot produce a terminal success transition. For implementation launch review, cross-family is preferred-and-recorded while the existing launch gate requires distinct judge + `sound`.
- **Production-loop contract drift.** If Stage 0 remains prose-only, later stages will test helpers but not orchestration. Mitigation: keep fake-adapter driver tests as the acceptance gate for every role integration.
- **`skeleton.run` drift.** As heavy roles land, keep the fixture's contract in sync or it stops being a meaningful proof. Mitigation: the fixture's gate-ordering test is the invariant, not the stub bodies.
- **Token cost of the agent-driven loop.** Model-tiering (`[[workflow-model-tiering]]`) is the lever; Opus only for code + analysis roles.
- **Scope creep guard.** Each stage must trace to a capability in §3 and a 核心问题 goal; no gate added that no problem asks for.
