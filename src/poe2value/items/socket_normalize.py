"""Strip modifier lines contributed by socketed items (runes, soul cores).

PoB's item text marks a socket's own header (``Sockets:``, ``Rune: <name>``)
separately from the modifier lines it grants. A rune/soul-core-granted line
carries explicit markup PoB itself writes -- ``{rune}``/``{soulcore}`` prefix
markup (exported/fixture text) or a trailing ``(rune)``/``(soul core)`` tag
(live client clipboard text) -- and a guaranteed "Bonded:" line uses the same
markup plus a ``Bonded:`` prefix. This is the same provenance PoB assigns the
mod; nothing here is guessed from wording or numeric similarity.

Exported/fixture text additionally counts rune-granted lines inside the
leading ``Implicits: N`` header alongside real implicits, so removing one
requires decrementing that header by the number removed -- real implicits
immediately after are otherwise miscounted as missing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_IMPLICITS_RE = re.compile(r"^Implicits:\s*(\d+)", re.I)
_RUNE_MARKUP_RE = re.compile(r"\{(?:rune|soulcore)\}", re.I)
_RUNE_TAG_RE = re.compile(r"\((?:rune|soul\s*core)\)\s*$", re.I)
_BONDED_PREFIX_RE = re.compile(r"^(?:\{[a-z]+\})*\s*bonded\s*:", re.I)
_BONDED_TAG_RE = re.compile(r"\(bonded\)\s*$", re.I)


def _is_socketed_line(stripped_line: str) -> bool:
    return bool(
        _RUNE_MARKUP_RE.search(stripped_line)
        or _RUNE_TAG_RE.search(stripped_line)
        or _BONDED_PREFIX_RE.search(stripped_line)
        or _BONDED_TAG_RE.search(stripped_line)
    )


@dataclass(frozen=True)
class SocketNormalizationResult:
    """Result of stripping socketed-item modifiers from one item's raw text."""

    text: str
    changed: bool
    removed_lines: tuple[str, ...] = ()


def strip_socketed_modifiers(raw_text: str) -> SocketNormalizationResult:
    """Remove modifier lines a socketed rune/soul core contributed.

    Leaves the ``Sockets:``/``Rune:`` header lines (socket count and identity)
    untouched, and never removes an implicit, explicit, crafted, fractured or
    desecrated modifier, quality, or any base stat line -- only lines PoB's
    own markup identifies as coming from a socketable.
    """
    text = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    out: list[str] = []
    removed: list[str] = []

    implicit_remaining = 0
    implicits_original_count = 0
    implicits_removed = 0
    implicits_out_index: int | None = None
    implicits_original_line = ""

    def _rewrite_implicits_header() -> None:
        if implicits_out_index is None:
            return
        new_count = max(0, implicits_original_count - implicits_removed)
        out[implicits_out_index] = _IMPLICITS_RE.sub(
            f"Implicits: {new_count}", implicits_original_line, count=1,
        )

    for line in lines:
        stripped = line.strip()
        implicits_match = _IMPLICITS_RE.match(stripped) if stripped else None
        if implicits_match:
            implicit_remaining = int(implicits_match.group(1))
            implicits_original_count = implicit_remaining
            implicits_removed = 0
            implicits_original_line = line
            implicits_out_index = len(out)
            out.append(line)
            continue

        in_implicit_region = implicit_remaining > 0
        if stripped and _is_socketed_line(stripped):
            removed.append(stripped)
            if in_implicit_region:
                implicit_remaining -= 1
                implicits_removed += 1
                _rewrite_implicits_header()
            continue

        if in_implicit_region:
            implicit_remaining -= 1
        out.append(line)

    if not removed:
        return SocketNormalizationResult(text=raw_text, changed=False, removed_lines=())
    return SocketNormalizationResult(text="\n".join(out), changed=True, removed_lines=tuple(removed))
