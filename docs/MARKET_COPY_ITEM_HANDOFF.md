# Market Copy Item → Item Check (MKT-UX-01)

Branch: `feat/weapon-set-component-contexts`. No production code changed:
the workflow already operates end to end.

## Existing workflow discovered

There is no "Copy Item" button in ExileLens. "Copy Item" is the PoE2
game/market action, which writes full item text to the Windows clipboard with
no Ctrl+C keystroke. ExileLens ingests it passively:

`ClipboardWatcher` → `main._on_clipboard_event` → owned Shift+C route →
gameplay-suppression check → `try_market_capture_clipboard` (only when a
market-capture session is active) → `try_external_clipboard_item_check` →
`ExternalClipboardRouter.evaluate` → `submit_clipboard_text` → the normal
Item Check pipeline (recognition, build readiness, evaluation, coverage,
restore, tooltip presentation). No second evaluation engine exists, and none
was added.

Market listings themselves never carry clipboard text (candidate rows,
search plans, NEXT SEARCH hints are JSON/labels), so there is nothing to
"fix" on the market side: the handoff point is the OS clipboard event.

## Missing functionality or defects

None requiring production changes. Two observations, both by design:

- While a market-capture session is active, the session consumes the
  clipboard sequence, so the passive Item Check path sees it as a duplicate
  and stays silent; the item is instead evaluated through the session drain
  (`_drain_market_capture_queue`). Batch-capture mode therefore never pops
  competing Item Check tooltips.
- Header-bearing but incomplete listings are ACCEPTED by the router
  (recognition is header-based by necessity) and rejected downstream at PoB
  parse with a surfaced error, never silently and never as a verdict.

The actual gap was regression coverage: the entire handoff had zero tests.
Closed by `tests/test_market_copy_item_handoff.py` (10 cases, mocks only).

## Changes implemented

Tests only. No market, scoring, coverage, verdict, clipboard, or UI changes.

## Before/after user experience

Unchanged, by intent: market Copy Item with PoE foreground and a loaded
build still raises the standard Item Check tooltip; without a build it
reports "No build loaded"; non-items stay silent. Existing Copy Search Plan
/ Copy NEXT SEARCH / diagnostics-copy behavior is untouched.

## Error and duplicate-event handling

Verified by the new tests plus existing pipeline gates: same OS sequence
repeated → `IGNORED_DUPLICATE` (and `submit_clipboard_text` re-checks);
same text under a new sequence → evaluated again (identical text is not
duplication); owned hotkey / foreign Ctrl+C / background window / non-item →
silent ignore; unrecognized text returns its recognition for diagnostics
only. In-flight evaluations are guarded by request/generation identity and
the single-active scheduler (existing, untouched).

## Clipboard privacy

Locked by test: the router logs only sequence, length, and derived
base-type/slot labels; the full item text (and its longest mod line) never
appears in logs. `main._on_clipboard_event` logs sequence/length only
(CS-001). No credentials, tokens, or clipboard content enter diagnostics.

## Focused test results

- `tests/test_market_copy_item_handoff.py`: 10 passed.
- Narrow real-PoB smoke: `test_supported_offense_and_defense_comparisons_are_measured` (same `core04_offense_ring.txt` bytes the router accepts) passed — the handoff's downstream end evaluates normally.
- Full suite / corpus not rerun (no production change).

## Remaining limitations

- Controller/Qt-level handoff (no-build messaging, build-change generations,
  in-flight supersede) has no direct unit test; covered indirectly by
  readiness tests and real-PoB restore/reload gates.
- A market listing that is not valid clipboard item text cannot be evaluated
  without speculative reconstruction; correctly ignored instead.

## Item Check semantics confirmation

Untouched: no `src/` or `runtime/` changes. Scoring, coverage, verdict,
restoration, presentation, and contextual-diagnostic call counts are
byte-identical to HEAD `78132d6`.
