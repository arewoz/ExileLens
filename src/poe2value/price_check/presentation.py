from __future__ import annotations

from typing import Any

from poe2value.items.metadata import parse_lightweight_metadata
from poe2value.items.raw_input import RawItemInput
from poe2value.price_check.models import (
    LiveSearchState,
    PriceCheckResult,
    PriceConfidence,
    PriceSourceKind,
    TheoreticalTier,
)
from poe2value.price_check.live_acquisition import live_state_ui
from poe2value.price_check.price_trust import format_price_check_overlay_text

_TIER_LABELS = {
    TheoreticalTier.HIGH_VALUE_RARE: "High-value rare",
    TheoreticalTier.MODERATE_VALUE: "Moderate-value item",
    TheoreticalTier.LOW_VALUE: "Low-value item",
    TheoreticalTier.UNKNOWN: "Unknown desirability",
}

_DESIRABILITY_LABELS = {
    TheoreticalTier.HIGH_VALUE_RARE: "HIGH",
    TheoreticalTier.MODERATE_VALUE: "MEDIUM",
    TheoreticalTier.LOW_VALUE: "LOW",
    TheoreticalTier.UNKNOWN: "UNKNOWN",
}

_CURRENCY_LABELS = {
    "quick_sale": "Quick sell",
    "fair": "Fair price",
    "optimistic": "Optimistic",
}

_MARKET_UNAVAILABLE = "Not enough comparable data"

_SOURCE_LABELS = {
    PriceSourceKind.LIVE_MARKET: "LIVE MARKET",
    PriceSourceKind.CACHED_LIVE_MARKET: "CACHED LIVE MARKET",
    PriceSourceKind.HISTORICAL_MARKET: "HISTORICAL MARKET COMPARABLES",
    PriceSourceKind.OBSERVATION_CORPUS: "OBSERVATION CORPUS",
    PriceSourceKind.MODEL_THEORETICAL: "THEORETICAL",
    PriceSourceKind.UNKNOWN: "UNKNOWN",
}


def _format_currency_short(currency: str) -> str:
    lowered = currency.lower()
    if lowered in {"divine", "div", "d"}:
        return "div"
    if lowered in {"exalted", "ex", "exa"}:
        return "ex"
    if lowered in {"chaos", "c"}:
        return "c"
    return currency


def format_price_amount(amount: float | None) -> str:
    """Round to a precision that keeps prices distinguishable.

    MARKET-01B12: rounding everything to whole units turned 0.84 / 0.96 / 1.12 into
    "1 / 1 / 1" and made three genuinely different bands look identical. Small values
    keep more precision, large ones need less.
    """
    if amount is None:
        return ""
    value = float(amount)
    if value < 0:
        value = 0.0
    if value == 0:
        return "0"
    if value < 0.1:
        text = f"{value:.2f}"
    elif value < 10:
        text = f"{value:.1f}"
    elif value < 100:
        text = f"{value:.0f}" if float(value).is_integer() else f"{value:.1f}"
    else:
        text = f"{value:.0f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _format_currency_long(currency: str) -> str:
    lowered = str(currency or "").lower()
    return {
        "divine": "Divine Orb",
        "exalted": "Exalted Orb",
        "chaos": "Chaos Orb",
        "regal": "Regal Orb",
        "vaal": "Vaal Orb",
    }.get(lowered, currency or "")


def _format_band_amount(amount: float, currency: str, amount_high: float | None = None) -> str:
    label = _format_currency_short(currency)
    low_text = format_price_amount(amount)
    if amount_high is not None and amount_high > amount:
        high_text = format_price_amount(amount_high)
        if high_text != low_text:
            return f"{low_text}–{high_text} {label}"
    return f"{low_text} {label}"


def format_comparable_price(row: Any) -> str:
    """`1 regal (~0.9 ex)` — raw price first, then the value the estimator used.

    The normalized figure comes from the estimator itself (MARKET-01B12); the UI never
    performs its own currency conversion.
    """
    raw_amount = row.get("price_amount") if isinstance(row, dict) else getattr(row, "price_amount", None)
    raw_currency = row.get("price_currency") if isinstance(row, dict) else getattr(row, "price_currency", None)
    norm_amount = row.get("normalized_amount") if isinstance(row, dict) else getattr(row, "normalized_amount", None)
    norm_currency = (
        row.get("normalized_currency") if isinstance(row, dict) else getattr(row, "normalized_currency", None)
    )
    if raw_amount is None or not raw_currency:
        return ""
    raw_text = f"{format_price_amount(raw_amount)} {raw_currency}"
    if norm_amount is None or not norm_currency:
        return raw_text
    if str(norm_currency).lower() == str(raw_currency).lower():
        return raw_text
    return f"{raw_text} (~{format_price_amount(norm_amount)} {_format_currency_short(norm_currency)})"


