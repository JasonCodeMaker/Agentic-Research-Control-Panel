"""Stages 1-6 role wiring — the driver-side helpers that turn each research role's work into a
research-op envelope (or a verdict the gate reads), composing the already-built deterministic libs.

Nothing here writes a package surface: every function returns an envelope the driver routes through
research-op, or a structured verdict/decision the real gates (validate.py / verifier) judge. The heavy
intelligence (coding, fetching, judging) is the live sub-agent the driver dispatches; this module owns
the trust wiring around it.
"""

import json
import re
import sys
from pathlib import Path

_PIPE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PIPE / "lib"))
sys.path.insert(0, str(_PIPE / "skills" / "research-ideate" / "scripts"))
sys.path.insert(0, str(_PIPE / "skills" / "research-reflect" / "scripts"))
sys.path.insert(0, str(_PIPE / "skills" / "research-apply" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import verifier  # noqa: E402
import cite_check  # noqa: E402
import banlist  # noqa: E402
import reflect  # noqa: E402
import apply as apply_mod  # noqa: E402
import dial  # noqa: E402


# ---- Stage 1: code role + two-layer IMPLEMENTATION_REVIEW ----

def build_reviewer_verdict(producer, judge, *, result, scope_version, artifact_id, degraded=False):
    """Build the implementation reviewer verdict; refuse self-review (coder != reviewer) at construction."""
    if producer == judge:
        raise ValueError("coder may DRIVE review but never ACQUIT its own work (producer == judge)")
    return {"producer": producer, "judge": judge, "result": result,
            "scope_version": scope_version, "artifact_id": artifact_id, "degraded": degraded}


def launch_update_envelope(reviewer_verdict):
    """Status update entering READY_TO_LAUNCH, carrying the reviewer verdict the launch gate reads."""
    return {"op": "update", "target": "status",
            "payload": {"to_status": "READY_TO_LAUNCH", "reviewer_verdict": reviewer_verdict}}


# ---- Stage 2: real run + artifact protocol ----

def read_metric_artifact(path):
    """Read the runtime metric artifact; a missing artifact raises (never a fabricated metric)."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _verdict_for(measured, predicate):
    """Compute pass/fail for a `measured >= <float>` success predicate."""
    m = re.match(r"measured\s*>=\s*([0-9.]+)", predicate.strip())
    if not m:
        raise ValueError(f"unsupported predicate shape: {predicate!r}")
    return "pass" if float(measured) >= float(m.group(1)) else "fail"


def verdict_update_envelope(artifact, predicate):
    """Results-verdict envelope; the measured value comes only from the artifact, never a prompt."""
    measured = artifact["measured"]
    return {"op": "update", "target": "results-verdict",
            "payload": {"measured": measured, "verdict": _verdict_for(measured, predicate)}}


# ---- Stage 3: L2 cross-model jury over runtime artifacts ----

def build_jury_request(artifact_paths, question, *, judge_model):
    """File-paths-only jury request for the cross-model judge (content is never inlined)."""
    return verifier.jury_request(artifact_paths, question, judge_model=judge_model)


def acquit_update_envelope(verdict, autonomy_level, *, termination_message, adoption_path, ack_token):
    """Acquit (cross into success) envelope; the acquit gate enforces judge independence for the dial."""
    return {"op": "update", "target": "status",
            "payload": {"to_category": "success", "to_status": "ADOPTED_PENDING_ACK",
                        "verdict": verdict, "autonomy_level": autonomy_level,
                        "terminationMessage": termination_message, "adoptionPath": adoption_path,
                        "ack_token": ack_token}}


# ---- Stage 4: dial revert + unattended run monitor ----

def dial_revert(tasks, transition):
    """Revert dial-affected Tasks to Supervised and emit one scope-transition envelope per reverted Task."""
    reverted = dial.revert_on_scope_change(tasks, transition)
    affected = set(transition.get("dial_revert", [])) if transition.get("level") in ("direction", "project") else set()
    envs = [{"op": "scope-transition", "target": t["id"],
             "payload": {"autonomy_level": "supervised", "locked": True, "cause": "dial-revert"}}
            for t in reverted if t["id"] in affected]
    return reverted, envs


def monitor_run(run_state, *, exp_id):
    """Route an observed run state to the next-status envelope(s) for the unattended driver-lite."""
    if run_state == "completed":
        return [{"op": "update", "target": "status", "payload": {"to_status": "RESULT_ANALYSIS"}}]
    if run_state in ("failed", "vanished", "stale"):
        return [{"op": "update", "target": "status", "payload": {"to_status": "BLOCKED"}},
                {"op": "update", "target": "currentBlocker",
                 "payload": {"value": f"run {exp_id} {run_state}"}}]
    return []  # running — keep going


# ---- Stage 5: heavy R2/R3 deterministic gates ----

def screen_citations(citations, source_ids):
    """R2 fetch-don't-fabricate: partition citation ids into (verified, rejected) by resolved source."""
    rejected = cite_check.unresolved_citations(citations, source_ids)
    verified = [c["id"] for c in citations if c["id"] not in set(rejected)]
    return verified, rejected


def filter_banned(candidates, banlist_entries):
    """R3 scope-conditional banlist: drop currently-banned candidate idea ids."""
    return banlist.allowed(candidates, banlist_entries)


# ---- Stage 6: self-learning proposer (read-only) + applier (human-gated) ----

def run_reflection(*, actions, transitions, cross_failures):
    """Read-only proposer: surface doom-loops / scope-thrash / cross-package dead-ends. Lands nothing."""
    findings = []
    if reflect.detect_doom_loop(actions):
        findings.append({"kind": "doom-loop"})
    if reflect.detect_scope_thrash(transitions):
        findings.append({"kind": "scope-thrash"})
    if reflect.detect_cross_package_dead_end(cross_failures):
        findings.append({"kind": "cross-package-dead-end"})
    return findings


def land_proposal(proposal_dir, *, human_token, jury_verdict, rules_path):
    """Human-gated applier: land a staged proposal — refuses without a human action + a sound verdict."""
    return apply_mod.apply(proposal_dir, human_token=human_token,
                           jury_verdict=jury_verdict, rules_path=rules_path)
