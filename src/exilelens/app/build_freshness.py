"""TRUST-01B: one canonical, cheap freshness state for the loaded PoB build.

ExileLens knows only what is on disk and what it loaded. It does NOT know whether the live game
character differs from the PoB build, so nothing here claims the character is outdated:

* strong evidence -- the selected file changed after it was loaded (`DISK_CHANGED`), a reload is in
  flight (`RELOADING`), or the newest revision failed to load and the previous one is in use
  (`USING_LAST_GOOD`);
* advisory only -- the file's modification time is old (`OLD_FILE`). An old file is NOT a confirmed
  stale character.

Pure and stat-only: no XML read, no hashing, no PoB calculation. It never affects score, verdict or
evaluation quality; it is source context.
"""

from __future__ import annotations

import time
from typing import Any

from exilelens.app.build_revision import BuildFileRevision

CURRENT = "CURRENT"
OLD_FILE = "OLD_FILE"
DISK_CHANGED = "DISK_CHANGED"
RELOADING = "RELOADING"
USING_LAST_GOOD = "USING_LAST_GOOD"
UNKNOWN = "UNKNOWN"

SOFT_STALE_AGE_DAYS = 7
SOFT_STALE_AGE_SECONDS = SOFT_STALE_AGE_DAYS * 86400

STRONG_STATES = frozenset({DISK_CHANGED, RELOADING, USING_LAST_GOOD})


def age_text(age_seconds: float | None) -> str:
    """Coarse human age: `today`, `1 day ago`, `9 days ago`."""
    if age_seconds is None:
        return ""
    days = int(max(0.0, age_seconds) // 86400)
    if days <= 0:
        return "today"
    return "1 day ago" if days == 1 else f"{days} days ago"


def _file_age(current: BuildFileRevision | None, now: float) -> tuple[float | None, float | None]:
    """(modified_at, age_seconds); both None when the timestamp is unusable (0, missing, future)."""
    if current is None or current.mtime_ns <= 0:
        return None, None
    modified = current.mtime_ns / 1e9
    age = now - modified
    if age < 0:
        return modified, None  # future timestamp / clock change: never stale
    return modified, age


def _payload(state: str, severity: str, *, modified_at, age, loaded_at, title="", detail="", note="", action="none") -> dict[str, Any]:
    return {
        "state": state,
        "severity": severity,
        "title": title,
        "detail": detail,
        "note": note,
        "file_modified_at": modified_at,
        "age_seconds": age,
        "loaded_at": loaded_at,
        "action": action,
    }


def assess_build_freshness(
    *,
    has_build: bool,
    loaded_revision: BuildFileRevision | None,
    current_revision: BuildFileRevision | None,
    loaded_at: float | None = None,
    reload_in_progress: bool = False,
    reload_failed_kept_previous: bool = False,
    now: float | None = None,
) -> dict[str, Any]:
    """Freshness of the loaded build from cheap facts only (see module docstring)."""
    now = time.time() if now is None else now
    modified_at, age = _file_age(current_revision, now)
    common = {"modified_at": modified_at, "age": age, "loaded_at": loaded_at}
    if not has_build:
        return _payload(UNKNOWN, "info", **common)

    if reload_in_progress:
        return _payload(
            RELOADING, "info", **common,
            title="PoB build is reloading", detail="PoB build changed on disk — reloading…",
        )
    if reload_failed_kept_previous:
        when = time.strftime("%H:%M", time.localtime(loaded_at)) if loaded_at else ""
        return _payload(
            USING_LAST_GOOD, "critical", **common,
            title="Latest PoB build could not be loaded",
            detail="Using the previous working version" + (f" (loaded at {when})." if when else "."),
            note="⚠ Latest PoB build could not be loaded · using the previous version",
            action="reload",
        )
    if loaded_revision is not None and (
        current_revision is None or current_revision.changed_from(loaded_revision)
    ):
        return _payload(
            DISK_CHANGED, "warning", **common,
            title="PoB build changed on disk", detail="PoB build changed on disk — reloading…",
            note="⚠ PoB build changed on disk · reloading", action="reload",
        )
    if age is not None and age >= SOFT_STALE_AGE_SECONDS:
        text = age_text(age)
        return _payload(
            OLD_FILE, "info", **common,
            title="PoB build may be outdated", detail=f"File last modified {text}.",
            note=f"⚠ PoB build may be outdated · last modified {text}", action="reload",
        )
    if current_revision is None:
        return _payload(UNKNOWN, "info", **common)
    return _payload(CURRENT, "ok", **common)
