# Windows executable packaging

Build a standalone **windowed** GUI executable with PyInstaller. Path of Building 2 remains external — the user selects their normal Path of Building Community (PoE2) installation on first launch via the in-app setup dialog.

## Prerequisites

- Windows 10/11
- Python 3.10+ for day-to-day development (`pip install -e ".[dev]"`)
- **Release builds:** exact pinned CPython from `.python-version` (currently **3.12.10**)

`requires-python >=3.10` in `pyproject.toml` is the **source compatibility** policy. The
`.python-version` pin is the **Windows release toolchain** policy only — it keeps PyInstaller
output reproducible and is enforced by `scripts/build_exe.ps1` before pip/PyInstaller run.

Verify the pinned interpreter:

```powershell
py -3.12 --version   # must print Python 3.12.10
Get-Content .python-version
```

## Build

```powershell
cd <path-to-your-checkout>
.\scripts\build_exe.ps1
```

The build script resolves `py -3.12` (or `python` on PATH) and **stops with a clear error**
if the active interpreter is not exactly the pinned patch from `.python-version`.

Output directory:

```
dist\ExileLens\ExileLens.exe
```

The build script also creates a desktop shortcut named **ExileLens**. Pass `-SkipShortcut` to skip that (used for closed-public packaging).

To recreate only the shortcut after a rebuild:

```powershell
.\scripts\create_desktop_shortcut.ps1 -ExePath "<path-to-your-checkout>\dist\ExileLens\ExileLens.exe"
```

## What gets bundled

- PySide6 (Qt) runtime and plugins
- `exilelens` Python package
- `runtime/lua/` bridge scripts used by the PoB worker subprocess
- `README.txt` (install/setup/troubleshooting guide, staged from `packaging/`)
- the MIT-licensed PoB headless support definitions documented in `THIRD_PARTY_NOTICES.txt`

**Not bundled:** the Path of Building application/runtime/data, build XML files, or user settings (`%LOCALAPPDATA%\ExileLens\settings.json`). A Git checkout is not required.

## Supported PoB folders

- Normal install: select `%APPDATA%\Path of Building Community (PoE2)` — the directory containing `Path of Building-PoE2.exe`, `Launch.lua`, `lua51.dll`, `Data`, and `Modules`.
- Developer checkout: select the repository root containing `src` and `runtime`.

## Frozen worker subprocess

The GUI spawns a worker subprocess (`--exilelens-worker`, with legacy `--poe2value-worker`) from the same executable to avoid Lua/Qt DLL conflicts on Windows. PoB's `lua51.dll` is loaded from either the selected installation root or a checkout's `runtime` directory. Startup errors are caught inside the frozen worker boundary so an invalid path cannot produce PyInstaller's unhandled-exception dialog.

## Windows release toolchain

| Policy | Value | Where |
|--------|-------|-------|
| Source compatibility | `requires-python >=3.10` | `pyproject.toml` |
| Release build Python | exact patch from `.python-version` | repo root |
| Packaging | PyInstaller onedir, UPX disabled | `packaging/exilelens-gui.spec` |

After a release build, `dist\ExileLens\build_stamp.json` records the detected
`python_version`, `pyinstaller_version`, `git_commit`, and `build_mode`.

## Rebuild from spec only

Use the pinned release interpreter (not the default `python` if it differs):

```powershell
py -3.12 -m pip install pyinstaller
py -3.12 -m PyInstaller packaging/exilelens-gui.spec --noconfirm --clean
```

## Git artifacts

`dist/` and `build/` are gitignored. Only `packaging/` and `scripts/build_exe.ps1` are committed.
