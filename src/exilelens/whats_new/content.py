"""Packaged, player-facing release summaries.

Qt-free on purpose: it loads and validates ``whats_new.json`` (shipped next to this module), finds the entries
that apply to an installed version and builds the summary the dialog renders. Nothing here reads the network.
Every failure path returns "no notes" instead of raising, so a missing or damaged file can never affect startup.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from exilelens.app.updates.constants import GITHUB_RELEASES_URL
from exilelens.app.updates.version import ExileLensVersion

logger = logging.getLogger(__name__)

CONTENT_FILE = "whats_new.json"
SCHEMA = 1

MAX_HIGHLIGHTS = 4
MAX_MINOR = 6
MAX_LIMITATIONS = 3
MAX_TITLE = 64
MAX_TEXT = 220
MAX_LINK_LABEL = 40

#: In-app places a highlight link may open. Anything else is rejected, so release text cannot navigate elsewhere.
DESTINATIONS = ("overview", "build_analysis", "settings", "updates", "supporter", "diagnostics")

SKIPPED_NOTE = "Several releases were skipped. Full release notes lists every change."

_ID_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


class ContentError(ValueError):
    """The packaged release data is not usable."""


@dataclass(frozen=True)
class Link:
    label: str
    destination: str


@dataclass(frozen=True)
class Highlight:
    id: str
    title: str
    text: str
    introduced: ExileLensVersion
    priority: int = 100
    link: Link | None = None


@dataclass(frozen=True)
class Minor:
    id: str
    text: str
    introduced: ExileLensVersion


@dataclass(frozen=True)
class ActionNote:
    text: str
    link: Link | None = None


@dataclass(frozen=True)
class Release:
    version: ExileLensVersion
    released: date
    previous: ExileLensVersion | None
    highlights: tuple[Highlight, ...] = ()
    minor: tuple[Minor, ...] = ()
    limitations: tuple[Minor, ...] = ()
    action: ActionNote | None = None


@dataclass(frozen=True)
class Catalog:
    releases: tuple[Release, ...]   # newest first

    def get(self, version: ExileLensVersion | None) -> Release | None:
        return next((release for release in self.releases if release.version == version), None)


@dataclass(frozen=True)
class SummaryHighlight:
    id: str
    title: str
    text: str
    link: Link | None
    since: str = ""   # the version it arrived in; only set on a cumulative summary


@dataclass(frozen=True)
class Summary:
    kind: str                       # "release" | "since" | "manual"
    version: ExileLensVersion
    title: str
    meta: str
    highlights: tuple[SummaryHighlight, ...]
    minor: tuple[str, ...]
    limitations: tuple[str, ...]
    action: ActionNote | None = None
    note: str = ""
    github_url: str = ""
    released: date | None = None


# --------------------------------------------------------------------------------------------- parsing
def _version(raw: Any, where: str) -> ExileLensVersion:
    parsed = ExileLensVersion.parse(raw) if isinstance(raw, str) else None
    if parsed is None:
        raise ContentError(f"{where}: invalid version {raw!r}")
    return parsed


def _text(raw: Any, where: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ContentError(f"{where}: expected non-empty text")
    return raw.strip()


def _link(raw: Any, where: str) -> Link | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ContentError(f"{where}: link must be an object or null")
    destination = _text(raw.get("destination"), f"{where}.destination")
    if destination not in DESTINATIONS:
        raise ContentError(f"{where}: destination {destination!r} is not allowed")
    return Link(_text(raw.get("label"), f"{where}.label"), destination)


def _item_id(raw: Any, where: str) -> str:
    if not isinstance(raw, str) or not _ID_RE.fullmatch(raw):
        raise ContentError(f"{where}: invalid id {raw!r}")
    return raw


def _list(raw: Any, where: str) -> list:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ContentError(f"{where}: expected a list")
    return raw


def _object(raw: Any, where: str) -> dict:
    if not isinstance(raw, dict):
        raise ContentError(f"{where}: expected an object")
    return raw


def _release(raw: Any, index: int) -> Release:
    where = f"releases[{index}]"
    data = _object(raw, where)
    version = _version(data.get("version"), f"{where}.version")
    try:
        released = date.fromisoformat(_text(data.get("released"), f"{where}.released"))
    except ValueError as exc:
        raise ContentError(f"{where}.released: not an ISO date") from exc
    previous_raw = data.get("previous")
    previous = None if previous_raw is None else _version(previous_raw, f"{where}.previous")
    highlights = []
    for n, item in enumerate(_list(data.get("highlights"), f"{where}.highlights")):
        spot = f"{where}.highlights[{n}]"
        item = _object(item, spot)
        priority = item.get("priority", 100)
        if isinstance(priority, bool) or not isinstance(priority, int):
            raise ContentError(f"{spot}.priority: expected an integer")
        highlights.append(
            Highlight(
                _item_id(item.get("id"), f"{spot}.id"),
                _text(item.get("title"), f"{spot}.title"),
                _text(item.get("text"), f"{spot}.text"),
                _version(item.get("introduced"), f"{spot}.introduced"),
                priority,
                _link(item.get("link"), f"{spot}.link"),
            )
        )
    def plain(key: str) -> tuple[Minor, ...]:
        rows = []
        for n, item in enumerate(_list(data.get(key), f"{where}.{key}")):
            spot = f"{where}.{key}[{n}]"
            item = _object(item, spot)
            rows.append(
                Minor(
                    _item_id(item.get("id"), f"{spot}.id"),
                    _text(item.get("text"), f"{spot}.text"),
                    _version(item.get("introduced"), f"{spot}.introduced"),
                )
            )
        return tuple(rows)

    action = None
    if data.get("action") is not None:
        spot = f"{where}.action"
        raw_action = _object(data["action"], spot)
        action = ActionNote(_text(raw_action.get("text"), f"{spot}.text"), _link(raw_action.get("link"), f"{spot}.link"))
    return Release(version, released, previous, tuple(highlights), plain("minor"), plain("limitations"), action)


def parse_document(raw: Any) -> Catalog:
    """Validate the structure of a decoded document. Raises :class:`ContentError`."""
    data = _object(raw, "document")
    if data.get("schema") != SCHEMA:
        raise ContentError(f"unsupported schema {data.get('schema')!r}")
    releases = [_release(item, n) for n, item in enumerate(_list(data.get("releases"), "releases"))]
    versions = [release.version for release in releases]
    if len(set(versions)) != len(versions):
        raise ContentError("duplicate release version")
    releases.sort(key=lambda release: release.version, reverse=True)
    return Catalog(tuple(releases))


def content_path() -> Path:
    return Path(__file__).with_name(CONTENT_FILE)


def load_catalog(path: Path | None = None) -> Catalog | None:
    """The packaged catalog, or ``None`` when it is missing or damaged (the feature then stays silent)."""
    target = path or content_path()
    try:
        return parse_document(json.loads(target.read_text(encoding="utf-8")))
    except (OSError, ValueError, UnicodeError, RecursionError) as exc:   # ContentError is a ValueError
        logger.info("whats_new_unavailable reason=%s", type(exc).__name__)
        return None


_cache: dict[str, Catalog | None] = {}


def packaged_catalog() -> Catalog | None:
    """Cached packaged catalog (the file never changes while the app runs)."""
    if "catalog" not in _cache:
        _cache["catalog"] = load_catalog()
    return _cache["catalog"]


def has_notes_for(version: ExileLensVersion | None, catalog: Catalog | None = None) -> bool:
    catalog = catalog if catalog is not None else packaged_catalog()
    return catalog is not None and version is not None and catalog.get(version) is not None


# --------------------------------------------------------------------------------------------- presentation helpers
def github_release_url(version: ExileLensVersion | str) -> str:
    """The GitHub Release page of exactly this version (tags are ``v<version>``)."""
    return f"{GITHUB_RELEASES_URL}/tag/v{version}"


def format_date(value: date) -> str:
    return f"{value.day} {_MONTHS[value.month - 1]} {value.year}"


def _meta(installed: ExileLensVersion, previous: str, action: bool) -> str:
    parts = []
    if not installed.final:
        parts.append("Pre-release build")
    if previous:
        parts.append(previous)
    parts.append("One thing to check" if action else "No action needed")
    return " · ".join(parts)


def _highlight_row(item: Highlight, *, since: str = "") -> SummaryHighlight:
    return SummaryHighlight(item.id, item.title, item.text, item.link, since)


def _ranked(items: list[Highlight]) -> list[Highlight]:
    # Stable: priority first, then the newer arrival, then the authored order.
    return sorted(items, key=lambda item: (item.priority, tuple(-v for v in _sort_key(item.introduced))))


def _sort_key(version: ExileLensVersion) -> tuple[int, int, int, int, int]:
    return (version.major, version.minor, version.patch, int(version.final), version.beta)


# --------------------------------------------------------------------------------------------- summaries
def manual_summary(catalog: Catalog | None, installed: ExileLensVersion | None) -> Summary | None:
    """The installed release's own notes, for reopening later. Never cumulative, never "updated from"."""
    release = catalog.get(installed) if catalog is not None and installed is not None else None
    if release is None:
        return None
    meta = f"Released {format_date(release.released)}"
    if not release.version.final:
        meta += " · Pre-release build"
    return _own_summary(release, "manual", meta)


