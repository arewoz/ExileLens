<!-- DRAFT, NOT ACTIVE. Replaces packaging/RELEASE_NOTES.md in slice 1.0-E, together with the version bump (the release gate requires the first line to be "# ExileLens <version>" and uses this file as the GitHub release body). Describes 0.6.0 -> 1.0.0; 0.7.x builds were internal. Remove this comment when applying. -->
# ExileLens 1.0.0

Build-aware item analysis for Path of Exile 2. Item Check compares the item you hover against your selected Path of Building for Path of Exile 2 build and shows an upgrade, downgrade, sidegrade or uncertain verdict in an overlay.

## What changed since 0.6.0

- **Item Check says what your build needs.** When an item fixes a resistance cap or another current priority of your build, the tooltip says so next to the measured result. The measured comparison against your equipped gear still decides the verdict.
- **Analyze Build shows what to do next.** What to fix first, the stats your build responds to most, and up to three next actions, each with the change that was tested. When something could not be established, it says so.
- **A redesigned desktop app.** A status panel shows your build and whether ExileLens is ready, with Overview, Analyze Build, Settings and Diagnostics beside it. A "What's new" dialog appears once after an update.
- **Verified updates that roll back.** Updates are checked against a signed manifest before they install, installs are journaled and rolled back if they fail, and ExileLens tells you the result after restarting.
- **Supporter convenience, nothing else.** Patreon supporters who link their account get more frequent checks, background download of verified updates and install when ExileLens closes. Everyone else keeps Download & install and Restart & update. It is the same signed release for everyone; there is no paid build and no DRM.
- **Optional usage statistics and error reports.** Two separate switches in Settings, both off by default. Only a fixed list of anonymous values is ever sent; Settings shows exactly what. Item Check, Analyze Build and manual updates work without them and without any account.
- **Clearer refusals.** Jewels and off-hand items that cannot be compared say why in plain words, without internal socket numbers.
- **Reliability.** Item Check and Analyze Build were checked against a corpus of real public builds, covering weapons, off-hands, jewels, loadouts and weapon sets, and your build is restored exactly after every comparison.
- **Fix:** crossbows with ammunition skills are measured on the skill that actually fires, so a stronger crossbow no longer shows no change.

## Installation

1. Download **ExileLens-v1.0.0-win64.zip** and **SHA256SUMS.txt** from this GitHub release.
2. Check the ZIP against `SHA256SUMS.txt` (PowerShell: `Get-FileHash .\ExileLens-v1.0.0-win64.zip -Algorithm SHA256`), then extract the full folder and run **ExileLens.exe**.
3. On first launch, connect your **Path of Building Community (PoE2)** installation and select a saved build XML.

Path of Building is not bundled. `README.txt` in the ZIP covers requirements, Shift+C usage and troubleshooting. The ZIP also contains `LICENSE`, `THIRD_PARTY_NOTICES.txt` and `third_party_licenses\`.

ExileLens is not signed with a paid Windows code-signing certificate, so Windows SmartScreen or antivirus software may warn about it. Download it only from this repository's GitHub Releases page.

**Supported PoB source revision (tested):** branch `dev`, commit `97cb973f8a114d32010bc1a4195c170628771714`.

## Updating

Packaged builds check GitHub shortly after start and then about once a day; there is no setting to turn the check off. To update, open **Settings -> Updates**, choose **Check for updates**, then **Download & install** and **Restart & update**. If that fails, download the new ZIP from GitHub Releases, check it against `SHA256SUMS.txt` and extract it over the old folder; your settings stay in `%LOCALAPPDATA%\ExileLens`. Source and development runs do not self-update.

## Known limitations

- Some Path of Exile 2 mechanics are not fully modeled by Path of Building or ExileLens, so some results are partial or `UNCERTAIN`.
- Jewels that change passive-tree connectivity cannot be evaluated.
- Your Path of Building build is the comparison baseline, not your live in-game gear.
- ExileLens does not show prices and does not contact the Path of Exile trade service.
- Item Check evaluates one hovered item at a time.

## Feedback

Discord: https://discord.gg/4jrhBbSwEn

Bug reports: **Diagnostics -> Report an issue** (GitHub) with reproduction steps and copied diagnostics.
