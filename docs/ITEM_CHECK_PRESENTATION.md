# Item Check presentation (P1.1 / P1.1b / P1.1c — Tooltip Presentation Polish)

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

---

## P1.1b — visual language, Jewel copy, More Info density

Real packaged-build screenshots of P1.1's output surfaced a second, distinct problem:
the *visual treatment* (a warm brown "premium" chrome the product owner rejected) and
three remaining information-hierarchy issues independent of P1.1's copy/wording work.
This section documents what changed. Nothing in P1.1b touches the evaluation engine,
scoring, thresholds, Jewel Intelligence discovery semantics, or the PoB bridge (the one
exception, the Jewel socket *discovery correctness* fix, is a separate defect — see
`POB2_ENGINE_CONTRACT.md`'s Jewel section — not a P1.1b presentation change).

### Visual hierarchy

The whole overlay/dashboard palette was retoned from a warm brown/tan family (e.g.
`#d8cbb6` text, `#141210` background, a `QColor(34, 29, 24, ...)` window gradient) to a
neutral graphite/off-white one, centralized in `ui/styles.py`'s token constants
(`OVERLAY_TEXT_*`, `DASHBOARD_*`, and the new `OVERLAY_WINDOW_GRADIENT_*`/
`OVERLAY_WINDOW_BORDER_RGBA` tuples). The three files that used to hardcode the same
brown `QColor` literals for the painted tooltip window background
(`ui/overlay.py`, `ui/pinned_item_overlay.py`, `ui/overlay_aux_companion.py`) now import
those tuples instead of repeating raw numbers — the actual centralization the product
owner asked for, not just a value swap. Color semantics, kept and reinforced:

- Gold (`#c9a227`, `DASHBOARD_ACCENT`) — the one restrained ExileLens accent. Used for
  the rarity label, the top accent stripe (already rarity-colored, unchanged), the pin
  affordance's border, and — new in P1.1b — the More Info drawer's divider/left border
  (`rgba(201, 162, 39, 35)`), since a divider is exactly the "subtle separator" role the
  product owner named for gold. Deliberately *not* used as the default button-text color
  (was gold pre-P1.1b via a wildcard `QPushButton` rule); every interactive control
  (Pin, More Info, close, retry) now uses neutral text plus its existing hover-brighten
  behavior, so gold stays rare rather than becoming the default accent for every clickable
  thing.
- Green (`#7dcf7d`) / red (`#d97b7b`) — gain / loss. Unchanged; these were already
  correct before P1.1b.
- Amber (`#e0a040`, with a couple of adjacent tiers like `#dba748`) — warning/uncertain/
  tradeoff. Unified: the pre-P1.1b palette had three or four different tan-gold shades
  (`#e8d3a4`, `#e0b35a`, `#d4bc6e`, ...) doing this job inconsistently; they now share one
  family.
- Neutral text — `OVERLAY_TEXT_PRIMARY`/`_SECONDARY`/`_MUTED` (off-white → mid-gray →
  dark-gray), replacing what used to be three different warm tan shades doing the same
  job.
- Rarity colors (`RARITY_COLOR`) — untouched; explicitly semantic and out of scope.

Chrome reduction: `baselineStrip` and `verdictBand` (both hidden in the compact surface
already — see the M1 audit above) had their linear gradients flattened to a single flat
`rgba` fill; `detailAnalysisDrawer`'s gradient background likewise flattened. No new
gradients, glow, or ornamental borders were introduced anywhere. No layout/widget
structure changed — this is a color-token pass, not a redesign.

### Compact impact selector: primary offense visibility

`compact_tooltip.select_impact_rows()`'s existing "at least one material loss survives
the row-count cap" rule had a gap: several large *defensive* losses (each individually
≥ `LARGE_DAMAGE_LOSS_PCT`, so each already lands in the higher-priority "large loss" rank
bucket) could fill the entire `MAX_IMPACT_ROWS` budget before a smaller-but-still-real
*offense* loss — ranked one bucket lower — was ever considered. A build losing 4.9% Spark
DPS alongside larger EHP/Max Hit/resistance losses could show every defensive number and
silently omit the damage change entirely. Fixed with a second, symmetric safety net:
`_is_material_primary_offense()` (MEASURED/MEASURED_ZERO delta kind only — this never
promotes an UNMEASURED/ESTIMATED/UNSUPPORTED damage number into visibility, respecting
the same truthfulness gate `rows_from_outcome_deltas()` already enforces — and ≥ 3%
magnitude, the same "major DPS" threshold the ranking already used elsewhere) now
guarantees a material, measured primary-offense row survives the row cap the same way a
material loss row does, without touching scoring, the verdict, or which axis the engine
considers "primary."

