# Item Check presentation (P1.1 — Tooltip Presentation Polish)

How the Shift+C Item Check tooltip decides what to show, in what order, and what moves
to More Info. This is a presentation contract: it describes copy and layout policy, not
the evaluation engine. See `ITEM_EVALUATION_CONTRACT.md` for how `EvaluationOutcome` is
computed; nothing in this document changes that contract.

## Where this lives in code

- `items/compact_tooltip.py` — compresses the full presentation model into the compact
  surface: verdict headline, impact rows, up to 3 "why" reasons, up to 2 notes. Owns
  `apply_compact_tooltip()`, the single entry point the passive/pinned overlay calls.
- `items/presentation.py`, `items/presentation_copy.py` — build the full (uncompressed)
  presentation model from an `EvaluationOutcome` / legacy `recommendation` payload, and
  the copy/wording policy (verdict labels, subtitles, dedupe).
- `items/more_info.py` — the structured "More Info" payload (`build_more_info`), read
  directly from `EvaluationOutcome` and the compact ranker's impact rows. This is what
  the drawer actually renders (see `bind_detail_content` in `ui/overlay_presentation.py`:
  `more_info` wins over the older `companion` payload whenever it has sections, which is
  effectively always).
- `items/companion.py` — an older, wider "Detailed Analysis" payload. Still built (so a
  future surface can use it) but not rendered today: `more_info` always has content, so
  `companion` never reaches the drawer in the current UI. Left in place; flagged below as
  a documentation/consistency loose end, not touched in P1.1.
- `ui/overlay_presentation.py` (`ItemOverlayPanel`) — the actual Shift+C tooltip widget.
  `render_presentation()` reads `model["compact_surface"]` and switches rendering: the
  score/value band and the wide baseline strip are hidden, the verdict headline moves
  directly under the item identity, and the drawer ("More Info ›") carries everything
  else.
- `ui/overlay_detail_drawer.py` (`DetailAnalysisDrawer`) — renders whichever of
  `more_info` / `companion` is present when the user opens More Info.

## Audit: what P1.1 found

The compact-surface compression system already existed at the start of this milestone
(present since the initial public commit, tagged `ITEM-UX-COMPRESS` in code comments) —
this was **not** built from scratch in P1.1. Before any change, the default Shift+C
tooltip already:

- hid the numeric score/value band (`model["value"] = None` in compact mode) and the
  0-100 rating never renders outside More Info;
- put the one verdict headline directly under the item name, instead of a separate
  "verdict band" lower in the tooltip;
- capped impact rows to 3–5 (`MIN_IMPACT_ROWS` / `MAX_IMPACT_ROWS`), "why" reasons to 3
  (`MAX_REASONS`), and notes to 2 (`MAX_NOTES`);
- moved axis breakdowns, trade-off lines, hard problems, important-mod call-outs,
  why-not-upgrade detail, build-fix suggestions, and badges out of the compact view
  (`MOVED_TO_COMPANION`), all still reachable in More Info.

So the audit's job was to find what was **still wrong**, not to redesign the hierarchy.
Three concrete gaps were found and fixed; the rest of the target hierarchy was already
in place and is documented below as "verified, unchanged."

### Gap 1 — "Build Value" leaking into the most common verdict explanation

For an ordinary comparison (`FULL` evaluation quality, no guardrail ceiling, no
trade-off pattern — i.e. most results), `EvaluationOutcome.verdict_reason` was built as:

> `"Net build value {delta:+.1f} against the current item."`

This is the fallback branch in `decide_verdict()` (`items/evaluation_outcome.py`), and it
reaches the player: `more_info.py::_why_verdict()` puts `outcome.verdict_reason` into the
More Info "WHY THIS VERDICT" section verbatim whenever no guardrail/trade-off line
already explains the verdict — which is the case for most upgrades and downgrades. This
is exactly the "BV terminology is unclear/unwanted" feedback the milestone brief names,
and it was reachable, not hypothetical.

