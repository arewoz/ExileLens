# ExileLens structured error codes (M4.5)

ExileLens uses stable `EL-*` codes for **application failures** (something went wrong) and
separate **evaluation limitation** identifiers for expected `UNCERTAIN` / `UNSUPPORTED` Item Check
outcomes (limitations of coverage, not bugs).

## Application error format

`EL-<CATEGORY>-<NNN>`

| Prefix | Subsystem |
|--------|-----------|
| EL-APP | Application / startup |
| EL-POB | Path of Building integration |
| EL-BLD | Build loading |
| EL-CHK | Item Check processing |
| EL-WRK | Calculation worker |
| EL-KEY | Hotkey / clipboard |
| EL-UI | Overlay / desktop UI |
| EL-UPD | Updates |
| EL-DIAG | Diagnostics export |

Authoritative definitions live in `src/exilelens/error_catalog/registry.py`.

Each entry includes severity, user-facing title and explanation, recommended recovery action,
retryability, and an allowlisted diagnostic metadata schema.

### Application codes added by R2

| Code | Meaning | Notes |
|------|---------|-------|
| EL-APP-100 | Unexpected session end | The previous session did not end cleanly (power loss, forced shutdown, Task Manager or a crash). Informational; only ever reported, as `exception_type = UnexpectedSessionEnd`, if the user turned on error reports. It is *not* a crash detector. |

### Update codes

| Code | Meaning | Typical cause | User action |
|------|---------|---------------|-------------|
| EL-UPD-001 | Newest release could not be verified | Missing or invalid signed manifest, or a manifest not bound to its release (tag, version, artifact) | Check again later; never install from untrusted sources |
| EL-UPD-002 | Download failed verification | Size or SHA-256 mismatch against the signed manifest | Cancel and check again |
| EL-UPD-003 | Update check failed | GitHub unreachable | Check the network and retry |
| EL-UPD-004 | Update not installed; previous version still in place | External updater: prepare failure, process timeout, swap failure rolled back, or interrupted install recovered | Retry Restart & Update; use GitHub Releases if it repeats |
| EL-UPD-005 | Update failed and previous version not fully restored | Swap and rollback both failed (recovery material is kept) | Extract the latest release ZIP from GitHub Releases over the install folder |

EL-UPD-004/005 come from the external updater's result file, which is consumed
once on the next launch (see `docs/UPDATE_RELEASE_SIGNING.md`).

## Evaluation limitations

Identifiers such as `OFFENSE_UNSUPPORTED` or `PRIMARY_METRIC_LOW_CONFIDENCE` describe why a
verdict is `UNCERTAIN` or `UNSUPPORTED`. They are defined in
`src/exilelens/error_catalog/evaluation_limitations.py` and are **not** application fault codes.

## Registering a new application error

1. Confirm the failure is detectable in production code today (no hypothetical codes).
2. Add a `StructuredErrorDefinition` to `registry.py` with a unique `EL-*` code.
3. Map legacy worker `EngineError.code` values in `_ENGINE_CODE_TO_EL` when applicable.
4. Record the error at the existing failure boundary via `record_engine_error`,
   `record_generic_failure`, or `record_exception` in `error_catalog/integration.py`.
5. Add a focused test in `public_tests/test_m4_5_structured_error_codes.py`.
6. Extend this document with code, meaning, typical causes, user action, and subsystem.

## Diagnostics

The last structured error and evaluation limitation are stored in `ErrorContextStore` on the
controller, included in the extended diagnostic summary under `error_codes.structured`, diagnostic
events (`error` / `evaluation_limitation` categories), and support bundles (via the summary).

Sensitive data (clipboard, credentials, full builds) must never appear in structured context.
