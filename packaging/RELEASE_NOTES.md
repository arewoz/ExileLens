# ExileLens 0.5.0b1

Early beta for Windows. Item Check uses your selected Path of Building for Path of Exile 2 and shows upgrade / downgrade guidance in an overlay.

## Highlights

### Diagnostics and support

- **Diagnostics 2.0:** Application health summary, single **Copy diagnostics** action, optional support package export, and collapsible Advanced diagnostics (event history and technical report).
- **Structured error codes:** Failures in Item Check, PoB connection, build loading, the calculation worker, and updates surface stable **EL-*** codes with plain-language recovery guidance in the overlay and Diagnostics.

### Updates

- **Unified release selection:** Automatic updates target the **newest verified** official release (beta or stable) using version ordering—not a separate channel picker.
- **Settings → Updates:** Installed version, check/download progress, and restart-to-apply live in Settings; the dashboard footer and system tray show the same state.

### Evaluation honesty

- **UNCERTAIN / UNSUPPORTED** Item Check outcomes use a separate **evaluation limitation** catalog; they are not treated as application crashes.
- Scoring, damage math, and truthfulness gates are unchanged from 0.4.0b1.

### Setup and Item Check

- **PoB2 auto-discovery** suggests a validated installation folder during setup when none is saved; manual Browse remains available.
- **Stale build protection** rejects Item Check that observed newer or missing on-disk build bytes instead of evaluating against an outdated in-memory baseline.

## Installation

1. Download **ExileLens-v0.5.0b1-win64.zip** from the GitHub Release (after publish approval).
2. Extract the full folder and run **ExileLens.exe**.
3. On first launch, connect your **Path of Building Community (PoE2)** installation and select a saved build XML.

Path of Building is **not** bundled. See `README.txt` in the ZIP for requirements, Shift+C usage, and troubleshooting.

The distribution includes **ExileLensUpdater.exe** under `_internal\` for in-place secure updates.

**Supported PoB source revision (tested):**

- branch: `dev`
- commit: `97cb973f8a114d32010bc1a4195c170628771714`

## Update system (packaged installs only)

1. Open **Settings → Updates** and choose **Check for updates**.
2. When a newer verified release is available, use **Download & Install**.
3. When the download is verified, choose **Restart & Update** to apply via the external updater.

Source/development runs do not self-update. If the newest release cannot be verified safely, ExileLens will **not** install an older release automatically.

## Known limitations

- **Path of Exile 2 game client** compatibility is **not verified** in this release.
- Structured error coverage focuses on Item Check, PoB, build, worker, updates, and diagnostics export—not every experimental module (market hub, tree tools, gear optimizer).
- Item Check evaluates **one hovered item** at a time.
- Beta quality: report issues via **Diagnostics → Copy diagnostics** and GitHub Issues.

## Feedback

Discord: https://discord.gg/4jrhBbSwEn

Bug reports: **Diagnostics → Report an issue** (GitHub) with reproduction steps and copied diagnostics.
