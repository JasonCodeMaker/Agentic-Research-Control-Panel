from __future__ import annotations

import json
import os
import signal
import socket
import sys
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = ROOT / "skills" / "research-init" / "scripts"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPT_DIR))

from lib.research_state import EventStore, ResearchPaths, StateQuery  # noqa: E402
import research_init  # noqa: E402


def _paths(tmp_path: Path) -> ResearchPaths:
    return ResearchPaths.resolve(workspace=tmp_path)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _setup_no_server(tmp_path: Path, skills_root: Path, **overrides):
    kwargs = {
        "agent": "codex",
        "merge_protocols": False,
        "skip_skill_install": False,
        "no_serve": True,
        "allow_external_research_root": False,
        "host": "127.0.0.1",
        "port": 8904,
        "max_port": 8999,
        "codex_root": skills_root,
    }
    kwargs.update(overrides)
    return research_init.setup_workspace(_paths(tmp_path), **kwargs)


def test_inspect_is_read_only_and_classifies_absent_workspace(tmp_path):
    skills_root = tmp_path / "codex-skills"

    report = research_init.inspect_workspace(
        _paths(tmp_path), agent="codex", codex_root=skills_root
    )

    assert report["arc"]["state"] == "ABSENT"
    assert report["setup_ready"] is False
    assert report["next_action"] == "run research-init setup"
    assert not (tmp_path / ".research").exists()
    assert not skills_root.exists()
    assert not (tmp_path / "AGENTS.md").exists()


def test_setup_initializes_attaches_installs_and_builds_without_scope(tmp_path):
    skills_root = tmp_path / "codex-skills"

    report = _setup_no_server(tmp_path, skills_root)

    assert report["ok"] is True
    assert report["arc_before"] == "ABSENT"
    assert report["setup_status"] == "READY_NO_PROJECT"
    assert report["server"]["status"] == "disabled-by-user"
    assert report["next_action"] == "use research-onboard"
    assert (_paths(tmp_path).interface / "index.html").is_file()
    assert StateQuery(_paths(tmp_path)).show("project")["data"] == {}
    for name in research_init.PROTOCOL_FILES:
        text = (tmp_path / name).read_text(encoding="utf-8")
        assert f"ARC-PROTOCOL:BEGIN source={name}" in text
        assert research_init.protocol_status(tmp_path, name)["status"] == "CURRENT"
    assert (skills_root / "research-init").resolve() == (
        ROOT / "skills" / "research-init"
    ).resolve()


def test_setup_is_idempotent_and_preserves_project_protocol_prefix(tmp_path):
    skills_root = tmp_path / "codex-skills"
    prefix = "# Project-specific rules\n\nKeep this text.\n"
    (tmp_path / "AGENTS.md").write_text(prefix, encoding="utf-8")

    with pytest.raises(research_init.InitBlocked) as blocked:
        _setup_no_server(tmp_path, skills_root)
    assert blocked.value.code == "PROTOCOL_REVIEW_REQUIRED"
    assert not (tmp_path / ".research").exists()
    assert not skills_root.exists()

    first = _setup_no_server(tmp_path, skills_root, merge_protocols=True)
    second = _setup_no_server(tmp_path, skills_root)

    assert first["protocols"]["AGENTS.md"] == "merged"
    assert second["protocols"] == {
        "AGENTS.md": "unchanged",
        "CLAUDE.md": "unchanged",
    }
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8").startswith(prefix)


def test_legacy_state_is_unsupported_and_setup_refuses_it_before_mutation(tmp_path):
    (tmp_path / "research_html").mkdir()
    skills_root = tmp_path / "codex-skills"

    inspection = research_init.inspect_workspace(
        _paths(tmp_path), agent="codex", codex_root=skills_root
    )

    with pytest.raises(research_init.InitBlocked) as blocked:
        _setup_no_server(tmp_path, skills_root)

    assert inspection["arc"]["state"] == "INVALID"
    assert "unsupported" in inspection["arc"]["detail"]
    assert blocked.value.code == "INVALID_RESEARCH_ROOT"
    assert not (tmp_path / ".research").exists()
    assert not skills_root.exists()
    assert not (tmp_path / "AGENTS.md").exists()


def test_cli_does_not_expose_legacy_migration(tmp_path):
    with pytest.raises(SystemExit):
        research_init.main(["--workspace", str(tmp_path), "migrate"])


def test_external_research_root_requires_explicit_permission(tmp_path):
    external = tmp_path.parent / f"{tmp_path.name}-external-state"
    paths = ResearchPaths.resolve(workspace=tmp_path, research_root=external)

    with pytest.raises(research_init.InitBlocked) as blocked:
        research_init.setup_workspace(
            paths,
            agent="codex",
            merge_protocols=False,
            skip_skill_install=True,
            no_serve=True,
            allow_external_research_root=False,
            host="127.0.0.1",
            port=8904,
            max_port=8999,
        )

    assert blocked.value.code == "EXTERNAL_RESEARCH_ROOT_REQUIRES_CONFIRMATION"
    assert not external.exists()


