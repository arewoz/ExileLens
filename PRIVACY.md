# Privacy

This document describes what ExileLens currently reads, stores, and
transmits. It describes current behavior only — not planned features.
See "Future features" at the end for how that's handled.

## What ExileLens reads

- **Windows clipboard.** ExileLens's clipboard listener runs continuously
  while the app is open — see "When clipboard access occurs" below for
  exactly what that means.
- **Path of Building (PoB) build data.** The PoB build file (XML) you
  select, and PoB's own calculation output for that build.
- **Local configuration.** Your saved settings (hotkey, PoB path, active
  build, feature toggles) from ExileLens's own settings file.
- **Foreground window / process information.** ExileLens checks which
  window is currently focused and which process it belongs to, so it can
  tell whether Path of Exile 2 is the active window before acting on the
  hotkey or reading a clipboard event as game data. This check reads
  window and process metadata (window handle, process id, executable
  name); it does not read the target process's memory contents.

## When clipboard access occurs

**The clipboard listener is active continuously while ExileLens is
running — not only when you press the hotkey.** ExileLens registers with
Windows to be notified of every clipboard change on your system, from
any application, so it can recognize the moment Path of Exile 2's own
copy-item response appears. Most of those notifications are immediately
discarded without further action: if Path of Exile 2 is not the focused
window, or the copied text doesn't look like a PoE item, ExileLens does
not treat it as item data and does not act on it.

Pressing the hotkey (default `Shift+C`) also **writes** to the clipboard:
it sends a synthetic `Ctrl+C` to trigger the game's own item-copy
function, which overwrites whatever was previously on your clipboard.
ExileLens does not currently save and restore your prior clipboard
contents around this — whatever you had copied before pressing the
hotkey may be gone afterward.

## What is stored locally

Under `%LOCALAPPDATA%\poe2-value-overlay\`:

- **Settings** (`settings.json`) — your configuration (hotkey, PoB path,
  selected build, feature toggles, overlay position, and similar).
- **Build cache** — cached calculation results tied to your selected PoB
  build, to avoid recomputing on every check.
- **Application logs** (`logs\poe2value.log`, rotated) and a crash log
  — see "Logging" below.

None of this leaves your machine on its own; it is written and read
locally only.

## What leaves the computer

The only outbound network destination in normal use is the official
Path of Exile trade website (`www.pathofexile.com`), and only when you
use the optional live-market-pricing feature. What is actually sent is a
**structured, derived search query** — item category/base type, rarity,
and the specific stat ranges the tool matched — built from the item
after it has already been recognized and parsed.

**Your raw clipboard/item text is not sent over the network.** Only the
structured values derived from it are, and only for the trade-search
feature specifically.

## Telemetry

ExileLens does not include any telemetry, analytics, or crash-reporting
upload. No usage data, error report, or diagnostic is sent anywhere
automatically. (You can manually copy a diagnostics report yourself, from
the app's "Copy diagnostics" action, to paste into a bug report — that is
an explicit, user-initiated action, not automatic collection.)

## Logging

ExileLens writes a local, rotating application log
(`logs\poe2value.log`) to help diagnose bugs, and a separate crash log
for unexpected native crashes. Log lines record event metadata — things
like a clipboard sequence number, a text length, a recognition outcome,
or a request id — not the underlying text.

**Clipboard content specifically:** the clipboard listener is continuous
(see above), so it sees every clipboard change on your system, from any
application, not only Path of Exile 2's. The code path that logs those
events records only the sequence number and the length of the copied
text; it does not intentionally write the clipboard's actual content —
from Path of Exile 2 or from anything else — into `poe2value.log`. This
is enforced by an automated regression test that specifically checks
this logging path never emits copied text.

That covers the clipboard-logging path specifically, not a blanket
guarantee about every log line ExileLens can ever produce. Application
logs still contain other technical context (file paths, item categories,
request/error details), and we don't claim no future code path could
ever log something sensitive by mistake. If you're asked to share
`poe2value.log` or `crash.log` for a bug report, it's still good practice
to skim it first and redact anything you'd rather not share before
attaching or pasting it anywhere.

## Third-party services

| Destination | Purpose | Trigger |
|---|---|---|
| `www.pathofexile.com` (official PoE trade API) | Market/trade comparables | Optional live-pricing feature, one request per price check |

No other third-party service is contacted by ExileLens's normal
operation.

## Future features

Planned features (such as syncing your character from your Path of Exile
account) are **not implemented today** and this document does not cover
them. If and when such a feature ships, this document will be updated to
describe what it actually reads, stores, and sends at that time — this
privacy behavior may change as features are added, and you'll be able to
find the current behavior here rather than in release announcements.
