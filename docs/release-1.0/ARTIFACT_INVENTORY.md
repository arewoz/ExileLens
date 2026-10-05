# 1.0-C artifact inventory and compliance evidence (internal 0.7.0b1 hardening artifact)

This records what a real, release-equivalent Windows package of **0.7.0b1** contains and the evidence behind the licensing and provenance
claims. It is **not** the 1.0 release candidate: the final artifact, its inventory and the hashes below are redone from the RC commit by
`release.yml` (`dry_run=true`) in 1.0-E. Nothing here was published, tagged or uploaded.

## 1. The build

| | |
|---|---|
| Command | `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_exe.ps1 -SkipShortcut` (the command `release.yml` runs) |
| Where | a fresh disposable `git worktree` of the 1.0-C branch (detached HEAD), no `dist/`, `build/` or `.release-venv` beforehand |
| Source commit | `9dbd68e2c19c85b7af0cfdc9d9b9c6c551093031` (later commits on the branch change only documents, tests and evidence, not packaged inputs) |
| Python | 3.12.10 (`.python-version`), release venv created and hash-verified by the preflight: `pip install --require-hashes -r packaging/requirements-release.lock` (279 hashes, 15 packages), contamination check passed |
| PyInstaller / PySide6 / cryptography | 6.22.2 / 6.11.2 / 50.0.0 |
| Duration | 1 min 23 s including creating the venv and installing the locked dependencies |
| Package | `dist\ExileLens`: 205 files, 100,598,759 bytes (96 MiB); ZIP made exactly as `release.yml` does (`Compress-Archive`, optimal): 47,852,441 bytes |
| ZIP SHA-256 | `526d4dae181e0db68c42d8e722d452c00fb529d5cdb935f2a2c277581236d716` (internal artifact, not published) |
| `ExileLens.exe` SHA-256 | `403ec9b107f54ec1c7832d31215720f7d0dfd95dca270d7ef21390ae9aa44c4c` (4,887,983 bytes) |
| `ExileLensUpdater.exe` SHA-256 | `c5bd66f6898ac716fc83d506e906e5c806287d64f9cd2ca46f07febfe5cb86fe` (9,757,017 bytes) |

The updater is built **once**. The build output (`dist\ExileLensUpdater.exe`) and the shipped copy (`_internal\ExileLensUpdater.exe`) have the same
SHA-256, and `binary_manifest.json` is written after that single build and refuses a package whose updater differs from it. Before 1.0-C the
updater was built twice (once inside `build_exe.ps1`, once more by a separate `release.yml` step after provenance was recorded).

Both executables carry the ExileLens icon and a Windows version resource with the same canonical version `0.7.0b1` (file and product version),
`ProductName` ExileLens, `CompanyName` ExileLens, `FileDescription` "ExileLens" / "ExileLens Updater", `OriginalFilename` `ExileLens.exe` /
`ExileLensUpdater.exe`. There is no separate updater version.

## 2. Provenance (`binary_manifest.json`, schema 2)

Records for **both** executables: SHA-256, size, and the SHA-256 of their build inputs (spec, version resource, icon, entry point); plus
application version, git commit, Python, PyInstaller, PySide6, architecture (`AMD64`), build timestamp and the SHA-256 of
`requirements-release.lock`. All 63 native files are listed with hash, size and an origin of the form `<root kind>/<relative path>`
(`release-venv/…`, `python-runtime/…`, `windows-system32/…`, `build/…`); no absolute path ships. The artifact gate cross-checks it against
the package byte for byte.

## 3. Qt in the real package

### 3.1 What ships

