"""Stage 4 — convert inputs/corpus_raw/ to canonical Markdown via a pluggable backend.

Backends:
  manual  — user already supplied Markdown/text; register + run the readability gate only.
  docling — default; subprocess wrapper. Degrades gracefully if Docling is not installed.

The backend interface stays pluggable so pymupdf4llm/marker/mineru/markitdown can be added later
without changing this contract.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

import common
import evaluate_conversion as ec

_MD_SUFFIXES = {".md", ".markdown", ".txt"}


def _manual_backend(source: Path, out_md_dir: Path, out_json_dir: Path) -> dict:
    """Register an already-Markdown source; PDFs cannot be converted without a backend."""
    if source.suffix.lower() not in _MD_SUFFIXES:
        return {"command": "manual", "output_md": "", "output_json": "", "page_count": None,
                "status_hint": ec.MANUAL_INPUT_REQUIRED, "note": "manual mode needs Markdown/text input"}
    out = out_md_dir / (source.stem + ".md")
    shutil.copyfile(source, out)
    return {"command": f"manual register {source.name}", "output_md": str(out), "output_json": "",
            "page_count": None, "status_hint": None, "note": ""}


def _docling_backend(source: Path, out_md_dir: Path, out_json_dir: Path) -> dict:
    """Convert via the Docling CLI; report failure (not crash) if Docling is absent."""
    out = out_md_dir / (source.stem + ".md")
    out_json = out_json_dir / (source.stem + ".json")
    cmd = ["docling", str(source), "--to", "md", "--output", str(out_md_dir)]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError:
        return {"command": " ".join(cmd), "output_md": "", "output_json": "", "page_count": None,
                "status_hint": ec.CONVERSION_FAILED, "note": "docling not installed"}
    except subprocess.CalledProcessError as exc:
        return {"command": " ".join(cmd), "output_md": "", "output_json": "", "page_count": None,
                "status_hint": ec.CONVERSION_FAILED, "note": f"docling failed: {exc.stderr[:200]}"}
    note = ""
    output_json = str(out_json)
    json_cmd = ["docling", str(source), "--to", "json", "--output", str(out_json_dir)]
    try:
        subprocess.run(json_cmd, check=True, capture_output=True, text=True)
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        note = f"json export unavailable: {str(exc)[:160]}"
        output_json = ""
    return {"command": " ".join(cmd), "output_md": str(out),
            "output_json": output_json, "page_count": None,
            "status_hint": None, "note": note}


_BACKENDS = {"manual": _manual_backend, "docling": _docling_backend}


def convert_corpus(paper_id: str, backend: str = "docling", root=None) -> dict:
    """Convert every raw corpus source, run the readability gate, and write manifest + reports."""
    home = common.project_dir(paper_id, root)
    raw_dir = home / "inputs" / "corpus_raw"
    md_dir = home / "inputs" / "corpus_md"
    json_dir = home / "inputs" / "corpus_json"
    conv_dir = home / "inputs" / "corpus_conversion"
    md_dir.mkdir(parents=True, exist_ok=True)
    json_dir.mkdir(parents=True, exist_ok=True)
    convert = _BACKENDS[backend]

    sources = []
    for source in sorted(p for p in raw_dir.iterdir() if p.is_file()):
        info = convert(source, md_dir, json_dir)
        if info["status_hint"]:                       # backend could not produce usable Markdown
            status, checks = info["status_hint"], {}
        else:
            md_text = common.read_text(Path(info["output_md"]))
            status, checks = ec.assess(md_text, source_kind="paper")
        sources.append({
            "source": str(source),
            "backend": backend,
            "command": info["command"],
            "output_md": info["output_md"],
            "output_json": info["output_json"],
            "page_count": info["page_count"],
            "readability_status": status,
            "checks": checks,
            "note": info["note"],
        })

    manifest = {"paper_id": paper_id, "backend": backend, "sources": sources}
    common.write_text(conv_dir / "file_manifest.json", json.dumps(manifest, indent=2))
    _write_conversion_report(conv_dir, manifest)
    _write_readability_report(conv_dir, manifest)
    return manifest


def accepted_corpus(manifest: dict) -> list[str]:
    """Return output Markdown paths that passed the gate (CONVERTED_VERIFIED only)."""
    return [s["output_md"] for s in manifest["sources"]
            if s["readability_status"] == ec.CONVERTED_VERIFIED and s["output_md"]]


def _write_conversion_report(conv_dir: Path, manifest: dict) -> None:
    lines = [f"# Conversion Report ({manifest['backend']})", "",
             "| Source | Backend | Status | Output |", "| --- | --- | --- | --- |"]
    for s in manifest["sources"]:
        lines.append(f"| {Path(s['source']).name} | {s['backend']} | {s['readability_status']} "
                     f"| {Path(s['output_md']).name if s['output_md'] else '-'} |")
    common.write_text(conv_dir / "conversion_report.md", "\n".join(lines) + "\n")


def _write_readability_report(conv_dir: Path, manifest: dict) -> None:
    lines = ["# Readability Report", ""]
    for s in manifest["sources"]:
        lines.append(f"## {Path(s['source']).name} — {s['readability_status']}")
        for k, v in (s.get("checks") or {}).items():
            lines.append(f"- {k}: {'ok' if v else 'FAIL'}")
        if s.get("note"):
            lines.append(f"- note: {s['note']}")
        lines.append("")
    common.write_text(conv_dir / "readability_report.md", "\n".join(lines) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="Convert raw corpus to Markdown and gate readability.")
    ap.add_argument("paper_id")
    ap.add_argument("--backend", default="docling",
                    choices=["docling", "manual", "pymupdf4llm", "marker", "mineru", "markitdown"])
    args = ap.parse_args()
    if args.backend not in _BACKENDS:
        raise SystemExit(f"backend {args.backend!r} not wired yet; use 'docling' or 'manual'.")
    manifest = convert_corpus(args.paper_id, backend=args.backend)
    accepted = accepted_corpus(manifest)
    print(f"converted {len(manifest['sources'])} sources; {len(accepted)} passed the gate.")


if __name__ == "__main__":
    main()
