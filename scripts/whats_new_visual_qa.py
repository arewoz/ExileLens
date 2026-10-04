"""Development tool: render the REAL Qt What's New dialog and its entry points and save PNGs.

Not part of the product. Like ``ui_visual_qa.py`` it builds the production ``DashboardWindow`` against an isolated
profile (a temporary ``LOCALAPPDATA``) and captures native windows with ``PrintWindow``, then composites the dialog
over the dashboard at its real on-screen position. ``--text-scale 1.25`` makes the app read 125 % as the Windows
"Text size" factor through the same ``theme.system_text_scale()`` path the dashboard uses at start-up, without
touching the real Windows setting.

    python scripts/whats_new_visual_qa.py --out artifacts/whats-new-qa
    python scripts/whats_new_visual_qa.py --out artifacts/whats-new-qa --text-scale 1.25 --suffix -125
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

SIZES = {"980x720": (980, 720), "720x560": (720, 560)}


def _hl(ident, title, text, introduced, priority, link=None):
    return {"id": ident, "title": title, "text": text, "introduced": introduced, "priority": priority, "link": link}


def _release(version, previous, highlights, minor=(), limitations=(), action=None, released="2026-10-04"):
    return {
        "version": version, "released": released, "previous": previous, "highlights": highlights,
        "minor": [{"id": f"minor-{i}-{version.replace('.', '')}", "text": t, "introduced": version} for i, t in enumerate(minor)],
        "limitations": [{"id": f"lim-{i}-{version.replace('.', '')}", "text": t, "introduced": version} for i, t in enumerate(limitations)],
        "action": action,
    }


ANALYZE = ("analyze", "Analyze Build is part of the main app",
           "Your strongest measured improvements and next actions now sit beside Overview, Settings and Diagnostics.")
SEAMLESS = ("seamless", "Seamless automatic updates",
            "Patreon supporters can have verified updates downloaded automatically and installed when ExileLens closes. Manual updates stay free.")
REDESIGN = ("redesign", "A redesigned desktop app",
            "Overview, Settings and Diagnostics now show your build and app status at a glance.")
SUPPORT_LINK = {"label": "Learn about supporter updates", "destination": "supporter"}


def _fixtures():
    from exilelens.whats_new import content

    def catalog(*releases):
        return content.parse_document({"schema": 1, "releases": list(releases)})

    stable = catalog(_release(
        "0.7.0", "0.6.0",
        [_hl(*ANALYZE, "0.7.0", 1), _hl(*SEAMLESS, "0.7.0", 2, SUPPORT_LINK), _hl(*REDESIGN, "0.7.0", 3)],
        ["Pre-release versions now show their update status correctly.", "Diagnostics points to a fix for each problem.", "Reliability fixes."]))
    cumulative = catalog(
        _release("0.7.0", "0.6.0",
                 [_hl(*ANALYZE, "0.7.0", 1), _hl(*SEAMLESS, "0.7.0", 2, SUPPORT_LINK), _hl(*REDESIGN, "0.7.0", 3)],
                 ["Pre-release versions show their update status correctly.", "Diagnostics points to a fix for each problem."]),
        _release("0.8.0", "0.7.0",
                 [_hl("verdicts", "Clearer Item Check verdicts", "Uncertain and unsupported results now say why, in plain language.", "0.8.0", 1)],
                 ["Path of Building reconnects faster after it restarts.", "Settings changes apply immediately."]),
    )
    long_release = catalog(_release(
        "0.8.0", "0.7.0",
        [_hl(*ANALYZE, "0.8.0", 1), _hl(*SEAMLESS, "0.8.0", 2, SUPPORT_LINK), _hl(*REDESIGN, "0.8.0", 3),
         _hl("privacy", "Two optional privacy switches",
             "Crash reports and usage stats stay off until you turn them on. Settings shows exactly what would be sent.", "0.8.0", 4,
             {"label": "See what is collected", "destination": "settings"})],
        ["Pre-release versions now show their update status correctly.", "Diagnostics points to a fix for each problem.",
         "Settings changes apply immediately.", "Path of Building reconnects faster after it restarts.",
         "The build name no longer truncates in the status rail.", "Reliability fixes."],
        ["Patreon linking may be unavailable in this beta. Manual updates are not affected."]))
    action = catalog(_release(
        "0.8.0", "0.7.0",
        [_hl(*ANALYZE, "0.8.0", 1), _hl(*SEAMLESS, "0.8.0", 2, SUPPORT_LINK), _hl(*REDESIGN, "0.8.0", 3)],
        ["Pre-release versions now show their update status correctly.", "Diagnostics points to a fix for each problem."],
        action={"text": "This update re-registers the Item Check shortcut. If Shift + C stops working, set it again in Settings.",
                "link": {"label": "Open Settings", "destination": "settings"}}))
    return {"stable": stable, "cumulative": cumulative, "long": long_release, "action": action}


def _composite(harness, dialog, out: Path) -> None:
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QPainter

    from ui_visual_qa import print_window

    main = print_window(int(harness.window.winId()))
    top = print_window(int(dialog.winId()))
    if main is None or top is None:
        main, top = harness.window.grab().toImage(), dialog.grab().toImage()
        origin = dialog.mapTo(harness.window, QPoint(0, 0))
        offset = (origin.x(), origin.y())
    else:
        frame_main, frame_dialog = harness.window.frameGeometry(), dialog.frameGeometry()
        offset = (frame_dialog.x() - frame_main.x(), frame_dialog.y() - frame_main.y())
    painter = QPainter(main)
    painter.drawImage(offset[0], offset[1], top)
    painter.end()
    out.parent.mkdir(parents=True, exist_ok=True)
    main.save(str(out))
    print(out)


def _settle(h, n=40):
    for _ in range(n):
        h.app.processEvents()


def _dialog_scene(h, name, size, out, *, catalog, installed, last_seen, manual=False):
    from exilelens.app.updates.version import ExileLensVersion

    flow = h.window.release_notes
    flow.installed = ExileLensVersion.parse(installed)
    flow._catalog_provider = lambda: catalog
    flow.auto_enabled = True
    h.settings.last_seen_release_notes_version = last_seen
    h.window.resize(*size)
    h.window.move(40, 40)
    h.window.navigate("overview")
    if flow.dialog is not None:
        flow.dialog.close()
    _settle(h)
    if manual:
        flow.show_manual()
    else:
        h.window.hide()
        h.window.show_dashboard()
    for _ in range(3):
        _settle(h)
    dialog = flow.dialog
    if dialog is None:
        print(f"!! {name}: no dialog")
        return
    dialog.repaint()
    h.window.repaint()
    _settle(h)
    _composite(h, dialog, out / f"{name}-{size[0]}x{size[1]}.png")
    dialog.close()
    _settle(h)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="artifacts/whats-new-qa")
    parser.add_argument("--text-scale", type=float, default=1.0)
    parser.add_argument("--suffix", default="")
    args = parser.parse_args(argv)
    out = Path(args.out)

    from exilelens.ui import theme

    if args.text_scale != 1.0:
        theme.system_text_scale = lambda: args.text_scale   # the dashboard reads the factor through this function

    from ui_visual_qa import Harness

    from exilelens.whats_new import content

    fixtures = _fixtures()
    real = content.packaged_catalog()
    with tempfile.TemporaryDirectory(prefix="exilelens-whatsnew-qa-") as tmp:
        h = Harness(Path(tmp))
        h.window.release_notes.settle_seconds = 0.5
        for size_name, size in SIZES.items():
            sfx = args.suffix
            _dialog_scene(h, f"A-stable-0.7.0{sfx}", size, out, catalog=fixtures["stable"], installed="0.7.0", last_seen="0.6.0")
            _dialog_scene(h, f"B-prerelease-0.7.0b1{sfx}", size, out, catalog=real, installed="0.7.0b1", last_seen="0.6.0")
            _dialog_scene(h, f"B2-prerelease-legacy-profile{sfx}", size, out, catalog=real, installed="0.7.0b1", last_seen="")
            _dialog_scene(h, f"C-since-0.6.0{sfx}", size, out, catalog=fixtures["cumulative"], installed="0.8.0", last_seen="0.6.0")
            _dialog_scene(h, f"D-long{sfx}", size, out, catalog=fixtures["long"], installed="0.8.0", last_seen="0.7.0")
            _dialog_scene(h, f"E-action{sfx}", size, out, catalog=fixtures["action"], installed="0.8.0", last_seen="0.7.0")
            _dialog_scene(h, f"F-manual-reopen{sfx}", size, out, catalog=real, installed="0.7.0b1", last_seen="0.7.0b1", manual=True)
            # G: Settings > Updates, with and without packaged notes
            flow = h.window.release_notes
            flow._catalog_provider = lambda: real
            from exilelens.app.updates.version import ExileLensVersion

            flow.installed = ExileLensVersion.parse("0.7.0b1")
            h.window._sync_whats_new_entry()
            h.update("ahead", "0.6.0")
            h.scroll_settings("Updates")
            h.shot(f"G-settings-updates-links{sfx}-{size_name}", size, out, page="settings")
            h.update("available", "0.7.0")
            h.shot(f"G2-settings-updates-available{sfx}-{size_name}", size, out, page="settings")
            h.update("ahead", "0.6.0")
            # H: the rail version at rest, hovered and keyboard-focused
            from PySide6.QtCore import QPoint, Qt
            from PySide6.QtTest import QTest

            h.window.navigate("overview")
            h.shot(f"H1-rail-version-rest{sfx}-{size_name}", size, out)
            button = h.window._rail.version_button()
            if h.window._rail.is_compact():
                print(f"-- H hover/focus skipped at {size_name}: compact rail has no version")
            else:
                QTest.mouseMove(h.window, button.mapTo(h.window, QPoint(button.width() // 2, button.height() // 2)))
                button.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, True)   # the :hover pseudo-state
                button._underline(True)
                button.style().unpolish(button)
                button.style().polish(button)
                button.update()
                h.shot(f"H2-rail-version-hover{sfx}-{size_name}", size, out)
                button.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
                button._underline(False)
                QTest.mouseMove(h.window, QPoint(2, 2))
                button.setFocus(Qt.FocusReason.TabFocusReason)
                h.shot(f"H3-rail-version-focus{sfx}-{size_name}", size, out)
                h.window.setFocus()
            # I: no packaged notes
            flow._catalog_provider = lambda: None
            h.window._sync_whats_new_entry()
            h.update("ahead", "0.6.0")
            h.scroll_settings("Updates")
            h.shot(f"I-no-notes-settings{sfx}-{size_name}", size, out, page="settings")
            h.window.navigate("overview")
            h.shot(f"I2-no-notes-rail{sfx}-{size_name}", size, out)
            flow._catalog_provider = lambda: real
            h.window._sync_whats_new_entry()
        h.controller.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