Also checked and confirmed **not** reachable from Item Check today (left unchanged, not
because they don't say "Build Value" — they do — but because nothing in the Shift+C
tooltip or its More Info drawer calls the code path that would show them):
`items/upgrade_path.py` repair-step text, `items/blocker_solver.py` repair text, and
`items/companion.py::_upgrade_path_section` (all feed `model["upgrade_path"]` /
`build_companion_analysis`, and `apply_compact_tooltip` clears `upgrade_path` before More
Info is built; `companion` itself is never rendered — see above). `presentation.py`'s
`recommendation_tag` ("Build Value +X") is unconditionally cleared by
`apply_compact_tooltip` for both compact surfaces (`PASSIVE_COMPACT`, `PINNED_EXTENDED`).
The Price Check panel's "VALUE / COST … Build Value / currency" line
(`overlay_presentation.py:858`) belongs to the separate Price Check feature, which never
populates `model["price"]` for Item Check results.

**Fix:** reworded the two reachable strings, keeping the same underlying numbers:

- `items/evaluation_outcome.py`: `"Net build value {delta:+.1f} against the current item."`
  → `"Net score {delta:+.1f} against the current item."`
- `items/presentation_copy.py` (`verdict_subtitle`, `NO_CHANGE` fallback — confirmed
  currently unreachable via the compact surface, fixed anyway for audit completeness
  since it is textually identical terminology in the same module family):
  `"No meaningful change to build value or guardrails."` →
  `"No meaningful change to score or guardrails."`

No internal field, key, or scoring number was renamed or removed — `score_delta`,
`build_value_delta`, `build_value_rating` and similar internal identifiers are untouched.
This is presentation-copy only.

**Out of scope, deferred:** the Gear Optimizer page, Market Assistant overlay, Market
Capture page, Analysis Window, and Tree heatmap/window all still say "Build Value" in
player-visible text. These are separate product surfaces from Item Check (the
Shift+C hover tooltip this milestone is scoped to), share none of `compact_tooltip.py`'s
code path, and touching them risks scope creep into unrelated features per the milestone
boundary ("Do not start Build Intelligence", "P1.1 must not change ... slot ranking").
Flagged as a follow-up candidate for a future, explicitly-scoped milestone.

### Gap 2 — UNCERTAIN/PARTIAL gave a headline but no reason

`verdict_headline()` already rendered `"UNCERTAIN · Partial comparison"` — so an
uncertain result was already visually distinct from a confident sidegrade, satisfying
"UNCERTAIN must not look like a weak upgrade/downgrade." But the compact surface stopped
there: the *why* (which the engine already knows — `EvaluationOutcome.evaluation_quality_reasons`,
e.g. "the main skill's damage change could not be measured for this build") only reached
the player if they opened More Info. The headline alone reads as an unexplained shrug.

**Fix:** added `compact_tooltip._quality_note()`, called first inside
`_semantic_notes()` (so it survives the `MAX_NOTES` budget ahead of ordinary warnings).
When `evaluation_quality != "FULL"`, it takes the first
`evaluation_quality_reasons[].detail` string — the same truthful, evidence-backed text
already used in More Info's quality line — capitalizes it, and prefixes it with `◐`
(distinct from `⚠`, which stays reserved for concrete warnings like a broken resistance
cap). Nothing is inferred or invented; a `FULL`-quality result produces no note at all.

### Gap 3 — Jewel evaluation delay had no acknowledgment

M1.3 (Jewel Intelligence) can make an evaluation take noticeably longer for builds with
many Jewel sockets. Audited the existing loading states:

- `show_analyzing()` / `show_warming()` — the *first* paint, shown before any Path of
  Building call has happened. At this point nothing about socket count (or even that the
  hovered item is a Jewel) is known without adding a new engine call, which the milestone
  brief explicitly forbids. Left unchanged — a generic "Analyzing…" / "Warming PoB…" is
  the correct, truthful state here.
