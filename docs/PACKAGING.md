# Windows executable packaging

Build a standalone **windowed** GUI executable with PyInstaller. Path of Building 2 remains external — the user selects their normal Path of Building Community (PoE2) installation on first launch via the in-app setup dialog.

There are two ways to build, and they are not equivalent:

| | Local development build | Official release build |
|---|---|---|
| Command | `.\scripts\build_exe.ps1` | the `Windows release` workflow (`.github/workflows/release.yml`), which runs `scripts\build_exe.ps1 -SkipShortcut` |
| Environment | your checkout | clean `windows-latest` runner, main only, `production-release` environment |
| Purpose | try the package locally | the only source of a public artifact (first as `dry_run=true`) |
| Publishes | never | tag + release + ZIP + `SHA256SUMS.txt` + signed `.update.json` (never when `dry_run`) |

## Prerequisites

- Windows 10/11
- Python 3.10+ for day-to-day development (`pip install -e ".[dev]"`)
- **Release builds:** the exact CPython patch in `.python-version` (currently **3.12.10**)

`requires-python >=3.10` in `pyproject.toml` is the **source compatibility** policy. The `.python-version` pin is the **Windows release toolchain** policy only: `scripts/release_python_preflight.ps1` stops the build unless the interpreter is exactly that patch.

```powershell
py -3.12 --version   # must print Python 3.12.10
Get-Content .python-version
```

## Release environment (reproducible)

The release venv is `.release-venv` in the checkout, created and verified by `scripts/release_python_preflight.ps1` on every build:

1. Python is resolved to the exact `.python-version` patch.
2. Every direct pin in `packaging/requirements-release.txt` must also be in `packaging/requirements-release.lock` at the same version.
3. Dependencies are installed **only** from the lock, with `pip install --require-hashes --requirement packaging/requirements-release.lock`.
4. The venv must then contain exactly the locked packages (plus `pip`). Anything else (pytest, ruff, a tool a script installed) fails the preflight as *contaminated*: delete `.release-venv` and rebuild. **Never `pip install` into it.** Run tests and tools from your normal development environment or a separate throwaway venv.
5. The build runs with a controlled `PATH` (the venv plus Windows system directories only).

Refresh the lock only when you intentionally change a direct pin (this is the only networked step):

```powershell
py -3.12 scripts\lock_release_deps.py          # rewrite packaging\requirements-release.lock from requirements-release.txt
py -3.12 scripts\lock_release_deps.py --check  # offline drift + hash check; runs in PR validation and in release.yml
```

## Build

```powershell
.\scripts\build_exe.ps1              # development build (also creates a desktop shortcut)
.\scripts\build_exe.ps1 -SkipShortcut  # what the release workflow runs
```

What it does, in order:

