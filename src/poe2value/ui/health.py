"""Read-only derivation of user-facing health from existing app state.

``EvaluationController.diagnostic_report()`` is a single formatted string, so a health
summary cannot be parsed out of it. This module derives health from the individual
accessors instead. It reads; it never mutates and never calls into the controller's
command surface, so UIUX-01 adds no backend-regression surface.

Vocabulary note -- ``restart_engine()`` restarts *ExileLens's own Path of Building
worker subprocess*; it does not launch the user's Path of Building application, and
ExileLens never checks whether that application is running. So the wording here is
connected / not connected / connecting, describing the ExileLens<->PoB integration,
and never "Path of Building is not running".
"""

from __future__ import annotations

from dataclasses import dataclass, field

OK = "ok"
WARN = "warn"
ERROR = "error"
NEUTRAL = "neutral"

#: Engine states that mean "ExileLens has no working PoB worker right now".
_ENGINE_READY = "ready"
_ENGINE_STARTING = "starting"
_ENGINE_STOPPED = "stopped"


@dataclass(frozen=True)
class HealthItem:
    key: str
    label: str
    value: str
    status: str = NEUTRAL
    detail: str = ""
    #: Short imperative label for the action that fixes this, if any.
    action: str = ""

    @property
    def ok(self) -> bool:
        return self.status == OK


@dataclass(frozen=True)
class AppHealth:
    app: HealthItem
    pob: HealthItem
    build: HealthItem
    hotkey: HealthItem
    market: HealthItem
    elevation: HealthItem | None = None

    def rows(self) -> list[HealthItem]:
        return [self.app, self.pob, self.build, self.hotkey, self.market]

    @property
    def degraded(self) -> bool:
        return any(row.status in (WARN, ERROR) for row in self.rows())

    @property
    def worst_status(self) -> str:
        statuses = [row.status for row in self.rows()]
        for candidate in (ERROR, WARN):
            if candidate in statuses:
                return candidate
        return OK if all(s == OK for s in statuses) else NEUTRAL


def _app_item() -> HealthItem:
    from poe2value._version import __version__

    return HealthItem("app", "ExileLens", __version__, OK)


def _pob_item(controller, settings) -> HealthItem:
    """PoB folder validity first, then the ExileLens worker's state."""
    from poe2value.app.setup_status import check_pob_folder

    folder = check_pob_folder(getattr(settings, "pob_path", "") or "")
    if not folder.ok:
        return HealthItem(
            "pob",
            "Path of Building",
            "Not found",
            ERROR,
            folder.detail or folder.label,
            "Locate Path of Building",
        )

    status = ""
    try:
        status = str(controller.engine_status() or "")
    except Exception:  # noqa: BLE001 - health must never raise into the UI
        status = ""

    if status == _ENGINE_READY:
        try:
            from poe2value.config import detect_pob_identity

            version = detect_pob_identity(getattr(settings, "pob_path", "")).version
        except Exception:  # noqa: BLE001 - identity is informational only
            version = "unknown"
        value = f"Connected · v{version}" if version != "unknown" else "Connected"
        return HealthItem("pob", "Path of Building", value, OK)
    if status == _ENGINE_STARTING:
        return HealthItem("pob", "Path of Building", "Connecting…", WARN)
    if status.startswith("failed:"):
        reason = status.split(":", 1)[1].strip()
        return HealthItem("pob", "Path of Building", "Not connected", ERROR, reason, "Reconnect")
    if status == _ENGINE_STOPPED:
        return HealthItem(
            "pob",
            "Path of Building",
            "Not connected",
            WARN,
            "ExileLens is not connected to Path of Building.",
            "Reconnect",
        )
    return HealthItem("pob", "Path of Building", "Unknown", NEUTRAL)


def loaded_text(controller, status) -> str:
    """Relative load time, or "" when there is genuinely no timestamp.

    The build cache carries ``loaded_at`` once a build has been persisted, but a
    freshly loaded build reports it on the controller first. Prefer the cache and
    fall back, so a running app says "loaded just now" instead of nothing.
    """
    from poe2value.app.build_cache import ActiveBuildStatus

    if status is not None and getattr(status, "loaded_at", 0):
        text = status.last_loaded_text()
        return "" if text == "never" else text
    loaded_at = getattr(controller, "build_loaded_at", None)
    if isinstance(loaded_at, (int, float)) and loaded_at > 0:
        text = ActiveBuildStatus(loaded_at=float(loaded_at)).last_loaded_text()
        return "" if text == "never" else text
    return ""


