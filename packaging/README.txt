EXILELENS 0.7.0b1
=================

Build-aware item analysis for Path of Exile 2.

ExileLens answers one question:

    "Is this item actually better for my build?"

It evaluates hovered items against your selected Path of Building for Path of Exile 2 build and shows an upgrade / downgrade verdict in an overlay. It also has an Analyze Build page that shows what your build responds to.

ExileLens is open source (MIT). Some Path of Exile 2 mechanics are not modeled by Path of Building or ExileLens, so some results are partial or uncertain. See KNOWN LIMITATIONS.


REQUIREMENTS
------------

- Windows 10 / 11
- Path of Exile 2
- Path of Building for Path of Exile 2
- A normal Path of Building Community (PoE2) installation
- A PoB build saved as XML

Path of Building is NOT included with ExileLens and must be installed separately.

Tested PoB source revision:

    branch: dev
    commit: 97cb973f8a114d32010bc1a4195c170628771714

The PoB desktop app does NOT need to stay open while using ExileLens.


INSTALLATION & SETUP
--------------------

1. Download and extract the full ExileLens ZIP.
2. Run:

       ExileLens.exe

3. On first launch, select:
   - your Path of Building Community (PoE2) installation folder;
   - your PoB build XML.

ExileLens automatically checks the usual AppData and Program Files locations,
your standard Documents/Desktop/Downloads folders (including OneDrive
Documents), and the POB2_PATH environment variable when it is set.

The usual installation folder is:

    %APPDATA%\Path of Building Community (PoE2)

Select the folder containing Path of Building-PoE2.exe, Launch.lua,
lua51.dll, Data, and Modules. A Git checkout is not required.
If automatic detection does not find a portable or custom installation, use
Browse in Setup to select that folder manually.

4. Save the setup.

ExileLens then runs in the Windows system tray.

IMPORTANT:
ExileLens compares items against the gear saved in your selected PoB build.
Keep that build updated if you change equipment, skills or passive tree.


HOW TO USE
----------

1. Start ExileLens.
2. Open Path of Exile 2.
3. Hover an item.
4. Press:

       SHIFT + C

5. ExileLens evaluates the item and shows the result.

Path of Exile 2 must be the foreground application.

UNCERTAIN means ExileLens does not have enough evidence for a reliable
verdict. It is not a judgment on the item. Open More info for the detailed
breakdown whenever a result needs explanation.

Copy Item is an action you perform inside Path of Exile 2 (for example on a
trade listing). The copied item text goes through the same Item Check as
Shift + C.


CONTROLS
--------

SHIFT + C
    Analyze hovered item.

ESC
    Close overlay.

P
    Pin current result.

More info >
    Open detailed analysis.

Copy diagnostics
    Copy evaluation data for bug reports.


HOTKEY
------

The default Item Check hotkey is SHIFT + C. It can be changed under
Dashboard -> Settings -> Hotkey (Change button), where a Test button
listens for the new chord to confirm it is detected.

If the hotkey never fires, check that Path of Exile 2 is the foreground
application, that no other tool uses the same chord, and that ExileLens
runs at the same privilege level as the game: if PoE2 runs as
administrator, run ExileLens as administrator too. Settings shows an
elevation note when a mismatch is detected.


WHAT IT DOES
------------

- Upgrade / downgrade / sidegrade verdicts against your equipped PoB gear
- Offensive, defensive and utility impact, with resistance cap awareness
- More Info breakdown for every result
- Partial / unsupported mechanic warnings instead of a guess
- Up to 4 pinned comparisons
- Balanced / Mapping / Bossing / Defensive profiles
- Loadout / Gear Set selection
- Analyze Build: what your loaded build responds to, with the measured change
- Diagnostics

Supported equipment:
Helmet, Body Armour, Gloves, Boots, Belt, Ring, Amulet,
1H/2H weapons and Offhand/Focus.
Jewels placed in allocated passive-tree sockets.

A small number of special jewels that alter passive-tree connectivity
cannot be evaluated.

ExileLens does not show prices. It does not contact the Path of Exile
trade service, and it has no market price feature in this build.


UPDATES
-------

Packaged builds check GitHub for a newer release shortly after start and
then about once a day. Every update is verified against a signed manifest
before it is installed. Nothing is installed without the verified update
flow, and a failed update is rolled back.