### Jewel socket copy: no raw node ids in player-facing text

Real Jewel diagnostics (post the discovery-correctness fix) showed raw tree-node
identifiers — `Jewel 11184`, `Jewel 17788`, ... — directly in player-facing text: the
compact "Best: {slot} — {name}" line, a per-socket `slot_verdict_lines()` listing, More
Info's verdict header, and the drawer's "COMPARE REPLACEMENT" ring-selector button
captions. A raw tree-node id is internal identity (Copy diagnostics still carries it,
unchanged), never player copy — PoB does not expose a real passive-tree name/location for
a socket. Fixed uniformly wherever a slot string reaches a label
(`items.slots.is_jewel_socket_pob_slot()` detects the pattern):

- **Compact `replacing_line()`**: `"Best: Jewel 11184 — Foe Joy, Sapphire"` →
  `"Best fit: Replacing Foe Joy, Sapphire · Checked 4 jewel sockets"`; an empty best
  socket reads `"Best fit: Empty jewel socket · Checked N jewel sockets"`. Non-jewel
  (equipment) slots are byte-for-byte unchanged (`"Best: Ring 2 — {name}"`).
- **Compact `slot_verdict_lines()`**: suppressed entirely for jewel candidates (returns
  `[]`) rather than relabeled — this is the "never dump the evaluated socket list" rule;
  `replacing_line()`'s single best-fit + count summary is the only jewel-socket copy the
  compact surface shows. Equipment slots keep their existing per-slot listing unchanged.
- **More Info `_verdict_header()`**: the same raw-slot suffix/bare-slot cases are
  suppressed for jewel sockets (e.g. `"Replacing: X · Jewel 11184"` → `"Replacing: X"`;
  a bare bindingless slot never renders at all for a jewel socket).
- **Drawer's ring selector** (`_render_ring_selector()`): still lets the player switch
  between the sockets that were actually checked (real, useful advanced functionality,
  kept), but labels each button `"Socket 1"`, `"Socket 2"`, ... (`items.slots.
  jewel_socket_display_label()`) instead of the raw node id.

**Truthfulness check performed on this work specifically** (per the product owner's
"Fulgent Stone" example — a textual `2% increased Cast Speed` modifier where PoB's
measured result is `0.0%` Cast/Attack Speed change): none of the four fixes above read or
reformat item modifier text at all — they only touch slot *identity* strings
(`"Jewel <nodeId>"` → an ordinal or a summary count) and continue to source every number
and name from the same `EvaluationOutcome`/`replacement_choices` data the rest of this
document's truthfulness boundary already governs. The measured-vs-raw-modifier trap does
not apply to this change by construction, not by omission.

### More Info: player-facing vs. advanced PoB information

`more_info.MORE_INFO_SECTION_ORDER` previously rendered `damage_reference` and
`native_components` — "Spark → Base", selected PoB stat-set, Full DPS configuration
status, individual native-component enumeration — second and third, immediately after
the verdict and *ahead of* `key_impact` (the actual build-impact numbers). Reordered to:
verdict header → key impact → offense → defense → resists → flexibility → why this
verdict → *(advanced)* score drivers → damage reference → native components →
unmodeled/conditional. The three sections now demoted to the tail
(`more_info.ADVANCED_SECTION_IDS`) also render with a visually quieter title style
(`detailSectionTitleAdvanced`: smaller, lower letter-spacing, muted color) via
`overlay_detail_drawer.py`'s `_render_sections()` — a one-line lookup against the
existing section id, no new data field, no architecture change. `unmodeled` (truthful
uncertainty/coverage caveats — the same philosophy as the compact surface's UNCERTAIN
quality note) deliberately stays in the normal-weight group: it is a caveat the player
should read, not PoB internals. No section content changed, nothing was deleted, `Copy
diagnostics` is untouched.

