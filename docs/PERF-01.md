# PERF-01 — Runtime responsiveness

Base: `origin/main` `959e54d`. Version unchanged. No verdict, scoring, uncertainty or supportability logic was changed; every change
removes work from the Qt UI thread, removes work nobody consumed, or reorders work onto the PoB lane that was already going to run.

Measured on the development machine (Windows 11, 20 logical cores, installed PoB Community PoE2 0.23.1, `POB2_PATH` unset), **source runs on Python 3.14**,
not on the packaged runtime. The machine was shared with a browser and a game launcher, so absolute timings drift by up to 3x between runs: every
comparison below is interleaved base/optimized and reported as medians (and p95 where the sample allows). Do not read the absolute numbers as packaged
performance (see [Limitations](#limitations)).

## Results (baseline `959e54d` vs this branch `dff6946`)

**Method.** `scripts/perf01_measure.py` (real PoB 0.23.1 installed runtime, real controller / overlay / dashboard objects, isolated profile, no global
hotkey, overlay opacity 0 so paints are real but invisible). Three rounds, each round runs base then optimized for every scenario, so machine drift
lands on both sides. Builds: `core04_player_ring` (small), `core04_melee_weapon`, `corpus02e_spell_totem_titan` (heavy, multi-skill, minion),
`core04_poison_ailment` (ailment audit). "Back-to-back" = next Shift+C about 120 ms after the previous result (loot scanning); "paced" = 4 s between
checks. Warm samples n=12 per build (3 rounds x 4), first-check and load samples n=3, startup n=3. **UI stall** = longest gap of a 4 ms event-loop
heartbeat (>= 40 ms reported); **compute** = the worker's `run_evaluation` span (PoB), so UI and compute are separate columns. Values are medians
with p95 in brackets; p95 over n=3 is just the largest sample. Raw per-run JSON is in `artifacts/perf01/ab/` (not committed).

### UI thread (what the user feels as a frozen app)

| Event | Baseline | Now |
|---|---|---|
| Build load / switch, UI thread held by the call (ring / melee / totem / poison) | 0.83 / 5.9 / 2.5 / 4.2 s | **41-49 ms** (all four) |
| Build load, longest event-loop stall | 0.8 / 1.8 / 1.8-2.0 / 1.3 s | **48-56 ms** |
| Startup load (tray visible), longest stall, ring / totem | 0.90 s / 2.0 s | **55 ms / 55 ms** |
| First Item Check on an ailment build: submit -> first placeholder paint | 2.1 s | **2 ms** |
| Overlay `show_result` (UI work per check) | 5-10 ms | 5-9 ms (unchanged) |

### Item Check latency (submit -> result), median [p95]

| Build | Scenario | Baseline | Now |
|---|---|---|---|
| ring | back-to-back warm | 939 [1275] ms | **262 [487] ms** |
| melee | back-to-back warm | 3906 [5010] ms | **494 [929] ms** |
| totem | back-to-back warm | 6041 [6501] ms | **1215 [1515] ms** |
| poison | back-to-back warm | 2392 [2581] ms | **750 [1027] ms** |
| melee | paced warm | 986 [1272] ms | **478 [775] ms** |
| totem | paced warm | 1990 [2688] ms | **1086 [1318] ms** |
| poison | paced warm | 984 [1329] ms | **705 [1069] ms** |
| ring | paced warm | 257 [279] ms | 265 [435] ms (no change; within noise) |
| ring / melee / totem / poison | first check after load | 470 / 1116 / 2205 / 3583 ms | **323 / 881 / 903 / 2673 ms** |
| any | result-cache hit | 19-29 ms | 19-28 ms (unchanged) |

Of the back-to-back baseline latency, the wait for the PoB lane held by the previous check's background work was 651 / 3002 / 4452 / 1495 ms
(ring / melee / totem / poison); it is now 5-6 ms. The PoB compute itself dropped 14-47 % on the builds where the redundant
loadout/item-set re-activation was a measurable share (melee 968 -> 459 ms, totem 1589 -> 1069 ms, poison 961 -> 687 ms paced) and is unchanged on the
small ring build (236 -> 248 ms).

### Startup (source run; process-relative, **not** packaged performance), median [p95]

| Milestone | ring base | ring now | totem base | totem now |
|---|---|---|---|---|
| UI composed, event loop running | 2376 [3325] ms | 1997 [2027] ms | 2348 [2413] ms | 2092 [2119] ms |
| PoB engine ready | 4582 [5059] ms | 2840 [2904] ms | 4055 [4076] ms | 2907 [3005] ms |
| Build loaded and READY | 5465 [5923] ms | 3639 [3707] ms | 6047 [6280] ms | 4535 [4638] ms |

(The measured script's clock starts after the interpreter is up; about 1.9 s of module import is inside the first row on both sides.)

### Packaged runtime smoke (Windows, canonical `scripts/build_exe.ps1`, commit `03156a7`)

A single canonical build (onedir, Python 3.12.10, PyInstaller 6.22.2; provenance validated: 63 native binaries, 2 executables) was launched twice
with an isolated profile pointing at `core04_player_ring.xml`, the network pinned to a dead local proxy, and quit through `ExileLens.exe --quit`.
From the application's own log: tray visible about 1 s after launch, PoB engine ready about 1.5 s, build loaded and READY **2.8-3.0 s** after
launch (`reload_ms` 695-752), Shift+C hook installed before the engine was ready, the preboot adopted by the controller (`engine_preboot_started` then
one `engine_boot_started` that adopts it; one worker process), clean shutdown in about 0.9 s with no leftover `ExileLens.exe` / worker process.
This is a functional smoke result with two samples and **no packaged baseline build was measured**, so it is not offered as a packaged
before/after comparison. A real Item Check cannot be driven without the game window (the capture path requires PoE to be foreground).

### Other measured effects
* Dashboard construction (`_compose_primary_ui`, isolated): 3.4-3.5 s -> 1.3-1.7 s from removing the parentless `setVisible(True)` native windows.
* `get_skill_report` prewarm (interleaved 3 pairs, totem): first check 3 s after the load 1.62 s -> 1.01 s; first check 20 ms after the load
  1.33 s -> 1.43 s (inside the 1.28-2.04 s noise of the baseline, because it waits for the remainder of a pass it would otherwise run inline).
* Identity re-activation in the bridge (3 builds, 3 calls each): `set_active_loadout` 157 / 409 / 279 ms -> 100 / 8 / 8 ms and
  `set_active_item_set` 139 / 415 / 267 ms -> 2 / 5 / 4 ms (the ring build's loadout name does not resolve all four ids, so it keeps the original
  path - correct, just not faster).

## Root causes and fixes

| # | Root cause (measured) | Fix | Commit area |
|---|---|---|---|
| 1 | Build load ran on the Qt UI thread: PoB load + baseline capture + tree ingest froze the app 1.5 s (small build) to 4.3 s (heavy), at startup with the tray already visible and on every build / loadout / item-set / context switch. | `capture_baseline` is a plain function of the engine; loads, switches and the startup load run as a `baseline` job on the PoB lane. The UI thread only begins the transaction (state turns LOADING/RELOADING at once) and applies the capture behind the baseline-generation guard. The tree view-model ingest is computed in the capture. | `baseline_capture.py`, `controller.py` |
| 2 | The post-paint Build Intelligence decomposition (up to 8 sequential PoB transactions) held the single PoB worker: the next Item Check waited for the whole run (2-3 s small builds, 8-11 s heavy), and a build switch waited for it too (8-13 s). | First made yieldable between probes; then, after confirming no consumer, not started by a normal Item Check at all (see [Decomposition](#decomposition-has-no-consumer)). | `decomposition.py`, `engine.py`, `controller.py` |
| 3 | `set_active_loadout` / `set_active_item_set` re-asserted the already-active identity with a full PoB recalculation on every Item Check, every tree snapshot and every baseline capture (130-420 ms each; 0.8-1.4 s of a 2.3-5.9 s heavy-build check). | The bridge skips activation + recalculation only when PoB itself reports exactly that identity (all four set ids) and has nothing pending; the main-effect settle and the response are never skipped. `force` keeps the original path reachable. | `runtime/lua/bridge.lua` |
| 4 | Startup built the whole dashboard with `setVisible(True)` on parentless labels: Qt created and showed a native window per label (~65 ms each). | Hide explicitly, leave children visible by default. Dashboard construction 3.4 s -> 1.3-1.7 s. | `dashboard_widgets.py`, `components.py` |
| 5 | The PoB worker (separate process, ~4 s boot) was started only after the UI was composed. | `EnginePreboot` starts the same boot right after the single-instance lock; the controller adopts it through the unchanged `engine_ready` / `engine_failed` signals. | `engine_preboot.py` |
| 6 | Shift+C right after saving the build in PoB reloaded the build synchronously inside the hotkey handler; the placeholder could not paint until the load ended. | The held Item Check shows the placeholder, the reload runs on the lane, the newest held request resumes against the new generation/identity. A request superseded by a newer Shift+C is retired. | `controller.py` |
| 7 | Worker-crash recovery booted PoB (~4 s) and reloaded the build synchronously on the UI thread. | The build is marked RELOADING with caches invalidated, the replacement worker boots in the background and the build reloads when it is up. | `controller.py` |
| 8 | The minion / ailment offense-coverage audit ran its PoB probes inline on the UI thread, concurrently with the lane, *before* the first placeholder paint (1.75 s on a poison build). | The controller decides from the `get_build_info` captured with the baseline; when an audit is needed its inputs travel with the request and the worker runs the same auditor first. | `controller.py` |
| 9 | The first Item Check after each load paid the multi-skill `get_skill_report` pass inline (0.1 s small, 1.3 s heavy). | Read once after load as a low-priority lane job into the exact cache Item Check reads. | `prewarm.py`, `evaluation.py` |
| 10 | PoB folder checks re-probed `Launch.lua` / `manifest.xml` once per path (a dozen per call, per refresh of every status widget). | One layout probe per call. | `config.py` |

## Decomposition has no consumer

The post-paint "build decomposition" (`run_bounded_decomposition`: up to 8 leave-one-group PoB transactions after every Item Check paint) was
traced to every reader of what it produces:

| Output | Reader | Effect |
|---|---|---|
| `marginal` / `measured` on the important-mod rows (`attach_decomposition` -> `_merge_mod_contributions`) | none: the overlay and the companion list render each row as `stars + label` only | none |
| synergy findings (`explanation.synergy_findings`) | none | none |
| intel `confidence` ASSISTED -> HIGH and its reasons | none (`intel_confidence` in the presentation has no reader; the diagnostics line shows the *decision* confidence) | none |
| `decomposition_status` | the words "Decomposition: ..." in the diagnostics section and "details pending" in the pinned extended window | wording only |
| completion -> `upgrade_path_updated` -> overlay `update_result_in_place` | a second overlay render of an unchanged tooltip | wasted UI work |

It changes no verdict and no quality/uncertainty field. A normal Item Check therefore no longer starts it
(`decomposition.AUTO_RUN_AFTER_ITEM_CHECK = False`); the status says `SKIPPED` instead of claiming "details pending". The function, its yield
support and `attach_decomposition` are unchanged for an explicit caller. (The yield support was the first fix and measured the same lane
release; it is kept because it is what an explicit caller gets.)


## Correctness evidence

* **Verdicts unchanged.** The real-PoB reliability gate (`generate_corpus_coverage_report.py --check-gate`: 188 registered cases, restore / state
  integrity, Build Intelligence gate) passes on the final code: 190/190 registered cases executed, 92 fully measured (both ratchets met), 24/24 restore / state-integrity cases, no WRONG_RESULT, no failing test outside the registry. `tests/integration/test_perf01_identity_reactivation.py` pins that the bridge's skipped
  re-activation is indistinguishable from the forced one (metrics, fingerprint, main-skill identity, full `evaluate_item` result) on two heavy builds,
  and that a real loadout / item-set change is still applied and reversible.
* **Build Intelligence gate** (`scripts/r4_gate_measure.py`, 22 builds): PASS - every build analysed, restore leaves the fingerprint unchanged,
  rescore pure with no PoB call, staleness correct, cache check reproduces the analysis with 0 recalculations. Item Check through
  `evaluate_item` (no controller) on the same run: warm median 200 / 508 / 940 ms (ring / melee / totem), 4 PoB calls per warm check as in R4.
* **No stale state is ever shown.** Every transaction (`_begin_reload_transaction`) bumps the baseline generation and invalidates the result,
  evaluation, probe, upgrade-path and offense-coverage caches at once; a load result is applied only while its generation is still current. Tests:
  superseded in-flight load, superseded queued load (no bookkeeping left), failed load, same-build rejection restoring the last good bytes, an
  unreadable file mid-reload, a second save mid-reload, rapid consecutive Shift+C (only the newest resumes, older ones retired), held check resumed
  with the new generation and context identity, apply exception, value-profile change mid-load, loadout switch asked for mid-load.
* **PoB mutations stay serialized.** Loads, loadout/item-set switches, the prewarm and the offense-coverage audit all run as jobs on the
  single PoB lane (or inside the evaluation job). The UI thread no longer issues PoB calls on the Item Check path (a test makes any UI-thread
  engine call fail), and applies results only after the lane job completed and before the scheduler starts the next one.
* **Worker lifetime.** Preboot adoption, discard on folder change / non-adoption, crash recovery (build RELOADING with caches invalidated, held
  Item Check, boot failure terminal, retarget during boot) and shutdown with a load in flight are covered by tests.
* **Independent review.** All commits were reviewed by a separate reviewer with no access to the intent; its four definite findings and the
  medium-confidence risks were fixed (see the last commit) and are covered by the tests above. Three low-confidence points are listed under
  Limitations.


## Limitations

* **Source runs, not packaged performance.** Timings come from `python -m exilelens` style runs on Python 3.14 on a shared development machine
  (browser and game launcher running; absolute timings drift up to 3x between runs, which is why every table is interleaved and median-based).
  Import time (about 2 s) and the Windows `git`/WMI calls in the Diagnostics page are dev-only costs. The packaged build was smoke-tested
  separately (above) and its startup is **not** presented as a measured improvement.
* **Hotkey and clipboard capture** (SendInput + clipboard poll) need a live game window and are not exercised by the harness; the harness
  starts at `submit_clipboard_text`.
* **A running upgrade-path analysis** is cancelled through the controller-side analyzer only; the job already running on the worker uses the
  worker's own analyzer and finishes inside its probe budget (up to 20 probes), so a build switch can still wait for it. It only runs for
  near-miss / trade-off items. Making it yield also needs a decision about not caching a partial result (an existing behaviour of cancel).
* **Bridge skip.** The skipped re-activation also skips "repair by re-assertion" of PoB drift that does not set `buildFlag`; no such path was
  found (restores recalculate and verify), and `force` exists to restore the old behaviour for a caller that wants it. If the installed PoB's
  `GetLoadoutByName` does not expose all four set ids the skip never fires (the original path runs).
* **Offense-coverage audit errors** now surface as an evaluation error from the worker instead of "Could not prepare item analysis", and the
  first minion/ailment check's audit time counts against the Item Check user timeout / watchdog (it is the same work as before, moved).
* **Not done / follow-ups:** the dormant Price Check import stack (about 0.3 s of import time); the Diagnostics page refresh at startup (about
  0.2 s in a source run); skipping the tree-set recapture on a context-only change; making `Engine.start` itself cheaper (the ~4 s is PoB's Lua
  data load); a second preboot-style overlap for the build file read.

The Filters/Diagnostics navigation follow-up is documented in [PERF-02](PERF-02.md),
including the remaining first-open rendering cost.

