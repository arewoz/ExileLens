"""When the release summary is due, and when it must wait. Qt-free, so the rules are tested without a window.

The rules in one place:

* A fresh install never sees it: :func:`record_fresh_install` stores the running version as already seen.
* An existing profile with no stored version (it predates this feature) is shown the installed release once.
* A newer installed version than the stored one is shown once; the same or an older version never is.
* The summary is marked seen only when the player dismisses it (:func:`mark_seen`), never because it was shown.
"""

from __future__ import annotations

import logging
from typing import Callable

from exilelens.app.updates.version import ExileLensVersion
from exilelens.ui import status_model
from exilelens.whats_new.content import Catalog, Summary, automatic_summary

logger = logging.getLogger(__name__)

SHOW = "show"
WAIT = "wait"      # Connecting / Loading: give the existing state signals a few seconds to settle
DEFER = "defer"    # something needs the player first: try again the next time they open the dashboard

#: How long a transient state may keep the summary waiting before it is deferred to the next dashboard open.
SETTLE_SECONDS = 5.0


def record_fresh_install(settings, installed: ExileLensVersion | None, *, loaded_from_disk: bool, load_error: bool = False) -> bool:
    """Mark the running version as seen on a profile that did not exist yet (or could not be read).

    Returns True when the value was recorded. It stays in memory until the next normal settings save, which is
    safe: until then the settings file does not exist either, so the next launch is still "fresh".
    """
    if installed is None or (loaded_from_disk and not load_error):
        return False
    if str(getattr(settings, "last_seen_release_notes_version", "") or "").strip():
        return False
    settings.last_seen_release_notes_version = str(installed)
    return True


def evaluate(settings, installed: ExileLensVersion | None, catalog: Catalog | None) -> Summary | None:
    """The summary to show automatically, or ``None`` (same version, downgrade, or no packaged notes)."""
    if installed is None or catalog is None:
        return None
    last_seen = ExileLensVersion.parse(getattr(settings, "last_seen_release_notes_version", "") or "")
    return automatic_summary(catalog, installed, last_seen)


def mark_seen(settings, installed: ExileLensVersion | None, save: Callable[[object], None]) -> bool:
    """Persist ``installed`` as the last dismissed version. Never lowers an already newer stored version."""
    if installed is None:
        return False
    stored = ExileLensVersion.parse(getattr(settings, "last_seen_release_notes_version", "") or "")
    if stored is not None and stored >= installed:
        return False
    settings.last_seen_release_notes_version = str(installed)
    try:
        save(settings)
    except Exception:  # noqa: BLE001 - a failed write must not trap the player in the dialog
        logger.exception("whats_new_mark_seen_failed")
        return False
    return True


def gate(status: status_model.AppStatus | None) -> str:
    """Whether the application's current state allows the summary now.

    Allowed: Ready, and the orange "Needs attention" states that are not a failure (build file changed, hotkey not
    active). Deferred: anything the player has to fix first (PoB missing, no build, not connected, build failed).
    The one-time privacy card is not a blocker: it stays behind the dialog.
    """
    if status is None:
        return WAIT
    key = status.key
    if key == status_model.READY:
        return SHOW
    if key in (status_model.CONNECTING, status_model.LOADING):
        return WAIT
    if key == status_model.ATTENTION:
        build = getattr(status.health, "build", None)
        return DEFER if getattr(build, "status", "") == "error" else SHOW
    return DEFER   # setup, disconnected
