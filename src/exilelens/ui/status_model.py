"""One shared derivation of the application's global status.

The Status Rail, Overview and Diagnostics all read from here (which in turn reads the
existing :func:`exilelens.ui.health.derive_health`), so they can never contradict each
other. Pure read; never raises into the UI.

``key`` values, in priority order of what is wrong:

* ``setup``         Path of Building not found, or no build selected
* ``connecting``    the Path of Building worker is starting
* ``disconnected``  the worker is not connected
* ``attention``     the build failed or changed, or the Item Check hotkey is not active
* ``loading``       the build is loading
* ``ready``         everything the product needs is working
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from exilelens.ui import health as _health
from exilelens.ui.health import AppHealth, HealthItem, header_status

READY = "ready"
SETUP = "setup"
CONNECTING = "connecting"
DISCONNECTED = "disconnected"
ATTENTION = "attention"
LOADING = "loading"

#: key -> (rail/page status word, status tone for the dot and word)
_WORDS = {
    READY: ("Ready", "ok"),
    SETUP: ("Setup needed", "warn"),
    CONNECTING: ("Connecting…", "neutral"),
    DISCONNECTED: ("Not connected", "error"),
    ATTENTION: ("Needs attention", "warn"),
    LOADING: ("Loading…", "neutral"),
}

NO_BUILD_NAME = "No build selected"


@dataclass(frozen=True)
class AppStatus:
    key: str
    label: str
    tone: str
    build_name: str
    pob_line: str
    attention_count: int
    health: AppHealth

    @property
    def needs_action(self) -> bool:
        """True when the page should repeat the state: the user has something to do."""
        return self.key not in (READY, LOADING, CONNECTING)

    @property
    def build_selected(self) -> bool:
        return self.build_name != NO_BUILD_NAME


def attention_rows(health: AppHealth) -> list[HealthItem]:
    """Rows that need action: warn or error. Neutral rows (Market) never count."""
    rows = [row for row in health.rows() if row.status in ("warn", "error")]
    if health.elevation is not None and health.elevation.status in ("warn", "error"):
        rows.append(health.elevation)
    return rows


def classify(health: AppHealth) -> str:
    pob, build, hotkey = health.pob, health.build, health.hotkey
    if pob.value == "Not found":
        return SETUP
    if pob.value.startswith("Connecting"):
        return CONNECTING
    if pob.status in ("error", "warn"):
        return DISCONNECTED
    if build.value == "Not selected":
        return SETUP
    if build.status == "error":
        return ATTENTION
    if "loading" in build.value or "refreshing" in build.value:
        return LOADING
    if build.status == "warn":
        return ATTENTION
    if hotkey.status in ("warn", "error"):
        return ATTENTION
    return READY


def current_build_name(controller) -> str:
    """The build's display name, or ``NO_BUILD_NAME``. Uses only data the controller already has."""
    try:
        status = controller.active_build_status()
    except Exception:  # noqa: BLE001 - never raise into the UI
        status = None
    info = getattr(controller, "build_info", None)
    path = ""
    if status is not None:
        path = getattr(status, "build_path", "") or ""
    if not path and info is not None:
        path = getattr(info, "path", "") or ""
    if not path:
        return NO_BUILD_NAME
    name = ""
    if status is not None:
        name = getattr(status, "display_name", "") or ""
    if not name and info is not None:
        name = getattr(info, "name", "") or ""
    return name or Path(path).stem


def derive_status(controller, settings) -> AppStatus:
    health = _health.derive_health(controller, settings)  # module attribute: tests and the QA harness may substitute it
    key = classify(health)
    word, tone = _WORDS[key]
    if key == ATTENTION and health.build.status == "error":
        tone = "error"
    pob_line, _pob_status = header_status(health)
    return AppStatus(
        key=key,
        label=word,
        tone=tone,
        build_name=current_build_name(controller),
        pob_line=pob_line,
        attention_count=len(attention_rows(health)),
        health=health,
    )
