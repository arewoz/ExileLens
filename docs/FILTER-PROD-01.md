# FILTER-PROD-01 integration evidence

This change brings Loot Filters and Analyze Build into the normal dashboard with a shared Experimental badge. Native PoE2 acceptance remains **UNVERIFIED**; the PR must remain unmerged until observations for the exact acceptance files and required GitHub checks pass. No release is published.

## Source and scope

- Research source: `filter-05-sync-main`, `85928d88d67a261bae1bb0b8474742da09fe8ce5`.
- Starting production main: `d7335703df847845135d30cb6f5175498a504656` (PERF-01).
- Integration branch: `integrate/filter-prod-01`, selectively ported from that source onto production main. The research history is not merged.
- Local backup reference: `backup/filter-prod-01-research-20261013`. Independent ENGINE work is preserved.

Production sensitivity, Build Priorities, item comparison, market/privacy contracts and cache scheduling are retained. Filters can request existing additional defence probes explicitly; normal Analyze Build uses its unchanged catalog. Filter UI is loaded on first navigation. Endgame settings migrate to Very Strict; Recommended remains the default.

## Product changes

Essential information is build identity/freshness, measured responses, the most urgent issue and ranked actions. Tested increments, confidence, Search Intent, health/coverage evidence and exports remain accessible through toggles, tooltips and disclosures. Internal slot identifiers become readable UI labels. Results describe measured PoB responses, without promising an in-game improvement.

Loot Filters shows profile/theme, compact personalization state, preview and one Generate & Install action. Selected, generated and installed configurations are distinct. Hashes, mapping limitations, market provenance, native effects and installation diagnostics live under Details & diagnostics. The preview seed persists across configuration changes; Reroll is explicit. All five approved profiles and eight V4 themes are retained, including the hero plaque, persistent top-category beams and restrained ordinary equipment.

Without PoB, generation is full and offline. Current analysis adds measured opportunities; missing/incomplete/stale analysis degrades conservatively. No market request or consent is needed. Installation validates before writing, checks ownership on every entry point, stages/flushes in the destination directory, replaces atomically and restores prior bytes after a verification failure. Folder inspection never overwrites a probe file; application verification never claims that PoE2 reloaded the filter.

Generated application files use `ExileLens_<Strictness>.filter`, for example `ExileLens_Recommended.filter` and `ExileLens_Very_Strict.filter`. Different profiles stay separately selectable; theme/build changes update only that profile. Legacy `ExileLens_Test.filter` is preserved and can still be inspected. The naming follow-up passed 31 focused installation/UI checks; it does not change generated filter bytes. New acceptance packages put strictness before theme/mode; the previously supplied acceptance package remains intact.

## Evidence and reproduction

The native registry separates ground items, synthetic PoB objects and non-ground objects. A dated registry establishes bounded evidence, not permanent game compatibility. Exact BaseType serialization and a separate unknown safety rule prevent substring collisions and default known-equipment presentation. There is no Soldier Cuirass special case.

- Native static preflight: 200 build/profile/theme combinations; 1,784 distinct emitted ground bases validated; zero unknown/ambiguous/synthetic names, text violations or generation failures.
- Styled coverage: 6,348 distinct item states, 126,960 decisions across five profiles, two build modes and campaign/maps; 339,200 Rare equipment evaluations. Zero visible unstyled fallthrough, known items in unknown safety, Rare equipment without styling or theme visibility differences.
- Acceptance package: 80 profile/theme/mode files, manifest file/rule SHA-256 values, static preflight, exhaustive ground-base load filter and manual checklist. Synthetic Spark is a contract fixture, not a real gameplay gain measurement.
- Application regression: 1,435 passed. UI/startup/installation suite: 90 passed. Production compatibility suite: 314 passed. Packaging/distribution/compliance contracts: 175 passed.
- Full filter suite: 414 passed, 8 skipped in 840.43 seconds. Six skips require an external PoB checkout/live analysis; two weapon-requirement cases do not apply to Wands/Sceptres and are covered by spell-build checks.
- Final packaging: PASS with pinned Python 3.12.10 / PyInstaller 6.22.2, onedir, code commit `12628465e70bf931c366e9a0f919b0f52e5aea72`. Provenance validates 63 native libraries and two executables. The actual frozen EXE constructed the filter page, generated all 40 general combinations and found both badges and the preview background. [Smoke report and executable SHA-256](validation/filter-prod-01/packaging-smoke.json). The Python 3.12 Windows-folder ABI error found during the first smoke was corrected; the build was repeated successfully. Subsequent documentation commits do not alter executable code. Version remains 0.7.0b1; this is local validation, not a published release.

Run offline checks from the repository root:

```powershell
$env:PYTHONPATH='src;.'
python scripts/filter_native_preflight.py --out .run/native --workers 4
python scripts/filter_style_coverage.py --out .run/coverage --legal 4000 --workers 4
python scripts/filter_product_acceptance.py --out .run/native-acceptance-final
python scripts/filter_product_qa.py --out .run/visual
python -m pytest
```

Filter tests use explicit `-o addopts= -m 'not integration and not real_pob'`, because the standard application suite excludes experimental feature tests. Portable needs fixtures contain public corpus measurement projections with source identities removed; the private research build was replaced by a synthetic fixture.

Actual Qt screenshots were inspected at 980×720 and 720×560, including errors, loading, stale results, disabled controls, keyboard shortcuts/focus, long build names, dense labels, light ground and scroll behavior. 125% uses `QT_SCALE_FACTOR=1.25` on Windows; this is Qt scaling emulation, not a claim that the OS display setting was changed. Before filter evidence mounts the research page in the production frame; it was not an existing production tab. Only a small selection of reviewed screenshots is committed; detailed logs and the native package remain local under `.run`.

| Screen | Before | After |
| --- | --- | --- |
| Analyze Build | [Production surface](media/filter-prod-01/analyze-before.png) | [Integrated surface](media/filter-prod-01/analyze-after.png) |
| Loot Filters | [Research surface](media/filter-prod-01/filters-before.png) | [Integrated surface](media/filter-prod-01/filters-after.png) |

Additional reviewed cases: [long build name](media/filter-prod-01/analyze-long-name.png), [dense light-ground preview](media/filter-prod-01/dense-light.png). Inspectable static evidence: [native preflight](validation/filter-prod-01/native-preflight.json), [styled coverage](validation/filter-prod-01/styled-coverage.json).

## Merge gates

Static correctness and coverage establish A–C within the pinned data/corpus bounds. Workflow/profile/theme, Analyze Build, installation, UI review and application regressions establish D–I. Packaging J is completed with the pinned Python 3.12.10 build and actual frozen feature report. Public hygiene L excludes private builds/paths, research scratchpads and generated release outputs, and retains data/asset attribution. Gate M requires the protected PR's strict `smoke` check and all other checks. Main ruleset 23609526 requires a PR, linear history and resolved review threads; no bypass or force push is used.

**Gate K is UNVERIFIED:** record client version, exact manifest hashes, parser loads, Rare equipment styling, five-profile/eight-theme gameplay, sounds/icons/persistent beams, and installation/reload observations. Static checks and simulated effects cannot supply this evidence. Merge is authorized only after every gate passes.

See [the product guide](EXPERIMENTAL-FEATURES.md) for usage, patch updates, limitations and reporting suspicious decisions.