PyInstaller's PySide6 hooks collect more Qt than ExileLens uses. The first (unfiltered) real build contained 12 Qt libraries and 21 plugins:
the five ExileLens imports (`QtCore`, `QtGui`, `QtWidgets`, `QtSvg`, `QtNetwork`) plus Qt Quick, Qt Qml (4 libraries), Qt PDF with its image
plugin, Qt6OpenGL, the 20 MB software OpenGL renderer `opengl32sw.dll` and five `qtimageformats` plugins (icns, tga, tiff, wbmp, webp). A PE import
graph of that package (parsed with `pefile`) showed that Qt6Pdf was imported only by `qpdf.dll`, Qt6Quick by nothing, Qt6Qml only by the Quick/Qml
libraries themselves and Qt6OpenGL only by Qt6Quick: nothing the application needs reaches them, and the source has no QML, PDF, OpenGL or
WebP/TIFF use. The spec now removes them by name (`_UNUSED_QT_BINARY_TOKENS`, mirrored in `release_gate.UNUSED_QT_BINARY_TOKENS`), so the
shipped Qt surface is exactly the two source modules **qtbase** and **qtsvg** and the Windows-relevant third-party components listed in
`QT_THIRD_PARTY_ATTRIBUTIONS.txt`. The final package (63 native files, was 77) contains, all under `_internal\PySide6\`:

| Library | Source module | | Plugin | Source module |
|---|---|---|---|---|
| `Qt6Core.dll` | qtbase | | `platforms\qwindows.dll` | qtbase |
| `Qt6Gui.dll` | qtbase | | `platforms\qdirect2d.dll`, `qminimal.dll`, `qoffscreen.dll` | qtbase |
| `Qt6Widgets.dll` | qtbase | | `styles\qmodernwindowsstyle.dll` | qtbase |
| `Qt6Network.dll` | qtbase | | `tls\qschannelbackend.dll`, `qopensslbackend.dll`, `qcertonlybackend.dll` | qtbase |
| `Qt6Svg.dll` | qtsvg | | `networkinformation\qnetworklistmanager.dll` | qtbase |
| | | | `generic\qtuiotouchplugin.dll` | qtbase |
| | | | `imageformats\qgif.dll`, `qico.dll`, `qjpeg.dll` | qtbase |
| | | | `imageformats\qsvg.dll`, `iconengines\qsvgicon.dll` | qtsvg |

Plus the PySide6 binding files (`QtCore.pyd`, `QtGui.pyd`, `QtWidgets.pyd`, `QtSvg.pyd`, `QtNetwork.pyd`, `pyside6.abi3.dll`, `shiboken6.abi3.dll`),
which are PySide6 / shiboken6 6.11.2 (Qt for Python).

### 3.2 Licence classification (official Qt 6.11.2 metadata)

* Every source file of the shipped modules and plugins in the official archives carries the SPDX header
  `LicenseRef-Qt-Commercial OR LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only` (build files `BSD-3-Clause`); checked for `src/corelib`, `src/gui`,
  `src/widgets`, `src/network`, `src/svg` and for each shipped plugin directory (platforms windows / direct2d / minimal / offscreen, styles
  modernwindows, tls schannel / openssl / certonly, networkinformation networklistmanager, generic tuiotouch, imageformats gif / ico / jpeg / svg).
  An LGPL-3.0 option exists for every shipped Qt file.
* **GPL-only / commercial-only Qt modules**: none. Qt Virtual Keyboard, Qt Charts, Qt Data Visualization, Qt Graphs, Qt HTTP Server and Qt
  Network Authorization were **not collected** by PyInstaller 6.22.2 with PySide6 6.11.2 in the unfiltered build (the 1.0-A finding came from an
  older build); the filter is still enforced: `test_release_1_0c_compliance.py` runs the spec's own `a.binaries = [...]` comprehension on rows
  named like each of those modules (and the removed unused ones) and proves they are dropped while the approved set is kept; the artifact gate
  fails if any such file, or any Qt library / plugin outside the approved list, is in a built package.
* Third-party components inside the shipped Qt libraries: 41 components from the `qt_attribution.json` files of qtbase and qtsvg
  (PCRE2, zlib, FreeType, HarfBuzz, libpng, libjpeg-turbo, md4c, Unicode CLDR / UCD, tinycbor, BLAKE2, SHA-3, double-conversion, the Public Suffix
  List, Wintab, XSVG and others) are written, with their license texts copied verbatim, to `third_party_licenses\qt\QT_THIRD_PARTY_ATTRIBUTIONS.txt`
  by `scripts/generate_qt_attributions.py`. Components Qt ties only to other platforms (macOS, Linux, Android, Wayland, xcb, ARM) or to modules that
  do not ship (SQL, D-Bus, Test, Quick, PDF, WebEngine) are excluded. Run-time confirmation: the process loads `Qt6Core`, `Qt6Gui`, `Qt6Widgets`,
  `Qt6Network`, `Qt6Svg`, `qwindows.dll`, `qmodernwindowsstyle.dll` and `qico.dll` from the package folder (section 5).

### 3.3 Source offer: retrievable archives

The shipped Qt libraries come from three upstream archives, re-downloaded from the official locations for this slice, opened, and hashed
(kept outside the repository in a local `compliance-evidence/qt-6.11.2/` folder beside the checkout; **not committed**). The Qt MD5 is the value
published in `md5sums.txt` beside the archives and matched; `download.qt.io` publishes no checksum for the Qt for Python archive, so only its
SHA-256 (computed here) is recorded. The three SHA-256 values equal those first recorded in 1.0-A, i.e. the files are stable.

| Archive | URL | MD5 | SHA-256 |
|---|---|---|---|
| `qtbase-everywhere-src-6.11.2.tar.xz` (50,582,668 B) | `https://download.qt.io/official_releases/qt/6.11/6.11.2/submodules/qtbase-everywhere-src-6.11.2.tar.xz` | `cb3b718e2e589b61bd781b4596604a5b` | `5b2e00eccaf5a4d8c14134ffa0ea8dfd0a35ae1ffc7f8d87fa4305a1ed23cf22` |
| `qtsvg-everywhere-src-6.11.2.tar.xz` (2,341,860 B) | `https://download.qt.io/official_releases/qt/6.11/6.11.2/submodules/qtsvg-everywhere-src-6.11.2.tar.xz` | `fb1c8366fe3de6ed3ca248bf4ae88c37` | `d594337feca84c26fb67fe87b85e6a5c12fda404b611d905f9d138210c311876` |
| `pyside-setup-everywhere-src-6.11.2.tar.xz` (18,053,248 B) | `https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.11.2-src/pyside-setup-everywhere-src-6.11.2.tar.xz` | (none published) | `cba47efbaad1bedd529725cbc14e21f156c7a19366f07b3edfbb076ffd7afdf8` |

