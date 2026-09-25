# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onefile spec for the external ExileLens updater."""

from pathlib import Path

repo_root = Path(SPECPATH).resolve().parent
src_root = repo_root / "src"

a = Analysis(
    [str(src_root / "exilelens" / "updater" / "__main__.py")],
    pathex=[str(src_root)],
    binaries=[],
    datas=[],
    hiddenimports=["exilelens.updater.install", "exilelens.app.logging_setup", "cryptography.hazmat.primitives.asymmetric.ed25519"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    upx=False,
    console=True,
)
