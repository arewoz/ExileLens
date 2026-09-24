# ExileLens 0.4.0b1

Early beta for Windows. Item Check uses your selected Path of Building for Path of Exile 2 build and shows upgrade / downgrade guidance in an overlay.

## Highlights

### Item Check and equipment

- **Two-handed weapons and paired offhands:** When a two-handed candidate would remove your shield or change which offhand PoB equips, verdict and tooltip text now name the **actual** item that would be dropped—including swap-set quiver vs. primary shield cases.
- **Safer weapon and offhand evaluation:** One-hand + offhand, bow + quiver, shield replacement, and two-handed weapon upgrades are measured with more reliable **equipment and build-context restoration** after each check.
- **Weapon-set swap slots:** Item Check refines component-context evaluation for builds using PoB’s second weapon set. This release improves correctness and restore behavior for swap-slot comparisons; it does **not** add whole-build, cross-weapon-set automation (you still check one hovered item at a time).

### Stability and reliability

- **Unicode worker compatibility** on Windows for PoB subprocess output.
- **Deferred restoration and crash handling:** If the calculation worker stops unexpectedly, ExileLens fails closed and avoids showing a successful result after a failed restore.
- **Non-weapon Item Check crash fix** for some ring and accessory comparisons that could abort evaluation.

### Quality

- Expanded real-PoB and mandatory regression coverage for weapon/offhand scenarios, incompatible placements, and paired-offhand disclosure.

## Not in the desktop app

Internal contextual proof and diagnostic enumeration APIs support engineering and automated tests. They are **not** a separate player-facing mode and do **not** compare your entire build across all weapon sets automatically.

## Installation

1. Download **ExileLens-v0.4.0b1-win64.zip** from the GitHub Release (published by the project’s release workflow).
2. Extract the full folder and run **ExileLens.exe**.
3. On first launch, connect your **Path of Building Community (PoE2)** installation and select a saved build XML.

Path of Building is **not** bundled. See `README.txt` in the ZIP for requirements, Shift+C usage, and troubleshooting.

**Supported PoB source revision (tested):**

- branch: `dev`
- commit: `97cb973f8a114d32010bc1a4195c170628771714`

## Known limitations

- **Path of Exile 2 game client** compatibility is **not verified** in this release; only the supported PoB revision above is recorded.
- Item Check evaluates **one hovered item** at a time—not every weapon-set combination across your whole build.
- Some mechanics remain cautious or unsupported (certain jewel sockets, multi-part skills without fixtures, and cases that must show uncertainty instead of a directional verdict).
- Beta quality: wrong or unsupported evaluations are still possible; use diagnostics and report issues via the in-app links.

## Feedback

Discord: https://discord.gg/4jrhBbSwEn

Bug reports: use **Diagnostics → Copy diagnostic report** and open a GitHub Issue with reproduction steps.
