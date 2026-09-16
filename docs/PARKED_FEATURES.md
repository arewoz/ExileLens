# Parked Features

This repo is temporarily focused on **Item Check** (Ctrl+C evaluation, item overlay, Item Lab, upgrade path). Other product areas remain in the codebase but are **parked**: disconnected from the default runtime and excluded from the default pytest suite.

## Parked modules

| Module | UI / runtime impact |
| --- | --- |
| `BUILD_ANALYSIS` | Overview “Analyze Build” and upgrade opportunities |
| `TREE_TOOLS` | Dashboard Tree Coach |
| `MARKET` | Dashboard Market hub, offline search/import |
| `MARKET_ASSISTANT` | In-game market capture overlay |
| `GEAR_OPTIMIZER` | Dashboard Gear Optimizer |
| `LIVE_TREE_OVERLAY` | Experimental in-game tree overlay |

**Active by default:** `ITEM_CHECK` only (`ITEM_CHECK_ONLY` preset).

Core infrastructure (PoB bridge, baseline lifecycle, tray, settings shell, scheduler) stays on so item evaluation can run against a loaded build.

## Runtime behavior

- Default settings: `module_preset = "ITEM_CHECK_ONLY"`.
- `PARKED_MODULES` in `app/modules/registry.py` is stripped by `resolve_enabled_modules()` unless unparked.
- Dashboard/tray nav hides parked sections automatically via MOD-01 module gates.
- Overview stays visible in minimal form (build health + active features); build-analysis cards are hidden.
- To re-enable parked modules locally (development only): set environment variable `POE2VALUE_UNPARK_MODULES=1` before launch, then use Settings → Features (Full/Custom).

## Tests

Default suite (from `pyproject.toml`):

```bash
pytest
# equivalent to:
pytest -m itemcheck
```

Parked feature tests are auto-marked `parked` in `tests/conftest.py` by filename patterns (`*phase5a*`, `*phase5b*`, `*phase5c*`, `*market_assist*`, `*gear*`, `*tree*`, `*live_api*`).

Run parked tests explicitly:

```bash
pytest -m parked
```

Run everything:

```bash
pytest -m ""
```

## Why parked

Item Check + Item Lab (ITEM-PRO) is the current delivery focus. Tree, Market, Gear Optimizer, and Build Analysis remain for later re-integration without deleting code paths.
