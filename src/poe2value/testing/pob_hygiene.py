"""PoB checkout hygiene helpers for tests (canonical engine dependency is read-only)."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

from poe2value.config import load_config


def canonical_pob_root() -> Path:
    return load_config().pob_path.resolve()


def stop_external_pob_tooling_processes() -> None:
    """Best-effort stop for known external research scripts that write under PoB/tools."""
    if os.name != "nt":
        return
    script = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.CommandLine -and "
        "($_.CommandLine -match 'PathOfBuilding-PoE2\\\\tools\\\\pob' -or "
        "$_.CommandLine -match 'item_tree_lab_work') } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        check=False,
    )


def remove_generated_pob_tools_tree() -> None:
    """Remove the known generated tools/ tree (never tracked in canonical PoB)."""
    tools = canonical_pob_root() / "tools"
    if tools.exists():
        shutil.rmtree(tools, ignore_errors=True)


def prepare_canonical_pob_for_itemcheck() -> None:
    stop_external_pob_tooling_processes()
    time.sleep(0.5)
    remove_generated_pob_tools_tree()


def pob_git_status_short() -> str:
    root = canonical_pob_root()
    result = subprocess.run(
        ["git", "-C", str(root), "status", "--short"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _remove_empty_generated_tools_stub() -> bool:
    tools = canonical_pob_root() / "tools"
    if not tools.exists():
        return False
    if any(path.is_file() for path in tools.rglob("*")):
        return False
    shutil.rmtree(tools, ignore_errors=True)
    return True


def assert_pob_clean(*, context: str = "") -> None:
    if pob_git_status_short().strip() == "?? tools/":
        _remove_empty_generated_tools_stub()
    status = pob_git_status_short()
    if status:
        prefix = f"{context}: " if context else ""
        raise AssertionError(f"{prefix}canonical PoB checkout is dirty:\n{status}")


def path_is_under_pob(path: Path | str, *, pob_root: Path | None = None) -> bool:
    root = (pob_root or canonical_pob_root()).resolve()
    candidate = Path(path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def assert_not_under_pob(path: Path | str, *, context: str = "") -> None:
    if path_is_under_pob(path):
        prefix = f"{context}: " if context else ""
        raise AssertionError(f"{prefix}writable path must not be under canonical PoB checkout: {path}")
