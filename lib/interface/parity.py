#!/usr/bin/env python3
"""Frozen DOM, CSS, and visual regression contract for the human interface."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable

from lib.research_state import EventStore, ResearchPaths

from .build import build_interface


PIPELINE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = (
    PIPELINE_ROOT
    / "skills"
    / "research-dashboard"
    / "assets"
    / "interface-contract.json"
)
ACTOR = {"type": "system", "id": "interface-regression-fixture"}
HTML_FILES = (
    "index.html",
    "live.html",
    "scope.html",
    "learnings.html",
    "module.html",
    "brainstorm/2026-07-20-fixture-brainstorm.html",
    "packages/fixture/index.html",
    "packages/fixture/plan.html",
    "packages/fixture/implementation.html",
    "packages/fixture/results.html",
    "packages/fixture/analysis.html",
    "packages/fixture/tracker.html",
    "packages/fixture/docs/index.html",
)
CSS_FILES = ("assets/research.css", "assets/toc.css", "assets/brainstorm.css")
VISUAL_PAGES = (
    "index.html",
    "live.html",
    "scope.html",
    "learnings.html",
    "module.html?package=fixture&module=plan",
    "brainstorm/2026-07-20-fixture-brainstorm.html",
    "packages/fixture/index.html",
    "packages/fixture/plan.html",
    "packages/fixture/implementation.html",
    "packages/fixture/results.html",
    "packages/fixture/analysis.html",
    "packages/fixture/tracker.html",
    "packages/fixture/docs/index.html",
)
SCREENSHOT_VIEWPORT = {
    "width": 1440,
    "height": 1200,
    "device_scale_factor": 1,
}
SCREENSHOT_POLICY = {
    "timezone": "UTC",
    "locale": "C.UTF-8",
    "language": "en-US",
    "reduced_motion": "reduce",
    "color_profile": "srgb",
    "animation_policy": "virtual-time-budget-2000ms",
}
SCREENSHOT_FLAGS = (
    "--headless=new",
    "--no-sandbox",
    "--disable-background-networking",
    "--disable-default-apps",
    "--disable-extensions",
    "--disable-sync",
    "--hide-scrollbars",
    "--disable-lcd-text",
    "--force-device-scale-factor=1",
    "--force-color-profile=srgb",
    "--force-prefers-reduced-motion=reduce",
    "--lang=en-US",
    "--run-all-compositor-stages-before-draw",
    "--window-size=1440,1200",
    "--virtual-time-budget=2000",
)
FONT_QUERIES = (
    "system-ui",
    "ui-serif",
    "ui-monospace",
    "Georgia",
    "Times New Roman",
    "Arial",
    "sans-serif",
    "serif",
    "monospace",
)
_CONTRACT_CACHE: dict[tuple[str, bool, str], Any] = {}
_CONTRACT_CACHE_LOCK = threading.Lock()


class InterfaceRegression(RuntimeError):
    """The generated interface departed from the frozen human contract."""


class _DOMSignature(HTMLParser):
    """Record hierarchy, selectors, and human-visible static text."""

    ATTRIBUTES = {"id", "class", "href", "src", "name", "type", "role"}
    NON_VISIBLE_TEXT = {"script", "style", "template"}

    def __init__(
        self,
        *,
        attribute_normalizer: Callable[[str, str], str] | None = None,
        text_normalizer: Callable[[str], str] | None = None,
        ignore_text: Callable[[str, dict[str, str]], bool] | None = None,
    ) -> None:
        super().__init__(convert_charrefs=True)
        self.tokens: list[Any] = []
        self._stack: list[str] = []
        self._ignore_text_stack: list[bool] = []
        self._attribute_normalizer = attribute_normalizer
        self._text_normalizer = text_normalizer
        self._ignore_text = ignore_text

    def _attrs(self, attrs: list[tuple[str, str | None]]) -> list[list[str]]:
        selected = []
        for name, value in attrs:
            if (
                name in self.ATTRIBUTES
                or name.startswith("data-")
                or name.startswith("aria-")
            ):
                normalized = value or ""
                if self._attribute_normalizer is not None:
                    normalized = self._attribute_normalizer(name, normalized)
                selected.append([name, normalized])
        return sorted(selected)

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self.tokens.append(["start", tag, self._attrs(attrs)])
        self._stack.append(tag)
        raw_attrs = {name: value or "" for name, value in attrs}
        inherited = self._ignore_text_stack[-1] if self._ignore_text_stack else False
        local = (
            self._ignore_text(tag, raw_attrs)
            if self._ignore_text is not None
            else False
        )
        self._ignore_text_stack.append(inherited or local)

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self.tokens.append(["empty", tag, self._attrs(attrs)])

    def handle_endtag(self, tag: str) -> None:
        self.tokens.append(["end", tag])
        if self._stack:
            # Well-formed generated HTML follows a stack discipline.  The
            # fallback keeps the signature deterministic for legacy fragments.
            if self._stack[-1] == tag:
                self._stack.pop()
                self._ignore_text_stack.pop()
            elif tag in self._stack:
                reverse_index = self._stack[::-1].index(tag)
                index = len(self._stack) - reverse_index - 1
                self._stack = self._stack[:index]
                self._ignore_text_stack = self._ignore_text_stack[:index]

    def handle_data(self, data: str) -> None:
        if any(tag in self.NON_VISIBLE_TEXT for tag in self._stack):
            return
        if self._ignore_text_stack and self._ignore_text_stack[-1]:
            return
        normalized = " ".join(data.split())
        if normalized and self._text_normalizer is not None:
            normalized = self._text_normalizer(normalized)
        if normalized:
            self.tokens.append(["text", normalized])


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _dom_digest_text(
    text: str,
    *,
    attribute_normalizer: Callable[[str, str], str] | None = None,
    text_normalizer: Callable[[str], str] | None = None,
    ignore_text: Callable[[str, dict[str, str]], bool] | None = None,
) -> str:
    parser = _DOMSignature(
        attribute_normalizer=attribute_normalizer,
        text_normalizer=text_normalizer,
        ignore_text=ignore_text,
    )
    parser.feed(text)
    parser.close()
    raw = json.dumps(
        parser.tokens,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256(raw)


def dom_digest(path: Path) -> str:
    return _dom_digest_text(path.read_text(encoding="utf-8"))


def _seed_fixture(paths: ResearchPaths) -> None:
    EventStore(paths).initialize()
    # This is a deterministic projection fixture, not a management write
    # path. Fixture mode makes that exceptional seed explicit while the
    # production store rejects generic Scope mutations.
    store = EventStore(paths, fixture_mode=True)
    store.commit(
        event_type="AggregateUpserted",
        aggregate_type="project",
        aggregate_id="project/fixture",
        payload={
            "record": {
                "id": "project/fixture",
                "level": "project",
                "parents": [],
                "version": 1,
                "status": "ACTIVE",
                "source": "interface-parity-fixture",
                "spec": {"objective": "Frozen interface regression fixture."},
            }
        },
        actor=ACTOR,
        idempotency_key="interface-fixture:project",
        expected_version=0,
    )
    store.commit(
        event_type="AggregateUpserted",
        aggregate_type="direction",
        aggregate_id="direction/fixture",
        payload={
            "record": {
                "id": "direction/fixture",
                "level": "direction",
                "parents": ["project/fixture"],
                "version": 1,
                "status": "ACTIVE",
                "source": "interface-parity-fixture",
                "spec": {
                    "hypothesis": "The fixture preserves the current layout.",
                    "metric": {"name": "layout_parity", "dir": "higher"},
                    "success_gate": "layout_parity = 1",
                },
            }
        },
        actor=ACTOR,
        idempotency_key="interface-fixture:direction",
        expected_version=0,
    )
    brainstorm_body = store.write_note(
        (
            '<section class="doc-section" id="core-question">'
            '<h2><span class="section-number">01 </span>'
            '<span>Core question</span></h2>'
            '<p>Can one governed draft preserve a broad direction while its '
            'dependent stages are refined?</p>'
            '<div class="doc-callout"><strong>Authority boundary</strong>'
            '<p>This document cannot authorize execution.</p></div></section>'
            '<section class="doc-section wide" id="stages">'
            '<h2><span class="section-number">02 </span>'
            '<span>Dependent stages</span></h2>'
            '<div class="table-wrap"><table class="doc-table">'
            '<caption>One direction, several stages</caption><thead><tr>'
            '<th scope="col">Stage</th><th scope="col">Decision</th>'
            '</tr></thead><tbody><tr><td>Reproduction</td>'
            '<td>Verify the mechanism.</td></tr><tr><td>Migration</td>'
            '<td>Test the same claim in the target task.</td></tr></tbody>'
            '</table></div></section>'
        ),
        mime="text/html;profile=brainstorm-fragment",
        title="fixture Brainstorm body",
    )
    store.commit(
        event_type="BrainstormCreated",
        aggregate_type="brainstorm",
        aggregate_id="fixture-brainstorm",
        payload={
            "record": {
                "id": "fixture-brainstorm",
                "title": "One revisable Brainstorm document",
                "idea": "Keep one broad direction in one governed draft.",
                "abstract": (
                    "Test the document contract that keeps related reproduction, "
                    "migration, audit, and risk work together until explicit promotion."
                ),
                "idea_snapshot": [
                    {"label": "Core question", "value": "Can one draft stay coherent?"},
                    {"label": "Authority", "value": "Pre-package only"},
                ],
                "document_note": brainstorm_body,
                "created_at": "2026-07-20T00:00:00+00:00",
                "updated_at": "2026-07-20T00:00:00+00:00",
                "page_language": "en",
                "status": "ACTIVE",
                "detailPath": "brainstorm/2026-07-20-fixture-brainstorm.html",
            }
        },
        actor=ACTOR,
        idempotency_key="interface-fixture:brainstorm",
        expected_version=0,
    )
    store.commit(
        event_type="AggregateUpserted",
        aggregate_type="package",
        aggregate_id="fixture",
        payload={
            "record": {
                "id": "fixture",
                "slug": "fixture",
                "name": "Interface Regression Fixture",
                "direction_id": "direction/fixture",
                "lifecycle": "ACTIVE",
                "phase": "READY_TO_LAUNCH",
                "blocker": None,
                "sourceDirection": "direction/fixture",
                "sourceVersion": 1,
                "sourceChange": "interface-fixture:direction",
                "sourceExperiments": [
                    {
                        "id": "fixture::layout",
                        "version": 1,
                        "source": "interface-parity-fixture",
                    }
                ],
                "problem": "Preserve the existing human interface.",
                "objective": "Detect structural or visual drift.",
                "hypothesis": "The new data authority does not redesign the UI.",
                "primaryMetric": "layout_parity",
                "baseline": "Frozen interface contract",
                "budget": "one deterministic fixture",
                "noChangeBoundary": "DOM hierarchy, selectors, classes, and CSS",
                "lastAction": "Run interface parity",
                "lastUpdated": "2026-07-20",
            }
        },
        actor=ACTOR,
        idempotency_key="interface-fixture:package",
        expected_version=0,
    )
    store.commit(
        event_type="AggregateUpserted",
        aggregate_type="experiment",
        aggregate_id="fixture::layout",
        payload={
            "record": {
                "id": "layout",
                "local_id": "layout",
                "package_id": "fixture",
                "direction_id": "direction/fixture",
                "status": "READY",
                "scope_status": "ACTIVE",
                "scope_confirmation": "CONFIRMED",
                "scope_version": 1,
                "scope_source": "interface-parity-fixture",
                "confirmed_direction_version": 1,
                "aliases": ["layout"],
                "spec": {
                    "purpose": "Verify frozen layout",
                    "config_ref": "interface-contract.json",
                    "gate": "layout_parity = 1",
                    "control_mode": "SUPERVISED",
                },
            }
        },
        actor=ACTOR,
        idempotency_key="interface-fixture:experiment",
        expected_version=0,
    )


def _build_fixture(workspace: Path) -> ResearchPaths:
    paths = ResearchPaths.resolve(workspace=workspace)
    _seed_fixture(paths)
    build_interface(paths)
    return paths


def _chromium() -> Path:
    executable = shutil.which("chromium") or shutil.which("chromium-browser")
    if not executable:
        raise InterfaceRegression(
            "visual regression requires chromium or chromium-browser"
        )
    return Path(executable)


def _browser_version(executable: Path) -> str:
    result = subprocess.run(
        [str(executable), "--version"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    version = " ".join((result.stdout or result.stderr).split())
    if not version:
        raise InterfaceRegression("chromium returned an empty version")
    return version


def _browser_major(executable: Path) -> int:
    version = _browser_version(executable)
    match = re.search(r"\b(\d+)(?:\.\d+){2,}\b", version)
    if not match:
        raise InterfaceRegression(f"cannot parse browser version: {version!r}")
    return int(match.group(1))


def _fingerprint(value: dict[str, Any]) -> dict[str, Any]:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {**value, "sha256": _sha256(payload)}


def _tool_version(command: list[str]) -> str:
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise InterfaceRegression(
            f"cannot inspect rendering dependency {command[0]!r}: {exc}"
        ) from exc
    return " ".join((result.stdout or result.stderr).split())


def _font_contract() -> dict[str, Any]:
    executable = shutil.which("fc-match")
    if not executable:
        raise InterfaceRegression("font fingerprint requires fc-match")
    matches: dict[str, Any] = {}
    for query in FONT_QUERIES:
        result = subprocess.run(
            [
                executable,
                "--format=%{file}\\t%{family}\\t%{style}\\n",
                query,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        line = result.stdout.splitlines()[0] if result.stdout.splitlines() else ""
        fields = line.split("\t", 2)
        if len(fields) != 3 or not fields[0]:
            raise InterfaceRegression(f"fc-match returned no font for {query!r}")
        path = Path(fields[0])
        if not path.is_file():
            raise InterfaceRegression(f"matched font is missing: {path}")
        matches[query] = {
            "file": str(path),
            "family": fields[1],
            "style": fields[2],
            "file_sha256": _sha256(path.read_bytes()),
        }
    return _fingerprint(
        {
            "fontconfig_version": _tool_version([executable, "--version"]),
            "matches": matches,
        }
    )


def _runtime_contract() -> dict[str, Any]:
    try:
        import PIL
    except ImportError as exc:
        raise InterfaceRegression("runtime fingerprint requires Pillow") from exc
    os_release = Path("/etc/os-release")
    return _fingerprint(
        {
            "python_implementation": platform.python_implementation(),
            "python_version": platform.python_version(),
            "platform_system": platform.system(),
            "platform_machine": platform.machine(),
            "libc": list(platform.libc_ver()),
            "pillow_version": PIL.__version__,
            "os_release_sha256": (
                _sha256(os_release.read_bytes()) if os_release.is_file() else None
            ),
        }
    )


def _render_environment(executable: Path) -> dict[str, Any]:
    browser_version = _browser_version(executable)
    return {
        "browser_version": browser_version,
        "browser_major": _browser_major(executable),
        "screenshot_policy": dict(SCREENSHOT_POLICY),
        "screenshot_flags": list(SCREENSHOT_FLAGS),
        "viewport": dict(SCREENSHOT_VIEWPORT),
        "fonts": _font_contract(),
        "runtime": _runtime_contract(),
    }


def _render_environment_fingerprint(environment: dict[str, Any]) -> str:
    return _sha256(
        json.dumps(
            environment,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _visual_digest(image_path: Path) -> str:
    try:
        from PIL import Image
    except ImportError as exc:
        raise InterfaceRegression("visual regression requires Pillow") from exc
    with Image.open(image_path) as image:
        pixels = list(
            image.convert("L").resize((32, 32), Image.Resampling.LANCZOS).getdata()
        )
    mean = sum(pixels) / len(pixels)
    bits = "".join("1" if pixel >= mean else "0" for pixel in pixels)
    return f"{int(bits, 2):0256x}"


def _screenshot(
    executable: Path,
    interface_root: Path,
    relative_url: str,
    destination: Path,
) -> None:
    url = (interface_root / relative_url.split("?", 1)[0]).resolve().as_uri()
    if "?" in relative_url:
        url += "?" + relative_url.split("?", 1)[1]
    environment = dict(os.environ)
    environment.update(
        {
            "TZ": "UTC",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "LANGUAGE": "en",
        }
    )
    subprocess.run(
        [
            str(executable),
            *SCREENSHOT_FLAGS,
            f"--screenshot={destination}",
            url,
        ],
        check=True,
        capture_output=True,
        env=environment,
        timeout=30,
    )


def _hamming(left: str, right: str) -> int:
    return (int(left, 16) ^ int(right, 16)).bit_count()


@dataclass(frozen=True)
class ParityResult:
    browser_major: int
    browser_version: str
    dom_files: int
    css_files: int
    visual_pages: int
    font_fingerprint: str
    runtime_fingerprint: str


def build_contract(*, include_visual: bool = True) -> dict[str, Any]:
    """Build the deterministic fixture and return its frozen fingerprints."""
    with tempfile.TemporaryDirectory(
        prefix=".research-interface-contract-",
        dir=PIPELINE_ROOT,
    ) as raw:
        workspace = Path(raw)
        paths = _build_fixture(workspace)
        contract: dict[str, Any] = {
            "schema_version": 2,
            "viewport": dict(SCREENSHOT_VIEWPORT),
            "dom": {
                relative: dom_digest(paths.interface / relative)
                for relative in HTML_FILES
            },
            "css": {
                relative: _sha256((paths.interface / relative).read_bytes())
                for relative in CSS_FILES
            },
            "visual_digest": "mean-threshold-32x32-v1",
            "visual_max_hamming": 8,
            "visual": {},
        }
        if include_visual:
            executable = _chromium()
            environment = _render_environment(executable)
            contract.update(environment)
            contract["render_environment_sha256"] = (
                _render_environment_fingerprint(environment)
            )
            screenshot_root = workspace / "screenshots"
            screenshot_root.mkdir()
            for index, relative in enumerate(VISUAL_PAGES):
                destination = screenshot_root / f"{index:02d}.png"
                _screenshot(executable, paths.interface, relative, destination)
                contract["visual"][relative] = _visual_digest(destination)
        return contract


def check_contract(
    contract_path: Path = DEFAULT_CONTRACT,
    *,
    include_visual: bool = True,
) -> ParityResult:
    """Fail closed on any non-whitelisted DOM, CSS, or screenshot drift."""
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    if contract.get("schema_version") != 2:
        raise InterfaceRegression("unknown interface contract schema version")
    coverage_failures: list[str] = []
    if set(contract.get("dom", {})) != set(HTML_FILES):
        coverage_failures.append("DOM contract does not cover the frozen page set")
    if set(contract.get("css", {})) != set(CSS_FILES):
        coverage_failures.append("CSS contract does not cover the frozen asset set")
    if set(contract.get("visual", {})) != set(VISUAL_PAGES):
        coverage_failures.append("visual contract does not cover the frozen page set")
    if contract.get("visual_digest") != "mean-threshold-32x32-v1":
        coverage_failures.append("visual digest policy changed")
    if contract.get("visual_max_hamming") != 8:
        coverage_failures.append("visual drift tolerance changed")
    if contract.get("viewport") != SCREENSHOT_VIEWPORT:
        coverage_failures.append("viewport policy changed")
    if coverage_failures:
        raise InterfaceRegression("; ".join(coverage_failures))
    with tempfile.TemporaryDirectory(
        prefix=".research-interface-parity-",
        dir=PIPELINE_ROOT,
    ) as raw:
        workspace = Path(raw)
        paths = _build_fixture(workspace)
        failures: list[str] = []
        for relative, expected in contract.get("dom", {}).items():
            actual = dom_digest(paths.interface / relative)
            if actual != expected:
                failures.append(f"DOM contract changed: {relative}")
        for relative, expected in contract.get("css", {}).items():
            actual = _sha256((paths.interface / relative).read_bytes())
            if actual != expected:
                failures.append(f"CSS changed: {relative}")

        visual_count = 0
        browser_major = 0
        browser_version = ""
        font_fingerprint = ""
        runtime_fingerprint = ""
        if include_visual:
            executable = _chromium()
            environment = _render_environment(executable)
            browser_major = int(environment["browser_major"])
            browser_version = str(environment["browser_version"])
            font_fingerprint = str(environment["fonts"]["sha256"])
            runtime_fingerprint = str(environment["runtime"]["sha256"])
            expected_environment = {
                key: contract.get(key)
                for key in (
                    "browser_version",
                    "browser_major",
                    "screenshot_policy",
                    "screenshot_flags",
                    "viewport",
                    "fonts",
                    "runtime",
                )
            }
            if environment != expected_environment:
                for key in expected_environment:
                    if environment.get(key) != expected_environment.get(key):
                        failures.append(f"render environment mismatch: {key}")
            expected_fingerprint = str(
                contract.get("render_environment_sha256") or ""
            )
            actual_fingerprint = _render_environment_fingerprint(environment)
            if actual_fingerprint != expected_fingerprint:
                failures.append("render environment fingerprint mismatch")
            expected_version = str(contract.get("browser_version") or "")
            if browser_version != expected_version:
                failures.append(
                    f"fixed browser mismatch: expected {expected_version!r}, "
                    f"got {browser_version!r}"
                )
            if not failures:
                screenshot_root = workspace / "screenshots"
                screenshot_root.mkdir()
                threshold = int(contract.get("visual_max_hamming", 0))
                for index, (relative, expected) in enumerate(
                    contract.get("visual", {}).items()
                ):
                    destination = screenshot_root / f"{index:02d}.png"
                    _screenshot(executable, paths.interface, relative, destination)
                    actual = _visual_digest(destination)
                    distance = _hamming(actual, expected)
                    if distance > threshold:
                        failures.append(
                            f"visual drift: {relative} "
                            f"(hamming={distance}, max={threshold})"
                        )
                    visual_count += 1
        if failures:
            raise InterfaceRegression("; ".join(failures))
        return ParityResult(
            browser_major=browser_major,
            browser_version=browser_version,
            dom_files=len(contract.get("dom", {})),
            css_files=len(contract.get("css", {})),
            visual_pages=visual_count,
            font_fingerprint=font_fingerprint,
            runtime_fingerprint=runtime_fingerprint,
        )


def clear_contract_cache() -> None:
    """Clear the process-local parity cache (primarily for tests)."""
    with _CONTRACT_CACHE_LOCK:
        _CONTRACT_CACHE.clear()


def cached_check_contract(
    contract_path: Path = DEFAULT_CONTRACT,
    *,
    include_visual: bool = True,
) -> ParityResult:
    """Check once per exact contract and rendering environment in this process."""
    contract_path = contract_path.resolve()
    contract_sha = _sha256(contract_path.read_bytes())
    if include_visual:
        environment_sha = _render_environment_fingerprint(
            _render_environment(_chromium())
        )
    else:
        environment_sha = "no-visual"
    key = (f"{contract_path}:{contract_sha}", include_visual, environment_sha)
    with _CONTRACT_CACHE_LOCK:
        cached = _CONTRACT_CACHE.get(key)
        if isinstance(cached, ParityResult):
            return cached
        if isinstance(cached, str):
            raise InterfaceRegression(cached)
        try:
            result = check_contract(
                contract_path,
                include_visual=include_visual,
            )
        except Exception as exc:
            message = (
                str(exc)
                if isinstance(exc, InterfaceRegression)
                else f"{type(exc).__name__}: {exc}"
            )
            _CONTRACT_CACHE[key] = message
            raise InterfaceRegression(message) from exc
        _CONTRACT_CACHE[key] = result
        return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("check", "print-baseline"),
        nargs="?",
        default="check",
    )
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--no-visual", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "print-baseline":
        print(
            json.dumps(
                build_contract(include_visual=not args.no_visual),
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    result = check_contract(
        args.contract,
        include_visual=not args.no_visual,
    )
    print(json.dumps(result.__dict__, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