Each archive extracts completely; version identity: qtbase `.cmake.conf` and qtsvg `.cmake.conf` set `QT_REPO_MODULE_VERSION "6.11.2"`;
`sources/pyside6/.cmake.conf` sets pyside 6.11.2. The complete single archive `qt-everywhere-src-6.11.2.tar.xz` (MD5 `669c1f3a41c37fdda389094882044d7a`)
was **not** downloaded: it is a superset and not needed. To re-acquire for a release: download the three URLs, compare the hashes above, and archive them
with the release. `QT_LGPL_COMPLIANCE.txt` (shipped) names exactly these archives.

## 4. Replacement proof (LGPL "replace the library" route)

`scripts\qt_replacement_proof.ps1` works on a **copy** of the built package with an isolated profile (the original package is never touched):

1. baseline: `ExileLens.exe` starts (tray ready); the loaded Qt modules and plugins are all taken from `_internal\PySide6\…` in the package folder;
2. replacement: `_internal\PySide6\Qt6Core.dll` is replaced by a different but valid copy (original bytes plus a 16-byte overlay, so a different SHA-256):
   the application starts and the **loaded** `Qt6Core.dll` has the replacement's SHA-256;
3. incompatible file: replaced by garbage, the application does **not** start (proves the file is really what gets loaded);
4. restore: original put back, the application starts again, and every file of the copy is byte-identical to the original package; nothing new was written
   into the package folder by running it.