1. release-venv preflight (above);
2. regenerates the Windows version resources (`scripts\generate_packaging_version_info.py`: `packaging\version_info.txt` for the GUI and `packaging\version_info_updater.txt` for the updater, both from `src\exilelens\_version.py`) and the icon;
3. PyInstaller **onedir**, windowed, UPX disabled: `packaging\exilelens-gui.spec` → `dist\ExileLens\ExileLens.exe`;
4. copies `README.txt`, `LICENSE`, `THIRD_PARTY_NOTICES.txt`, `QT_LGPL_COMPLIANCE.txt` and `third_party_licenses\` next to the executable;
5. builds the updater **exactly once** (`scripts\build_updater.ps1`: PyInstaller **onefile**, stdlib-only, console, `packaging\exilelens-updater.spec`, same icon and the same ExileLens version resource) and stages that binary as `dist\ExileLens\_internal\ExileLensUpdater.exe`. `release.yml` does not rebuild it, so the hashed and gated binary is the shipped one;
6. provenance (`scripts\validate_release_binary_provenance.py`) → `dist\ExileLens\binary_manifest.json`, then `build_stamp.json`.

### Provenance

`binary_manifest.json` (schema 2) records, with **no absolute path** (origins are `<root kind>/<relative path>`, for example `release-venv/Lib/site-packages/PySide6/Qt6Core.dll`):

- both executables (`ExileLens.exe`, `_internal\ExileLensUpdater.exe`): SHA-256, size and their build inputs (spec, version resource, icon, entry point, each with its SHA-256);
- every native `.exe/.dll/.pyd` in the package: hash, size and origin. A native file with no PyInstaller COLLECT entry, or from outside the release venv / build tree / pinned Python / Windows system directories, fails the build; the shipped updater must be byte-identical to the single updater build output;
- application version, git commit, Python and PyInstaller versions, architecture, build timestamp and the SHA-256 of `requirements-release.lock`.

`build_stamp.json` holds the commit, version and toolchain versions.

## Gates

`python -m exilelens.ops.cli release-gate` (**pre-build**: the configuration appears valid) and `... release-gate --require-artifact` (**post-build**: the artifact is verified). The pre-build mode never claims artifact compliance.

Pre-build checks include: version coherence (both version resources), the spec audit (`exilelens.ops.packaging_spec`: structural AST checks of both specs: entry points, icon, version resource, UPX off, hookspath, runtime hook, excludes, onedir vs onefile, no code-signing configuration), dependency-lock and license documentation consistency, shipping copy, update trust set, cloud config.

Post-build (`--require-artifact`) adds: both executables present and carrying the canonical version/product/description/original-filename in their Windows version resource; `binary_manifest.json` matching the packaged files byte for byte and containing no absolute path; license and notice files present and byte-identical to the committed copies; no GPL-only Qt module or plugin; the Qt module inventory matches the LGPL-approved set and layout; leak scan clean; the packaged binary itself reports that it trusts only `exilelens-prod-1` and loads its release notes.

### Leak scan and secret scan

```powershell
$env:PYTHONPATH = "src"
python -m exilelens.ops.leak_scan source .                                  # committed credentials in tracked files (PR validation, release.yml)
python -m exilelens.ops.leak_scan package dist\ExileLens --zip <release.zip>  # the built package and the final ZIP (release.yml, gate)
```

They report **only category, file path and count — never a matched value**. The package scan blocks absolute developer paths (`C:\Users\<person>\…`, the build machine's checkout/profile path), private-key headers, `.pem`/`.key`/`.dev.vars`/`.env` files, GitHub/Cloudflare/Discord token shapes, named secrets (`PATREON_ID_PEPPER`, `EXILELENS_UPDATE_SIGNING_KEY_B64`, …) with a non-placeholder value, a bad `release_config.json`, and `*.workers.dev` hosts. The allowlist (`exilelens.ops.leak_scan.ALLOWLIST`) is tiny and path-specific (the public test signing key and two test fixtures). PyInstaller's compressed PYZ archive is not scannable byte-wise; the source scan covers what it is built from.

## What gets bundled

- PySide6 (Qt) runtime and plugins, filtered so no GPL-only Qt module ships (`QT_LGPL_COMPLIANCE.txt`)
- `exilelens` Python package, `cryptography` (with its OpenSSL), `cffi`
- `runtime/lua/` bridge scripts used by the PoB worker subprocess
- `README.txt`, `LICENSE`, `THIRD_PARTY_NOTICES.txt`, `QT_LGPL_COMPLIANCE.txt`, `third_party_licenses\`
- the MIT-licensed PoB headless support definitions documented in `THIRD_PARTY_NOTICES.txt`

**Not bundled:** the Path of Building application/runtime/data, build XML files, or user settings (`%LOCALAPPDATA%\ExileLens\settings.json`). A Git checkout is not required. The measured inventory of a real build is in `docs/release-1.0/ARTIFACT_INVENTORY.md`.

## External updater

`ExileLensUpdater.exe` is staged at `dist\ExileLens\_internal\ExileLensUpdater.exe`; the release gate blocks without it. It carries the ExileLens icon and a Windows version resource with the **same** version as `ExileLens.exe` (there is no separate updater version).

**Self-refresh:** at runtime the app copies the bundled updater to `%LOCALAPPDATA%\ExileLens\ExileLensUpdater.exe`, and refreshes that copy whenever its SHA-256 differs from the bundled one (never while an updater holds the `Local\ExileLens.Updater` mutex). A new updater therefore reaches existing installs on their first launch of the new version.

**Install-folder work directories:** updates swap entries through `.update-new\` and `.update-old\` inside the install folder, so every move is a same-volume rename. `.update-old\` is removed after the next healthy launch. The install folder must therefore be user-writable, which the portable ZIP layout already requires.

**Cloud contract and endpoint (R2):** `exilelens/cloud/events.v1.json` (byte-identical to `cloud/schema/events.v1.json`, checked by the release gate) is bundled as data. `release_config.json` is generated by `release.yml` from the repository variable `EXILELENS_CLOUD_API_URL` and is git-ignored; when the variable is unset the file is absent and all cloud features stay off. A `*.workers.dev` or non-https value is rejected by the workflow, the gate (`cloud_config`) and the leak scan.

**Trust self-report:** `ExileLens.exe --exilelens-update-trust-report <file>` writes the update trust set of the built binary (key ids only) and exits before any UI starts. The artifact gate uses it to prove that shipping builds trust only `exilelens-prod-1`.

The full contract, transaction and recovery are in `docs/UPDATE_RELEASE_SIGNING.md`.

## Release workflow (summary)

`release.yml` (workflow_dispatch; **main only**; one run at a time via `concurrency: release-production`, never cancelled mid-publication): reject non-main → checkout without persisted credentials → pinned Python → static checks (lock `--check`, version resources, source secret scan) → tag/release must not exist → source gate → release regressions → cloud config → **one** build (`build_exe.ps1`) → `release-gate --require-artifact` → materialize the production signing key (only this step sees the secret) → ZIP, `SHA256SUMS.txt`, signed manifest, verification under the production trust profile → remove the key file (always) → leak scan of directory and ZIP → release-notes check → (unless `dry_run`) `gh release create` with all assets in one call. The previous manual asset-upload flow no longer exists. See `docs/UPDATE_RELEASE_SIGNING.md` for key handling.

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
| Release dependencies | hash-locked, no extras | `packaging/requirements-release.lock` |
| Packaging | PyInstaller onedir (GUI) + onefile (updater), UPX disabled, no code signing | `packaging/*.spec` |

## Rebuild from spec only

PyInstaller is installed only by the hash-locked release venv (never ad hoc). Use the release venv that `build_exe.ps1` creates; to rebuild only the GUI spec:

```powershell
.\.release-venv\Scripts\python.exe -m PyInstaller packaging/exilelens-gui.spec --noconfirm --clean
```

(A spec-only rebuild skips provenance, notices and the updater; use `build_exe.ps1` for anything you intend to inspect.)

## Git artifacts

`dist/` and `build/` are gitignored. `packaging/` and `scripts/` are committed.
