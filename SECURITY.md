# Security

This document describes ExileLens's security model in plain terms: what
it does, what it deliberately does not do, and what to expect from
Windows and antivirus software around an unsigned beta build.

## Official sources and reports

The official source is this GitHub repository. Official Windows downloads are
published at [itch.io](https://blackjacky21.itch.io/exilelens). Do not disable
antivirus protection to run any download. If you suspect a false positive,
report the product version, the detection name and (when available) the
published SHA-256/build-provenance information through
[Discord](https://discord.gg/4jrhBbSwEn) or a GitHub issue.

## Security model

ExileLens is a **local desktop overlay**. It runs entirely on your own
machine as a normal Windows process, with no server component and no
account system of its own. Its job is to notice when you want to check
an item (via a hotkey), read that item's text from the Windows clipboard,
evaluate it against a Path of Building 2 (PoB2) calculation you already
have configured, and show the result in an overlay window.

The trust boundaries that matter for that job are:

- **The game (Path of Exile 2):** ExileLens never reads the game's memory
  and never injects code into the game process. It only observes the
  Windows clipboard and the currently-focused window, the same
  information any other running application on your PC can also see.
- **Path of Building 2:** ExileLens loads PoB2's own calculation engine
  (its Lua scripts and native library) from the installation folder you
  point it at during setup, and runs it in-process to reuse PoB's own
  math. ExileLens trusts that folder's contents to be a genuine PoB2
  installation; it does not verify a cryptographic signature on it.
  Point ExileLens at an installation you trust, the same way you'd trust
  any other calculation tool you run.
- **The network:** the only third party ExileLens's normal operation can
  talk to is the official Path of Exile trade website, over HTTPS, and
  only when you use the optional live-market-pricing feature.
- **Your clipboard:** ExileLens's clipboard listener is active any time
  the app is running, not only when you press the hotkey — see
  `PRIVACY.md` for exactly when and how it's read.

## What ExileLens does

- **A global hotkey** (default `Shift+C`) that you press while playing.
- **Clipboard-based item capture**: pressing the hotkey sends one
  synthetic `Ctrl+C` keystroke to the game (Path of Exile 2's own
  "copy item" shortcut), then reads the resulting clipboard text.
- **PoE-foreground gating**: the hotkey and the synthetic keystroke only
  act while Path of Exile 2 is the active, focused window — pressing
  the hotkey while any other application is focused does nothing.
- **Local PoB2 integration**: item evaluation runs your configured Path
  of Building 2 engine locally to compare the item against your build.
- **Optional trade lookups**: if you enable live market pricing,
  ExileLens sends structured search parameters (item category, rarity,
  matched stat ranges — not your raw clipboard text) to the official
  Path of Exile trade API over HTTPS.
- **Local application logs**, written to your own machine, to help
  diagnose bugs.

## What ExileLens does NOT do

Based on the current source code:

- **No game-memory reading.** ExileLens never opens or reads Path of
  Exile 2's process memory.
- **No process injection.** ExileLens does not inject code or DLLs into
  the game process.
- **No packet interception.** ExileLens does not intercept, sniff, or
  modify the game's network traffic.
- **No gameplay automation.** The only synthetic input ExileLens ever
  sends is the single `Ctrl+C` keystroke described above, gated on the
  game being in the foreground; it never moves your character, uses
  skills, or performs any other in-game action for you.
- **No telemetry or analytics.** ExileLens does not phone home usage
  data, crash reports, or any other analytics to its developers or any
  third party.
- **No auto-update / download-and-execute behavior.** ExileLens does not
  check for updates, download files, or execute anything it fetches from
  the network. You update by downloading a new release yourself.
- **No administrator privilege requirement.** ExileLens runs, and is
  designed to run, as a normal user without elevation.

## Windows security / antivirus notes

ExileLens is currently **not code-signed** (no Authenticode certificate).
Because of that:

- **Windows SmartScreen may warn** on first run ("Windows protected your
  PC"). This is expected for any unsigned, unfamiliar Windows
  executable, not specific to ExileLens.
- **Some antivirus engines may flag it heuristically.** ExileLens uses a
  global low-level keyboard hook (to detect the hotkey), a global mouse
  hook (to dismiss its own overlay), and synthetic input (the single
  `Ctrl+C` described above) — the same category of Windows APIs used by
  keyloggers and input-automation tools, even though ExileLens's use of
  them is narrow and game-foreground-gated. Combined with being an
  unsigned PyInstaller-packaged executable, this combination is a
  well-known source of heuristic ("machine-learning") antivirus
  detections on legitimate game-assist tools generally.
- **An antivirus warning by itself is not proof of anything**, in either
  direction — it is not proof of malware, and it is not proof of safety.
  If you want to verify a specific build yourself, read the source, or
  ask in the project's community channel.
- **Only download ExileLens from the project's official release
  location.** Do not trust copies distributed through unofficial mirrors,
  file-sharing sites, or unsolicited links.

## Release integrity

If a given release publishes SHA-256 checksums alongside its download
(check the release notes for that build), you can verify your download
matches by computing its SHA-256 hash yourself and comparing it against
the published value. If a release does not publish checksums, none exist
for it yet — this document will be updated if and when that becomes a
standard part of every release.

## Reporting a security issue

There is currently no dedicated private security-reporting email or
security.txt endpoint. Please ask a maintainer in
[Discord](https://discord.gg/4jrhBbSwEn) for a private reporting channel
instead of opening a public issue with exploit details attached.

**Please do not include credentials, session tokens, private keys, or
raw application log files in a public issue or public channel message.**
If a report requires sharing a log file, redact it first, or ask a
maintainer privately for a way to share it out of public view.

## Responsible disclosure

If you find a security issue, please give the maintainers a reasonable
chance to understand and address it before discussing it publicly, and
avoid posting proof-of-concept details, secrets, or other sensitive
material in a public issue, forum post, or chat channel. We're a small,
unofficial community project — clear, private reports help far more than
public pressure.
