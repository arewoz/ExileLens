from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

SUPPORTED_CURRENCIES = ("Divine", "Exalted", "Chaos", "Annul", "Mirror", "Regal", "Alchemy")


class PowerValueClass(str, Enum):
    EXCELLENT_VALUE = "EXCELLENT_VALUE"
    GOOD_VALUE = "GOOD_VALUE"
    FAIR_VALUE = "FAIR_VALUE"
    LOW_VALUE = "LOW_VALUE"
    BAD_VALUE = "BAD_VALUE"


# MVP heuristic — same-currency profile_gain per unit. Not a market truth.
PPC_CLASS_THRESHOLDS = {
    PowerValueClass.EXCELLENT_VALUE: 12.0,
    PowerValueClass.GOOD_VALUE: 6.0,
    PowerValueClass.FAIR_VALUE: 3.0,
    PowerValueClass.LOW_VALUE: 1.0,
}


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


def classify_power_per_currency(profile_gain: float, amount: float) -> PowerValueClass:
    if profile_gain <= 0:
        return PowerValueClass.BAD_VALUE
    ppc = profile_gain / amount
    if ppc >= PPC_CLASS_THRESHOLDS[PowerValueClass.EXCELLENT_VALUE]:
        return PowerValueClass.EXCELLENT_VALUE
    if ppc >= PPC_CLASS_THRESHOLDS[PowerValueClass.GOOD_VALUE]:
        return PowerValueClass.GOOD_VALUE
    if ppc >= PPC_CLASS_THRESHOLDS[PowerValueClass.FAIR_VALUE]:
        return PowerValueClass.FAIR_VALUE
    if ppc >= PPC_CLASS_THRESHOLDS[PowerValueClass.LOW_VALUE]:
        return PowerValueClass.LOW_VALUE
    return PowerValueClass.BAD_VALUE


def compute_power_per_currency(profile_gain: float, price: ManualPrice | None) -> dict[str, Any] | None:
    if price is None:
        return None
    amount = float(price.amount)
    if amount <= 0:
        raise ManualPriceError("price must be greater than 0")
    classification = classify_power_per_currency(profile_gain, amount)
    power = round(profile_gain / amount, 2) if profile_gain > 0 else round(min(profile_gain / amount, 0.0), 2)
    return {
        "price": price.to_dict(),
        "profile_gain": round(profile_gain, 2),
        "power_per_currency": power,
        "classification": classification.value,
        "currency": price.currency,
        "heuristic": True,
        "mvp_thresholds": True,
        "converted": False,
    }
