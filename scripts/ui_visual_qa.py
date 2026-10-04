"""Development tool: render the REAL Qt dashboard in deterministic states and save PNGs.

Not part of the product and not exposed in the UI. It builds the production
``DashboardWindow`` against an isolated profile (a temporary ``LOCALAPPDATA``), substitutes
only the *read-only inputs* (``derive_health`` and the controller's build accessors, the
update service state, the Patreon view) and grabs the window. Nothing is mutated in a real
profile and nothing touches the network.

Usage (from the repo root, with the project Python):

    python scripts/ui_visual_qa.py --out artifacts/ui-qa --states overview-ready settings-top
    python scripts/ui_visual_qa.py --out artifacts/ui-qa --all
    python scripts/ui_visual_qa.py --list

Screenshots are taken with the native frame included (``--frame``, default) by grabbing
the screen rectangle of the window, so the real Windows dark title bar is visible; use
``--no-frame`` for a client-area grab that works when the window is partly obscured.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))  # the QA fixtures reuse the analysis fixtures from tests/

SIZES = {
    "980x720": (980, 720),
    "980x900": (980, 900),
    "840x640": (840, 640),
    "720x560": (720, 560),
}


def _health(**over):
    from exilelens.ui.health import AppHealth, HealthItem

    items = {
        "app": HealthItem("app", "ExileLens", "0.7.0b1", "ok"),
        "pob": HealthItem("pob", "Path of Building", "Connected · v0.23.1", "ok"),
        "build": HealthItem("build", "Build", "Spark Stormweaver · loaded 3 min ago", "ok"),
        "hotkey": HealthItem("hotkey", "Item check hotkey", "Shift + C · active", "ok"),
        "market": HealthItem("market", "Market", "Live", "neutral", "Availability is checked per lookup."),
    }
    items.update(over)
    return AppHealth(items["app"], items["pob"], items["build"], items["hotkey"], items["market"], over.get("elevation"))


def health_for(state: str):
    from exilelens.ui.health import HealthItem

    if state == "ready":
        return _health()
    if state == "setup":
        return _health(build=HealthItem("build", "Build", "Not selected", "warn", "Choose the Path of Building .xml you play.", "Choose build"))
    if state == "pob-missing":
        return _health(pob=HealthItem("pob", "Path of Building", "Not found", "error", "Choose your Path of Building installation folder.", "Locate Path of Building"))
    if state == "connecting":
        return _health(pob=HealthItem("pob", "Path of Building", "Connecting…", "warn"))
    if state == "disconnected":
        return _health(
            pob=HealthItem("pob", "Path of Building", "Not connected", "error", "The Path of Building worker stopped.", "Reconnect"),
            build=HealthItem("build", "Build", "Spark Stormweaver · not loaded", "warn", "", "Refresh"),
            hotkey=HealthItem("hotkey", "Item check hotkey", "Not active", "warn", "ExileLens is not listening for the Item Check shortcut.", "Open Diagnostics"),
        )
    if state == "attention":
        return _health(
            build=HealthItem("build", "Build", "Spark Stormweaver", "warn", "The build file changed on disk.", "Refresh"),
            hotkey=HealthItem("hotkey", "Item check hotkey", "Not active", "warn", "ExileLens is not listening for the Item Check shortcut.", "Open Diagnostics"),
        )
    if state == "build-failed":
        return _health(build=HealthItem("build", "Build", "Failed to load", "error", "The file is not a valid Path of Building export.", "Choose another build"))
    raise KeyError(state)


def print_window(hwnd: int):
    """Capture a top-level window INCLUDING its native frame, even when other windows cover it.

    Uses ``PrintWindow(..., PW_RENDERFULLCONTENT)`` (DWM renders the window itself), then
    converts the DIB to a QImage. Returns None when anything fails.
    """
    try:
        import ctypes
        from ctypes import wintypes

        from PySide6.QtGui import QImage

        user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        width, height = rect.right - rect.left, rect.bottom - rect.top
        hdc = user32.GetWindowDC(hwnd)
        mem = gdi32.CreateCompatibleDC(hdc)
        bmp = gdi32.CreateCompatibleBitmap(hdc, width, height)
        gdi32.SelectObject(mem, bmp)
        user32.PrintWindow(hwnd, mem, 2)

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
                        ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]

        info = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
        buffer = ctypes.create_string_buffer(width * height * 4)
        gdi32.GetDIBits(mem, bmp, 0, height, buffer, ctypes.byref(info), 0)
        image = QImage(buffer.raw, width, height, QImage.Format.Format_ARGB32).copy()
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem)
        user32.ReleaseDC(hwnd, hdc)
        return image.convertToFormat(QImage.Format.Format_RGB32)
    except Exception:  # noqa: BLE001
        return None


class FakePatreon:
    """Read-only stand-in for the Patreon link: only ``view()`` and listeners, no network."""

    def __init__(self) -> None:
        from exilelens.cloud.patreon import PatreonState

        self.PatreonState = PatreonState
        self.state = PatreonState.NOT_CONNECTED
        self.expires_at = None
        self.detail = ""
        self._listeners: list = []

    def available(self) -> bool:
        return True

    def add_listener(self, listener) -> None:
        self._listeners.append(listener)

    def view(self):
        from exilelens.cloud.patreon import PatreonView

        caps = frozenset({"seamless_updates"}) if self.state in (self.PatreonState.ACTIVE, self.PatreonState.OFFLINE_GRACE) else frozenset()
        return PatreonView(self.state, capabilities=caps, expires_at=self.expires_at, detail=self.detail)

    def set(self, state, *, expires_at=None, detail="") -> None:
        self.state, self.expires_at, self.detail = state, expires_at, detail
        for listener in list(self._listeners):
            listener(self.view())

    def start_link(self) -> None: ...
    def cancel_link(self) -> None: ...
    def refresh(self) -> None: ...
    def unlink(self) -> None: ...


class FakeCloud:
    """Stand-in for ``CloudServices`` so Privacy and Patreon render without an endpoint or network."""

    def __init__(self) -> None:
        self.patreon = FakePatreon()

    def configured(self) -> bool:
        return True

    def status(self) -> dict:
        idle = {"active": False, "queued": 0, "disabled": False, "last_attempt": 0}
        return {"endpoint_configured": True, "usage": dict(idle), "errors": dict(idle), "previous_session": ""}

    def apply_consent(self) -> None: ...


class Harness:
    def __init__(self, profile: Path, text_scale: float = 1.0) -> None:
        os.environ["LOCALAPPDATA"] = str(profile)
        from PySide6.QtWidgets import QApplication

        from exilelens.cloud import hooks

        self.cloud = FakeCloud()
        hooks.register(self.cloud)

        self.app = QApplication.instance() or QApplication([])
        from exilelens.app.build_state import BuildInfo, BuildState
        from exilelens.app.controller import EvaluationController
        from exilelens.app.settings import AppSettings

        self.BuildInfo, self.BuildState = BuildInfo, BuildState
        self.settings = AppSettings()
        self.settings.pob_path = r"C:\PoB2\Path of Building Community (PoE2)"
        self.settings.build_path = r"C:\PoB2\Builds\Spark_Stormweaver_v3.xml"
        self.settings.privacy_card_resolved = True  # the one-time consent card is shown only when a state asks for it
        from exilelens.app.settings import ONBOARDING_VERSION

        self.settings.onboarding_version_completed = ONBOARDING_VERSION
        self.controller = EvaluationController(self.settings)
        from exilelens.ui.dashboard_window import DashboardWindow

        self.window = DashboardWindow(self.settings, self.controller)
        if text_scale != 1.0:
            # Text-only scaling (Windows "Text size"): grow every pixel font in the sheet, leave geometry alone.
            import re

            self.window.setStyleSheet(
                re.sub(r"font-size:\s*(\d+(?:\.\d+)?)px", lambda m: f"font-size: {round(float(m.group(1)) * text_scale)}px", self.window.styleSheet())
            )
            font = self.app.font()
            font.setPointSizeF(font.pointSizeF() * text_scale)
            self.app.setFont(font)
        self.window.show_dashboard()
        self.state = "ready"
        self.set_state("ready")

    # --- state ------------------------------------------------------------------------------
    def set_state(self, state: str, *, build: bool | None = None) -> None:
        import exilelens.ui.health as health_mod

        self.state = state
        health = health_for(state)
        health_mod.derive_health = lambda controller, settings, _h=health: _h  # type: ignore[assignment]
        has_build = (state not in ("setup",)) if build is None else build
        path = r"C:\PoB2\Builds\Spark_Stormweaver_v3.xml" if has_build else ""
        status = SimpleNamespace(
            build_path=path,
            display_name="Spark Stormweaver" if has_build else "",
            loaded_at=1.0,
            last_loaded_text=lambda: "3 min ago",
            engine_state="READY",
            freshness="CURRENT",
            last_error="",
        )
        self.controller.active_build_status = lambda: status  # type: ignore[method-assign]
        self.controller.build_info = self.BuildInfo(
            path=path, name="Spark Stormweaver" if has_build else "",
            state=self.BuildState.READY if has_build else self.BuildState.NO_BUILD,
        )
        self.refresh()

    # --- supporter / update / privacy inputs ---------------------------------------------------
    def patreon(self, state_name: str, **kw) -> None:
        from exilelens.cloud.patreon import PatreonState

        self.cloud.patreon.set(PatreonState(state_name), **kw)
        self.app.processEvents()

    def update(self, state: str, version: str = "", *, download: str | None = None, percent: int | None = None) -> None:
        service = self.window.update_service
        service.download_state_changed.emit("")  # every update state starts without a download in flight
        service.state_changed.emit(state, version)
        if download is not None:
            service.download_state_changed.emit(download)
        if percent is not None:
            service.download_progress.emit(percent, 100)
        self.app.processEvents()

    def consent_card(self, show: bool) -> None:
        self.settings.privacy_card_resolved = not show
        self.window._overview._consent_card = None
        self.window._overview.refresh()

    def scroll_settings(self, title: str | None) -> None:
        from exilelens.ui.dashboard_widgets import SettingsSection

        page = self.window._settings_page
        self.app.processEvents()
        bar = page.scroll.verticalScrollBar()
        if title is None:
            bar.setValue(0)
        elif title == "__bottom__":
            bar.setValue(bar.maximum())
        else:
            for section in page.findChildren(SettingsSection):
                if section.title() == title:
                    bar.setValue(max(0, section.mapTo(page.scroll.widget(), section.rect().topLeft()).y() - 8))
        self.app.processEvents()

    def refresh(self) -> None:
        self.window._rail.refresh()
        self.window._overview.refresh()
        self.window._diagnostics.refresh()
        self.app.processEvents()

    # --- rendering ----------------------------------------------------------------------------
    def shot(self, name: str, size: tuple[int, int], out: Path, *, frame: bool = True, page: str | None = None) -> Path:
        from PySide6.QtCore import QTimer

        if page:
            self.window.navigate(page)
        self.window.resize(*size)
        self.window.move(40, 40)
        for _ in range(30):  # height-for-width settles over several layout passes
            self.app.processEvents()
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"{name}.png"
        # PrintWindow reads the window's backing store, which can still hold a frame painted before the final layout
        # (the widget tree is already correct). Repaint first so the capture matches the tree.
        self.window.repaint()
        self.app.processEvents()
        image = print_window(int(self.window.winId())) if frame else None
        if image is None or image.isNull():
            image = self.window.grab().toImage()
        image.save(str(path))
        return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="artifacts/ui-qa")
    parser.add_argument("--states", nargs="*", default=["overview-ready"])
    parser.add_argument("--sizes", nargs="*", default=["980x720"])
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--no-frame", action="store_true")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--text-scale", type=float, default=1.0)
    parser.add_argument("--suffix", default="")
    args = parser.parse_args(argv)

    from qa_states import STATE_REGISTRY  # type: ignore[import-not-found]

    if args.list:
        print("\n".join(sorted(STATE_REGISTRY)))
        return 0
    names = sorted(STATE_REGISTRY) if args.all else args.states
    with tempfile.TemporaryDirectory(prefix="exilelens-ui-qa-") as tmp:
        harness = Harness(Path(tmp), args.text_scale)
        for name in names:
            builder = STATE_REGISTRY[name]
            builder(harness)
            for size_name in args.sizes:
                path = harness.shot(f"{name}-{size_name}{args.suffix}", SIZES[size_name], Path(args.out), frame=not args.no_frame)
                print(path)
        harness.controller.shutdown()
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(main())
