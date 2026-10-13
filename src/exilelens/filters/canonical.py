"""Portable offline contract fixtures used by development checks only."""
from __future__ import annotations

from pathlib import Path

ARTIFACTS = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "filter_needs"
CANONICAL_NEEDS_DIR = ARTIFACTS / "filter08e"
CANONICAL_OUT_DIR = ARTIFACTS / "filter08e"
HISTORICAL_NEEDS_DIRS = (ARTIFACTS / "filter08b", ARTIFACTS / "filter08c")