def _build_item(controller) -> HealthItem:
    from poe2value.app.build_state import BuildState

    try:
        status = controller.active_build_status()
    except Exception:  # noqa: BLE001
        status = None
    info = getattr(controller, "build_info", None)
    path = ""
    if status is not None:
        path = status.build_path or ""
    if not path and info is not None:
        path = info.path or ""

    if not path:
        return HealthItem(
            "build",
            "Build",
            "Not selected",
            WARN,
            "Choose the Path of Building .xml you play.",
            "Choose build",
        )

    name = ""
    if status is not None:
        name = status.display_name or ""
    if not name and info is not None:
        name = info.name or ""
    if not name:
        from pathlib import Path

        name = Path(path).stem
    engine_state = getattr(status, "engine_state", "") if status is not None else ""
    state = getattr(info, "state", None)

    if engine_state == BuildState.FAILED.value or state == BuildState.FAILED:
        reason = ""
        if status is not None:
            reason = status.last_error or ""
        if not reason and info is not None:
            reason = info.error_message or ""
        return HealthItem("build", "Build", "Failed to load", ERROR, reason, "Choose another build")
    if engine_state in (BuildState.LOADING.value, BuildState.RELOADING.value) or state in (
        BuildState.LOADING,
        BuildState.RELOADING,
    ):
        return HealthItem("build", "Build", f"{name} · loading…", WARN)

    freshness = getattr(status, "freshness", "") if status is not None else ""
    if freshness == "REFRESH_FAILED":
        return HealthItem(
            "build", "Build", name, WARN, "Reload failed — using previous build metadata.", "Refresh"
        )
    if freshness == "CHANGED_ON_DISK":
        return HealthItem("build", "Build", name, WARN, "The build file changed on disk.", "Refresh")
    if freshness == "REFRESHING":
        return HealthItem("build", "Build", f"{name} · refreshing…", WARN)

    loaded = loaded_text(controller, status)
    # No timestamp -> omit the clause entirely rather than render "loaded never".
    value = f"{name} · loaded {loaded}" if loaded else name
    if state == BuildState.READY:
        return HealthItem("build", "Build", value, OK)
    return HealthItem("build", "Build", f"{name} · not loaded", WARN, "", "Refresh")


def hotkey_display(settings) -> str:
    """The currently configured Item Check chord, formatted for display."""
    from poe2value.platform.windows.hotkey_binding import HotkeyBinding

    raw = getattr(settings, "price_check_hotkey", "") or ""
    try:
        return HotkeyBinding.parse(raw).display
    except Exception:  # noqa: BLE001 - never let a bad stored chord break the UI
        return raw or "—"


def _hotkey_item(controller, settings) -> HealthItem:
    display = hotkey_display(settings)
    hotkey = getattr(controller, "price_check_hotkey", None)
    if hotkey is None:
        return HealthItem("hotkey", "Item check hotkey", display, NEUTRAL)

    install_error = ""
    hook = getattr(hotkey, "hook", None)
    if hook is not None:
        install_error = str(getattr(hook, "install_error", "") or "")
    registered = bool(getattr(hotkey, "hook_registered", False))

    if install_error:
        return HealthItem(
            "hotkey", "Item check hotkey", "Unavailable", ERROR, install_error, "Open Diagnostics"
        )
    if not registered:
        return HealthItem(
            "hotkey",
            "Item check hotkey",
            "Not active",
            WARN,
            "ExileLens is not listening for the Item Check shortcut.",
            "Open Diagnostics",
        )
    return HealthItem("hotkey", "Item check hotkey", f"{display} · active", OK)


def _market_item(settings) -> HealthItem:
    """Reports the configured mode only.

    ``resolve_live_market_mode`` does not probe reachability, so this must never
    render a green "Available" tick that implies a successful connection check.
    """
    try:
        from poe2value.price_check.market_policy import resolve_live_market_mode

        # Takes the mode string, not the settings object: passing the dataclass
        # stringifies to a repr that never matches "disabled", so the row silently
        # read "Live" even when the user had switched live market off.
        mode = str(resolve_live_market_mode(getattr(settings, "live_market_mode", None)) or "auto")
    except Exception:  # noqa: BLE001
        return HealthItem("market", "Market", "Unknown", NEUTRAL)
    if mode == "disabled":
        return HealthItem("market", "Market", "Disabled", NEUTRAL)
    return HealthItem("market", "Market", "Live", NEUTRAL, "Availability is checked per lookup.")


def _elevation_item() -> HealthItem | None:
    try:
        from poe2value.platform.windows.elevation import evaluate_elevation_status

        elevation = evaluate_elevation_status()
    except Exception:  # noqa: BLE001
        return None
    detail = str(getattr(elevation, "detail", "") or "")
    if getattr(elevation, "mismatch", False):
        return HealthItem("elevation", "Hotkey access", "Needs attention", WARN, detail)
    if not detail:
        return None
    return HealthItem("elevation", "Hotkey access", detail, OK)


def derive_health(controller, settings) -> AppHealth:
    """Derive the full health summary. Pure read; never raises."""
    return AppHealth(
        app=_app_item(),
        pob=_pob_item(controller, settings),
        build=_build_item(controller),
        hotkey=_hotkey_item(controller, settings),
        market=_market_item(settings),
        elevation=_elevation_item(),
    )


def header_status(health: AppHealth) -> tuple[str, str]:
    """Collapse health into the one global status the app header shows.

    PoB connectivity is the single global fact worth a permanent slot; everything
    else is contextual and belongs to a page.
    """
    pob = health.pob
    if pob.status == OK:
        suffix = pob.value.removeprefix("Connected").strip()
        return f"PoB connected {suffix}".rstrip(), OK
    if pob.value == "Not found":
        return "PoB not found", ERROR
    if pob.value.startswith("Connecting"):
        return "PoB connecting…", WARN
    if pob.status == ERROR:
        return "PoB not connected", ERROR
    if pob.status == WARN:
        return "PoB not connected", WARN
    return "PoB unknown", NEUTRAL