def _own_summary(release: Release, kind: str, meta: str, *, only_after: ExileLensVersion | None = None, note: str = "") -> Summary:
    def visible(item) -> bool:
        return item.introduced <= release.version and (only_after is None or item.introduced > only_after)

    highlights = [item for item in release.highlights if visible(item)]
    minor = [item for item in release.minor if visible(item)]
    limitations = [item for item in release.limitations if item.introduced <= release.version]
    if only_after is not None and not highlights and not minor:
        # Nothing arrived after the version the player last saw; show the release as written rather than an empty page.
        highlights = [item for item in release.highlights if item.introduced <= release.version]
        minor = [item for item in release.minor if item.introduced <= release.version]
    return Summary(
        kind=kind,
        version=release.version,
        title=f"What's new in ExileLens {release.version}",
        meta=meta,
        highlights=tuple(_highlight_row(item) for item in _ranked(highlights)[:MAX_HIGHLIGHTS]),
        minor=tuple(item.text for item in minor[:MAX_MINOR]),
        limitations=tuple(item.text for item in limitations[:MAX_LIMITATIONS]),
        action=release.action,
        note=note,
        github_url=github_release_url(release.version),
        released=release.released,
    )


def automatic_summary(
    catalog: Catalog | None,
    installed: ExileLensVersion | None,
    last_seen: ExileLensVersion | None,
) -> Summary | None:
    """What to show once after an update, or ``None``.

    ``last_seen`` is the version whose notes the player last dismissed (``None`` for a profile that predates this
    feature: it is shown the installed release without claiming where it came from). Releases skipped in between
    collapse into one "since" summary; when the packaged history cannot prove it covers them all, the installed
    release is shown alone with a short note.
    """
    release = catalog.get(installed) if catalog is not None and installed is not None else None
    if release is None:
        return None
    if last_seen is None:
        return _own_summary(release, "release", _meta(release.version, "", release.action is not None))
    if last_seen >= release.version:
        return None
    chain = _chain(catalog, release, last_seen)
    if chain is None:
        return _own_summary(
            release, "release", _meta(release.version, "", release.action is not None), note=SKIPPED_NOTE
        )
    if len(chain) == 1:
        return _own_summary(
            release,
            "release",
            _meta(release.version, f"Updated from {last_seen}", release.action is not None),
            only_after=last_seen,
        )
    return _since_summary(chain, release, last_seen)


