"""Make paper/scripts importable and give tests an isolated projects root."""

import sys
from pathlib import Path

import pytest

COMPONENT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = COMPONENT_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


@pytest.fixture
def tmp_root(tmp_path):
    """A throwaway component root so projects/ writes never touch the repo."""
    (tmp_path / "projects").mkdir()
    return tmp_path
