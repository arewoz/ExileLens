"""M4 packaging metadata: dynamic version resolves from canonical source."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


pytestmark = pytest.mark.ops


def test_pyproject_dynamic_version_matches_canonical() -> None:
    from exilelens._version import __version__

    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "exilelens._version.__version__" in pyproject
    assert __version__ == "0.5.0b1"


def test_generate_packaging_version_info_check_passes() -> None:
    script = ROOT / "scripts" / "generate_packaging_version_info.py"
    result = subprocess.run(
        [sys.executable, str(script), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_editable_install_exposes_exilelens_distribution(tmp_path, monkeypatch) -> None:
    from exilelens._version import __version__

    env = {"PYTHONPATH": str(ROOT / "src"), **{k: v for k, v in __import__("os").environ.items() if k != "PYTHONPATH"}}
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-e", str(ROOT), "--no-deps", "--target", str(tmp_path / "site")],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    dist_info = next((tmp_path / "site").glob("exilelens-*.dist-info"))
    metadata = dist_info / "METADATA"
    assert f"Version: {__version__}" in metadata.read_text(encoding="utf-8")
