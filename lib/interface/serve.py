"""Serve only ``.research/interface`` plus read-only state/run APIs."""

from __future__ import annotations

import argparse
import functools
import json
import os
import signal
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
from typing import Any, Mapping

from lib.experiments.status import canonical_status
from lib.research_state import EventStore, ResearchPaths
from lib.research_state.io import write_json_atomic
from lib.research_state.paths import add_research_root_argument

from .build import build_interface
from .project import live_run_views, project_run_record


DEFAULT_PORT = 8904
DEFAULT_MAX_PORT = 8999


def static_document_root(paths: ResearchPaths) -> Path:
    """The server has exactly one static document root."""
    return paths.interface.resolve()


def should_disable_cache(path: str) -> bool:
    clean = urllib.parse.urlsplit(path).path
    return (
        clean.startswith("/api/")
        or clean.endswith("/assets/live-data.js")
        or ("/data/" in clean and clean.endswith((".js", ".json", ".jsonl")))
    )


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def safe_run_dir(
    paths: ResearchPaths,
    run_id: str,
    record: Mapping[str, Any],
) -> Path | None:
    package_id = record.get("package_id") or record.get("pkg")
    internal_experiment_id = record.get("experiment_id") or record.get("exp_id")
    if not package_id or not internal_experiment_id:
        return None
    experiment_id = (
        record.get("experiment_local_id")
        or record.get("local_experiment_id")
        or str(internal_experiment_id).rsplit("::", 1)[-1]
    )
    try:
        canonical = paths.run_dir(
            str(package_id), str(experiment_id), str(run_id)
        ).resolve(strict=False)
    except ValueError:
        return None
    try:
        canonical.relative_to(paths.experiments.resolve())
    except ValueError:
        return None
    raw = record.get("dir")
    if raw:
        candidate = Path(str(raw))
        if not candidate.is_absolute():
            # Run records store paths relative to RESEARCH_ROOT so the whole
            # managed tree remains relocatable, including when RESEARCH_ROOT
            # itself is outside the workspace.
            candidate = paths.root / candidate
        if candidate.resolve(strict=False) != canonical:
            return None
    return canonical


def _unavailable_status(
    run_id: str,
    record: Mapping[str, Any],
    detail: str,
) -> dict[str, Any]:
    projected = project_run_record(run_id, record)
    return {
        "ok": False,
        "run_id": run_id,
        "pkg": projected.get("pkg"),
        "exp_id": projected.get("exp_id"),
        "status": "UNKNOWN",
        "management_status": str(record.get("status") or "UNKNOWN"),
        "latest_metrics": {},
        "progress": {},
        "eta": "unknown",
        "status_error": detail,
    }


def _status_payload(
    paths: ResearchPaths,
    run_id: str,
    record: Mapping[str, Any],
) -> tuple[dict[str, Any], str | None]:
    run_dir = safe_run_dir(paths, run_id, record)
    if run_dir is None:
        error = "run dir is missing, non-canonical, or outside experiments root"
        return _unavailable_status(run_id, record, error), error
    status_path = run_dir / "status.json"
    if not status_path.is_file():
        error = f"status snapshot is missing: {status_path}"
        return _unavailable_status(run_id, record, error), error
    try:
        parsed = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        error = f"status snapshot is unreadable: {exc}"
        return _unavailable_status(run_id, record, error), error
    if not isinstance(parsed, dict):
        error = "status snapshot must be a JSON object"
        return _unavailable_status(run_id, record, error), error
    status = parsed
    projected = project_run_record(run_id, record)
    status.setdefault("run_id", run_id)
    status.setdefault("pkg", projected.get("pkg"))
    status.setdefault("exp_id", projected.get("exp_id"))
    try:
        canonical = canonical_status(status.get("status"))
    except ValueError as exc:
        error = f"status snapshot is invalid: {exc}"
        return _unavailable_status(run_id, record, error), error
    status["status"] = project_run_record(
        run_id, {**dict(record), "status": canonical}
    ).get("final_status") or canonical
    return status, None


