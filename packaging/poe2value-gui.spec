# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the ExileLens Windows GUI."""

from pathlib import Path

import shiboken6

block_cipher = None

repo_root = Path(SPECPATH).resolve().parent
src_root = repo_root / "src"
entry_script = src_root / "poe2value" / "app" / "main.py"
runtime_lua = repo_root / "runtime" / "lua"
app_assets = repo_root / "assets" / "app"
app_icon = app_assets / "exilelens.ico"
# ``QtCore.pyd`` imports ``shiboken6.abi3.dll`` through the Windows loader.
# PyInstaller normally places it in ``_internal/shiboken6``; put a copy beside
# PySide6's extension modules as well, so the frozen app does not depend on a
# developer's PATH or a separately installed shiboken6 package.
shiboken_runtime = Path(shiboken6.__file__).resolve().parent / "shiboken6.abi3.dll"
# Ship only what the running app resolves via poe2value.branding — the original
# .webp the artwork arrived as stays in the repo as provenance, not in the bundle.
bundled_icons = [
    (str(app_assets / "exilelens.ico"), "assets/app"),
    (str(app_assets / "exilelens.png"), "assets/app"),
]

# Do not use collect_all("PySide6") — it drags in the full Qt distribution
# (WebEngine, QML, Designer, translations, dev tools). PyInstaller's per-module
# PySide6 hooks collect only the Qt stacks referenced by application imports.

hiddenimports = [
    "poe2value.worker",
    "poe2value.app.controller",
    "poe2value.app.build_state",
    "poe2value.app.settings",
    "poe2value.items.evaluation",
    "poe2value.items.recognition",
    "poe2value.platform.windows.clipboard",
    "poe2value.ui.tray",
    "poe2value.ui.overlay",
    "poe2value.ui.settings_dialog",
    "poe2value.ui.setup_dialog",
    "poe2value.ui.diagnostics",
    "poe2value.ui.tray_icon",
    "poe2value.ui.styles",
    "poe2value.price_check.market_drivers",
    "poe2value.price_check.stat_registry",
    "poe2value.price_check.market_signatures",
    "poe2value.price_check.signature_store",
    "poe2value.price_check.price_trust",
    "poe2value.ui.refine_price_dialog",
    "poe2value.ui.interactive_price_check_panel",
    "poe2value.ui.overlay_detail_drawer",
    "poe2value.price_check.panel_model",
    "poe2value.price_check.panel_edits",
    "poe2value.price_check.market_plan",
    "poe2value.price_check.market_mod",
    "poe2value.price_check.desirability",
    "poe2value.price_check.base_value",
    "poe2value.app.refine_price_hotkey",
    "poe2value.branding",
    "poe2value._version",
    "poe2value.ui.profile_catalog",
]

# Guardrails: heavyweight Qt stacks and dev-only Python packages that must never
# ship in the closed-public GUI, even if a transitive import slips through analysis.
excludes = [
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickControls2",
    "PySide6.QtQuickWidgets",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtPositioning",
    "PySide6.QtLocation",
    "PySide6.QtSerialPort",
    "PySide6.QtSerialBus",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtHelp",
    "PySide6.QtDesigner",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtGraphs",
    "PySide6.QtGraphsWidgets",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DExtras",
    "PySide6.Qt3DAnimation",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtHttpServer",
    "PySide6.QtNetworkAuth",
    "PySide6.QtWebSockets",
    "PySide6.QtWebView",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtSensors",
    "PySide6.QtSpatialAudio",
    "PySide6.QtTextToSpeech",
    "PySide6.QtStateMachine",
    "PySide6.QtUiTools",
    "PySide6.QtAxContainer",
    "PySide6.QtDBus",
    "pytest",
    "unittest",
    "test",
    "tests",
    "pip",
    "setuptools",
]

a = Analysis(
    [str(entry_script)],
    pathex=[str(src_root)],
    binaries=[(str(shiboken_runtime), "PySide6")],
    datas=[(str(runtime_lua), "runtime/lua")] + bundled_icons,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(repo_root / "packaging" / "pyi_runtime_qt_dll.py")],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ExileLens",
    icon=str(app_icon),
    version=str(repo_root / "packaging" / "version_info.txt"),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ExileLens",
)
