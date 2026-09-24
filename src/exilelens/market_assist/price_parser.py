"""Parse in-game trade price notes from copied item text."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from exilelens.market.models import ListingPrice

_PRICE_LINE_RE = re.compile(
    r"(?im)^(?:Note:\s*)?~b/o\s+(\d+(?:\.\d+)?)\s+([a-zA-Z]+)\s*$"
)

_CURRENCY_ALIASES: dict[str, str] = {
    "alch": "Alchemy",
    "alchemy": "Alchemy",
    "div": "Divine",
    "divine": "Divine",
    "divines": "Divine",
    "ex": "Exalted",
    "exa": "Exalted",
    "exalted": "Exalted",
    "exalts": "Exalted",
    "chaos": "Chaos",
    "c": "Chaos",
    "annul": "Annul",
    "annulment": "Annul",
    "mirror": "Mirror",
    "regal": "Regal",
}


@dataclass(frozen=True)
class ParsedPriceNote:
    price: ListingPrice | None
    raw_price_note: str | None
    supported: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "price": self.price.to_dict() if self.price else None,
            "raw_price_note": self.raw_price_note,
            "supported": self.supported,
        }


def _normalize_currency(token: str) -> str | None:
    key = (token or "").strip().lower()
    if not key:
        return None
    if key in _CURRENCY_ALIASES:
        return _CURRENCY_ALIASES[key]
    title = token.strip().title()
    if title in {"Divine", "Exalted", "Chaos", "Annul", "Mirror", "Regal", "Alchemy"}:
        return title
    return None


def parse_price_note(item_raw: str) -> ParsedPriceNote:
    """Extract ~b/o price from item clipboard text. Unsupported notes do not reject the item."""
    raw_note: str | None = None
    for line in item_raw.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("note:") or stripped.lower().startswith("~b/o"):
            raw_note = stripped
            break
    if raw_note is None:
        return ParsedPriceNote(price=None, raw_price_note=None, supported=False)

    match = _PRICE_LINE_RE.search(raw_note) or _PRICE_LINE_RE.search(item_raw)
    if not match:
        return ParsedPriceNote(price=None, raw_price_note=raw_note, supported=False)

    amount = float(match.group(1))
    currency = _normalize_currency(match.group(2))
    if currency is None or amount <= 0:
        return ParsedPriceNote(price=None, raw_price_note=raw_note, supported=False)

    return ParsedPriceNote(
        price=ListingPrice(amount=amount, currency=currency),
        raw_price_note=raw_note,
        supported=True,
    )


def observation_key(content_hash: str, price: ListingPrice | None) -> str:
    if price is None:
        return content_hash
    return f"{content_hash}:{price.amount}:{price.currency}"
