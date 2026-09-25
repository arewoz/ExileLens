from __future__ import annotations

from typing import Any

ZERO_NOISE_ABS = 0.005
ZERO_NOISE_PCT = 0.049


def normalize_zero(value: float | None, *, abs_tol: float = ZERO_NOISE_ABS) -> float | None:
    if value is None:
        return None
    if abs(value) < abs_tol:
        return 0.0
    return value


def format_large_number(value: float | int | None) -> str:
    if value is None:
        return "—"
    number = float(value)
    if abs(number) >= 100:
        return f"{number:,.0f}"
    if abs(number) >= 10:
        return f"{number:,.1f}"
    if abs(number - round(number)) < 0.05:
        return f"{round(number):,}"
    return f"{number:,.2f}"


def format_percent(value: float | None, *, signed: bool = True, digits: int = 1) -> str:
    if value is None:
        return "—"
    cleaned = normalize_zero(float(value), abs_tol=ZERO_NOISE_PCT)
    assert cleaned is not None
    if cleaned == 0.0:
        return "0.0%"
    sign = "+" if signed and cleaned > 0 else ""
    return f"{sign}{cleaned:.{digits}f}%"


def format_signed_int(value: float | None) -> str:
    if value is None:
        return "—"
    cleaned = normalize_zero(float(value), abs_tol=0.5)
    assert cleaned is not None
    integer = int(round(cleaned))
    if integer == 0:
        return "0"
    sign = "+" if integer > 0 else ""
    return f"{sign}{integer}"


def format_resistance(value: float | None) -> str:
    if value is None:
        return "—"
    return str(int(round(float(value))))


def direction_symbol(direction: str) -> str:
    if direction == "positive":
        return "▲"
    if direction == "negative":
        return "▼"
    return ""


def format_metric_delta(metric: dict[str, Any]) -> str:
    display = metric.get("display_format") or "large_number"
    direction = metric.get("direction") or "neutral"
    symbol = direction_symbol(direction)
    if display == "resistance":
        text = format_signed_int(metric.get("absolute_delta"))
        return f"{text} {symbol}".strip()
    if display == "percent_mod":
        current = float(metric.get("current") or 0)
        candidate = float(metric.get("candidate") or 0)
        # MovementSpeedMod is a PoB multiplier (1.0 = baseline speed).
        pct = (candidate - current) * 100.0 if abs(current) <= 8 and abs(candidate) <= 8 else metric.get("percent_delta")
        return f"{format_percent(pct)} {symbol}".strip()
    pct = metric.get("percent_delta")
    if pct is None:
        text = format_signed_int(metric.get("absolute_delta"))
        return f"{text} {symbol}".strip()
    return f"{format_percent(pct)} {symbol}".strip()


def format_resistance_range(
    *,
    effective_current: float | None,
    effective_candidate: float | None,
    uncapped_current: float | None = None,
    uncapped_candidate: float | None = None,
    cap_current: float | None = None,
    cap_candidate: float | None = None,
) -> str:
    """Effective (capped) resistance vs uncapped total when they diverge."""
    eff = f"eff {format_resistance(effective_current)} → {format_resistance(effective_candidate)}"
    uncapped_differs = (
        uncapped_current is not None
        and uncapped_candidate is not None
        and (
            abs(float(uncapped_current) - float(effective_current or 0)) > 0.5
            or abs(float(uncapped_candidate) - float(effective_candidate or 0)) > 0.5
        )
    )
    if uncapped_differs:
        eff += f" · uncapped {format_resistance(uncapped_current)} → {format_resistance(uncapped_candidate)}"
    cap_differs = cap_current is not None or cap_candidate is not None
    if cap_differs and (cap_current != cap_candidate or uncapped_differs):
        eff += f" · max cap {format_resistance(cap_current)} → {format_resistance(cap_candidate)}"
    return eff


def format_current_candidate(metric: dict[str, Any]) -> str:
    display = metric.get("display_format") or "large_number"
    current = metric.get("current")
    candidate = metric.get("candidate")
    if display == "resistance":
        if metric.get("uncapped_current") is not None or metric.get("uncapped_candidate") is not None:
            return format_resistance_range(
                effective_current=current,
                effective_candidate=candidate,
                uncapped_current=metric.get("uncapped_current"),
                uncapped_candidate=metric.get("uncapped_candidate"),
                cap_current=metric.get("cap_current"),
                cap_candidate=metric.get("cap_candidate"),
            )
        return f"{format_resistance(current)} → {format_resistance(candidate)}"
    if display == "percent_mod":
        def _as_pct(value: float | None) -> str:
            if value is None:
                return "—"
            number = float(value)
            shown = (number - 1.0) * 100.0 if 0 <= number <= 8 else number
            return format_percent(shown, signed=False)
        return f"{_as_pct(current)} → {_as_pct(candidate)}"
    return f"{format_large_number(current)} → {format_large_number(candidate)}"
