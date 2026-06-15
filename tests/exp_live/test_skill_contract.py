from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "research-exp-live" / "SKILL.md"
CONTROLLER_TS = ROOT / "workflow.ts"
CLAUDE = ROOT / "CLAUDE.md"


def test_research_exp_live_skill_carries_adaptive_tracking_protocol():
    text = SKILL.read_text(encoding="utf-8")

    for phrase in (
        "Startup health gate",
        "Evidence ladder",
        "Hard cap 60 min",
        "status.json",
        "report.py --open",
        "scan-events",
        "Scheduler-neutral",
        "must not report startup-confirmed",
        "Next Check",
        "serve_dashboard.py ensure --json",
        "repair_required",
        "Dashboard repair must not pause run monitoring",
    ):
        assert phrase in text

    assert "ScheduleWakeup(" not in text
    assert "Monitor(" not in text


def test_protocol_hooks_preserve_workflow_and_add_wrapper_exception():
    workflow = CONTROLLER_TS.read_text(encoding="utf-8")
    claude = CLAUDE.read_text(encoding="utf-8")

    assert "use the project live-run skill when available" in claude
    assert "structured runtime artifacts, not ad hoc raw scrollback parsing" in claude
    assert "cadenceMillis" in workflow
    assert "heartbeatTimeoutSeconds" in workflow
    assert "DashboardServerSnapshot" in workflow
    assert "ENSURE_DASHBOARD_SERVER" in workflow
    assert "buildStopGate" in workflow