def _chain(catalog: Catalog, installed: Release, last_seen: ExileLensVersion) -> list[Release] | None:
    """Releases after ``last_seen`` up to ``installed`` (newest first), or ``None`` if the history has a gap."""
    chain = [installed]
    current = installed
    while True:
        previous = current.previous
        if previous is None or previous <= last_seen:
            return chain
        step = catalog.get(previous)
        if step is None:
            return None
        chain.append(step)
        current = step


def _since_summary(chain: list[Release], installed: Release, last_seen: ExileLensVersion) -> Summary:
    seen_ids: set[str] = set()
    highlights: list[Highlight] = []
    minor: list[Minor] = []
    for release in chain:   # newest first, so a repeated id keeps its most recent wording
        for item in release.highlights:
            if item.id not in seen_ids and last_seen < item.introduced <= installed.version:
                seen_ids.add(item.id)
                highlights.append(item)
        for entry in release.minor:
            if entry.id not in seen_ids and last_seen < entry.introduced <= installed.version:
                seen_ids.add(entry.id)
                minor.append(entry)
    action = next((release.action for release in chain if release.action is not None), None)
    previous = f"Updated from {last_seen} to {installed.version}"
    return Summary(
        kind="since",
        version=installed.version,
        title=f"What's new since ExileLens {last_seen}",
        meta=_meta(installed.version, previous, action is not None),
        highlights=tuple(_highlight_row(item, since=str(item.introduced)) for item in _ranked(highlights)[:MAX_HIGHLIGHTS]),
        minor=tuple(item.text for item in sorted(minor, key=lambda m: _sort_key(m.introduced), reverse=True)[:MAX_MINOR]),
        limitations=tuple(item.text for item in installed.limitations[:MAX_LIMITATIONS]),
        action=action,
        github_url=github_release_url(installed.version),
        released=installed.released,
    )


