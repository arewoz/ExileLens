# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onefile spec for the external ExileLens updater."""

from pathlib import Path

repo_root = Path(SPECPATH).resolve().parent
src_root = repo_root / "src"
app_icon = repo_root / "assets" / "app" / "exilelens.ico"
# Same ExileLens release version as ExileLens.exe (generated from src/exilelens/_version.py by
# scripts/generate_packaging_version_info.py). There is no separate updater version.
version_resource = repo_root / "packaging" / "version_info_updater.txt"

a = Analysis(
    [str(src_root / "exilelens" / "updater" / "__main__.py")],
    pathex=[str(src_root)],
    binaries=[],
    datas=[],
    # Stdlib-only updater: it re-checks the package SHA-256 and archive CRCs but never verifies signatures
    # (the app did that before staging), so no crypto dependency is bundled.
    hiddenimports=[
        "exilelens.updater.install",
        "exilelens.updater.job",
        "exilelens.updater.layout",
        "exilelens.updater.result",
        "exilelens.updater.transaction",
        "exilelens.updater.winsys",
        "exilelens.app.logging_setup",
        "exilelens.app.settings",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Nothing outside the standard library and the exilelens modules above may enter the updater: no Qt, no crypto stack,
    # no test tooling. (release_gate / ops.packaging_spec assert this list.)
    excludes=[
        "PySide6",
        "shiboken6",
        "cryptography",
        "cffi",
        "pycparser",
        "pytest",
        "unittest",
        "tkinter",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ExileLensUpdater",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    icon=str(app_icon),
    version=str(version_resource),
    upx=False,
    console=True,
)
