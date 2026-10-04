from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# R5-C: a price is a plain fact. There is no Build Value / price ratio, no value class and no buy recommendation anywhere in the product.
SUPPORTED_CURRENCIES = ("Divine", "Exalted", "Chaos", "Annul", "Mirror", "Regal", "Alchemy")


class ManualPriceError(ValueError):
    pass


@dataclass(frozen=True)
class ManualPrice:
    amount: float
    currency: str
    source: str = "MANUAL"

    def to_dict(self) -> dict[str, Any]:
        return {"amount": self.amount, "currency": self.currency, "source": self.source}


def parse_manual_price(amount: float, currency: str) -> ManualPrice:
    if amount is None:
        raise ManualPriceError("price amount is required")
    number = float(amount)
    if number <= 0:
        raise ManualPriceError("price must be greater than 0")
    label = (currency or "").strip()
    if not label:
        raise ManualPriceError("currency is required")
    return ManualPrice(amount=number, currency=label, source="MANUAL")
