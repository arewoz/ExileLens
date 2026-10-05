# Parked Features

This repo is focused on **Item Check** (Ctrl+C evaluation, item overlay, Item Lab, upgrade path) and, since R1, **Build Analysis** (the Analyze Build page; see `docs/R1-BUILD-INTELLIGENCE-PRODUCTIZATION.md`). Other product areas remain in the codebase but are **parked**: disconnected from the default runtime and excluded from the default pytest suite.

## Parked modules

| Module | UI / runtime impact |
| --- | --- |
| `TREE_TOOLS` | Dashboard Tree Coach |
| `MARKET` | Dashboard Market hub, offline search/import |
| `MARKET_ASSISTANT` | In-game market capture overlay |
| `GEAR_OPTIMIZER` | Dashboard Gear Optimizer |
| `LIVE_TREE_OVERLAY` | Experimental in-game tree overlay |

**Active by default:** `ITEM_CHECK` and `BUILD_ANALYSIS` (`SUPPORTED_MODULES` in `app/modules/registry.py`). Build Analysis runs only on the explicit Analyze Build action; Item Check never starts it.

Core infrastructure (PoB bridge, baseline lifecycle, tray, settings shell, scheduler) stays on so item evaluation can run against a loaded build.

## Runtime behavior

- Default settings: `module_preset = "ITEM_CHECK_ONLY"`.
- `PARKED_MODULES` in `app/modules/registry.py` is stripped by `resolve_enabled_modules()` unless unparked.
- Dashboard/tray nav hides parked sections automatically via MOD-01 module gates.
- Overview stays visible in minimal form (build health + active features). Build Analysis has its own "Analyze Build" page and tray entry.
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

Item Check + Item Lab (ITEM-PRO) and Build Analysis are the current delivery focus. Tree, Market and Gear Optimizer remain for later re-integration without deleting code paths.

## Legacy Price Check: DORMANT / LEGACY / NOT A 1.0 ENTRY POINT

The interactive Price Check panel, its Refine dialog and the legacy `submit_price_check` / `refine_last_price` chain are not reachable from the shipped app: Shift+C is Item Check
(`submit_clipboard_text`), and nothing starts a legacy price check. They are kept, unwired, until a later release decides their fate. The legacy Refine hotkey (Ctrl+Shift+R, a
`RegisterHotKey` global grab) is **not registered** (R5 closeout): registering it for a flow that cannot run only stole the chord from other applications. The current market product
surface is `result["market_evidence"]` (`docs/MARKET_EVIDENCE_CONTRACT.md`): Item Check compact line, More Info "Market", Settings and Diagnostics. The live trade2 provider is
POLICY-BLOCKED, so none of it is visible in a shipped build. Do not add entry points to the legacy panel.
