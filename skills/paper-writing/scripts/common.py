"""Shared path, IO, and text helpers for the paper-writing component."""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml

# Canonical paper type identifiers (kebab-case domain labels).
PAPER_TYPE = ("method", "system-for-ml", "benchmark", "empirical", "theory", "safety", "interdisciplinary")


def component_root() -> Path:
    """Return the installed paper-writing skill directory."""
    return Path(__file__).resolve().parent.parent


def workspace_root(root: Path | None = None) -> Path:
    """Return the runtime paper workspace (default: ./paper from the caller's cwd)."""
    if root is not None:
        return Path(root)
    env_root = os.environ.get("PAPER_WRITING_HOME")
    if env_root:
        return Path(env_root)
    return Path.cwd() / "paper"


def projects_root(root: Path | None = None) -> Path:
    """Return the projects/ directory that holds every paper project."""
    return workspace_root(root) / "projects"


def project_dir(paper_id: str, root: Path | None = None) -> Path:
    """Return the home directory for one paper project."""
    return projects_root(root) / paper_id


# Canonical sub-directories inside a single paper project.
PROJECT_SUBDIRS = [
    "inputs/manuscript",
    "inputs/results",
    "inputs/notes",
    "inputs/corpus_raw",
    "inputs/corpus_md",
    "inputs/corpus_json",
    "inputs/corpus_assets",
    "inputs/corpus_conversion",
    "context",
    "adapter/style_cards",
    "drafts",
    "logs",
    "exports/markdown",
    "exports/latex",
    "exports/pdf",
]


def ensure_project_skeleton(paper_id: str, root: Path | None = None) -> Path:
    """Create the full runtime directory tree for a paper project."""
    home = project_dir(paper_id, root)
    for sub in PROJECT_SUBDIRS:
        (home / sub).mkdir(parents=True, exist_ok=True)
    return home


PAPER_YAML_STUB = """\
paper:
  id: {paper_id}
  title: ""
  target_venue: null
  paper_type: method   # method | system-for-ml | benchmark | empirical | theory | safety | interdisciplinary
claims:
  identity: ""
  main: []      # - {{id: C1, text: "", evidence: inputs/results/<f>, value: "", status: supported, wording: strong}}
  secondary: []
  limitations: []
evidence:
  results: []
  metrics: []   # - {{name: "", value: "", source: inputs/results/<f>}}
  baselines: []
  ablations: []
  datasets: []
  runtime_provenance: ""
figures:
  existing: []  # - {{name: "", kind: non-data}}
  missing: []
terminology:
  method_name: ""
  module_names: []
  metric_names: []
  dataset_names: []
  forbidden_synonyms: []
  citation_keys: []
"""


def init_project(paper_id: str, root: Path | None = None) -> Path:
    """Create a project's directory tree and a paper.yaml stub if absent."""
    home = ensure_project_skeleton(paper_id, root)
    stub = home / "paper.yaml"
    if not stub.exists():
        write_text(stub, PAPER_YAML_STUB.format(paper_id=paper_id))
    return home


def load_yaml(path: Path) -> dict:
    """Load a YAML file into a dict (empty dict if the file is empty)."""
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def write_text(path: Path, text: str) -> Path:
    """Write text to path, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def read_text(path: Path) -> str:
    """Read a UTF-8 text file."""
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def split_paragraphs(markdown_text: str) -> list[str]:
    """Split markdown body prose into paragraphs (blank-line separated)."""
    blocks = re.split(r"\n\s*\n", markdown_text.strip())
    paras = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        # Skip pure heading / list / code-fence lines for paragraph-role analysis.
        if block.startswith("#") or block.startswith("```"):
            continue
        paras.append(block)
    return paras


def split_sentences(text: str) -> list[str]:
    """Naive sentence splitter good enough for audit heuristics."""
    text = " ".join(text.split())
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def ngrams(text: str, n: int = 8) -> set[str]:
    """Return the set of lowercased n-grams (word windows) in text."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {" ".join(words[i : i + n]) for i in range(len(words) - n + 1)}
