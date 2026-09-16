"""Run the deterministic offline smoke suite via pytest."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from poe2value.ops.paths import repo_root

# Limit collection to smoke-bearing modules so CI does not import PySide6-only suites.
SMOKE_TARGETS = (
    "tests/ops",
    "tests/unit/test_market_01b6d_funnel_diag.py",
    "tests/unit/test_release_candidate.py",
    "tests/unit/test_build_source.py",
    "tests/unit/test_item_recognition.py",
)


def run_pytest(targets: list[str] | None = None, *, root: Path | None = None, extra: list[str] | None = None) -> dict[str, Any]:
    base = root or repo_root()
    env = os.environ.copy()
    src = str(base / "src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    args = [sys.executable, "-m", "pytest", "-o", "addopts=", "-q", *(extra or [])]
    args.extend(targets or ["-m", "smoke"])
    completed = subprocess.run(args, cwd=str(base), env=env, capture_output=True, text=True)
    return {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "args": args[3:],
        "stdout": completed.stdout[-4000:],
        "stderr": completed.stderr[-2000:],
    }


def run_smoke(*, root: Path | None = None) -> dict[str, Any]:
    return run_pytest(["-m", "smoke", *SMOKE_TARGETS], root=root)
