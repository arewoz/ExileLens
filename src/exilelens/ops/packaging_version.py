"""Shared Windows ``version_info.txt`` rendering for build tooling and release gate."""

from __future__ import annotations

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
          StringStruct('FileDescription', 'ExileLens'),
          StringStruct('FileVersion', '{version}'),
          StringStruct('InternalName', 'ExileLens'),
          StringStruct('OriginalFilename', 'ExileLens.exe'),
          StringStruct('ProductName', 'ExileLens'),
          StringStruct('ProductVersion', '{version}'),
        ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def render_version_info(version: str = __version__) -> str:
    numeric = ", ".join(str(part) for part in windows_version_tuple(version))
    return _TEMPLATE.format(version=version, numeric=numeric)