Result on the 0.7.0b1 artifact: all four steps passed. Documented paths in `QT_LGPL_COMPLIANCE.txt` (`_internal\PySide6\`, `Qt6*.dll`, `plugins\`, `_internal\shiboken6\`)
match the real layout; `ExileLens.exe` is 4.9 MB and contains none of the Qt libraries. The proof replaced a library with a modified copy of the same
build, not with a Qt rebuilt from source (not required for the claim; a rebuilt, interface-compatible Qt behaves the same at load time).

## 5. Bundled dependency inventory (measured)

| Component | Present | Evidence / notes |
|---|---|---|
| Python runtime 3.12.10 | yes | `python312.dll` version resource 3.12.10; `python3.dll`; PSF license + incorporated-software file shipped byte-identically (expat, libffi, zlib, libmpdec, OpenSSL are listed there) |
| OpenSSL for Python's `ssl`/`hashlib` | yes, **OpenSSL 3.0.16** | `libcrypto-3.dll` reports `OpenSSL 3.0.16 11 Feb 2025`; `libssl-3.dll`. Origin: the CPython 3.12.10 runtime (`python-runtime/DLLs/`). Its Apache-2.0 text is inside `LICENSES-incorporated-software.rst` |
| OpenSSL inside `cryptography` | yes, **OpenSSL 4.0.1**, statically linked | `cryptography\hazmat\bindings\_rust.pyd` reports `OpenSSL 4.0.1 9 Jun 2026`; equals the wheel's own SBOM; license `openssl\LICENSE.txt` |
| cryptography 50.0.0 | yes | `cryptography`, `_rust.pyd`, dist-info licenses and SBOMs |
| cffi | **only the compiled backend** `_cffi_backend.cp312-win_amd64.pyd` (+ CPython's `libffi-8.dll`) | no `cffi` Python modules in the frozen archive; MIT-0 license shipped |
| pycparser | **no** | no module in the frozen archive and no file in the package; it is pinned only because cffi needs it to build. Its notice and license file were removed (they claimed redistribution) |
| bzip2 / liblzma | yes (`_bz2.pyd` = bzip2 1.0.8, `_lzma.pyd`) | bzip2 license `python\BZIP2-LICENSE.txt` added (source `bzip2-1.0.8.tar.gz`, SHA-256 `ab5a03176ee106d3f0fa90e381da478ddae405918153cca248e682cd0c4a2269`); XZ is public domain |
| PySide6 / shiboken6 6.11.2 | yes | section 3 |
| PyInstaller bootloader | yes (the stub of **both** executables) | `pyinstaller\COPYING.txt` shipped (GPL-2.0-or-later with the bootloader exception) |
| Microsoft Visual C++ runtime | yes | `vcruntime140*.dll` (`_internal`, `PySide6`, `shiboken6`), `msvcp140*.dll` (`PySide6`, `shiboken6`) |
| Spectral SemiBold + OFL | yes | `assets\fonts\Spectral-SemiBold.ttf`, `OFL.txt` |
| Vendored PoB support files | yes | `runtime\lua\bridge.lua`, `pob_headless_wrapper.lua`, `pob_simplegraphic.def.lua`, `worker_init.lua` |
| `release_config.json` | absent in this build | no `EXILELENS_CLOUD_API_URL` was configured; cloud features stay off |
| License material | yes | `LICENSE`, `THIRD_PARTY_NOTICES.txt`, `QT_LGPL_COMPLIANCE.txt`, `third_party_licenses\` byte-identical to the committed copies |

Python license material: the shipped `python\LICENSE.txt` and `LICENSES-incorporated-software.rst` are the committed CPython 3.12.10 files (byte-identical,
SHA-256 pinned by `test_third_party_texts_are_the_exact_upstream_bytes`) and match the runtime (`python312.dll` = 3.12.10). The one incorporated component the
runtime ships that is **not** in that file is bzip2, which is now covered above.

Native build paths: the third-party binaries carry their upstream CI paths in diagnostic strings (the Qt CI account in every Qt library and the GitHub-hosted
runner account in cryptography's Rust module). They are not ExileLens developer paths, and the leak scanner tolerates exactly those two account names, only
inside third-party `.dll`/`.pyd` files; any other account name, any path inside an ExileLens-built file, and the build machine's own checkout and profile
paths still block a release.

## 6. Checks run on this artifact

| Check | Result |
|---|---|
| `release-gate --require-artifact` (23 checks) | **PASS** (one pre-existing warning: `game_compatibility` UNVERIFIED) |
| leak scan of `dist\ExileLens` and of the final ZIP, with the build machine's checkout and profile paths as literals | **PASS** (0 findings) |
| `ExileLens.exe --exilelens-update-trust-report` | exit 0; frozen, profile `production`, key ids `["exilelens-prod-1"]` |
| `ExileLens.exe --exilelens-whats-new-report` | exit 0; notes for 0.7.0b1 loaded, no problems |
| `ExileLensUpdater.exe --help` / `--recover --updates-dir <empty>` | exit 0 / exit 0 |
| GUI launch with an isolated profile | tray ready, setup dialog, Dashboard composed (it builds the Settings and Diagnostics pages), PoB worker started and `engine_ready`, second launch activated the running instance, `--quit` exit 0, process ended cleanly with exit code 0, no stray process; no `Traceback` / `ImportError` / `DLL load failed` in the log |
| Windows Defender (`MpCmdRun -Scan -ScanType 3`, engine 1.1.26080.3, signatures 1.459.557.0) on each executable | `ExileLens.exe`: no threats; `ExileLensUpdater.exe`: no threats |
| VirusTotal | **not run** (a submission would publish the hash of an internal artifact); deferred to the RC in 1.0-E |

The GUI launch is a packaging smoke only, not the 1.0-D UX pass.
