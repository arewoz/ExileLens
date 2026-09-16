
### `SECURITY.md`

```md
# Security

This document describes ExileLens's security model in plain terms: what the application does, what it deliberately does not do, what data it interacts with, and what to expect from Windows and antivirus software when running an unsigned beta build.

## Official source and downloads

The only official source repository for ExileLens is:

https://github.com/arewoz/ExileLens

Official Windows builds are published through GitHub Releases:

https://github.com/arewoz/ExileLens/releases

Do not download ExileLens from unofficial mirrors, file-sharing sites, reposted executables or unsolicited links.

Do not disable antivirus protection simply to run ExileLens.

If you receive an antivirus warning or suspect a false positive, report the ExileLens version, antivirus product, detection name and any other useful details through GitHub Issues or Discord.

GitHub Issues:

https://github.com/arewoz/ExileLens/issues

Discord:

https://discord.gg/4jrhBbSwEn

## Security model

ExileLens is a local Windows desktop overlay.

It runs on your own machine as a normal user process. ExileLens has no account system and no ExileLens-operated server component.

Its main job is to:

1. Detect when you request an item evaluation using the configured hotkey.
2. Use Path of Exile 2's normal copy-item functionality to copy the hovered item's text.
3. Read that item text from the Windows clipboard.
4. Evaluate the item against the Path of Building 2 build you configured.
5. Display the result in the ExileLens overlay.

The main trust boundaries are described below.

### Path of Exile 2

ExileLens does not read Path of Exile 2 process memory.

ExileLens does not inject code or DLLs into the game process.

ExileLens does not intercept or modify Path of Exile 2 network traffic.

Item capture is based on Path of Exile 2's normal copy-item behavior and the Windows clipboard.

The ExileLens hotkey is gated so item capture is intended to act only while Path of Exile 2 is the active foreground application.

### Path of Building 2

ExileLens uses Path of Building 2 as its build calculation engine.

During setup, you select a Path of Building Community PoE2 installation that you trust.

ExileLens loads PoB2 calculation components from that installation so it can reuse PoB2's build calculations when evaluating candidate items.

ExileLens does not cryptographically verify the Path of Building 2 installation you select.

Only point ExileLens at a Path of Building 2 installation obtained from a source you trust.

Official Path of Building Community PoE2 repository:

https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2

### Network access

Most ExileLens build evaluation happens locally.

When the optional live market pricing functionality is used, ExileLens may communicate with the official Path of Exile trade service over HTTPS.

Market queries use structured item information required to search for comparable listings.

ExileLens does not operate its own telemetry or analytics backend.

### Clipboard access

ExileLens uses the Windows clipboard as part of item capture.

The application may observe clipboard changes while it is running because its item-capture system relies on clipboard state.

The hotkey-triggered capture flow sends a single synthetic `Ctrl+C` input to Path of Exile 2 while the game is in the foreground and then reads the resulting item text.

See [`PRIVACY.md`](PRIVACY.md) for the detailed clipboard, storage and network privacy model.

## What ExileLens does

ExileLens currently uses the following capabilities:

- A global hotkey, `Shift+C` by default
- Windows clipboard access
- A synthetic `Ctrl+C` input used for Path of Exile 2's normal copy-item functionality
- Foreground-window detection
- Local Path of Building 2 integration
- Local application logs
- Optional HTTPS requests to official Path of Exile trade services for live market pricing
- Overlay windows shown on the user's desktop

## What ExileLens does not do

Based on the current source code and intended architecture:

- **No game-memory reading.** ExileLens does not open or inspect Path of Exile 2 process memory.
- **No process injection.** ExileLens does not inject code, DLLs or other components into the game process.
- **No packet interception.** ExileLens does not sniff, intercept or modify Path of Exile 2 network traffic.
- **No gameplay automation.** ExileLens does not move the player, use skills, interact with inventory items, navigate menus or perform gameplay actions.
- **No automated trading.** ExileLens does not automatically contact players, purchase items or execute trades.
- **No telemetry or analytics.** ExileLens does not send usage analytics or behavioral telemetry to the developers.
- **No ExileLens account system.** ExileLens does not require an account with the project.
- **No automatic download-and-execute updater.** ExileLens does not silently download and execute replacement application binaries.
- **No administrator privilege requirement.** ExileLens is intended to run as a normal Windows user without elevation.

The synthetic `Ctrl+C` input used for item capture is limited to the copy-item workflow described above.

## Windows security and antivirus notes

ExileLens Windows beta builds are currently not Authenticode code-signed.

Because of this, Windows SmartScreen may display a warning such as:

> Windows protected your PC

This is common for new or unsigned Windows applications with limited reputation.

Some antivirus products may also produce heuristic detections.

ExileLens uses Windows functionality that security software may consider sensitive, including:

- a global keyboard hook used for the ExileLens hotkey
- a global mouse hook used for overlay interaction and dismissal
- foreground-window detection
- Windows clipboard access
- synthetic `Ctrl+C` input
- a packaged Python application executable

Some of these APIs are also used by malware, keyloggers and automation tools. Security products therefore sometimes classify unfamiliar unsigned applications using them as suspicious.

An antivirus detection by itself is not proof that software is malicious.

Likewise, the absence of an antivirus warning is not proof that software is safe.

Users who want additional assurance can inspect the public source code, compare release information and verify published checksums.

Do not disable your antivirus software simply to run ExileLens.

## Release integrity

Official ExileLens builds are published through GitHub Releases.

Each official release should include SHA-256 checksum information for distributed Windows packages.

A SHA-256 checksum allows you to verify that a downloaded file is byte-for-byte identical to the file published with that release.

On Windows PowerShell, a file can be checked with:

```powershell
Get-FileHash .\ExileLens-<version>-win64.zip -Algorithm SHA256
