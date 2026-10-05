"""Shared Windows ``version_info.txt`` rendering for build tooling and release gate.

Both shipped executables (ExileLens.exe and ExileLensUpdater.exe) carry the SAME release version, derived from
``exilelens._version``. There is no separate updater version.
"""

from __future__ import annotations

from dataclasses import dataclass

from exilelens._version import __version__, windows_version_tuple

_TEMPLATE = """# Generated from src/exilelens/_version.py — do not edit by hand.
# Regenerate: python scripts/generate_packaging_version_info.py
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({numeric}),
    prodvers=({numeric}),
    mask=0x3f,
    flags=0x2,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0),
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [
          StringStruct('CompanyName', 'ExileLens'),
          StringStruct('FileDescription', '{description}'),
          StringStruct('FileVersion', '{version}'),
          StringStruct('InternalName', '{internal_name}'),
          StringStruct('OriginalFilename', '{original_filename}'),
          StringStruct('ProductName', 'ExileLens'),
          StringStruct('ProductVersion', '{version}'),
        ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


@dataclass(frozen=True)
class ExecutableIdentity:
    """What a shipped executable's Windows version resource must say (besides the shared version)."""

    role: str
    version_file: str  # repo-relative, committed
    file_name: str
    description: str
    internal_name: str


GUI = ExecutableIdentity("gui", "packaging/version_info.txt", "ExileLens.exe", "ExileLens", "ExileLens")
UPDATER = ExecutableIdentity(
    "updater", "packaging/version_info_updater.txt", "ExileLensUpdater.exe", "ExileLens Updater", "ExileLensUpdater"
)
EXECUTABLES = (GUI, UPDATER)


def render_version_info(version: str = __version__, identity: ExecutableIdentity = GUI) -> str:
    numeric = ", ".join(str(part) for part in windows_version_tuple(version))
    return _TEMPLATE.format(
        version=version,
        numeric=numeric,
        description=identity.description,
        internal_name=identity.internal_name,
        original_filename=identity.file_name,
    )
