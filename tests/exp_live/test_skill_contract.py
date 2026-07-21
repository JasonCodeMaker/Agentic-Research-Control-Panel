import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "research-exp-live" / "SKILL.md"
CONTROLLER_TS = ROOT / "workflow.ts"
CLAUDE = ROOT / "CLAUDE.md"


def test_research_exp_live_skill_carries_adaptive_tracking_protocol():
    text = SKILL.read_text(encoding="utf-8")

    for phrase in (
        "Startup health gate",
        "first 30 minutes",
        "more than 60 minutes",
        "status.json",
        "lib.experiments.report",
        "lib.experiments.reconcile",
        "scan-events",
        "$RESEARCH_ROOT/experiments",
        "$RESEARCH_ROOT/state",
        "$RESEARCH_ROOT/interface",
        ".research/experiments/",
        ".research/state/",
        ".research/interface/",
        "$XDG_RUNTIME_DIR",
        "read-only",
        "Interface health",
        "Next Check",
    ):
        assert phrase in text

    for retired in (
        "research_html",
        "outputs/",
        "RESEARCH_RUNTIME_ROOT",
        "serve_dashboard.py",
        "lib/exp_live",
        "meta.json",
        "RUN_FAILED",
        "RUN_HALTED",
    ):
        assert retired not in text
    assert "ScheduleWakeup(" not in text
    assert "Monitor(" not in text


def test_exp_live_references_use_the_same_authority_boundary():
    references = SKILL.parent / "references"
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(references.glob("*.md"))
    )
    for phrase in (
        "$RESEARCH_ROOT/state",
        "$RESEARCH_ROOT/experiments",
        "$RESEARCH_ROOT/interface",
        "$XDG_RUNTIME_DIR",
        "read-only",
    ):
        assert phrase in text
    for retired in ("research_html", "outputs/", "RESEARCH_RUNTIME_ROOT"):
        assert retired not in text


def test_every_exp_live_reference_has_a_skill_caller():
    references = SKILL.parent / "references"
    available = {path.name for path in references.glob("*.md")}
    linked = set(re.findall(r"\(references/([^)]+\.md)\)", SKILL.read_text(encoding="utf-8")))

    assert linked == available


def test_protocol_hooks_preserve_workflow_and_add_wrapper_exception():
    workflow = CONTROLLER_TS.read_text(encoding="utf-8")
    claude = CLAUDE.read_text(encoding="utf-8")

    assert "Long experiments use `research-exp-live` when" in claude
    assert "Structured status is the routine source" in claude
    assert "cadenceMillis" in workflow
    assert "heartbeatTimeoutSeconds" in workflow
    assert "DashboardServerSnapshot" in workflow
    assert "ENSURE_DASHBOARD_SERVER" in workflow
    assert "buildStopGate" in workflow