# --------------------------------------------------------------------------------------------- release-gate checks
_INTERNAL_PATTERNS = (
    (re.compile(r"\b[RM]\d+(?:\.\d+)?\b"), "internal roadmap code"),
    (re.compile(r"\b[A-Z]{3,}-\d{2,}[A-Za-z]?\b"), "internal ticket or milestone code"),
    (re.compile(r"\bEL-[A-Z0-9-]+\b"), "internal error code"),
    (re.compile(r"\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}\b"), "commit hash"),
    (re.compile(r"[\w./\\-]+\.(?:py|pyc|spec|ps1|lua)\b", re.IGNORECASE), "source file name"),
    (re.compile(r"\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b"), "class-like identifier"),
)
#: Brand and product names that look like identifiers but are ordinary player-facing words.
_NAME_ALLOWLIST = frozenset({"ExileLens", "PayPal", "GitHub", "YouTube", "StormWeaver"})


def _leaks(text: str) -> list[str]:
    found = []
    for pattern, label in _INTERNAL_PATTERNS:
        for match in pattern.finditer(text):
            token = match.group(0)
            if label == "class-like identifier" and token in _NAME_ALLOWLIST:
                continue
            found.append(f"{label} {token!r}")
    return found


def lint_catalog(catalog: Catalog, candidate: ExileLensVersion) -> list[str]:
    """Release-gate problems for ``candidate``: structure, limits and obvious internal wording. Empty means fine."""
    problems: list[str] = []
    release = catalog.get(candidate)
    if release is None:
        return [f"no entry for {candidate}"]
    all_ids: dict[str, str] = {}

    def check_text(where: str, text: str, limit: int) -> None:
        if len(text) > limit:
            problems.append(f"{where}: {len(text)} characters (limit {limit})")
        problems.extend(f"{where}: {leak}" for leak in _leaks(text))

    def check_id(where: str, ident: str) -> None:
        if ident in all_ids:
            problems.append(f"{where}: id {ident!r} already used in {all_ids[ident]}")
        all_ids[ident] = where

    for entry in catalog.releases:
        scope = f"{entry.version}"
        if entry.released > date.today() + timedelta(days=366):
            problems.append(f"{scope}: release date {entry.released} is not plausible")
        if entry.previous is not None and entry.previous >= entry.version:
            problems.append(f"{scope}: previous {entry.previous} is not older than the release")
        for item in (*entry.highlights, *entry.minor, *entry.limitations):
            if item.introduced > entry.version:
                problems.append(f"{scope}/{item.id}: introduced {item.introduced} is newer than its release")
        if entry.version > candidate:
            problems.append(f"{scope}: newer than the candidate {candidate}")

    if len(release.highlights) > MAX_HIGHLIGHTS:
        problems.append(f"{len(release.highlights)} highlights (limit {MAX_HIGHLIGHTS})")
    if len(release.minor) > MAX_MINOR:
        problems.append(f"{len(release.minor)} smaller items (limit {MAX_MINOR})")
    if len(release.limitations) > MAX_LIMITATIONS:
        problems.append(f"{len(release.limitations)} limitations (limit {MAX_LIMITATIONS})")
    for item in release.highlights:
        where = f"highlight {item.id}"
        check_id(where, item.id)
        check_text(f"{where} title", item.title, MAX_TITLE)
        check_text(f"{where} text", item.text, MAX_TEXT)
        if item.link is not None:
            check_text(f"{where} link", item.link.label, MAX_LINK_LABEL)
    for kind, rows in (("smaller item", release.minor), ("limitation", release.limitations)):
        for item in rows:
            check_id(f"{kind} {item.id}", item.id)
            check_text(f"{kind} {item.id}", item.text, MAX_TEXT)
    if release.action is not None:
        check_text("action note", release.action.text, MAX_TEXT)
        if release.action.link is not None:
            check_text("action link", release.action.link.label, MAX_LINK_LABEL)
    return problems
