# PoB Import and Load Reliability (POB-REL-01)

Branch: `feat/weapon-set-component-contexts`. No production code changed.

## Verdict

No reproducible production defect found. All eight critical scenarios behave
as designed; the new `tests/test_pob_import_load_reliability.py` (14 tests)
locks the verified Engine-boundary contracts in place. Historical fixes in
this area (stable-read validation, revision-gated reuse, restore-failure
invalidation, loadout-API compat in `e5d14bd`) remain effective.

## Scenarios investigated (with evidence)

- Valid build loads: `Engine.load_build` records source, ref, revision token,
  `source_generation`/`reload_count`, `last_load_reloaded` (new test +
  real-PoB check: reuse returns `reloaded=False` with identical fingerprint
  and no new generation; different build reloads; return re-parses).
- Invalid/corrupted input (missing, empty, whitespace, non-XML, wrong root):
  `read_build_source` raises `BuildNotFound`/`BuildParseFailed` before the
  worker is contacted (stub records zero calls) and no loaded state exists.
- Missing/incompatible PoB folder: `validate_pob_path` raises typed
  `POB_PATH_INVALID` (generic vs looks-like-PoB message); revision mismatch
  raises `UNSUPPORTED_POB_REVISION` only when a git HEAD is observable.
  Existing `public_tests` (16 tests) pass.
- Worker initialization failure: `Engine.start` failure propagates and leaves
  `_session is None` (no half-open session).
- Import failure during an active session: Python-side validation failure
  never touches the worker; worker-side parse failure clears
  `loaded_source/ref/revision` (bridge unloads globally:
  `bridge.lua` failed-parse branch sets `loaded=false, healthy=false`).
  Controller additionally keeps the last-good build for same-path reloads
  (`_keep_last_good_build`) and replays last-good bytes after engine-level
  rejection (`_restore_last_good_build`); otherwise `_fail_baseline` marks
  `FAILED` -- stale state is never presented as newly loaded.
- Loading another build after import: new identity, generation +1, both
  per-build component caches cleared.
- Retry after failed import: next load re-parses (`reloaded=True`) with the
  next generation (bridge retry path sits before the health guards; the
  in-process `WorkerSession.load_build` also resets `healthy` first).
- Repeated import of the same bytes: revision-gated reuse, no new
  generation, caches preserved.
- Error reporting: `_fail_baseline` publishes `FAILED` baseline/active
  status plus cache refresh error; `derive_readiness` maps to
  `BUILD_ERROR`/`RUNTIME_ERROR` (missing PoB wins); global diagnostics and
  health header use an allowlist (versions, states, reasons -- never paths,
  stderr, exceptions, or credentials).

## Test-harness corrections during development (not production)

- Retry test initially asserted reuse (`reloaded=False`) after a failure;
  the bridge unloads globally on failed parse, so re-parse is correct --
  stub fixed to mirror `bridge.lua`.
- Worker-start test used the in-process default; switched to
  `use_subprocess=True` so the patched `SubprocessWorkerClient.start` path
  is the one exercised.

## Remaining risks / limitations (no change)

- Controller keep-last-good/restore paths need Qt and have no direct unit
  test; covered indirectly via readiness tests and real-PoB restore/reload
  gates.
- `UnsupportedPobRevision` only fires when `git rev-parse` succeeds in the
  PoB folder; installed (non-git) layouts skip the check by design.
- Mid-save races rely on the bounded stable-read retry plus revision
  freshness; a save landing exactly between validation and snapshot is still
  detected on the next check via `freshness_token`.
- `public_tests/` has no `conftest.py` pinning `sys.path`; invoking pytest
  on it without the repo `src` first on the path can import a sibling
  checkout (observed locally, environment-only, out of scope).
- No PoE2 account sync / OAuth exists or was added; no credentials, tokens,
  or clipboard content enter diagnostics.

## Focused test results

- `tests/test_pob_import_load_reliability.py`: 14 passed.
- `tests/test_onboarding_readiness.py` + path/version public tests: 26 passed.
- One narrow real-PoB load/reuse/reload check: passed
  (reuse `reloaded=False`, same fingerprint, generations 1→2→3).
- Full unit suite / public corpus not rerun (no production change).

## Item Check / proof-composition confirmation

Untouched: no `src/` or `runtime/` changes in this task. Ordinary Item
Check, contextual proof/composition, and evaluation logic are byte-identical
to HEAD `84d3c00`.