### Width / density

`styles.OVERLAY_DETAIL_WIDTH_BASE` (the More Info drawer's width): 380 → 350, with its
clamp range narrowed from 340–430 to 310–400. Screenshots with More Info open showed a
very wide two-column surface (compact ~408px + drawer ~380–430px + divider ≈ 790–820px
total) for content that is only ever short text lines and small tables. The compact
tooltip's own width (`OVERLAY_COMPACT_WIDTH_BASE = 408`) is unchanged — it was not the
problem, and per the product owner's explicit instruction this pass does not shrink text
or increase density to cram more in; it narrows the one dimension (drawer width) that was
oversized for what it actually renders.

### What P1.1b did not touch

Evaluation formulas, score calculation, verdict thresholds, guardrails, the truthfulness
gate, PoB calculation behavior, Jewel placement *semantics* (which sockets are legal —
see the separate discovery-correctness fix), slot-ranking semantics, cache/fingerprint
behavior, the version number, or the release pipeline. No new widget, window, or page was
added; no existing one was removed.

---

## P1.1c — More Info hierarchy: normal vs. Advanced

P1.1b fixed More Info's *section order* and gave three technical sections a quieter
title. Real packaged-build review found that was not enough: with ten sections all
rendered inline, More Info still read as a diagnostic dump — Verdict, Key Impact,
Offense, Defense, Resists & Requirements, Build Flexibility, Why This Verdict, Score
Drivers, Damage Reference, PoB Damage Components all competed for the same attention.
P1.1c does not touch the compact Item Check panel or Jewel discovery/evaluation at all
(both accepted as-is from the prior passes) — it is a More-Info-only pass.

### Two-level hierarchy

`items.more_info.ADVANCED_SECTION_IDS` now names four sections — `flexibility` (build
flexibility / resistance buffer detail), `score_drivers`, `damage_reference`, `native_components`
— as advanced/PoB-provenance detail (P1.1b had three of these; `flexibility` joined in
P1.1c once the normal `resists` section stopped needing its raw numbers inline — see
below). `ui.overlay_detail_drawer.DetailAnalysisDrawer._render_sections()` now splits on
this set instead of only re-styling titles: every **normal** section (`verdict_header`,
`key_impact`, `offense`, `defense`, `resists`, `why_verdict`, `unmodeled`) renders
immediately, in that order; every **advanced** section renders inside a single
`"▸ Advanced"` / `"▾ Advanced"` disclosure toggle, collapsed by default, that shows/hides
one `QWidget` container holding all of them. Nothing is deleted, nothing moved to
diagnostics-only — the exact same section payload from `build_more_info()` is used either
way, just routed to a different Qt layout target
(`_render_one_section(section, block, layout=..., advanced=...)`). `Copy diagnostics`
is unaffected — it reads `_diagnostics_result`, never the section widgets.

`unmodeled` deliberately stays in the normal group: it carries truthful
uncertainty/coverage caveats (the same philosophy as the compact surface's UNCERTAIN
quality note), not PoB internals, so it must not be hidden behind a click a player might
never make.

**Advanced state persistence**: `DetailAnalysisDrawer._advanced_expanded` resets to
`False` in `clear()` (called at the start of every `set_content()` — i.e. every new
Item Check result starts collapsed) but is *not* reset by `_clear_body()`, which
`select_choice()` uses when switching between Jewel/ring candidates within the same
result — so expanding Advanced and then comparing a different socket keeps it open,
rather than snapping shut on every click.

### Resists & Requirements: decision-relevant state over raw engine language

Previously every resistance rendered its cap threshold, uncapped total, and buffer as
three separate `"cap X → Y  ·  uncapped X → Y  ·  buffer X → Y  ·  CAPPED STAYS CAPPED"`
clauses per element, always, regardless of whether any of those numbers were decision
material. `items.more_info._resist_summary()` now derives one line per element from the
same `EvaluationOutcome.resistances[]` data (never re-derived/guessed):

- Both sides at the effective cap (`CAPPED_STAYS_CAPPED`, `OVER_CAP_REDUCED_BUT_STILL_CAPPED`)
  → `"capped → capped"` — the exact overflow amount is a flexibility question, not a
  "is this fine" one, and now lives only in the Advanced `flexibility` section.
- `CAP_REACHED` (crossed into cap) → `"{current} → capped"`.
- `CAP_LOST` (fell out of cap) → `"capped → {candidate}"`, marked a warning.
- Anything never at cap on either side (most often Chaos Resistance, and any
  `BELOW_CAP_*` state) → the real effective numbers, `"{current} → {candidate}"`, marked
  a warning when the outcome's own `severity` classification (`critical`/`high`, read
  unchanged from `resist_caps.py` — never re-derived) says so.