Everyone can update manually: Settings -> Updates -> Check for updates, then
Download & install and Restart & update. If that ever fails, download the new
ZIP from the official GitHub Releases page, check it against SHA256SUMS.txt
and extract it over the old folder (your settings are kept in
%LOCALAPPDATA%\ExileLens).

Supporters who link Patreon in Settings -> Updates get convenience only:
ExileLens checks more often (about every 6 hours), downloads a verified
update in the background and can install it when you close ExileLens or when
you choose Restart & update. Both supporter switches can be turned off.
The update itself and its source are the same for everyone: there is no
paid build, no DRM and no separate download channel.

No account is needed to use ExileLens.


KNOWN LIMITATIONS
-----------------

- Some PoE2 mechanics may not be fully modeled by PoB or ExileLens.
- Some results may therefore be partial.
- A small number of special jewels that alter passive-tree connectivity cannot be evaluated.
- Your PoB build is the comparison baseline, not automatically your live in-game gear.
- The first analysis after launch may be slower while the PoB worker starts.
- Some multi-monitor / DPI setups may still have UI issues.


TROUBLESHOOTING
---------------

Overlay does not appear:
- Make sure ExileLens is running in the system tray.
- Make sure PoE2 is in the foreground.
- Make sure a valid item tooltip is visible.
- Press the configured hotkey again (default Shift+C; see HOTKEY above
  if you rebound it or suspect a conflict).

"No build loaded":
- Select or reload the correct build XML from ExileLens.

PoB worker fails:
- Check that your Path of Building installation folder is correct.
- Use the Setup Test option.

"Could not read hovered item":
- Keep PoE2 focused.
- Make sure the item tooltip is visible.
- Do not Alt-Tab while pressing Shift+C.

Partial / unsupported result:
- ExileLens could not fully evaluate the item or mechanic.
- UNCERTAIN means there was not enough evidence for a reliable verdict.
- Please report suspicious results.


WINDOWS SMARTSCREEN
-------------------

ExileLens is not digitally signed with a paid Windows code-signing
certificate. Windows may show:

    Windows protected your PC

If you downloaded ExileLens from the official GitHub Releases page:

    More info -> Run anyway

Before you run it, check the ZIP against SHA256SUMS.txt from the same
release (PowerShell: Get-FileHash <zip> -Algorithm SHA256). A matching hash
shows the file is the one that was published; it is not a safety guarantee
beyond that.


BUG REPORTS
-----------

Main log:

    %LOCALAPPDATA%\ExileLens\logs\poe2value.log

When reporting a bug, please include:

- Copy diagnostic report output from Diagnostics;
- what you expected and what happened instead;
- short reproduction steps;
- a screenshot when relevant.

Diagnostics are generated locally and copied only when you choose Copy
diagnostic report. Nothing is submitted automatically. Open logs is for deeper
troubleshooting: logs stay local unless you explicitly choose to share them.

Before sharing poe2value.log, a quick skim is still good practice, the
same as with any local log file - see PRIVACY.md for what it does and
does not record.

Feedback / Discord:

    https://discord.gg/4jrhBbSwEn


PRIVACY
-------

Normal item evaluation runs locally.

Network use, for a default install:

- The update check described under UPDATES (GitHub only). It sends no
  identifier. There is no switch to turn the check off.
- Nothing else. ExileLens does not contact the Path of Exile trade service.

Two optional settings send data only if you turn them on, both OFF by
default and independent of each other:

- Usage statistics
- Error reports

Linking Patreon is optional and separate from both. The app never receives
your Patreon name or email.

See PRIVACY.md in the project repository for full details, including
what is read from the clipboard, when, and what is stored locally.


OPEN SOURCE AND LICENSES
------------------------

ExileLens is free and open source (MIT). Source code, license information and
security guidance are available in the official GitHub repository:

    https://github.com/arewoz/ExileLens

Please obtain Windows builds only from the official GitHub Releases page.

This folder includes:

    LICENSE                  the ExileLens license (MIT)
    THIRD_PARTY_NOTICES.txt  third-party components and their licenses
    QT_LGPL_COMPLIANCE.txt   Qt/PySide6 (LGPL-3.0): how to replace the Qt
                             libraries, rebuild from source, and the written
                             offer of the Qt source code
    third_party_licenses\    license texts for bundled components
