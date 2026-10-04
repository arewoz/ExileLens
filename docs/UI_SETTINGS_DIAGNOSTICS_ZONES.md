# Settings and Diagnostics: zones and structure

Implementation notes for the dashboard's Settings and Diagnostics pages (Status Rail redesign). The approved design is
the published canvas "ExileLens Redesign", spec "9 · Settings and Diagnostics regroup"; this file records what the code
does so the two stay in step.

## Four treatments, chosen by what a block is for

| Zone | Object name | Used for | Surface and border |
|---|---|---|---|
| Neutral | none | Hotkey, Updates (manual row), Item evaluation, Overlay, Privacy | none: flat rows, hairlines `HAIRLINE` |
| Setup / health | `setupCard` | **Path of Building** (Settings), **Application health** (Diagnostics). Max one per page | `SURFACE_1`, 1 px `CARD_LINE`, radius 6, inner rules `CARD_RULE` |
| Supporter | `supporterZone` | Seamless updates and every Patreon control. Max one per page | `SUPPORT_SURFACE` `#27232a` (raised neutral + ~5% plum), 1 px neutral `CARD_LINE`, rules `CARD_RULE`. **Never red**: a red/burgundy surface read as a warning or the destructive style; this is a barely warm raised surface, and the exact Patreon mark stays the only red |
| Help | `helpZone` | **Report a problem** only | `HELP_TINT` (~5.5%), 1 px `HELP_LINE` (~24%), rules `HELP_RULE` |

All tokens are in `ui/theme.py`; the rules are in `ui/redesign_style.py` and are scoped to the zone object names, so the
colours cannot leak into the rail, the buttons or the destructive style (tested). A page uses at most two marked zones.

