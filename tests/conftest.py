"""Pytest bootstrap: make the repo root importable (``src`` package)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))