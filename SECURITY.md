# Security

This document describes ExileLens's security model in plain terms: what it does, what it deliberately does not do, the trust boundaries involved, and what to expect from Windows and antivirus software around an unsigned beta build.

## Official source and downloads

The official source code and official Windows builds of ExileLens are published through this GitHub repository:

https://github.com/arewoz/ExileLens

Official binaries are attached to:

https://github.com/arewoz/ExileLens/releases

Do not trust copies distributed through unofficial mirrors, file-sharing sites, reposted archives, or unsolicited links.

Do **not** disable antivirus protection in order to run ExileLens.

If you suspect a false positive, report:

- the ExileLens version
- the antivirus product
- the detection name
- the affected filename
- the file's SHA-256 hash, when available

Use GitHub Issues or Discord for suspected false positives unless the report contains security-sensitive information.

---

## Security model

ExileLens is a **local desktop overlay**.

It runs entirely on your own Windows machine as a normal user process. It has no account system of its own and no ExileLens server component.

Its normal job is to:

1. detect when you request an item check through the configured hotkey
2. copy the hovered Path of Exile 2 item using the game's normal copy-item behavior
3. read the resulting item text from the Windows clipboard
4. evaluate the item against the Path of Building 2 installation and build you configured
5. show the result in an overlay
6. optionally query the official Path of Exile trade service for live market information

The important trust boundaries are described below.

---

## Path of Exile 2

ExileLens does not read Path of Exile 2 process memory.

It does not inject code or DLLs into the game process.

It does not intercept or modify the game's network traffic.

The item-capture workflow uses the game's normal copy-item behavior. When the ExileLens hotkey is used while Path of Exile 2 is the active foreground window, ExileLens sends a single synthetic `Ctrl+C` input and reads the resulting clipboard text.

The hotkey action is gated on Path of Exile 2 being the active, focused window.

---

## Path of Building 2

ExileLens uses a local Path of Building Community installation for Path of Exile 2.

It loads PoB2 calculation components from the installation directory you select during setup and runs them locally to reuse PoB2's calculation logic.

ExileLens therefore trusts the selected PoB2 installation directory.

ExileLens does not independently verify a cryptographic signature for that installation. Only point ExileLens at a Path of Building installation you trust.

Path of Building 2 is not bundled with ExileLens.

---

## Clipboard access

ExileLens uses the Windows clipboard as part of item capture.

Its clipboard listener may remain active while the application is running, not only at the exact moment the hotkey is pressed.

The intended workflow is to process copied Path of Exile 2 item text. For the exact rules around what is read, retained, logged, or transmitted, see:

[PRIVACY.md](PRIVACY.md)

Do not assume that the system clipboard is private from other applications running on your computer.

---

## Network access

Normal ExileLens item evaluation runs locally.

The optional live market pricing feature can communicate over HTTPS with the official Path of Exile trade service.

For market lookups, ExileLens sends structured search information derived from the item being evaluated, such as:

- item category
- rarity
- matched stat information
- search ranges used to find comparable listings

ExileLens does not use a proprietary ExileLens account or telemetry backend.

For the precise privacy behavior of network requests, see:

[PRIVACY.md](PRIVACY.md)

---

## What ExileLens does

Based on the current source code, ExileLens uses:

- a global hotkey, `Shift+C` by default
- clipboard-based item capture
- one synthetic `Ctrl+C` input for item capture
- foreground-window checks so item capture only acts while Path of Exile 2 is focused
- a local Path of Building 2 installation for build calculations
- an overlay window for results
- optional HTTPS requests to the official Path of Exile trade service
- local application logs for diagnostics
- Windows input hooks used for overlay and hotkey behavior

---

## What ExileLens does not do

Based on the current source code:

