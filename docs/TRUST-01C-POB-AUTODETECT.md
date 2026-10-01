# TRUST-01C — Path of Building Auto-detect v2

**Discovery finds candidates; PoB validation decides whether they are usable.**

`src/exilelens/pob_discovery.py` proposes paths from several local sources. Every proposal, from any
source, goes through the one existing boundary (`config._is_discoverable_pob2`: required runtime files,
`validate_pob_path`, manifest provenance, PoB1 rejection, `Path of Building.exe`-only rejection). Directory
names, registry strings and shortcut names are never trusted on their own. `validate_pob_path`,
`detect_pob_identity` and the provenance checks are unchanged. A cheap `exists()` pre-filter keeps the `git`
probe inside validation from running on non-PoB folders.

## Sources (strongest first)

1. `POB2_PATH` (explicit)
2. the saved `settings.pob_path` (if it still validates)
3. Uninstall registry: `HKCU`, `HKLM` and the WOW6432 view of `Software\Microsoft\Windows\CurrentVersion\Uninstall`;
   entries whose `DisplayName` mentions Path of Building; directory taken from `InstallLocation`, else `DisplayIcon`,
   else `UninstallString` (quotes, `,index` and the exe name stripped). At most 3000 subkeys per hive.
4. App Paths: only the real executable name `Path of Building-PoE2.exe` (`Path` / default value).
5. Existing exact standard locations (`pob_installation_candidates`, unchanged).
6. Start Menu shortcuts: `%APPDATA%` and `%PROGRAMDATA%` `...\Start Menu\Programs` and its immediate PoB-named
   subfolders; `.lnk` files whose name mentions Path of Building (max 64, each under 64 KiB), resolved by a small
   stdlib parser of the Shell Link `LocalBasePath`. No dependency, no PowerShell.
7. Shallow scan: child folders (depth 1 only) of `%LOCALAPPDATA%\Programs`, Program Files (both), Documents,
   Downloads, Desktop and OneDrive Documents whose own name looks PoB-related. At most 400 children and 8 matches per
   root, plus a 3 s overall time budget. No recursion, no whole-drive or other-profile scan.

Registry and shortcut readers are injectable and import-guarded (`winreg`), so non-Windows hosts and tests never
need a real registry. A failing source is skipped, never fatal.

## Deduplication and ranking

Duplicates collapse on the case-insensitive normalised absolute path (existence is not required); the strongest
source is kept and all finders are recorded for diagnostics. Order:

1. user intent (explicit, then saved)
2. verified official PoB2 manifest over unverified/missing manifest
3. installed application over developer source checkout
4. higher known version (existing manifest version; unknown never ranks as newest and is never rejected)
5. source confidence (registry > App Paths > standard > shortcut > scan)
6. canonical path (final deterministic tie-break only)

## Ambiguity and settings

One clearly best installation is auto-selected. If two or more non-user-intent candidates are equivalent
(same verified state, layout and version) nothing is chosen. Startup then leaves `pob_path` untouched and the
Settings → Advanced **Auto-detect** button lists them ("Multiple Path of Building installations were found":
version · installed/source · shortened path). Manual **Browse** is always available.

* A configured path that still validates is kept and discovery does not run.
* An invalid/empty path is replaced only by exactly one clear validated installation, and saved after validation.
* **Auto-detect** (Settings → Advanced): one result is applied, several are offered, none keeps the current path
  and points to Browse.

## Local only

No network, no process launch, no PoB worker, no recursion. Nothing leaves the machine. Logs record counts and source
names only, never registry contents or paths.

## Not done

Recursive/whole-disk search; reading other users' profiles; downloading or updating PoB.
