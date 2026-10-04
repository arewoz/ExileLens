"""Player-facing view of `result["market_evidence"]` (R5-C). Pure; reads MarketEvidence v1 and the existing evaluation outcome.

This is the only place market evidence becomes words. Widgets render these strings and never interpret price_check internals.

Rules:
- Absence is normal. No evidence, a disabled/unavailable/rate-limited state, or a policy-blocked provider produces NO view at all (no
  placeholder, no "unavailable" line): the build verdict is the product and the market is secondary.
- A price is the cost to buy a comparable listing (cheapest first), never what the item is "worth".
- No enum names, trust codes, percentages of confidence, seller concentration figures or provider ids ever reach a string.
- The impact + price pairing is two numbers the player already understands, side by side. There is no ratio, no combined score and no value class.
"""

from __future__ import annotations

from typing import Any, Mapping

_CURRENCY = {
    "exalted": "Ex",
    "divine": "Div",
    "chaos": "Chaos",
    "regal": "Regal",
    "alchemy": "Alch",
    "annul": "Annul",
    "mirror": "Mirror",
}

_FRESHNESS = {
    "CURRENT": "Listings are current.",
    "RECENT": "Listings are from the last day.",
    "AGING": "Listings are a few days old.",
    "STALE": "Listings are old.",
}

_UPGRADES = frozenset({"MEANINGFUL_UPGRADE", "MINOR_UPGRADE"})
# Measured metrics the pairing may name. Anything else (resistances, movement, recovery) is not paired.
_PAIR_LABELS = {"primary_offense": "Damage", "ehp": "EHP", "worst_max_hit": "Max hit"}
_PAIR_AXES = ("OFFENSE", "DEFENSE")
_MAX_COVERAGE_LINES = 3


def currency_label(currency: Any) -> str:
    text = str(currency or "").strip()
    return _CURRENCY.get(text.lower(), text)


def _number(value: float) -> str:
    value = float(value)
    return f"{value:.0f}" if value >= 10 else f"{value:.1f}".rstrip("0").rstrip(".")


def _range_text(price: Mapping[str, Any]) -> str:
    low, high = float(price["low"]), float(price["high"])
    unit = currency_label(price.get("display_currency"))
    a, b = _number(low), _number(high)
    return f"~{a} {unit}" if a == b else f"~{a}–{b} {unit}"


def _point_text(price: Mapping[str, Any]) -> str:
    point = price.get("point")
    value = float(point) if point is not None else (float(price["low"]) + float(price["high"])) / 2.0
    return f"~{_number(value)} {currency_label(price.get('display_currency'))}"


def _listed_text(listed: Mapping[str, Any]) -> str:
    return f"{_number(listed['amount'])} {currency_label(listed.get('currency'))}"


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def pairing_line(evidence: Mapping[str, Any], outcome: Mapping[str, Any] | None) -> str:
    """"Damage +6.8% · Comparable cost ~34 Ex", or "" unless every condition holds. Uses the measured impact as is; never recomputes it."""
    price = evidence.get("price")
    if (
        not price
        or evidence.get("headline") not in {"STRONG_COMPARABLE_SET", "WEAK_COMPARABLE_SET"}
        or evidence.get("freshness") == "STALE"
    ):
        return ""
    outcome = outcome or {}
    if str(outcome.get("evaluation_quality") or "") != "FULL" or str(outcome.get("verdict") or "") not in _UPGRADES:
        return ""
    impact = outcome.get("item_impact") or {}
    axes = impact.get("axes") or {}
    if str((impact.get("conflict") or {}).get("kind") or "NONE") != "NONE" or str(impact.get("pattern") or "") in {"TRADEOFF", "MIXED"}:
        return ""
    if any(bool((axis or {}).get("material_negative")) for axis in axes.values()):
        return ""
    best: tuple[float, str] | None = None
    for axis_name in _PAIR_AXES:
        axis = axes.get(axis_name) or {}
        if not axis.get("material_positive"):
            continue
        for metric in axis.get("metrics") or ():
            label = _PAIR_LABELS.get(str(metric.get("key") or ""))
            delta = metric.get("percent_delta")
            if label is None or not isinstance(delta, (int, float)) or delta <= 0:
                continue
            if best is None or delta > best[0]:
                best = (float(delta), label)
    if best is None:
        return ""
    return f"{best[1]} +{best[0]:.1f}% · Comparable cost {_point_text(price)}"


