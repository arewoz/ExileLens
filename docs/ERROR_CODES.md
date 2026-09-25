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
