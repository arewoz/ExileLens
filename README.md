# ExileLens

Free and open-source, build-aware item analysis for Path of Exile 2.

ExileLens answers one question: *"Is this item actually better for my
build?"* It evaluates a hovered item against your Path of Building 2
build and shows an upgrade/downgrade verdict in an overlay, using a
hotkey and clipboard-based capture — see `SECURITY.md` and `PRIVACY.md`
for exactly how.

ExileLens is an unofficial, fan-made project and is not affiliated with
or endorsed by Grinding Gear Games or the Path of Building project. Path
of Exile and Path of Exile 2 are trademarks of Grinding Gear Games.

## Status

ExileLens is a Windows beta. It is useful today, but unsupported mechanics
and occasional incorrect evaluations are still expected. Official downloads
and release notes are published at [itch.io](https://blackjacky21.itch.io/exilelens).

## Install and use

1. Install Path of Building Community for Path of Exile 2 separately.
2. Download and extract the current ExileLens Windows package from the
   official [itch.io page](https://blackjacky21.itch.io/exilelens).
3. Start `ExileLens.exe`, then choose your PoB2 installation and saved build.
4. In Path of Exile 2, hover an item and press `Shift+C`.

ExileLens compares that item with the equipment, skills, passive tree and
other active context in the selected PoB2 build. It shows a build-aware
verdict rather than a generic item score.

## Build from source

Windows and a pinned Python version from `.python-version` are required.
The release build creates an isolated `.release-venv` from
`packaging/requirements-release.txt` and produces an onedir build:

```powershell
scripts\build_exe.ps1 -SkipShortcut
```

The application also requires a local Path of Building Community (PoE2)
installation and a PoB build XML at runtime. PoB2 is not bundled.

## Current limitations

- Windows only.
- Jewels are currently unsupported.
- Some PoE2 mechanics may be partial or unsupported in PoB2 or ExileLens.
- The selected PoB build, rather than automatically detected live gear, is
  the comparison baseline.

## Documentation

- [`SECURITY.md`](SECURITY.md) — security model, what ExileLens does and
  does not do, and Windows/antivirus notes.
- [`PRIVACY.md`](PRIVACY.md) — what is read, stored, and transmitted.
- [`packaging/THIRD_PARTY_NOTICES.txt`](packaging/THIRD_PARTY_NOTICES.txt)
  — third-party components bundled with the distributed build and their
  licenses.
- [`docs/`](docs/) — technical reference for the engine, packaging, branding
  and feature contracts.

## Requirements

- Windows 10/11
- Path of Exile 2
- Path of Building Community (PoE2), installed separately

## Reporting issues

Report bugs through [Discord](https://discord.gg/4jrhBbSwEn) or the public
GitHub issue tracker. For security issues, follow `SECURITY.md`; do not put
credentials, tokens or raw logs in a public report.

ExileLens is an unofficial community tool and is not affiliated with or
endorsed by Grinding Gear Games. Path of Exile and Path of Exile 2 are
trademarks of Grinding Gear Games.