def _around_text(bands: list[dict[str, Any]]) -> str:
    """One representative figure for an estimate that cannot support three.

    MARKET-01B13: used for base-only estimates, where quick / fair / optimistic would
    imply the sample says something about the item rather than about its base type.
    """
    fair = next((row for row in bands if str(row.get("label", "")).lower().startswith("fair")), None)
    row = fair or (bands[0] if bands else None)
    if row is None:
        return ""
    low = row.get("amount")
    high = row.get("amount_high")
    if not isinstance(low, (int, float)):
        return ""
    currency = _format_currency_short(str(row.get("currency") or ""))
    low_text = format_price_amount(low)
    if isinstance(high, (int, float)) and format_price_amount(high) != low_text:
        return f"Around {low_text}–{format_price_amount(high)} {currency}".strip()
    return f"Around {low_text} {currency}".strip()


def _public_hypothesis(hypothesis: Any) -> dict[str, Any] | None:
    if hypothesis is None:
        return None
    payload = hypothesis.to_dict() if hasattr(hypothesis, "to_dict") else dict(hypothesis)
    payload.pop("signature_id", None)
    return payload


def _public_discovery(discovery: Any) -> dict[str, Any] | None:
    if not isinstance(discovery, dict):
        return discovery
    payload = dict(discovery)
    signature = dict(payload.get("signature") or {})
    signature.pop("signature_id", None)
    if signature:
        payload["signature"] = signature
    payload.pop("price_trust", None)
    return payload


def summarise_bands(bands: list[dict[str, Any]]) -> tuple[bool, str]:
    """Detect the case where every band really is the same number.

    Returns `(collapsed, cluster_text)`. Three identical rows are not three concepts, so
    the caller renders one "around X" line instead.
    """
    values: list[float] = []
    for band in bands:
        for key in ("amount", "amount_high"):
            value = band.get(key)
            if isinstance(value, (int, float)):
                values.append(float(value))
    if not values:
        return False, ""
    displayed = {format_price_amount(value) for value in values}
    if len(displayed) > 1:
        return False, ""
    currency = str(bands[0].get("currency") or "")
    return True, f"Around {displayed.pop()} {_format_currency_short(currency)}"


def _format_age(seconds: float | None) -> str:
    value = max(0, int(seconds or 0))
    if value < 60:
        return f"{value}s"
    minutes = value // 60
    return f"{minutes}m" if minutes < 60 else f"{minutes // 60}h"


def build_price_check_queued(
    *,
    seconds_until_refresh: float,
    cached_age_seconds: float | None = None,
    cached_comparable_count: int = 0,
    reason: str = "",
    stage: str = "",
) -> dict[str, Any]:
    """MARKET-01B11 / 02F2A — server pacing is a short wait, not a failure.

    Shown when a fresh search or fetch is genuinely needed but the current server
    policy says it is not safe yet. The app continues on its own; the user does not
    press Shift+C again.
    """
    wait = max(0.0, float(seconds_until_refresh))
    stage_key = str(stage or reason or "").lower()
    if stage_key in {"fetch", "fetch_pacing", "fetch_continuation"}:
        subtitle = f"Comparables queued — ~{_format_age(wait)}"
        disclaimer = "Waiting for the market to allow listing fetch — this continues automatically."
    elif str(reason or "") == "discovery":
        subtitle = f"Refining market match — queued ~{_format_age(wait)}"
        disclaimer = "Waiting for the market to allow another search — this continues automatically."
    else:
        subtitle = f"Live search queued — ~{_format_age(wait)}"
        disclaimer = "Waiting for the market to allow another search — this continues automatically."
    if cached_comparable_count:
        subtitle = f"{subtitle} · {cached_comparable_count} recent listings held"
    return {
        "mode": "price_check",
        "headline": "PRICE CHECK",
        "market_price": "",
        "title": "CHECKING MARKET",
        "subtitle": subtitle,
        "source_kind": PriceSourceKind.UNKNOWN.value,
        "source_label": "",
        "confidence": "",
        "price_confidence": "",
        "show_currency": False,
        "currency_bands": [],
        "important_mods": [],
        "disclaimer": disclaimer,
        "blocker": "queued_live_refresh",
        "comparable_count": cached_comparable_count,
        "search_basis": "",
        "top_comparables": [],
        "live_search_state": None,
        "theoretical_desirability": None,
        "theoretical_tier": None,
        "league_note": "",
        "message": subtitle,
        "failure_code": "queued_live_refresh",
        "queued_seconds": round(wait, 1),
        "live_cache_age_seconds": cached_age_seconds,
        "awaiting_live_refresh": True,
        "queue_stage": stage_key or "search",
    }