This produces exactly the worked example from the spec on real data shaped like it:
`Fire: capped → capped`, `Cold: capped → capped`, `Lightning: capped → capped`,
`⚠ Chaos: 15 → 0` — without hard-coding those numbers; the section builder only knows
the state machine, never the specific values. Requirement deltas (strength/dex/int) stay
in the same `resists` section, unchanged — the spec's "resistance/requirement
consequences" are both normal-tier.

### Jewel drawer

Not modified beyond inheriting the layout-parameterization refactor (`_render_ring_selector`
itself is untouched). Verified still correct: the best socket keeps its `★` marker and
selected/checked state; `select_choice()` only re-renders the drawer body
(`_clear_body()` + `_render_sections()`), never touches the compact panel, which
continues to read `replacing_line()`'s single best-fit summary (P1.1b, unchanged) for
the overall placement; ring captions still read `"Socket 1"`, `"Socket 2"`, ... (P1.1b's
`jewel_socket_display_label()`), never a raw node id.

### Visual density

`_add_section_title()` now inserts an extra 6px gap before each section title (on top of
the layout's existing 8px item spacing) whenever it is not the first item in its layout
target — roughly 14px between major sections, unchanged ~8px between lines inside one
section. No font size changed. No section headings were merged/removed — Offense and
Defense stay as separate tables (a genuinely different purpose from the curated Key
Impact headline), so no all-caps heading was cut merely for the sake of cutting one.
Drawer width is unchanged from P1.1b (350, clamp 310–400) — not widened.

### What P1.1c did not touch

The compact Item Check panel (`items/compact_tooltip.py`, `ui/overlay_presentation.py`'s
`ItemOverlayPanel`) — accepted as-is per instruction. Jewel socket discovery/evaluation
(`runtime/lua/bridge.lua`) — accepted as-is per instruction. Evaluation formulas, scoring,
verdict thresholds, guardrails, the truthfulness gate, slot-ranking semantics, PoB
calculation behavior, cache/fingerprint behavior, the version number, the release
pipeline.

---

## More Info drawer whitespace bug (post-P1.1c fix)

Packaged-build manual testing found a real layout defect introduced by P1.1c's own
inter-section spacing change: after viewing one More Info result and then a different
one in the same session (the drawer widget is reused, not recreated, across Item Checks
and pinned-overlay refreshes), the second result's content could render with a large
blank gap above it — the first visible section pushed down, sometimes off the top of the
visible area.

**Root cause**: `_add_section_title()`'s extra inter-section spacing used
`QLayout.addSpacing()`, which inserts a raw `QSpacerItem` with no handle to remove later.
`_clear_body()` — called by both `set_content()` (a new result) and `select_choice()`
(switching Jewel/ring candidates) — only ever removed and deleted the `QWidget`s it
explicitly tracks in `_section_widgets`; it never touched these spacer items, which have
no owning widget to track. Every spacer `addSpacing()` ever added therefore stayed in
`_line_layout` forever, and every subsequent render's real content was appended *after*
all the accumulating orphaned spacers from every previous render — confirmed by
reproduction: after 5 repeated dense→sparse switches, the layout accumulates spacer
items without bound and the first real widget's vertical position grows every cycle.

**Fix**: spacers are now small fixed-height `QWidget`s (`_add_gap()`) added through the
exact same tracked-widget path as every other section widget (label, table, toggle),
so `_clear_body()` cleans them up identically. No `QLayout.addSpacing()`/raw
`QSpacerItem` remains anywhere in the file. Verified: content always starts at the very
top of the drawer regardless of what was shown before it, and repeated cycling between
dense and sparse results no longer grows the layout's item count.
