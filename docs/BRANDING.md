# Branding — ExileLens

The canonical user-facing product name is **ExileLens**.

`src/exilelens/branding.py` is the single source of truth for user-facing identity:

| Constant | Value | Used for |
| --- | --- | --- |
| `APP_NAME` | `ExileLens` | window titles, tray tooltip/menu, notifications, diagnostic report header |
| `APP_USER_MODEL_ID` | `ExileLens.App` | Windows taskbar grouping and pinned-shortcut identity |
| `EXE_BASENAME` | `ExileLens` | packaged executable name |
| `window_title(context)` | `ExileLens — Setup` | contextual windows |

Contextual windows use an em dash: `ExileLens — Price Check`, `ExileLens — Setup`.

## Python package and versioning

| Identifier | Value | Notes |
| --- | --- | --- |
| Python package | `exilelens` | import path under `src/exilelens/` |
| Distribution (PyPI/local) | `exilelens` | `pyproject.toml`; version from `exilelens._version.__version__` only |
| Console scripts | `exilelens`, `exilelens-gui` | primary CLI entry points |
| User data | `%LOCALAPPDATA%\\ExileLens` | canonical settings directory |

## Icon

* Source artwork: `assets/app/exilelens.png` — the high-resolution original. Never resized in place.
* Windows icon: `assets/app/exilelens.ico` — multi-resolution (16/24/32/48/64/128/256), transparency preserved.
* Regenerate with `python scripts/make_app_icon.py` (also run automatically by `scripts/build_exe.ps1`).

The ICO is embedded into `ExileLens.exe` by `packaging/exilelens-gui.spec` (`EXE(icon=...)`), and the same
assets are bundled as data so the running app can set the Qt window and tray icon from them.

Windows `version_info.txt` is generated from `src/exilelens/_version.py` via
`scripts/generate_packaging_version_info.py` (also invoked by `scripts/build_exe.ps1`).

## Intentionally preserved legacy identifiers

These are **not** user-facing. They remain for migration, external compatibility, or immutable runtime contracts:

| Identifier | Why it stays |
| --- | --- |
| Console scripts `poe2value` / `poe2value-gui` | alias entry points for existing scripts and editable installs |
| `%LOCALAPPDATA%/poe2-value-overlay/` | legacy settings directory; copied once into `ExileLens` on first launch |
| Log file `logs/poe2value.log` | support workflows and docs reference this filename |
| Worker flag `--poe2value-worker` | accepted alongside `--exilelens-worker` for older packaged builds |
| Trade API user agents (`poe2-value-overlay/0.5 (price-check)`, `poe2-value-overlay/phase35`) | GGG rate-limit policy is keyed to a stable user agent |
| `LOCK_NAME` in `app/single_instance.py` | mutex must match older `PoE2ValueForMyBuild.exe` installs |
| `"PoE2 Value"` in `EXCLUDE_TITLE_HINTS` | stale window titles excluded from PoE-window detection |

Historical task/exit reports under `docs/` keep the product name that was correct when they were written.