* **Tint is identity, not state.** Borders and fills never change with status. Status is a word plus a dot or glyph
  (the header word of a card, the state word of the supporter zone) and, for a card, the one row that has the problem
  (`problem` property: a faint lift, and that row owns the page's single primary button).
* **Hue map.** Champagne = primary / selected. Patreon red = the shipped Patreon mark only, never a surface (it keeps its own
  `#ff424d`). Honey `#e6b84f` = help only: yellower than `WARN`, more saturated than `ACCENT`. Green / orange / salmon =
  status words only.
* **Buttons inside zones stay neutral** (secondary / tertiary).
* Contrast on the tints is asserted in `tests/test_ui_settings_diagnostics_regroup.py` (informational text at least
  4.5:1; the mark and the lifebuoy at least 3:1).

## Settings

Top to bottom: **Path of Building** card, **Hotkey**, **Updates**, **Item evaluation**, **Overlay**, **Privacy**, page
foot (**Reset configuration** and a pointer to Diagnostics).

* **Path of Building card** (`SetupCard` + `CardRow`). Header status from the same health model as the rail and
  Diagnostics: *Ready*, *Setup needed*, *Not connected*, *Needs attention*. Installation: state, the folder path,
  **Detect**, **Change folder**, and **Reconnect** while the integration is down. Build: name and age (both from the one
  health value), the file path, **Reload**, **Change build** (**Choose build** when none is selected). Paths are
  read-only, selectable, middle-elided with the full value in the tooltip; the context menu and Ctrl+C copy the *full*
  path. There is no second build status: a detail line shows only when the health model, a reload warning or the file
  check reports a problem. Only one button on the page is primary: Reconnect, Change folder (PoB not found), Choose
  build / Change build (build missing or failed) or Reload (build stale), in that order of precedence.
* **Updates.** The free manual row (`UpdatesPanel`) is never tinted. Directly beneath it, `PatreonPanel` is the
  **supporter zone**: header (the Patreon mark once, "Seamless updates", state word), one description, the two
  supporter switches, and a footer with one sentence and the actions for the state. The old "Support ExileLens" section
  is merged into it; "Manual updates and all core features stay free." sits under the zone, outside it. Unlinked or
  ineligible switches are disabled and **locked** (dashed track, no fill, tooltip "Needs an active Patreon link."); the
  reason is said once, in the footer. *Link Patreon* links; *Support on Patreon* opens the Patreon page.
* **Removed: Advanced › Troubleshooting & diagnostics.** Every control was a duplicate, dead or misplaced:
  folder field + Browse / Auto-detect / Apply → the card's Change folder / Detect / Reconnect; build field + Browse /
  Load → Change build; Reload build → the card's Reload; read-only Live market → the hint under Market league
  ("Market prices off · …" by default, "Market prices unavailable · …" if enabled while the provider is not authorized; R5-A); Dedup window → removed (below).
* **Market prices (R5-C).** The "Market prices" switch and the "Market league" row are created only when the provider can serve prices (`market_capability().provider_available`);
  in a shipped build they are hidden. Diagnostics' Market row reads Off / Provider unavailable / Ready / Looking up… / Rate limited / Unavailable, always neutral.
* **Dedup window (removed).** `AppSettings.dedup_window_seconds` was written by the UI but read by no runtime code
  (checked by a test over `src/`). The field and its UI are deleted. Existing `settings.json` files that still contain
  the key load normally (`from_dict` picks known keys only) and drop it on the next save. The fixed clipboard-event
  dedup in the capture path never consulted settings and is unchanged.

## Rail "Support ExileLens"

Internal navigation, never an external open: `DashboardWindow.show_supporter_area()` navigates to Settings,
`SettingsPage.focus_supporter()` scrolls the zone into view and puts keyboard focus on its first action (Link Patreon,
Reconnect, Support on Patreon, ...). The tray's "Support on Patreon ↗" still opens the browser directly. Opening Patreon
or starting a link happens only from the buttons inside the zone.

## Diagnostics

Top to bottom: **Application health** card (aggregate header: *All good* / *N need attention*; the recovery hint and
structured error summary in the card footer, only when present), **Report a problem** (honey help zone), **Advanced
diagnostics** (collapsed, with a one-line preview).

* **Report a problem:** short explanation, optional problem description, **Copy diagnostics**, **Export support
  package…**, **Open a GitHub issue** (right-aligned: the one control that leaves the app), and the **Support ID** with
  **Copy** (moved here from Advanced). No primary button: the fix is the health card's.
* **Advanced diagnostics:** tools row (**Open logs folder**, **Enable verbose diagnostics for 15 min**, **Clear
  diagnostic history**), then one viewer with an *Event history | Technical report* switch and **Copy** for what is
  shown. Event history is one readable line per event (time, category, name, every detail as `key=value`); the technical
  report is the unchanged allowlisted report.

## Narrow windows and large text

Rows stack deliberately instead of squeezing: `CardRow` and `HealthGridRow` drop their actions under the value,
`ZoneFooter` drops its actions under the sentence, `FlowLayout` wraps button rows (the GitHub / Clear / Copy controls are
right-aligned *trailing* items that wrap to their own line). Paths truncate; nothing clips or overlaps down to
720 × 560, including at 150% Windows text size (asserted in `tests/test_ui_settings_diagnostics_regroup.py`).

## Information dialogs: `InfoDialog`

`ui/info_dialog.py` is the one dialog shell: about 560 px wide (scaled with the Windows text size), fixed header (title
and a one-line muted intro), a body that scrolls only when it must, a fixed footer (optional secondary link on the left,
default **Close** on the right), height capped at 80% of the app window, hairline under the header only after the body
has scrolled. No tabs, no cards. **What ExileLens collects** (`CollectedDialog`, opened by *See what is collected*) is
built on it; the planned What's New dialog is meant to use the same shell.

The collected summary is deliberately short (about 140 words): usage statistics, crash and error reports, never
collected, one closing line, and a *Full privacy details* link to `PRIVACY.md`. It shows no event names, field schemas,
JSON, IDs or retention periods. Semantic tests (`tests/test_ui_privacy_dialog_and_supporter_polish.py`) tie it to
`events.v1.json`: every usage event, every error-report field and every "never collected" entry must still be covered,
so a contract change fails a test until the copy is reviewed.

## Updates copy

The pre-release line ("Pre-release · Latest stable 0.6.0") stays; the "Beta channel…" helper is no longer shown. The
update channel logic itself is unchanged.
