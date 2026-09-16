from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CurrencyRateTable:
    """Optional manual FX — clearly labeled, never invented."""

    rates_to_chaos: dict[str, float] = field(default_factory=dict)
    source: str = "MANUAL"
    label: str = "User-supplied conversion table (heuristic only)"

    def convert(self, amount: float, from_currency: str, to_currency: str) -> float | None:
        if from_currency == to_currency:
            return amount
        if from_currency not in self.rates_to_chaos or to_currency not in self.rates_to_chaos:
            return None
        chaos = amount * self.rates_to_chaos[from_currency]
        return chaos / self.rates_to_chaos[to_currency]

    def comparable(self, left: str, right: str) -> bool:
        if left == right:
            return True
        return left in self.rates_to_chaos and right in self.rates_to_chaos

    def to_dict(self) -> dict[str, Any]:
        return {
            "rates_to_chaos": self.rates_to_chaos,
            "source": self.source,
            "label": self.label,
            "heuristic": True,
        }
