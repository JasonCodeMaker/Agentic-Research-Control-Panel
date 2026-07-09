#!/usr/bin/env python3
"""Serve the research dashboard with a local live-run API.

The static dashboard is served from the repository root so existing URLs such
as /research_html/index.html keep working. Runtime files stay under outputs/;
the API reads them server-side so browser preview reloaders do not need to
watch the volatile outputs tree.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import json
import os
import shlex
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


TERMINAL = {"COMPLETED", "RUN_FAILED", "RUN_HALTED", "SKIPPED"}
DEFAULT_PORT = 8904
DEFAULT_MAX_PORT = 8999


def should_disable_cache(path: str) -> bool:
    """True for live API and self-refreshing dashboard data files."""
    parsed = urllib.parse.urlsplit(path)
    clean = parsed.path
    return (
        clean.startswith("/api/")
        or clean.endswith("/assets/live-data.js")
        or ("/data/" in clean and clean.endswith((".js", ".json")))
    )


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def read_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    if not path.exists():
        return records, errors
    for idx, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append({"line": idx, "message": str(exc)})
            continue
        if isinstance(obj, dict):
            records.append(obj)
    return records, errors


def fold_index(outputs_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records, errors = read_jsonl(outputs_root / "_live" / "runs.jsonl")
    folded: dict[str, dict[str, Any]] = {}
    for rec in records:
        run_id = rec.get("run_id")
        if not run_id:
            continue
        current = folded.setdefault(str(run_id), {})
        if rec.get("op") == "launched":
            current.update(rec)
            current["terminal"] = False
        elif rec.get("op") == "terminal":
            current.update(rec)
            current["terminal"] = True
    return list(folded.values()), errors


def safe_run_dir(repo_root: Path, outputs_root: Path, run: dict[str, Any]) -> Path | None:
    raw = run.get("dir")
    if not raw:
        return None
    path = Path(str(raw))
    if not path.is_absolute():
        path = repo_root / path
    resolved = path.resolve(strict=False)
    outputs_resolved = outputs_root.resolve(strict=False)
    try:
        resolved.relative_to(outputs_resolved)
    except ValueError:
        return None
    return resolved


def terminal_recent(run: dict[str, Any], now: float) -> bool:
    ended = run.get("ended_at")
    return bool(ended and now - float(ended) <= 7 * 24 * 3600)


def should_include_status(run: dict[str, Any], now: float) -> bool:
    if not run.get("terminal"):
        return True
    return terminal_recent(run, now)


def attach_status(repo_root: Path, outputs_root: Path, run: dict[str, Any]) -> dict[str, Any]:
    run = dict(run)
    run_dir = safe_run_dir(repo_root, outputs_root, run)
    if run_dir is None:
        run["status_error"] = "run dir missing or outside outputs root"
        return run
    status = read_json(run_dir / "status.json")
    if status:
        run["status"] = status
    return run


def state_path(outputs_root: Path) -> Path:
    return outputs_root / "_live" / "dashboard_server.json"


def server_state(
    *,
    repo_root: Path,
    outputs_root: Path,
    host: str,
    port: int,
    started_at: float,
    tmux_session: str | None,
    ok: bool = True,
    status: str = "running",
    error: str | None = None,
) -> dict[str, Any]:
    base = f"http://{host}:{port}"
    payload: dict[str, Any] = {
        "ok": ok,
        "status": status,
        "pid": os.getpid(),
        "host": host,
        "port": port,
        "repo_root": str(repo_root),
        "outputs_root": str(outputs_root),
        "url": f"{base}/research_html/index.html",
        "live_url": f"{base}/research_html/live.html",
        "api_base": f"{base}/api",
        "started_at": started_at,
        "tmux_session": tmux_session,
    }
    if error:
        payload["error"] = error
        payload["repair_required"] = True
    return payload


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(
        self,
        *args: Any,
        repo_root: Path,
        outputs_root: Path,
        started_at: float,
        tmux_session: str | None,
        **kwargs: Any,
    ) -> None:
        self.repo_root = repo_root
        self.outputs_root = outputs_root
        self.started_at = started_at
        self.tmux_session = tmux_session
        super().__init__(*args, directory=str(repo_root), **kwargs)

    def end_headers(self) -> None:
        if should_disable_cache(self.path):
            self.send_header("Cache-Control", "no-store")
        if self.path.startswith("/api/"):
            self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def write_json(self, payload: dict[str, Any], status: int = HTTPStatus.OK) -> None:
        body = (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def api_health(self) -> None:
        host, port = self.server.server_address[:2]
        self.write_json(
            server_state(
                repo_root=self.repo_root,
                outputs_root=self.outputs_root,
                host=str(host),
                port=int(port),
                started_at=self.started_at,
                tmux_session=self.tmux_session,
            )
        )

    def api_runs(self, query: dict[str, list[str]]) -> None:
        runs, errors = fold_index(self.outputs_root)
        include_status = query.get("include_status", ["0"])[0] in {"1", "true", "yes"}
        now = time.time()
        if include_status:
            runs = [
                attach_status(self.repo_root, self.outputs_root, run) if should_include_status(run, now) else run
                for run in runs
            ]
        self.write_json({"ok": True, "runs": runs, "errors": errors, "count": len(runs)})

    def api_status(self, run_id: str) -> None:
        runs, _ = fold_index(self.outputs_root)
        by_id = {str(run.get("run_id")): run for run in runs if run.get("run_id")}
        run = by_id.get(run_id)
        if not run:
            self.write_json({"ok": False, "error": "unknown run_id"}, status=HTTPStatus.NOT_FOUND)
            return
        run_dir = safe_run_dir(self.repo_root, self.outputs_root, run)
        if run_dir is None:
            self.write_json({"ok": False, "error": "run dir missing or outside outputs root"}, status=HTTPStatus.NOT_FOUND)
            return
        status = read_json(run_dir / "status.json")
        if not status:
            self.write_json({"ok": False, "error": "status.json not found"}, status=HTTPStatus.NOT_FOUND)
            return
        self.write_json({"ok": True, "run_id": run_id, "status": status})

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/health":
            self.api_health()
            return
        if parsed.path == "/api/live/runs":
            self.api_runs(urllib.parse.parse_qs(parsed.query))
            return
        prefix = "/api/live/status/"
        if parsed.path.startswith(prefix):
            run_id = urllib.parse.unquote(parsed.path[len(prefix):])
            self.api_status(run_id)
            return
        super().do_GET()


def check_health(url: str, repo_root: Path, timeout: float = 1.0) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or not payload.get("ok"):
        return None
    if Path(str(payload.get("repo_root", ""))).resolve(strict=False) != repo_root.resolve(strict=False):
        return None
    return payload


def port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def choose_port(host: str, start: int, end: int) -> int:
    for port in range(start, end + 1):
        if port_available(host, port):
            return port
    raise RuntimeError(f"no free dashboard port in {start}-{end}")


def tmux_session_exists(session: str) -> bool:
    if not shutil.which("tmux"):
        return False
    result = subprocess.run(["tmux", "has-session", "-t", f"={session}"], capture_output=True, text=True)
    return result.returncode == 0


def pick_tmux_session(repo_root: Path) -> str:
    digest = hashlib.sha1(str(repo_root).encode("utf-8")).hexdigest()[:8]
    base = f"research-dashboard-{digest}"
    if not tmux_session_exists(base):
        return base
    for idx in range(2, 20):
        candidate = f"{base}-{idx}"
        if not tmux_session_exists(candidate):
            return candidate
    raise RuntimeError("could not allocate dashboard tmux session name")


def start_background_server(
    *,
    repo_root: Path,
    outputs_root: Path,
    host: str,
    port: int,
) -> str | None:
    script = Path(__file__).resolve()
    outputs_root.mkdir(parents=True, exist_ok=True)
    log_path = outputs_root / "_live" / "dashboard_server.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    tmux_session = pick_tmux_session(repo_root) if shutil.which("tmux") else None
    cmd = [
        sys.executable,
        str(script),
        "--repo-root",
        str(repo_root),
        "--outputs-root",
        str(outputs_root),
        "serve",
        "--host",
        host,
        "--port",
        str(port),
    ]
    if tmux_session:
        cmd.extend(["--tmux-session", tmux_session])
        shell_cmd = " ".join(shlex.quote(part) for part in cmd)
        shell_cmd += f" >> {shlex.quote(str(log_path))} 2>&1"
        subprocess.run(["tmux", "new-session", "-d", "-s", tmux_session, "-c", str(repo_root), shell_cmd], check=True)
        return tmux_session

    log = log_path.open("a", encoding="utf-8")
    subprocess.Popen(cmd, cwd=str(repo_root), stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    return None


def emit(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, sort_keys=True))
    else:
        if payload.get("ok"):
            print(payload.get("live_url") or payload.get("url") or "dashboard server ok")
        else:
            print(payload.get("error") or "dashboard server unavailable", file=sys.stderr)


def command_serve(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve()
    outputs_root = (repo_root / args.outputs_root).resolve() if not Path(args.outputs_root).is_absolute() else Path(args.outputs_root).resolve()
    started_at = time.time()
    state = server_state(
        repo_root=repo_root,
        outputs_root=outputs_root,
        host=args.host,
        port=args.port,
        started_at=started_at,
        tmux_session=args.tmux_session,
    )
    atomic_json(state_path(outputs_root), state)
    handler = functools.partial(
        DashboardHandler,
        repo_root=repo_root,
        outputs_root=outputs_root,
        started_at=started_at,
        tmux_session=args.tmux_session,
    )
    with ThreadingHTTPServer((args.host, args.port), handler) as httpd:
        httpd.serve_forever()
    return 0


def command_ensure(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve()
    outputs_root = (repo_root / args.outputs_root).resolve() if not Path(args.outputs_root).is_absolute() else Path(args.outputs_root).resolve()
    existing = read_json(state_path(outputs_root))
    if existing.get("api_base"):
        health = check_health(str(existing["api_base"]) + "/health", repo_root, timeout=1.0)
        if health:
            emit(health, args.json)
            return 0

    try:
        port = choose_port(args.host, args.port, args.max_port)
        tmux_session = start_background_server(repo_root=repo_root, outputs_root=outputs_root, host=args.host, port=port)
        health_url = f"http://{args.host}:{port}/api/health"
        deadline = time.time() + args.timeout
        health = None
        while time.time() < deadline:
            health = check_health(health_url, repo_root, timeout=0.5)
            if health:
                if tmux_session and not health.get("tmux_session"):
                    health["tmux_session"] = tmux_session
                    atomic_json(state_path(outputs_root), health)
                emit(health, args.json)
                return 0
            time.sleep(0.2)
        raise RuntimeError(f"dashboard server did not become healthy at {health_url}")
    except Exception as exc:
        payload = server_state(
            repo_root=repo_root,
            outputs_root=outputs_root,
            host=args.host,
            port=args.port,
            started_at=time.time(),
            tmux_session=None,
            ok=False,
            status="error",
            error=str(exc),
        )
        atomic_json(state_path(outputs_root), payload)
        emit(payload, args.json)
        return 1


def command_status(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve()
    outputs_root = (repo_root / args.outputs_root).resolve() if not Path(args.outputs_root).is_absolute() else Path(args.outputs_root).resolve()
    existing = read_json(state_path(outputs_root))
    if existing.get("api_base"):
        health = check_health(str(existing["api_base"]) + "/health", repo_root, timeout=1.0)
        if health:
            emit(health, args.json)
            return 0
    payload = dict(existing) if existing else {
        "ok": False,
        "status": "missing",
        "repo_root": str(repo_root),
        "outputs_root": str(outputs_root),
        "error": "dashboard server state is missing",
        "repair_required": True,
    }
    payload["ok"] = False
    payload.setdefault("repair_required", True)
    emit(payload, args.json)
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=str(default_repo_root()))
    parser.add_argument("--outputs-root", default="outputs")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the dashboard HTTP server in the foreground")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve.add_argument("--tmux-session")
    serve.set_defaults(func=command_serve)

    ensure = sub.add_parser("ensure", help="start or reuse a healthy dashboard server")
    ensure.add_argument("--host", default="127.0.0.1")
    ensure.add_argument("--port", type=int, default=DEFAULT_PORT)
    ensure.add_argument("--max-port", type=int, default=DEFAULT_MAX_PORT)
    ensure.add_argument("--timeout", type=float, default=5.0)
    ensure.add_argument("--json", action="store_true")
    ensure.set_defaults(func=command_ensure)

    status = sub.add_parser("status", help="check the dashboard server recorded in outputs/_live")
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=command_status)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