def build_price_check_league_required(
    *,
    failure_code: str = "",
    stale_league: str | None = None,
    selecting: bool = True,
) -> dict[str, Any]:
    """MARKET-01B10 — replace the LEAGUE REQUIRED dead end with an actionable prompt.

    The passive overlay is click-through by design, so it cannot host a button. It
    states what is about to happen and the app opens the picker; `selecting=False`
    is used when no picker can be opened and the user must go to Settings.
    """
    if stale_league:
        title = "LEAGUE NO LONGER AVAILABLE"
        subtitle = f"Your saved league '{stale_league}' is not in the current league list."
    else:
        title = "SELECT LEAGUE"
        subtitle = "Live market needs to know which league to search."

    if selecting:
        disclaimer = "Choose your league in the window that just opened — this is asked once."
    else:
        disclaimer = "Open Settings → Market and choose your league."

    return {
        "mode": "price_check",
        "headline": "PRICE CHECK",
        "market_price": "",
        "title": title,
        "subtitle": subtitle,
        "source_kind": PriceSourceKind.UNKNOWN.value,
        "source_label": "",
        "confidence": "",
        "price_confidence": "",
        "show_currency": False,
        "currency_bands": [],
        "important_mods": [],
        "disclaimer": disclaimer,
        "blocker": "league_required",
        "comparable_count": 0,
        "search_basis": "",
        "top_comparables": [],
        "live_search_state": LiveSearchState.LEAGUE_REQUIRED.value,
        "theoretical_desirability": None,
        "theoretical_tier": None,
        "league_note": "",
        "message": subtitle,
        "failure_code": failure_code or "league_required",
        "stale_league": stale_league,
        "awaiting_league_selection": bool(selecting),
    }


def build_price_check_acquisition_failure(message: str, *, failure_code: str = "") -> dict[str, Any]:
    headline = "PRICE CHECK"
    title = "Could not read hovered item."
    if "Path of Exile 2 must be active" in message:
        title = "Path of Exile 2 must be active."
    subtitle = ""
    if message and message != title:
        subtitle = message
    return {
        "mode": "price_check",
        "headline": headline,
        "market_price": "",
        "title": title,
        "subtitle": subtitle,
        "source_kind": PriceSourceKind.UNKNOWN.value,
        "source_label": "",
        "confidence": "",
        "show_currency": False,
        "currency_bands": [],
        "important_mods": [],
        "disclaimer": "No item was acquired for price check.",
        "blocker": "acquisition_failed",
        "comparable_count": 0,
        "search_basis": "",
        "top_comparables": [],
        "live_search_state": None,
        "theoretical_desirability": None,
        "theoretical_tier": None,
        "message": message,
        "failure_code": failure_code or "acquisition_failed",
    }


def _extract_affix_lines(item_raw: str, limit: int = 4) -> list[str]:
    affixes: list[str] = []
    for line in str(item_raw or "").splitlines():
        cleaned = line.strip()
        if cleaned.startswith(("+", "-")) or " increased " in cleaned or " reduced " in cleaned:
            affixes.append(cleaned)
            if len(affixes) >= limit:
                break
    return affixes


