"""MARKET-03 — recover the affix tier range the game already prints on every roll.

The live game's *Advanced Item Description* annotates each rolled explicit with the
range of the tier that mod rolled on::

    +89(85-99) to maximum Life
    76(68-79)% increased Energy Shield
    38(36-40)% reduced Freeze Duration on you

Until MARKET-03 that annotation was deleted by
:func:`exilelens.price_check.comparable_features.strip_value_ranges` before anything
could read it, so every search floor had to be guessed from a hand-written global
affix range. This module reads it instead.

Coverage is *opportunistic*, and callers must treat that as normal rather than
exceptional:

* live-clipboard explicit mods carry a range;
* implicits, rune-granted mods and some fixed-value mods (movement speed on boots has
  been observed unannotated) carry none;
* PoB-exported corpus items carry none at all.

Everything here returns ``None`` rather than a fabricated range when the game did not
print one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: ``<value>(<low>-<high>)``. The value is attached to the left of the parenthesis, so
#: the same expression captures the roll and its tier bounds together. Negative bounds
#: are printed with a bare ``-`` separator (``-40--36``); the digit runs are greedy, so
#: the separator is the first ``-`` that follows a complete number.
_ANNOTATED_VALUE_RE = re.compile(
    r"(?<![\d.])([+-]?\d+(?:\.\d+)?)"
    r"\(\s*([+-]?\d+(?:\.\d+)?)\s*-\s*([+-]?\d+(?:\.\d+)?)\s*\)"
)


@dataclass(frozen=True)
class TierRange:
    """One rolled value and the bounds of the tier it rolled on.

    ``low``/``high`` are the tier's own bounds, not the family's global affix range.
    """

    value: float
    low: float
    high: float

    @property
    def span(self) -> float:
        return self.high - self.low

    @property
    def percentile(self) -> float:
        """Where the roll sits inside its tier, 0.0 at the floor and 1.0 at the top.

        A single-value tier (``low == high``) is a full roll by definition, not a
        division by zero.
        """
        if self.span <= 0:
            return 1.0
        return max(0.0, min(1.0, (self.value - self.low) / self.span))

    @property
    def is_max_roll(self) -> bool:
        return self.value >= self.high

    def to_dict(self) -> dict[str, float]:
        return {
            "value": self.value,
            "low": self.low,
            "high": self.high,
            "percentile": round(self.percentile, 4),
        }


def parse_tier_ranges(line: str) -> tuple[TierRange, ...]:
    """Every ``value(low-high)`` annotation on one mod line, left to right.

    Hybrid mods print one annotation per rolled component
    (``Adds 5(4-6) to 12(10-14) Physical Damage``), so this returns a tuple.
    Returns ``()`` for an unannotated line.
    """
    found: list[TierRange] = []
    for value, low, high in _ANNOTATED_VALUE_RE.findall(str(line or "")):
        try:
            parsed = TierRange(float(value), float(low), float(high))
        except ValueError:  # pragma: no cover - regex already constrains the shape
            continue
        if parsed.low > parsed.high:
            # Trust the printed pair only when it is ordered; a reversed pair means
            # the line was not an Advanced Item Description annotation.
            continue
        found.append(parsed)
    return tuple(found)


def parse_tier_range(line: str) -> TierRange | None:
    """The annotation that describes the mod's headline value, or ``None``.

    For a hybrid mod the widest component is the one that carries the mod's tier
    identity, so it wins over an incidental small component.
    """
    ranges = parse_tier_ranges(line)
    if not ranges:
        return None
    return max(ranges, key=lambda row: (row.span, row.high))


def tier_range_for_value(line: str, value: float) -> TierRange | None:
    """The annotation whose rolled value is ``value``, or ``None``.

    Used when a feature parser has already decided which number on the line is the
    economically meaningful one, so the tier bounds attach to *that* number rather
    than to the widest component.
    """
    for row in parse_tier_ranges(line):
        if abs(row.value - float(value)) < 1e-9:
            return row
    return None


def has_tier_data(item_raw: str) -> bool:
    """True when the item text came from a client with Advanced Item Description on.

    Lets a caller choose the tier-aware or the degraded range policy once per item
    instead of re-deciding per mod.
    """
    return bool(_ANNOTATED_VALUE_RE.search(str(item_raw or "")))