- `show_timeout()` — fires after `ITEM_CHECK_USER_TIMEOUT_MS` (4 seconds;
  `app/item_check_lifecycle.py`) if no result has arrived yet. **This already exists and
  already replaces the spinner with an explanation** ("STILL ANALYZING" / "Path of
  Building is taking longer than usual.") — the UI does not actually freeze or go silent
  during a slow Jewel evaluation. This is the audit finding: there was no frozen/silent
  state to fix, contrary to what the milestone brief anticipated might be found.

**Fix:** the one truthful, zero-new-engine-call improvement available — reworded the
timeout copy to name the actual, known cause class: `"Path of Building is taking longer
than usual. Builds with many Jewel sockets can take longer to evaluate."` This does not
claim a specific socket count (not cheaply known at that point) and does not add any new
timer, signal, or engine call.

**Deferred, not implemented in P1.1:** a live `"Evaluating 9 jewel sockets…"` message
(the brief's preferred concept) needs `PobParseResult.allocated_jewel_socket_count`,
which is only known after `parse_item_with_pob()` — a *separate, already-existing* engine
call from the per-socket comparison work, but still strictly later than the very first
paint (`_paint_analyzing` in `app/controller.py`, which fires before any Path of Building
interaction at all). Threading that count from the controller's async scheduler through
to a second, mid-flight loading state is a real, bounded feature — new signal payload,
a new overlay state between "Analyzing…" and the result — not a one-line copy change, and
touches the async controller (`app/controller.py`, ~5,000 lines) the milestone brief
explicitly says not to redesign. Recommended as a small, separately-scoped follow-up
(see "Remaining gaps" in the milestone report), not attempted here.

## Verified unchanged (already met the target hierarchy)

- **Item identity**: name (word-wrapped, handles long names), rarity color, base type —
  compact, no duplicate giant tooltip.
- **Verdict is the hero**: `_score_headline` (despite the internal name, this is the
  verdict headline, not a score) sits directly under identity/base, colored by verdict
  class; the old lower "verdict band" (score + verdict + explanation) is hidden entirely
  in compact mode (`_set_result_chrome_visible` / `verdict_band.setVisible(not
  compact_surface)`).
- **Primary impact**: `impact_rows`, ranked by `_decision_rank` (cannot-equip and
  requirement failures first, then resistance cap breaks, then large losses, then
  primary offense/EHP/speed/movement/resource/attribute, in that order), 3–5 rows,
  reading-order sorted after selection. Percentages render at one decimal
  (`_delta_text_from_outcome`), never raw float precision.
- **"Why" reasons**: sourced from `current_edge` / `why_not_upgrade` / `why_reasons`,
  which are themselves built upstream from `ItemImpact` / metric deltas by
  `decision.py`/`ranking.py` — not invented by the compact ranker. Capped at 3
  (`MAX_REASONS`).
- **Trade-off presentation**: `select_impact_rows()` has a hard rule — if any candidate
  row is a material loss, at least one loss row survives selection even when gain rows
  would otherwise fill the row budget (`ranked_losses` fallback in
  `select_impact_rows`). A SIDEGRADE/TRADEOFF result shows both directions as separate
  rows; nothing is collapsed into one scalar.
- **More Info**: already structured (`more_info.py::MORE_INFO_SECTION_ORDER`) —
  verdict header (label, `Score N / 100`, quality line, replacement target), damage
  reference, native-component partial-comparison detail, key impact, score drivers,
  offense/defense tables, resists & requirements, build flexibility, "why this verdict,"
  conditional/unmodeled. Already omits empty sections. `"Score N / 100"` was judged
  already human-readable and secondary (More Info only) — not renamed further.
- **Sizing**: row/reason/note caps above already bound compact-surface growth; height is
  additionally capped relative to the anchor monitor's work area
  (`ui/overlay_geometry.py::max_overlay_height_logical`). The one new line
  (`_quality_note`) is folded into the existing `MAX_NOTES = 2` budget, not additive to
  it, so it cannot grow the tooltip beyond what warnings already could.
- **Accessibility**: gain/loss/critical rows already carry a text marker (`▲` / `▼` /
  `!` / `~` from `impact_marker()`) in addition to color — color is never the only
  signal.

## The truthfulness boundary for "Why" (binding for any future change here)

`compact_tooltip.py` reasons and notes are read, never derived. The module's own
docstring states the rule this milestone preserved: *"Nothing is computed here. The
verdict and score are read from the recommendation's `EvaluationOutcome`; no second
verdict is derived from the score or product verdict."* Concretely:

- "Why" lines (`primary_reasons`) come from `current_edge` / `why_not_upgrade` /
  `why_reasons`, which are **build-level effect summaries** (e.g. "+11% Spell Damage",
  "further below Fire Resistance cap") produced upstream from measured metric deltas —
  never a claim that one specific item modifier caused a specific build-level change.
  The data model does not support that attribution today, and P1.1 does not pretend it
  does.
- The new `_quality_note()` is the same rule applied to uncertainty: it surfaces the
  existing `evaluation_quality_reasons[].detail` text verbatim (capitalized), never a
  paraphrase or inference layered on top.
- Internal codes (`OFFENSE_UNAVAILABLE`, guardrail codes, exception names) never reach
  the player; only the paired human-readable `detail`/`reason` string does, in both the
  compact note and More Info.

## What moved to More Info (unchanged inventory, confirmed by this audit)

`items/compact_tooltip.py::MOVED_TO_COMPANION`: axis rows, trade-off lines, hard
problems, important mods, why-not-upgrade detail, build fixes, compact notes,
multi-profile row, badges. Plus the score/value block and the full baseline/compared-with
strip. All still present in `more_info.py`'s structured payload or via `companion.py`
(currently unrendered — see the Companion note above).

## Terminology changes in this milestone

| Before | After | Where |
|---|---|---|
| "Net build value +X.X against the current item." | "Net score +X.X against the current item." | `EvaluationOutcome.verdict_reason` (default branch) — reaches More Info "WHY THIS VERDICT" |
| "No meaningful change to build value or guardrails." | "No meaningful change to score or guardrails." | `presentation_copy.verdict_subtitle` NO_CHANGE fallback (currently unreachable from Item Check; fixed for consistency) |
| "Path of Building is taking longer than usual." | "Path of Building is taking longer than usual. Builds with many Jewel sockets can take longer to evaluate." | `ItemOverlayPanel.show_timeout()` |
| *(none)* | `◐ {evaluation_quality_reasons[0].detail}` | New: first line of `critical_notes` whenever `evaluation_quality != FULL` |

No verdict label, threshold, score band, or guardrail changed. `VERDICT_LABELS`,
`classify_score_verdict()`, `SCORE_SCALE`, and all guardrail ceilings are untouched.

## Remaining gaps (not fixed in P1.1, by design)

1. **Live jewel-socket-count loading state** — see Gap 3 above. Needs a small, scoped
   controller-side change (thread `allocated_jewel_socket_count` from
   `parse_item_with_pob()` through the existing analyzing-repaint signal path) that was
   judged too close to "redesigning Jewel engine/async behaviour" for this milestone's
   risk budget. Recommended as a separate, small follow-up milestone.
2. **"Build Value" wording outside Item Check** — Gear Optimizer, Market Assistant,
   Market Capture, Analysis Window, Tree heatmap/window. Deliberately out of scope (see
   Gap 1).
3. **`companion.py` / `items/companion.py`'s `_upgrade_path_section`, `_score_section`**
   still contain "Build Value"-flavored/legacy phrasing and are effectively dead code
   today (superseded by `more_info.py`, per the audit above). Left alone rather than
   edited-but-unreachable code, to avoid touching a surface with no current renderer and
   no test coverage protecting it. Worth a cleanup or removal pass in a future milestone
   once it's confirmed no surface still depends on it.
