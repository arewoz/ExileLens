# Branding — ExileLens

The canonical user-facing product name is **ExileLens**.

`src/poe2value/branding.py` is the single source of truth:

| Constant | Value | Used for |
| --- | --- | --- |
| `APP_NAME` | `ExileLens` | window titles, tray tooltip/menu, notifications, diagnostic report header |
| `APP_USER_MODEL_ID` | `ExileLens.App` | Windows taskbar grouping and pinned-shortcut identity |
| `EXE_BASENAME` | `ExileLens` | packaged executable name |
| `window_title(context)` | `ExileLens — Setup` | contextual windows |

Contextual windows use an em dash: `ExileLens — Price Check`, `ExileLens — Setup`.

## Icon

* Source artwork: `assets/app/exilelens.png` — the high-resolution original. Never resized in place.
* Windows icon: `assets/app/exilelens.ico` — multi-resolution (16/24/32/48/64/128/256), transparency preserved.
* Regenerate with `python scripts/make_app_icon.py` (also run automatically by `scripts/build_exe.ps1`).

The ICO is embedded into `ExileLens.exe` by `packaging/poe2value-gui.spec` (`EXE(icon=...)`), and the same
assets are bundled as data so the running app can set the Qt window and tray icon from them.

## Intentionally preserved legacy identifiers

These are **not** user-facing. Renaming them would break existing installs or working scripts, so they keep
their historical names:

| Identifier | Why it stays |
| --- | --- |
| Python package `poe2value` | thousands of intra-repo imports, `--poe2value-worker` subprocess arg, PyInstaller hidden imports |
| Console script `poe2value` / `poe2value-gui` | existing scripts, docs and test invocations; `exilelens` / `exilelens-gui` added as aliases |
| Distribution name `poe2-value-overlay` in `pyproject.toml` | existing editable installs and virtualenvs resolve by this name |
| `%LOCALAPPDATA%/poe2-value-overlay/` settings directory | a cosmetic rename must not make existing user configuration, calibration state or build selections disappear |
| Trade API user agents (`poe2-value-overlay/0.5 (price-check)`, `poe2-value-overlay/phase35`) | GGG rate-limit policy is keyed to a stable user agent; changing it silently is a live-traffic change, not a rename |
| Spec filename `packaging/poe2value-gui.spec` | referenced by `scripts/build_exe.ps1` and CI notes; the artifacts it produces are named ExileLens |
| `LOCK_NAME` in `app/single_instance.py` | the single-instance mutex is not user-facing. Renaming it would let an old `PoE2ValueForMyBuild.exe` and a new `ExileLens.exe` run at the same time, both registering the Price Check hotkey and both spending the same per-IP trade budget — exactly what MARKET-01B13 added the lock to prevent. |
| `"PoE2 Value"` in `EXCLUDE_TITLE_HINTS` | kept alongside `"ExileLens"` so any stale window is still excluded from PoE-window detection |

Historical task/exit reports under `docs/` keep the product name that was correct when they were written.
