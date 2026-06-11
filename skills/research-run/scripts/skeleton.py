"""Stage-1 walking skeleton: one thin idea->verified-result pass through all six roles + the real gates.

Each role is thin/stub; what is real is the wiring — the scope write routes through the SSOT's
gated writer, R5 reads the yardstick back from the SSOT node, L1 cite-exists partitions citations,
and the terminal acquit routes through research-op's acquit gate at Supervised (T1 ack), blocked
when the metric oracle fails. Roles split into their own skills in Stage 2b (research-scope /
research-lit / research-ideate); the package execution controller is research-run.
"""

import json
import sys
from pathlib import Path

_PIPE = Path(__file__).resolve().parents[3]  # scripts -> research-run -> skills -> pipeline root
sys.path.insert(0, str(_PIPE / "lib"))
sys.path.insert(0, str(_PIPE / "skills" / "research-op" / "scripts"))
import scope_ssot  # noqa: E402
import validate  # noqa: E402


def scope(intent, pkg_id):
    """R1 (thin): turn a fixed intent into a typed Direction node (problem + yardstick)."""
    return {
        "id": f"dir/{pkg_id}",
        "level": "direction",
        "parents": ["project/main"],
        "version": 1,
        "status": "ACTIVE",
        "yardstick": {
            "hypothesis": intent,
            "metric": {"name": "toy_metric", "dir": "higher"},
            "baselines": ["baseline-0"],
            "success_predicate": "measured >= 0.80",
        },
        "provenance": "txn-0",
    }


def search_read(citations):
    """R2 + L1 cite-exists: partition citations by whether their source resolves on disk."""
    verified, rejected = [], []
    for c in citations:
        (verified if Path(c["source"]).exists() else rejected).append(c["id"])
    return verified, rejected


def ideate(node):
    """R3 (stub): adopt the direction's hypothesis as the idea under test."""
    return node["yardstick"]["hypothesis"]


def experiment(pkg_id, runtime_root, measured):
    """R4 (toy): run the experiment and persist its metric as a verified artifact on disk."""
    artifact_id = "exp-001"
    artifact_path = Path(runtime_root) / pkg_id / "artifacts" / f"{artifact_id}.json"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(
        json.dumps({"artifact_id": artifact_id, "metric": "toy_metric", "measured": measured}),
        encoding="utf-8")
    return {"artifact_id": artifact_id, "path": str(artifact_path)}


def verify(artifact_path, yardstick):
    """R5 L1 metric oracle: read the measured value from the artifact on disk, compare to the SSOT predicate."""
    artifact = json.loads(Path(artifact_path).read_text(encoding="utf-8"))  # missing artifact => no fabricated metric
    threshold = float(yardstick["success_predicate"].split(">=")[1].strip())
    measured = artifact["measured"]
    return {"judge": "L1-metric-oracle",
            "result": "PASS" if measured >= threshold else "FAIL",
            "measured": measured, "artifact_id": artifact["artifact_id"]}


def run(intent, *, pkg_id, runtime_root, citations, measured):
    """Drive one thin idea->verified-result pass through R1..R6 and the real gates. Returns the run record."""
    runtime_root = Path(runtime_root)
    log_path = runtime_root / "_scope" / "transitions.jsonl"
    chain = []

    node = scope(intent, pkg_id)
    scope_ssot.propose_transition(node, op="create", gate="USER_CROSS_MODEL_AUDIT", log_path=log_path,
                                  trigger=f"intent:{intent}", cause="R1 scope")
    chain.append("R1:scope")

    verified, rejected = search_read(citations)
    chain.append("R2:search")

    idea = ideate(node)
    chain.append("R3:ideate")

    artifact = experiment(pkg_id, runtime_root, measured)
    chain.append("R4:experiment")

    yardstick = node["yardstick"]  # read the bar from the SSOT node, not a prompt
    verdict = verify(artifact["path"], yardstick)  # read the number from the artifact, not a prompt
    chain.append("R5:verify")

    # R6 remember + terminal acquit at Supervised — gated by the L1 metric oracle.
    acquitted, ack_token = False, None
    if verdict["result"] == "PASS":
        payload = {
            "to_status": "ADOPTED_UNCONFIRMED", "to_category": "success",
            "ack_token": "T1:supervised-ack",
            "terminationMessage": f"measured={verdict['measured']} meets gate",
            "adoptionPath": "CLAUDE.md#current-best",
            "verdict": verdict,
        }
        rej = validate.validate(pkg_id, "update", "status", payload,
                                {"category": "in-progress", "status": "RESULT_ANALYSIS"})
        if rej is not None:
            raise RuntimeError(f"acquit unexpectedly blocked: {rej.rule}")
        acquitted, ack_token = True, "T1:supervised-ack"
    chain.append("R6:remember")

    record = {
        "chain": chain, "idea": idea, "yardstick": yardstick, "verdict": verdict,
        "verified_citations": verified, "rejected_citations": rejected,
        "acquitted": acquitted, "ack_token": ack_token,
    }
    (runtime_root / "run.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record