- **No game-memory reading.** ExileLens does not open or read Path of Exile 2 process memory.
- **No process injection.** ExileLens does not inject code or DLLs into the game process.
- **No packet interception.** ExileLens does not sniff, intercept, or modify Path of Exile 2 network traffic.
- **No gameplay automation.** ExileLens does not move your character, use skills, interact with inventory, or perform gameplay actions for you.
- **No telemetry or analytics.** ExileLens does not send usage analytics or behavioral telemetry to the project maintainers.
- **No automatic download-and-execute updater.** ExileLens does not silently download and execute new ExileLens versions.
- **No administrator privilege requirement.** ExileLens is designed to run as a normal Windows user without elevation.

The only synthetic game-directed input used by the normal item-capture workflow is the single `Ctrl+C` copy action described above.

---

## Windows SmartScreen and antivirus

ExileLens is currently **not Authenticode code-signed**.

Because the application is unsigned and has limited reputation with Windows security services, Windows SmartScreen may display a warning such as:

> Windows protected your PC

This can occur with legitimate unsigned Windows applications and does not by itself prove that a file is malicious.

ExileLens also uses Windows APIs that antivirus products may treat as security-sensitive, including:

- a global keyboard hook for the hotkey
- a global mouse hook used for overlay behavior
- synthetic input for the single `Ctrl+C` item-copy action

These categories of APIs are also used by malicious software, which means heuristic or machine-learning antivirus systems may flag an unsigned ExileLens build even when the detection is a false positive.

An antivirus result by itself is not proof of safety or proof of malware.

If a release is flagged:

1. confirm that it came from the official GitHub Releases page
2. verify its SHA-256 checksum when one is provided
3. check whether the reported hash matches the official release asset
4. report the detection so it can be investigated

Do not disable security software globally in order to run ExileLens.

---

## Release integrity

Official ExileLens releases should publish SHA-256 checksums alongside downloadable Windows builds.

When a checksum is available, you can verify a downloaded file in PowerShell:

```powershell
Get-FileHash .\ExileLens.exe -Algorithm SHA256
```

For an archive:

```powershell
Get-FileHash .\ExileLens-<version>-win64.zip -Algorithm SHA256
```

Compare the resulting hash with the SHA-256 value published in the corresponding GitHub Release.

A matching SHA-256 value confirms that the file you downloaded is byte-for-byte identical to the file for which that checksum was published.

It does **not** prove that the software itself is safe, and it does not replace code signing.

---

## Reporting a security vulnerability

Please do **not** open a normal public GitHub issue for a security vulnerability before the maintainers have had a chance to review it.

If GitHub private vulnerability reporting is enabled for this repository, use it as the preferred reporting method.

Otherwise, contact the maintainers through:

https://discord.gg/4jrhBbSwEn

and ask for a private channel to report a security issue.

Please include, when relevant:

- affected ExileLens version
- affected component or file
- clear reproduction steps
- expected and observed behavior
- security impact
- logs or screenshots only after removing unrelated sensitive information

Do **not** post any of the following publicly:

- passwords
- credentials
- session tokens
- API tokens
- private keys
- authentication cookies
- raw logs containing private information
- exploit details that would unnecessarily expose users before a fix is available

---

## Responsible disclosure

If you discover a security issue, please give the maintainers a reasonable opportunity to understand, reproduce, and address it before publishing technical exploit details.

Clear, reproducible, private reports are the most useful.

Once a fix is available, the project can coordinate public disclosure when appropriate.

---

## Security scope

Security reports are especially useful when they involve issues such as:

- unintended access to sensitive local data
- unsafe handling of clipboard contents
- unexpected network transmission
- arbitrary code execution
- unsafe update or release behavior
- dependency or packaging vulnerabilities
- bypasses of the Path of Exile foreground gating
- behavior that contradicts the guarantees documented in this file or in `PRIVACY.md`

Normal gameplay-calculation bugs, incorrect upgrade/downgrade results, unsupported mechanics, and market-pricing inaccuracies should be reported through normal GitHub Issues rather than as security vulnerabilities.