def live_runs(paths: ResearchPaths, *, include_status: bool) -> tuple[list[dict[str, Any]], list[str]]:
    state = EventStore(paths).state()
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for row in live_run_views(state):
        run_id = str(row["run_id"])
        if include_status:
            status, error = _status_payload(paths, run_id, row)
            row["status"] = status
            if error:
                row["status_error"] = error
                errors.append(f"{run_id}: {error}")
        rows.append(row)
    return rows, errors


def server_state(
    *,
    paths: ResearchPaths,
    host: str,
    port: int,
    started_at: float,
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
        "workspace": str(paths.workspace),
        "research_root": str(paths.root),
        "document_root": str(static_document_root(paths)),
        "url": f"{base}/index.html",
        "live_url": f"{base}/live.html",
        "api_base": f"{base}/api",
        "started_at": started_at,
    }
    if error:
        payload["error"] = error
        payload["repair_required"] = True
    return payload


class DashboardHandler(SimpleHTTPRequestHandler):
    """Static interface handler with narrow read-only runtime endpoints."""

    def __init__(
        self,
        *args: Any,
        paths: ResearchPaths,
        started_at: float,
        **kwargs: Any,
    ) -> None:
        self.paths = paths
        self.started_at = started_at
        super().__init__(*args, directory=str(static_document_root(paths)), **kwargs)

    def end_headers(self) -> None:
        if should_disable_cache(self.path):
            self.send_header("Cache-Control", "no-store")
        if self.path.startswith("/api/"):
            self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def _write_json(self, value: Any, status: int = HTTPStatus.OK) -> None:
        body = (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode(
            "utf-8"
        )
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _run(self, run_id: str) -> Mapping[str, Any] | None:
        state = EventStore(self.paths).state()
        open_record = state.get("open_runs", {}).get(run_id)
        record = state.get("aggregates", {}).get("run", {}).get(run_id)
        if not isinstance(record, Mapping):
            return None
        if isinstance(open_record, Mapping):
            return {**dict(record), **dict(open_record)}
        projected = project_run_record(run_id, record)
        return projected if projected["terminal"] else None

    def _health(self) -> None:
        host, port = self.server.server_address[:2]
        self._write_json(
            server_state(
                paths=self.paths,
                host=str(host),
                port=int(port),
                started_at=self.started_at,
            )
        )

    def _runs(self, query: Mapping[str, list[str]]) -> None:
        include_status = query.get("include_status", ["0"])[0].lower() in {
            "1",
            "true",
            "yes",
        }
        rows, errors = live_runs(self.paths, include_status=include_status)
        self._write_json(
            {"ok": True, "runs": rows, "errors": errors, "count": len(rows)}
        )

    def _status(self, run_id: str) -> None:
        record = self._run(run_id)
        if record is None:
            self._write_json(
                {"ok": False, "error": "unknown run_id"},
                status=HTTPStatus.NOT_FOUND,
            )
            return
        status, error = _status_payload(self.paths, run_id, record)
        if error:
            self._write_json(
                status,
                status=HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return
        self._write_json(status)

    def _log(self, run_id: str) -> None:
        record = self._run(run_id)
        run_dir = (
            safe_run_dir(self.paths, run_id, record)
            if record is not None
            else None
        )
        log = run_dir / "log.txt" if run_dir is not None else None
        if log is None or not log.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "run log not found")
            return
        body = log.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/health":
            self._health()
            return
        if parsed.path == "/api/live/runs":
            self._runs(urllib.parse.parse_qs(parsed.query))
            return
        for prefix, handler in (
            ("/api/live/status/", self._status),
            ("/api/live/log/", self._log),
        ):
            if parsed.path.startswith(prefix):
                handler(urllib.parse.unquote(parsed.path[len(prefix) :]))
                return
        super().do_GET()


def make_handler(paths: ResearchPaths, *, started_at: float):
    return functools.partial(
        DashboardHandler,
        paths=paths,
        started_at=started_at,
    )


def _port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            connection.bind((host, port))
        except OSError:
            return False
    return True


def _choose_port(host: str, start: int, end: int) -> int:
    for port in range(start, end + 1):
        if _port_available(host, port):
            return port
    raise RuntimeError(f"no free dashboard port in {start}-{end}")


def _check_health(
    url: str, paths: ResearchPaths, *, timeout: float = 1.0
) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or not payload.get("ok"):
        return None
    if Path(str(payload.get("document_root", ""))).resolve() != static_document_root(
        paths
    ):
        return None
    return payload


def _paths(args: argparse.Namespace) -> ResearchPaths:
    return ResearchPaths.resolve(
        workspace=args.workspace,
        research_root=args.research_root,
    )


def _emit(payload: Mapping[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(dict(payload), ensure_ascii=False, sort_keys=True))
    elif payload.get("action") in {"stopped", "already-stopped"}:
        print(payload.get("action"))
    elif payload.get("ok"):
        print(payload.get("live_url") or payload.get("url"))
    else:
        print(payload.get("error") or "dashboard server unavailable", file=sys.stderr)


def _command_serve(args: argparse.Namespace) -> int:
    paths = _paths(args)
    paths.load_version()
    if not paths.interface.is_dir():
        build_interface(paths)
    started_at = time.time()
    state = server_state(
        paths=paths,
        host=args.host,
        port=args.port,
        started_at=started_at,
    )
    write_json_atomic(paths.dashboard_server_state, state)
    with ThreadingHTTPServer(
        (args.host, args.port), make_handler(paths, started_at=started_at)
    ) as server:
        server.serve_forever()
    return 0


def _start_background(paths: ResearchPaths, host: str, port: int) -> None:
    paths.runtime.mkdir(parents=True, exist_ok=True)
    log = (paths.runtime / "dashboard_server.log").open("a", encoding="utf-8")
    command = [
        sys.executable,
        "-m",
        "lib.interface.serve",
        "--workspace",
        str(paths.workspace),
        "--research-root",
        str(paths.root),
        "serve",
        "--host",
        host,
        "--port",
        str(port),
    ]
    environment = dict(os.environ)
    prior = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        str(Path(__file__).resolve().parents[2])
        + (os.pathsep + prior if prior else "")
    )
    subprocess.Popen(
        command,
        cwd=str(paths.workspace),
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        env=environment,
    )
    log.close()


def _command_ensure(args: argparse.Namespace) -> int:
    paths = _paths(args)
    paths.load_version()
    build_interface(paths)
    existing = _read_json(paths.dashboard_server_state)
    if existing.get("api_base"):
        healthy = _check_health(
            str(existing["api_base"]) + "/health", paths, timeout=1.0
        )
        if healthy:
            _emit(healthy, as_json=args.json)
            return 0
    port = _choose_port(args.host, args.port, args.max_port)
    try:
        _start_background(paths, args.host, port)
        health_url = f"http://{args.host}:{port}/api/health"
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            healthy = _check_health(health_url, paths, timeout=0.5)
            if healthy:
                _emit(healthy, as_json=args.json)
                return 0
            time.sleep(0.2)
        raise RuntimeError(f"dashboard server did not become healthy at {health_url}")
    except Exception as exc:
        payload = server_state(
            paths=paths,
            host=args.host,
            port=port,
            started_at=time.time(),
            ok=False,
            status="error",
            error=str(exc),
        )
        write_json_atomic(paths.dashboard_server_state, payload)
        _emit(payload, as_json=args.json)
        return 1


def _command_status(args: argparse.Namespace) -> int:
    paths = _paths(args)
    existing = _read_json(paths.dashboard_server_state)
    if existing.get("api_base"):
        healthy = _check_health(
            str(existing["api_base"]) + "/health", paths, timeout=1.0
        )
        if healthy:
            _emit(healthy, as_json=args.json)
            return 0
    payload = dict(existing) if existing else {
        "ok": False,
        "status": "missing",
        "workspace": str(paths.workspace),
        "research_root": str(paths.root),
        "document_root": str(static_document_root(paths)),
        "error": "dashboard server state is missing",
        "repair_required": True,
    }
    payload["ok"] = False
    payload.setdefault("repair_required", True)
    _emit(payload, as_json=args.json)
    return 1


def _command_stop(args: argparse.Namespace) -> int:
    """Stop only the healthy Dashboard recorded for this workspace."""
    paths = _paths(args)
    existing = _read_json(paths.dashboard_server_state)
    healthy = None
    if existing.get("api_base"):
        healthy = _check_health(
            str(existing["api_base"]) + "/health", paths, timeout=1.0
        )
    if healthy is None:
        payload = {
            **existing,
            "ok": True,
            "status": "stopped",
            "action": "already-stopped",
            "health": "stopped",
            "workspace": str(paths.workspace),
            "research_root": str(paths.root),
            "document_root": str(static_document_root(paths)),
        }
        _emit(payload, as_json=args.json)
        return 0

    try:
        pid = int(healthy["pid"])
    except (KeyError, TypeError, ValueError):
        payload = {
            **healthy,
            "ok": False,
            "status": "error",
            "action": "stop-failed",
            "error": "healthy Dashboard did not report a valid PID",
        }
        _emit(payload, as_json=args.json)
        return 1
    if pid <= 1 or pid == os.getpid():
        payload = {
            **healthy,
            "ok": False,
            "status": "error",
            "action": "stop-failed",
            "error": f"refusing to signal unsafe Dashboard PID: {pid}",
        }
        _emit(payload, as_json=args.json)
        return 1

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except PermissionError as exc:
        payload = {
            **healthy,
            "ok": False,
            "status": "error",
            "action": "stop-failed",
            "error": str(exc),
        }
        _emit(payload, as_json=args.json)
        return 1

    health_url = str(healthy["api_base"]) + "/health"
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        if _check_health(health_url, paths, timeout=0.2) is None:
            break
        time.sleep(0.1)
    else:
        payload = {
            **healthy,
            "ok": False,
            "status": "error",
            "action": "stop-failed",
            "error": f"Dashboard PID {pid} did not stop within {args.timeout:g}s",
        }
        _emit(payload, as_json=args.json)
        return 1

    stopped = {
        **healthy,
        "ok": False,
        "status": "stopped",
        "health": "stopped",
        "stopped_at": time.time(),
        "repair_required": False,
    }
    write_json_atomic(paths.dashboard_server_state, stopped)
    payload = {**stopped, "ok": True, "action": "stopped"}
    _emit(payload, as_json=args.json)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default=".")
    add_research_root_argument(parser)
    subcommands = parser.add_subparsers(dest="command", required=True)

    serve = subcommands.add_parser("serve", help="run the dashboard in the foreground")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve.set_defaults(func=_command_serve)

    ensure = subcommands.add_parser("ensure", help="build and start or reuse the dashboard")
    ensure.add_argument("--host", default="127.0.0.1")
    ensure.add_argument("--port", type=int, default=DEFAULT_PORT)
    ensure.add_argument("--max-port", type=int, default=DEFAULT_MAX_PORT)
    ensure.add_argument("--timeout", type=float, default=5.0)
    ensure.add_argument("--json", action="store_true")
    ensure.set_defaults(func=_command_ensure)

    status = subcommands.add_parser("status", help="check the recorded dashboard server")
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=_command_status)

    stop = subcommands.add_parser("stop", help="stop the recorded workspace dashboard")
    stop.add_argument("--timeout", type=float, default=5.0)
    stop.add_argument("--json", action="store_true")
    stop.set_defaults(func=_command_stop)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