def test_check_reports_repair_required_when_default_server_is_missing(tmp_path):
    skills_root = tmp_path / "codex-skills"
    _setup_no_server(tmp_path, skills_root)

    strict = research_init.check_workspace(
        _paths(tmp_path), agent="codex", require_server=True, codex_root=skills_root
    )
    headless = research_init.check_workspace(
        _paths(tmp_path), agent="codex", require_server=False, codex_root=skills_root
    )
    inspection = research_init.inspect_workspace(
        _paths(tmp_path), agent="codex", codex_root=skills_root
    )

    assert strict["ok"] is False
    assert strict["setup_status"] == "REPAIR_REQUIRED"
    assert any(
        failure["code"] == "DASHBOARD_SERVER_UNHEALTHY"
        for failure in strict["failures"]
    )
    assert headless["ok"] is True
    assert headless["setup_status"] == "READY_NO_PROJECT"
    assert inspection["setup_ready"] is False
    assert inspection["next_action"] == (
        "run research-init setup to reconcile the reported setup gaps"
    )


def test_setup_starts_then_reuses_dashboard_and_reports_connection(
    tmp_path, monkeypatch
):
    runtime_root = tmp_path / "runtime"
    skills_root = tmp_path / "codex-skills"
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime_root))
    port = _free_port()
    pid = None
    try:
        first = _setup_no_server(
            tmp_path,
            skills_root,
            no_serve=False,
            port=port,
            max_port=port,
        )
        second = _setup_no_server(
            tmp_path,
            skills_root,
            no_serve=False,
            port=port,
            max_port=port,
        )
        pid = int(first["server"]["pid"])

        assert first["server"]["ok"] is True
        assert first["server"]["action"] == "started"
        assert first["server"]["health"] == "healthy"
        assert first["server"]["url"] == f"http://127.0.0.1:{port}/index.html"
        assert first["server"]["remote_access"] == (
            f"ssh -L {port}:127.0.0.1:{port} <host>"
        )
        assert "lib.interface.serve" in first["server"]["stop_command"]
        assert " stop --json" in first["server"]["stop_command"]
        assert second["server"]["action"] == "reused"
        assert second["server"]["pid"] == pid

        returncode, stopped, stderr = research_init._run_json(
            [
                sys.executable,
                "-m",
                "lib.interface.serve",
                "--workspace",
                str(tmp_path),
                "--research-root",
                str(_paths(tmp_path).root),
                "stop",
                "--json",
            ]
        )
        assert returncode == 0, stderr
        assert stopped["action"] == "stopped"
        assert stopped["health"] == "stopped"
        assert research_init.dashboard_status(_paths(tmp_path))["ok"] is False
        returncode, stopped_again, stderr = research_init._run_json(
            [
                sys.executable,
                "-m",
                "lib.interface.serve",
                "--workspace",
                str(tmp_path),
                "--research-root",
                str(_paths(tmp_path).root),
                "stop",
                "--json",
            ]
        )
        assert returncode == 0, stderr
        assert stopped_again["action"] == "already-stopped"
        pid = None
    finally:
        if pid is not None:
            os.kill(pid, signal.SIGTERM)
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.05)


def test_server_start_failure_returns_repair_required(tmp_path, monkeypatch):
    skills_root = tmp_path / "codex-skills"

    def fail_server(*args, **kwargs):
        research_init.build_interface(args[0])
        raise research_init.InitBlocked(
            "DASHBOARD_SERVER_FAILED", "synthetic server failure"
        )

    monkeypatch.setattr(research_init, "ensure_dashboard_server", fail_server)
    report = _setup_no_server(tmp_path, skills_root, no_serve=False)

    assert report["ok"] is False
    assert report["setup_status"] == "REPAIR_REQUIRED"
    assert report["server"]["action"] == "failed"
    assert report["server"]["health"] == "unhealthy"
    assert report["server"]["error"] == "DASHBOARD_SERVER_FAILED"
    assert (_paths(tmp_path).interface / "index.html").is_file()


def test_duplicate_protocol_blocks_are_a_hard_conflict(tmp_path):
    source, digest = research_init._protocol_source("AGENTS.md")
    block = research_init._protocol_block("AGENTS.md", source, digest)
    (tmp_path / "AGENTS.md").write_text(block + "\n" + block, encoding="utf-8")

    status = research_init.protocol_status(tmp_path, "AGENTS.md")

    assert status["status"] == "CONFLICT"
    assert status["detail"] == "multiple managed protocol blocks exist"


def test_cli_setup_emits_machine_readable_completion(tmp_path, capsys):
    skills_root = tmp_path / "codex-skills"

    rc = research_init.main(
        [
            "--workspace",
            str(tmp_path),
            "setup",
            "--no-serve",
            "--codex-skills-root",
            str(skills_root),
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["setup_status"] == "READY_NO_PROJECT"
    assert payload["server"]["action"] == "not-started"
