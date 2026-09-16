"""Windows release build toolchain policy (not runtime compatibility).

``requires-python >=3.10`` in pyproject.toml governs source compatibility for
development and installs. Release builds pin an exact CPython patch via
``.python-version`` for reproducible PyInstaller output.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_VERSION_FILE = ".python-version"
_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def repo_root(start: Path | None = None) -> Path:
    """Return the repository root containing ``.python-version``."""
    here = (start or Path(__file__).resolve()).parent
    for candidate in (here, *here.parents):
        if (candidate / _VERSION_FILE).is_file():
            return candidate
    raise FileNotFoundError(f"Could not locate {_VERSION_FILE} from {here}")


def load_pinned_python_version(root: Path | None = None) -> str:
    """Read the pinned release Python version (``major.minor.patch``)."""
    path = (root or repo_root()) / _VERSION_FILE
    value = path.read_text(encoding="utf-8").strip()
    if not _VERSION_RE.fullmatch(value):
        raise ValueError(f"{_VERSION_FILE} must contain major.minor.patch, got: {value!r}")
    return value


def parse_version(version: str) -> tuple[int, int, int]:
    match = _VERSION_RE.fullmatch(version.strip())
    if not match:
        raise ValueError(f"Invalid Python version: {version!r}")
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def validate_python_version(
    version_info: tuple[int, int, int],
    pinned: str | None = None,
) -> None:
    """Raise ``ValueError`` when ``version_info`` does not match the pinned release."""
    expected = parse_version(pinned or load_pinned_python_version())
    actual = version_info
    if actual != expected:
        raise ValueError(
            "Release build requires Python "
            f"{expected[0]}.{expected[1]}.{expected[2]}, "
            f"but found {actual[0]}.{actual[1]}.{actual[2]}"
        )


def current_python_version_tuple() -> tuple[int, int, int]:
    return sys.version_info.major, sys.version_info.minor, sys.version_info.micro


def assert_release_python() -> str:
    """Validate the active interpreter and return the pinned version string."""
    pinned = load_pinned_python_version()
    validate_python_version(current_python_version_tuple(), pinned)
    return pinned
