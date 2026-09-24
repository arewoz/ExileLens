"""Execute the P0 regression evidence required for a release."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from poe2value.ops.paths import repo_root
from poe2value.ops.regression import RegressionRegistryError, load_registry, mandatory_p0_test_nodeids
from poe2value.ops.smoke import run_pytest


def run_mandatory_release_regressions(*, root: Path | None = None) -> dict[str, Any]:
    """Run declared P0 evidence; declaration alone never counts as a passing test."""
    base = root or repo_root()
    try:
        entries = load_registry(base / "ops" / "regression_registry.json", root=base)
        nodeids = mandatory_p0_test_nodeids(entries)
    except RegressionRegistryError as exc:
        return {
            "status": "BLOCKED",
            "detail": str(exc),
            "tests": [],
            "test_run": None,
        }
    test_run = run_pytest(nodeids, root=base)
    return {
        "status": "PASS" if test_run["ok"] else "BLOCKED",
        "detail": "mandatory P0 regressions passed" if test_run["ok"] else "mandatory P0 regressions failed",
        "tests": nodeids,
        "test_run": test_run,
    }