def _compact_lines(evidence: Mapping[str, Any], outcome: Mapping[str, Any] | None) -> list[str]:
    headline = evidence.get("headline")
    price = evidence.get("price")
    if headline == "SPARSE_MARKET":
        return ["Sparse market · use cautiously"]
    if headline == "VOLATILE_ESTIMATE":
        return ["Volatile market · no reliable price"]
    if headline not in {"STRONG_COMPARABLE_SET", "WEAK_COMPARABLE_SET"} or not price:
        return []
    quality = "Strong market" if headline == "STRONG_COMPARABLE_SET" else "Limited comparables"
    price_line = f"Price {_range_text(price)} · {quality}"
    listed = evidence.get("listed_price")
    verdict = evidence.get("listed_vs_market")
    listed_line = ""
    if listed and verdict in {"BELOW", "WITHIN", "ABOVE"}:
        listed_line = f"Listed {_listed_text(listed)} · {verdict.lower()} market {_range_text(price)}"
    pair = pairing_line(evidence, outcome)
    if pair and listed_line:
        return [listed_line, pair]
    if pair:
        return [pair]
    return [listed_line or price_line]


def _more_info_lines(evidence: Mapping[str, Any]) -> list[str]:
    headline = evidence.get("headline")
    price = evidence.get("price")
    count = int(evidence.get("comparable_count") or 0)
    lines: list[str] = []
    if headline in {"STRONG_COMPARABLE_SET", "WEAK_COMPARABLE_SET"} and price:
        lines.append(_range_text(price))
        lines.append(("Strong" if headline == "STRONG_COMPARABLE_SET" else "Limited") + f" comparable set · {_plural(count, 'listing')}")
        lines.append(
            "Asking prices of every comparable listing."
            if evidence.get("band_basis") == "FULL_SAMPLE"
            else "Asking prices of the cheapest comparable listings."
        )
    elif headline == "SPARSE_MARKET":
        lines.append("Sparse market")
        lines.append(f"Only {_plural(count, 'comparable listing')} {'was' if count == 1 else 'were'} found. Use the observed range cautiously.")
        if price:
            lines.append(f"Observed {_range_text(price)}")
    elif headline == "VOLATILE_ESTIMATE":
        lines.append("Volatile market")
        lines.append("No reliable price: " + (str(evidence.get("reason") or "").rstrip(".").lower() or "prices are inconsistent") + ".")
    else:
        lines.append("No trustworthy estimate")
        reason = str(evidence.get("reason") or "").strip()
        if reason:
            lines.append(reason)
    reasons = list(evidence.get("reasons") or ())
    if "SELLER_CONCENTRATED" in reasons and headline in {"STRONG_COMPARABLE_SET", "WEAK_COMPARABLE_SET", "SPARSE_MARKET"}:
        lines.append(f"{_plural(int(evidence.get('distinct_sellers') or 0), 'seller')}; most listings are from one or two of them.")
    fresh = _FRESHNESS.get(str(evidence.get("freshness") or ""))
    if fresh:
        lines.append(fresh)
    listed = evidence.get("listed_price")
    if listed:
        verdict = evidence.get("listed_vs_market")
        if verdict in {"BELOW", "WITHIN", "ABOVE"} and price:
            lines.append(f"Listed {_listed_text(listed)} · {verdict.lower()} the comparable range")
        else:
            lines.append(f"Listed {_listed_text(listed)}")
    lines.extend(str(row) for row in list(evidence.get("coverage") or ())[:_MAX_COVERAGE_LINES])
    return [line for line in lines if line]


def market_view(evidence: Mapping[str, Any] | None, outcome: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
    """The player-facing view, or None when there is nothing worth saying (the normal case today)."""
    try:
        if not evidence or str(evidence.get("status") or "") != "AVAILABLE" or not evidence.get("headline"):
            return None
        return {
            "compact_lines": _compact_lines(evidence, outcome),
            "more_info_lines": _more_info_lines(evidence),
        }
    except Exception:  # noqa: BLE001 - presentation of an optional layer must never break Item Check
        return None
