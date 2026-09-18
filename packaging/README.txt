EXILELENS 0.2.0b2 BETA
=======================

Build-aware item analysis for Path of Exile 2.

ExileLens answers one question:

    "Is this item actually better for my build?"

It evaluates hovered items against your selected Path of Building for Path of Exile 2 build and shows an upgrade / downgrade verdict in an overlay.

This is an early beta. Bugs, unsupported mechanics and occasional incorrect evaluations are expected.


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

The usual installation folder is:

    %APPDATA%\Path of Building Community (PoE2)

Select the folder containing Path of Building-PoE2.exe, Launch.lua,
lua51.dll, Data, and Modules. A Git checkout is not required.

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


CURRENT BETA FEATURES
---------------------

- Value for My Build
- Upgrade / downgrade verdicts
- Comparison against equipped PoB gear
- Ring 1 / Ring 2 comparison
- Offensive, defensive and utility impact
- Resistance cap / buffer awareness
- More Info analysis
- Partial / unsupported mechanic warnings
- Up to 4 pinned comparisons
- Balanced / Mapping / Bossing / Defensive profiles
- Loadout / Gear Set selection
- Diagnostics

Supported equipment:
Helmet, Body Armour, Gloves, Boots, Belt, Ring, Amulet,
1H/2H weapons and Offhand/Focus.

Jewels are currently unsupported.


MARKET PRICING
--------------

Live market pricing is NOT part of the normal Shift+C flow in this beta.

The main purpose of this release is:

    VALUE FOR MY BUILD


KNOWN LIMITATIONS
-----------------

- Jewels are unsupported.
- Some PoE2 mechanics may not be fully modeled by PoB or ExileLens.
- Some results may therefore be partial.
- Your PoB build is the comparison baseline, not automatically your live in-game gear.
- The first analysis after launch may be slower while the PoB worker starts.
- Some multi-monitor / DPI setups may still have UI issues.


TROUBLESHOOTING
---------------

Overlay does not appear:
- Make sure ExileLens is running in the system tray.
- Make sure PoE2 is in the foreground.
- Make sure a valid item tooltip is visible.
- Try Shift+C again.

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
- Please report suspicious results.


WINDOWS SMARTSCREEN
-------------------

Current beta builds are not digitally signed.

Windows may show:

    Windows protected your PC

If you downloaded ExileLens from the official beta page:

    More info -> Run anyway


BUG REPORTS
-----------

Main log:

    %LOCALAPPDATA%\poe2-value-overlay\logs\poe2value.log

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

ExileLens currently has no analytics / telemetry system.

Optional functionality (live market pricing) may contact the official
Path of Exile trade site for league data and trade search results.

See PRIVACY.md in the project repository for full details, including
what is read from the clipboard, when, and what is stored locally.


OPEN SOURCE
-----------

ExileLens is free and open source. Source code, license information and
security guidance are available in the official GitHub repository. Please
obtain Windows builds only from the official GitHub Releases page.


DISCLAIMER
----------

ExileLens is an unofficial community project and is not affiliated with or
endorsed by Grinding Gear Games or the Path of Building project.

Path of Exile and Path of Exile 2 are trademarks of Grinding Gear Games.
