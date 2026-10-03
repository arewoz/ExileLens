# Privacy

This document describes what ExileLens currently reads, stores, and
transmits. It describes current behavior only — not planned features.
See "Future features" at the end for how that's handled.

**In short:** ExileLens works fully offline for item checks and build
analysis. By default it contacts only the services it needs (GitHub for
updates, and the official Path of Exile website for optional market
features). Two *optional* settings — usage statistics and crash/error
reports — are **off by default** and send nothing until you turn them on.

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

Under `%LOCALAPPDATA%\ExileLens\` (older installs may still have an
unused `poe2-value-overlay` folder from before the rename; ExileLens copies
its settings once and never deletes the old folder):

- **Settings** (`settings.json`) — your configuration (hotkey, PoB path,
  selected build, feature toggles, overlay position, privacy choices, and
  similar).
- **Build cache** — cached calculation results tied to your selected PoB
  build, to avoid recomputing on every check.
- **Application logs** (`logs\poe2value.log`, rotated) and a crash log
  — see "Logging" below.
- **Update files** (`updates\`) — a downloaded update package, its
  verification record and the external updater's status files, while an
  update is pending.
- **Optional cloud queues** (`cloud\`) — exists only if you turned on usage
  statistics and/or error reports: one random ID and a small bounded queue
  of not-yet-sent items per category. Turning a category off deletes its
  folder.

None of this leaves your machine on its own, except the opt-in items
described below.

## What leaves the computer

| Destination | What is sent | When |
|---|---|---|
| `api.github.com`, `github.com` (ExileLens releases) | A request for the list of ExileLens releases and, if a newer one exists, its signed update manifest. The update package is downloaded only when you choose to install it. No account, no identifier. | Packaged builds check at startup and at most about once every 24 hours. |
| `www.pathofexile.com` (official Path of Exile site) | The structured market search derived from the item you checked (category, rarity, matched stat ranges), and the league list. Your raw clipboard/item text is not sent. | Only for the optional live-market features. |
| ExileLens cloud service (`api` host of the project; **only if this build has it configured and you opted in**) | Only the items in "Optional usage statistics and error reports" below. | Only for the category you switched on. |

**Your raw clipboard/item text is not sent over the network.** Only the
structured values derived from it are, and only for the trade-search
feature specifically.

## Optional usage statistics and error reports

Two separate switches in Settings → Privacy, **both off by default**. They
are independent: turning one on never turns on the other, and ExileLens
behaves identically with both off. A card on the Overview page asks once
after setup; "Not now" leaves both off. **See what is collected** in
Settings shows the exact fields, the identifiers and a real example of
your next upload.

**Privacy-friendly usage statistics** — counts that show whether
ExileLens works and is used: that the app started (and whether the previous
session ended unexpectedly), setup finished, PoB started and how long
that took in broad buckets, Item Check *result categories* with speed
buckets (verdict, confidence, evaluation quality — grouped counts, never
one event per item and never the item), Analyze Build outcome categories
(coverage, number of follow-up curves, whether a hard issue exists, health
category, duration bucket) and update outcomes. App version, release channel,
packaged/source and Windows 10/11 are included.

**Crash and error reports** — a registered ExileLens error code, its
component, the *type* of the exception and normalised stack frames
(module and function names, optionally a line number), how often, and when
(rounded to the hour).

**Never collected:** item text, item names or modifiers, anything from the
clipboard, build or PoB files, character, account, skill, stat or equipment
names, trade searches or prices, file paths, log files, settings values,
environment variables, error messages or raw stack traces, hardware or
Windows account identity, email, Path of Exile or Patreon identity. The
service rejects any field that is not in the published list.

**Identifiers.** Each category creates its own random ID on your PC the
first time it has something to send (no hardware, Windows account or
network information is used). The two IDs are different and are never
combined. The service stores only a keyed hash of the ID, never the ID
itself. This makes the data *pseudonymous*, not anonymous: the same install
can be recognised across uploads, which is what makes "active
installations" countable. Active-installation numbers describe only people
who opted in and are not a count of players.

**Turning a switch off** immediately stops collecting for that category,
deletes its queue and ID on your PC, and sends one best-effort request
asking the service to delete the data stored under that ID. A request that
was already in flight at that moment may still arrive. Turning it on again
creates a new random ID with no link to the old one. "Reset configuration"
also turns both off.

**Retention.** Raw usage events are deleted after 30 days; install activity
after 120 days; daily summaries are kept 13 months. Error occurrences are
grouped, error groups are kept 12 months, and the list of which anonymous
IDs saw a group is deleted after 60 days. The service does not store IP
addresses, user agents or request bodies in its database; the hosting
provider (Cloudflare) necessarily sees network addresses for any web
request and keeps its own short-lived operational logs, which are not used
for statistics.

**If the service is unreachable or over its free quota**, ExileLens keeps a
small bounded queue (500 items, 7 days), backs off, and eventually discards
old items. Nothing about the app depends on it.

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
attaching or pasting it anywhere. Log files are **never** uploaded
automatically. You can copy a diagnostics report yourself from the app's
"Copy diagnostics" action; that is an explicit, user-initiated action.

## Third-party services

| Destination | Purpose | Trigger |
|---|---|---|
| `www.pathofexile.com` (official PoE trade API) | Market/trade comparables, league list | Optional live-pricing feature |
| `api.github.com` / `github.com` | Update check and (on your action) update download | Packaged builds, about once per 24 h |
| ExileLens cloud service (Cloudflare Workers + D1) | Opt-in usage statistics and error reports | Only if configured in this build and switched on by you |

No other third-party service is contacted by ExileLens's normal
operation. Patreon account linking is not part of this version.

## Future features

Planned features (such as syncing your character from your Path of Exile
account, or optional Patreon linking) are **not implemented today** and
this document does not cover them. If and when such a feature ships, this
document will be updated to describe what it actually reads, stores, and
sends at that time — this privacy behavior may change as features are
added, and you'll be able to find the current behavior here rather than in
release announcements.