def build_capture_test_presentation(
    *,
    item_raw: str,
    capture_id: int,
    sequence_before: int,
    sequence_after: int | None,
    foreground_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """CAPTURE-ONLY diagnostic UI — acquisition proof without market pipeline."""
    meta = parse_lightweight_metadata(RawItemInput.from_text(item_raw))
    affix_lines = _extract_affix_lines(item_raw)
    first_affix = affix_lines[0] if affix_lines else ""
    sequence_line = f"{sequence_before} → {sequence_after if sequence_after is not None else 'pending'}"
    name_part = meta.name or meta.base_type or "Item"
    subtitle = (
        f"{name_part} / {meta.base_type or 'Unknown base'} / {meta.category or 'Unknown'} / "
        f"{meta.rarity or 'Unknown'} / seq {sequence_line}"
    )
    if first_affix:
        subtitle = f"{subtitle} / {first_affix}"
    payload = {
        "mode": "capture_test",
        "headline": "CAPTURE TEST",
        "market_price": "",
        "title": "ACQUIRED",
        "subtitle": subtitle,
        "source_kind": PriceSourceKind.UNKNOWN.value,
        "source_label": "CAPTURE TEST",
        "confidence": "",
        "show_currency": False,
        "currency_bands": [],
        "important_mods": affix_lines,
        "disclaimer": "Capture-only diagnostic — market pipeline disabled.",
        "blocker": "",
        "comparable_count": 0,
        "search_basis": "",
        "top_comparables": [],
        "live_search_state": None,
        "theoretical_desirability": None,
        "theoretical_tier": None,
        "message": "Capture acquisition succeeded.",
        "capture_id": capture_id,
        "sequence_before": sequence_before,
        "sequence_after": sequence_after,
        "item_name": meta.name,
        "item_class": meta.category,
        "item_base": meta.base_type,
        "item_rarity": meta.rarity,
        "first_affix": first_affix,
        "affix_count": len(affix_lines),
        "foreground_info": dict(foreground_info or {}),
    }
    return payload


def build_market_only_presentation(result: PriceCheckResult, *, debug: bool = False) -> dict[str, Any]:
    """MARKET-ONLY diagnostic presentation — live pipeline without capture."""
    presentation = build_price_check_presentation(result, debug=debug)
    presentation["mode"] = "market_only"
    presentation["headline"] = "MARKET TEST"
    if result.diagnostics is not None:
        presentation["http_status"] = result.diagnostics.http_status
        presentation["search_requests"] = result.diagnostics.search_requests
        presentation["fetch_requests"] = result.diagnostics.fetch_requests
        presentation["total_http_requests"] = result.diagnostics.total_http_requests
    return presentation


def build_price_check_presentation(result: PriceCheckResult, *, debug: bool = False) -> dict[str, Any]:
    """Build overlay presentation for Shift+C price check (distinct from build eval)."""
    estimate = result.estimate
    source_kind = estimate.source_kind
    hypothesis = getattr(result, "hypothesis", None)
    show_currency = estimate.has_currency_estimate and source_kind not in {
        PriceSourceKind.MODEL_THEORETICAL,
        PriceSourceKind.UNKNOWN,
    }

    headline = "PRICE CHECK"
    if result.no_item_text:
        return {
            "mode": "price_check",
            "headline": headline,
            "market_price": _MARKET_UNAVAILABLE,
            "title": "Could not read hovered item.",
            "subtitle": result.message or "No item text was acquired.",
            "source_kind": PriceSourceKind.UNKNOWN.value,
            "source_label": "",
            "confidence": PriceConfidence.NONE.value,
            "show_currency": False,
            "currency_bands": [],
            "important_mods": [],
            "disclaimer": "No item was acquired for price check.",
            "blocker": "acquisition_failed",
            "comparable_count": 0,
            "search_basis": "",
            "top_comparables": [],
        }

    tier = estimate.theoretical_tier
    tier_label = _TIER_LABELS.get(tier, "Unknown") if tier else "Unknown"
    desirability = _DESIRABILITY_LABELS.get(tier, "UNKNOWN") if tier else "UNKNOWN"
    source_label = _SOURCE_LABELS.get(source_kind, source_kind.value.replace("_", " "))

    market_status = result.market_status or ""
    price_confidence = estimate.confidence.value if show_currency else ""
    discovery = getattr(result, "discovery", None)
    trust = {}
    if isinstance(discovery, dict) and isinstance(discovery.get("price_trust"), dict):
        trust = discovery["price_trust"]
    user_refined = bool(
        hypothesis is not None and getattr(hypothesis.hypothesis_source, "value", "") == "USER_REFINED"
    )
    observed_range = ""
    if trust.get("q25") is not None and trust.get("q75") is not None:
        currency = estimate.display_currency or ""
        lo = trust["q25"]
        hi = trust["q75"]
        if currency:
            observed_range = f"{lo:.1f}–{hi:.1f} {currency}"
        else:
            observed_range = f"{lo:.1f}–{hi:.1f}"
    trust_note = str(trust.get("note") or "")
    compact_reasons = tuple(trust.get("compact_reasons") or ())

    if result.diagnostics and result.diagnostics.auth_required:
        body_title = "CONNECT TRADE"
        body_subtitle = result.message or "Live market search requires trade authentication."
        market_price = _MARKET_UNAVAILABLE
        disclaimer = estimate.disclaimer or "Connect Trade once to enable live comparable search."
        price_confidence = ""
    elif str(getattr(result, "estimate_state", "") or "") == "NEEDS REFINEMENT":
        body_title = "NEEDS REFINEMENT"
        note = ""
        if isinstance(discovery, dict):
            note = str((discovery.get("final") or {}).get("note") or "")
        body_subtitle = trust_note or note or estimate.summary or "Market depends heavily on matched mods."
        if observed_range and "Observed" not in body_subtitle:
            body_subtitle = f"{body_subtitle} Observed {observed_range}.".strip()
        if result.cache_age_seconds is not None:
            body_subtitle = f"{body_subtitle} (updated {_format_age(result.cache_age_seconds)} ago)".strip()
        market_price = _MARKET_UNAVAILABLE
        show_currency = False
        price_confidence = ""
        disclaimer = estimate.disclaimer or "Refine: Ctrl+Shift+R"
    elif str(getattr(result, "estimate_state", "") or "") == "HIGH CONFIDENCE" and show_currency:
        body_title = "HIGH CONFIDENCE"
        body_subtitle = trust_note or " · ".join(compact_reasons) or estimate.summary or "Stable live comparables."
        market_price = None
        price_confidence = ""
        disclaimer = estimate.disclaimer or "Refine available."
    elif bool(getattr(result, "auto_adjusted", False)) and show_currency:
        body_title = str(getattr(result, "estimate_state", "") or "") or "ASSISTED ESTIMATE"
        body_subtitle = trust_note or "Auto-adjusted market match. Original match was too narrow."
        market_price = None
        disclaimer = estimate.disclaimer or "Refine available."
        price_confidence = ""
    elif user_refined and show_currency:
        body_title = str(getattr(result, "estimate_state", "") or "") or "ASSISTED ESTIMATE"
        body_subtitle = trust_note or estimate.summary or " · ".join(compact_reasons) or "Live comparable listings"
        market_price = None
        price_confidence = ""
        disclaimer = estimate.disclaimer or "Refine available."
    elif (
        hypothesis is not None
        and hypothesis.hypothesis_source.value == "SIGNATURE"
        and show_currency
    ):
        body_title = str(getattr(result, "estimate_state", "") or "") or "ASSISTED ESTIMATE"
        body_subtitle = "Learned market pattern"
        if estimate.summary:
            body_subtitle = f"{estimate.summary} · Learned market pattern"
        market_price = None
        disclaimer = estimate.disclaimer or "Refine available."
        price_confidence = ""
    elif market_status and result.estimate.has_currency_estimate:
        body_title = str(getattr(result, "estimate_state", "") or "") or "ASSISTED ESTIMATE"
        body_subtitle = estimate.summary or ""
        if result.cache_age_seconds is not None:
            # MARKET-01B11: cached live data is legitimate, but it must never look fresh.
            body_subtitle = f"{body_subtitle} (updated {_format_age(result.cache_age_seconds)} ago)".strip()
        market_price = None
        disclaimer = estimate.disclaimer or market_status
        price_confidence = estimate.confidence.value
    elif result.is_live_failure and result.live_search_state is not None:
        body_title, body_subtitle = live_state_ui(result.live_search_state)
        if result.live_search_state == LiveSearchState.LIVE_SEARCH_RATE_LIMITED:
            body_title = "LIVE MARKET TEMPORARILY LIMITED"
            if market_status:
                body_subtitle = market_status.replace("LIVE MARKET TEMPORARILY LIMITED — ", "")
            elif result.message:
                body_subtitle = result.message
            price_confidence = ""
        elif result.message:
            body_subtitle = result.message
        market_price = body_title
        disclaimer = estimate.disclaimer or body_subtitle
    elif source_kind == PriceSourceKind.MODEL_THEORETICAL:
        body_title = f"THEORETICAL DESIRABILITY: {desirability}"
        body_subtitle = tier_label
        market_price = _MARKET_UNAVAILABLE
        disclaimer = estimate.disclaimer or "Theoretical desirability only — not a market price."
        price_confidence = ""
    elif show_currency:
        body_title = str(getattr(result, "estimate_state", "") or "") or "ASSISTED ESTIMATE"
        body_subtitle = estimate.summary or ""
        market_price = None
        disclaimer = estimate.disclaimer or ""
    elif source_kind == PriceSourceKind.UNKNOWN:
        body_title = "PRICE UNAVAILABLE"
        body_subtitle = estimate.summary or "No market evidence"
        market_price = _MARKET_UNAVAILABLE
        disclaimer = estimate.disclaimer or "No reliable market data available."
    else:
        body_title = source_kind.value.replace("_", " ").title()
        body_subtitle = estimate.summary
        market_price = estimate.summary or _MARKET_UNAVAILABLE
        disclaimer = estimate.disclaimer

    currency_rows: list[dict[str, Any]] = []
    if show_currency:
        for band in estimate.currency_bands:
            currency_rows.append(
                {
                    "label": _CURRENCY_LABELS.get(band.label, band.label.replace("_", " ").title()),
                    "amount": band.amount,
                    "currency": band.currency,
                    "amount_high": band.amount_high,
                    "display": _format_band_amount(band.amount, band.currency, band.amount_high),
                }
            )

    league = result.request.league
    league_note = ""
    if league.status.value == "UNKNOWN":
        league_note = "League unknown — market comparables may not apply."

    # MARKET-01B12: only listings that actually contributed to the bands are shown, and
    # each carries the value the estimator used so a mixed-currency estimate is auditable.
    top_comparables: list[dict[str, Any]] = []
    for row in estimate.comparables[:3]:
        entry = {
            "listing_id": row.listing_id,
            "price_amount": row.price_amount,
            "price_currency": row.price_currency,
            "normalized_amount": row.normalized_amount,
            "normalized_currency": row.normalized_currency,
            "converted": row.was_converted,
            "source": row.source,
            "accepted": True,
        }
        entry["display"] = format_comparable_price(entry)
        top_comparables.append(entry)

    estimate_currency = estimate.display_currency or (
        currency_rows[0]["currency"] if currency_rows else ""
    )
    currency_basis = ""
    if show_currency and estimate_currency:
        if any(row.get("converted") for row in top_comparables):
            currency_basis = f"Prices normalized to {_format_currency_long(estimate_currency)}"
        else:
            currency_basis = f"Estimate currency: {_format_currency_long(estimate_currency)}"

    bands_collapsed, cluster_text = summarise_bands(currency_rows) if show_currency else (False, "")

    # MARKET-01B13: a result the query could only reach through the base type is a price
    # for the base type. It says so, it shows one figure rather than a quick/fair/
    # optimistic structure it cannot support, and its confidence cannot read above LOW.
    base_only = str(getattr(result, "identity_source", "") or "") == "BASE_ONLY"
    estimate_state = str(getattr(result, "estimate_state", "") or "")
    if estimate_state == "BASE MARKET ESTIMATE":
        base_only = True
    basis_note = ""
    if base_only and show_currency:
        body_title = "BASE MARKET ESTIMATE"
        basis_note = "Based on base type only"
        price_confidence = "LOW"
        if not bands_collapsed:
            bands_collapsed = True
            cluster_text = _around_text(currency_rows)

    driver_rows: list[dict[str, Any]] = []
    ignored_rows: list[dict[str, Any]] = []
    match_mode_label = ""
    if hypothesis is not None:
        for row in hypothesis.available_drivers:
            driver_rows.append(
                {
                    "driver_id": row.driver_id,
                    "label": row.label,
                    "enabled": row.enabled,
                    "search_min": row.search_min,
                    "actual_value": row.actual_value,
                    "overlay_row": row.overlay_row(),
                    "trade_stat_ids": list(row.trade_stat_ids),
                    "driver_kind": row.driver_kind.value,
                    "family": row.family,
                    "floor_policy": row.floor_policy,
                }
            )
        ignored_rows = [{"label": text, "ignored": True} for text in hypothesis.ignored_mod_texts]
        selected_n = len(hypothesis.selected_drivers)
        if hypothesis.match_mode.value == "COUNT" and hypothesis.count_min:
            match_mode_label = f"{hypothesis.count_min} of {selected_n}"
        elif selected_n:
            match_mode_label = f"ALL {selected_n}"

    refine_available = bool(hypothesis is not None and not result.no_item_text)
    if str(getattr(result, "estimate_state", "") or "") == "NEEDS REFINEMENT":
        refine_hint = "Refine: Ctrl+Shift+R" if refine_available else ""
    else:
        refine_hint = "Refine available — Ctrl+Shift+R or tray: Refine Last Item Check" if refine_available else ""

    confidence_detail = " · ".join(compact_reasons) if compact_reasons else (estimate.confidence_reason or "")
    drivers_collapsed = str(getattr(result, "estimate_state", "") or "") == "HIGH CONFIDENCE"
    if trust and str(getattr(result, "estimate_state", "") or "") != "BASE MARKET ESTIMATE":
        price_confidence = ""

    payload = {
        "mode": "price_check",
        "headline": headline,
        "market_price": market_price,
        "title": body_title,
        "subtitle": body_subtitle,
        "source_kind": source_kind.value,
        "source_label": source_label,
        "confidence": price_confidence,
        "price_confidence": price_confidence,
        "market_status": market_status,
        "theoretical_tier": tier.value if tier else None,
        "theoretical_desirability": desirability if source_kind == PriceSourceKind.MODEL_THEORETICAL else None,
        "show_currency": show_currency,
        "currency_bands": currency_rows,
        "important_mods": list(result.important_mods),
        "disclaimer": disclaimer,
        "league": league.league,
        "league_status": league.status.value,
        "league_note": league_note,
        "provider_id": result.provider_id,
        "message": result.message,
        "cache_hit": result.cache_hit,
        "comparable_count": result.comparable_count or len(estimate.comparables),
        "search_basis": result.search_basis,
        "matched_features": getattr(result, "matched_features", "") or "",
        "estimate_currency": estimate_currency,
        "currency_basis": currency_basis,
        "bands_collapsed": bands_collapsed,
        "cluster_text": cluster_text,
        "identity_source": str(getattr(result, "identity_source", "") or ""),
        "base_only": base_only,
        "basis_note": basis_note,
        "confidence_reason": confidence_detail,
        "search_relaxation_tier": result.search_relaxation_tier,
        "live_search_state": result.live_search_state.value if result.live_search_state else None,
        "top_comparables": top_comparables,
        "estimate_state": estimate_state or body_title,
        "drivers": driver_rows,
        "ignored_mods": ignored_rows,
        "match_mode_label": match_mode_label,
        "refine_available": refine_available,
        "refine_hint": refine_hint,
        "learned_market_pattern": bool(
            hypothesis is not None and hypothesis.hypothesis_source.value == "SIGNATURE"
        ),
        "auto_selected_from": (
            "Learned market pattern"
            if hypothesis is not None and hypothesis.hypothesis_source.value == "SIGNATURE"
            else "Default market rules"
        ),
        "hypothesis": _public_hypothesis(hypothesis),
        "query_fingerprint": hypothesis.query_fingerprint if hypothesis is not None else "",
        "auto_adjusted": bool(getattr(result, "auto_adjusted", False)),
        "stability": str(getattr(result, "stability", "") or ""),
        "original_hypothesis": _public_hypothesis(result.original_hypothesis),
        "original_auto_summary": (
            result.original_hypothesis.search_basis
            if bool(getattr(result, "auto_adjusted", False))
            and getattr(result, "original_hypothesis", None) is not None
            else ""
        ),
        "discovery": _public_discovery(getattr(result, "discovery", None)),
        "price_trust": dict(trust) if trust else {},
        "trust_compact_reasons": list(compact_reasons),
        "drivers_collapsed": drivers_collapsed,
        "show_observed_range": str(getattr(result, "estimate_state", "") or "") == "NEEDS REFINEMENT"
        and bool(observed_range),
        "observed_range": observed_range,
        "refined_by_you": user_refined,
    }
    payload["overlay_text"] = format_price_check_overlay_text(payload)
    if debug and result.diagnostics is not None:
        payload["diagnostics"] = result.diagnostics.to_dict()
    return payload
