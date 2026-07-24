"""Parse common ML-training output into small typed runtime events."""

from __future__ import annotations

import json
import math
import re
import subprocess
from typing import Any, Callable, Iterable, Pattern


_NUMBER = r"-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_KV_RE = re.compile(
    r"(?P<key>[A-Za-z][A-Za-z0-9_@./-]*)\s*[:=]\s*(?P<value>" + _NUMBER + r")"
)
_TQDM_RE = re.compile(
    r"(?P<pct>\d+(?:\.\d+)?)%\|.*?\|\s*(?P<step>\d+)\s*/\s*(?P<total>\d+)"
    r".*?,\s*(?P<rate>\d+(?:\.\d+)?)\s*(?P<unit>[A-Za-z/]+)"
)
_PHASE_FENCED_RE = re.compile(
    r"^\s*[-=#]{3,}\s*(?P<label>[^-=#\s].*?)\s*(?:[-=#]{3,}\s*)?$"
)
_PHASE_MARKER_RE = re.compile(
    r"^\s*(?P<label>(?:P\d+[a-z]?\b|Epoch\s+\d+\b|Phase\s*\d+\b).*?)\s*$",
    re.I,
)
_ANOMALY_RE = re.compile(
    r"Traceback|(?i:\bCUDA out of memory\b)|(?i:\bout of memory\b)|"
    r"\bKilled\b|(?i:\bnan\b)|(?i:\binf\b)|(?i:\binfinity\b)"
)
_FATAL_RE = re.compile(
    r"Traceback|(?i:\bCUDA out of memory\b)|(?i:\bout of memory\b)|\bKilled\b"
)


def compile_custom_regex(pattern: str) -> Pattern[str]:
    return re.compile(pattern)


def _number(value: Any) -> float | int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    return None


def _parse_number(value: str) -> int | float:
    parsed = float(value)
    if parsed.is_integer() and not any(ch in value.lower() for ch in (".", "e")):
        return int(parsed)
    return parsed


def _metric(
    values: dict[str, int | float],
    *,
    source: str,
    step: int | None = None,
    total: int | None = None,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "kind": "metric",
        "source": source,
        "step": step,
        "values": values,
    }
    if total is not None:
        event["total"] = total
    return event


def _parse_json(line: str) -> dict[str, Any] | None:
    try:
        value = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict):
        return None
    step = _number(value.get("step"))
    total = _number(value.get("total"))
    rate = _number(value.get("rate"))
    epoch = _number(value.get("epoch"))
    metrics: dict[str, int | float] = {}
    ignored = {"step", "total", "rate", "unit", "epoch", "phase", "kind", "t"}
    for key, raw in value.items():
        if key in ignored:
            continue
        parsed = _number(raw)
        if parsed is not None:
            metrics[str(key)] = parsed
    if step is not None and total is not None and rate is not None and not metrics:
        event: dict[str, Any] = {
            "kind": "progress",
            "source": "jsonl",
            "step": int(step),
            "total": int(total),
            "rate": float(rate),
            "unit": str(value.get("unit") or "it/s"),
        }
        if epoch is not None:
            event["epoch"] = int(epoch)
        return event
    if metrics:
        return _metric(
            metrics,
            source="jsonl",
            step=int(step) if step is not None else None,
            total=int(total) if total is not None else None,
        )
    return None


def _parse_custom(line: str, regexes: Iterable[Pattern[str]]) -> dict[str, Any] | None:
    for regex in regexes:
        match = regex.search(line)
        if not match:
            continue
        values: dict[str, int | float] = {}
        step = None
        total = None
        for key, raw in match.groupdict().items():
            if raw is None:
                continue
            try:
                parsed = _parse_number(raw)
            except ValueError:
                continue
            if key == "step":
                step = int(parsed)
            elif key == "total":
                total = int(parsed)
            else:
                values[key] = parsed
        if values:
            return _metric(values, source="custom", step=step, total=total)
    return None


def _parse_tqdm(line: str) -> dict[str, Any] | None:
    match = _TQDM_RE.search(line)
    if not match:
        return None
    return {
        "kind": "progress",
        "source": "tqdm",
        "step": int(match.group("step")),
        "total": int(match.group("total")),
        "rate": float(match.group("rate")),
        "unit": match.group("unit"),
    }


def _parse_key_values(line: str) -> dict[str, Any] | None:
    values: dict[str, int | float] = {}
    step = None
    total = None
    rate = None
    for match in _KV_RE.finditer(line):
        key = match.group("key")
        value = _parse_number(match.group("value"))
        normalized = key.lower()
        if normalized in {"step", "iter", "iteration"}:
            step = int(value)
        elif normalized == "total":
            total = int(value)
        elif normalized in {"rate", "it/s"}:
            rate = float(value)
        else:
            values[key] = value
    if step is not None and total is not None and rate is not None and not values:
        return {
            "kind": "progress",
            "source": "kv-metrics",
            "step": step,
            "total": total,
            "rate": rate,
            "unit": "it/s",
        }
    if total is not None:
        values["total"] = total
    if values:
        return _metric(values, source="kv-metrics", step=step)
    return None


def _parse_phase(line: str) -> dict[str, Any] | None:
    match = _PHASE_FENCED_RE.match(line) or _PHASE_MARKER_RE.match(line)
    if not match:
        return None
    label = match.group("label").strip(" -=#\t")
    return {"kind": "phase", "label": label} if label else None


def _parse_anomaly(line: str) -> dict[str, Any] | None:
    match = _ANOMALY_RE.search(line)
    if not match:
        return None
    if match.group(0).lower() == "inf" and re.search(
        r"""["']?steps_per_print["']?\s*[:=]\s*inf\b""",
        line,
        re.I,
    ):
        return None
    return {
        "kind": "anomaly",
        "label": match.group(0),
        "tail": line.rstrip("\n")[-500:],
        "fatal": bool(_FATAL_RE.search(line)),
    }


def parse_line(
    line: str,
    custom_regexes: Iterable[Pattern[str]] | None = None,
) -> dict[str, Any] | None:
    regexes = list(custom_regexes or [])
    parsers = (
        _parse_json,
        lambda value: _parse_custom(value, regexes),
        _parse_tqdm,
        _parse_key_values,
        _parse_phase,
        _parse_anomaly,
    )
    for parser in parsers:
        event = parser(line)
        if event is not None:
            return event
    return None


def gpu_sampler(
    gpu_ids: list[str],
    runner: Callable[..., Any] = subprocess.run,
) -> Callable[[], dict[str, Any] | None]:
    command = [
        "nvidia-smi",
        "--query-gpu=utilization.gpu,memory.used",
        "--format=csv,noheader,nounits",
    ]
    if gpu_ids:
        command += ["-i", ",".join(gpu_ids)]

    def sample() -> dict[str, Any] | None:
        result = runner(command, capture_output=True, text=True, timeout=5)
        lines = (result.stdout or "").strip().splitlines()
        if not lines:
            return None
        utilization, memory = [
            part.strip() for part in lines[0].split(",")[:2]
        ]
        return {
            "gpu_util": float(utilization),
            "gpu_mem_gb": round(float(memory) / 1024, 1),
        }

    return sample
