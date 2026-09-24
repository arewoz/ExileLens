"""Centralized Tree Coach heatmap bands. Product heuristic — not PoB truth.

Bands use absolute Build Value / value-per-point thresholds so a locally-weak
neighborhood cannot make +2 look exceptional. Color interpolation may use
in-band position; the named band itself stays absolute.
"""

from __future__ import annotations

from dataclasses import dataclass

from exilelens.tree.models import HeatmapBand, HeatmapMetric, HeatmapSource

# Absolute score_delta (or value-per-point) bands. Calibrated so Fast Mapper
# "useful" notables stay USEFUL/HIGH even if one outlier is much larger.
EXCEPTIONAL_MIN = 12.0
HIGH_MIN = 7.0
USEFUL_MIN = 3.0
LOW_MIN = 0.05
NEUTRAL_ABS = 0.05

BAND_FILL_HEX = {
    HeatmapBand.UNKNOWN: "#3a3a3c",
    HeatmapBand.PENDING: "#5a6a88",
    HeatmapBand.NEGATIVE: "#3d5a6e",
    HeatmapBand.NEUTRAL: "#4a453c",
    HeatmapBand.LOW: "#6b5a32",
    HeatmapBand.USEFUL: "#c9a227",
    HeatmapBand.HIGH: "#e08a2c",
    HeatmapBand.EXCEPTIONAL: "#ffd4a0",
}

BAND_LABEL = {
    HeatmapBand.UNKNOWN: "UNEVALUATED",
    HeatmapBand.PENDING: "PENDING",
    HeatmapBand.NEGATIVE: "NEGATIVE",
    HeatmapBand.NEUTRAL: "NEUTRAL",
    HeatmapBand.LOW: "LOW",
    HeatmapBand.USEFUL: "USEFUL",
    HeatmapBand.HIGH: "HIGH",
    HeatmapBand.EXCEPTIONAL: "EXCEPTIONAL",
}


@dataclass(frozen=True)
class HeatmapScale:
    source: HeatmapSource = HeatmapSource.MY_BUILD_VALUE
    metric: HeatmapMetric = HeatmapMetric.VALUE_PER_POINT
    exceptional_min: float = EXCEPTIONAL_MIN
    high_min: float = HIGH_MIN
    useful_min: float = USEFUL_MIN
    low_min: float = LOW_MIN
    neutral_abs: float = NEUTRAL_ABS


DEFAULT_SCALE = HeatmapScale()


def heat_value(evaluation: dict, metric: HeatmapMetric | str = HeatmapMetric.VALUE_PER_POINT) -> float | None:
    """Pick the renderer metric from a contract evaluation. Never invents value."""
    mode = metric if isinstance(metric, HeatmapMetric) else HeatmapMetric(str(metric))
    status = str(evaluation.get("evaluation_status") or evaluation.get("status") or "")
    if status and status != "VALID":
        return None
    if mode == HeatmapMetric.VALUE_PER_POINT:
        raw = evaluation.get("value_per_point")
        if raw is not None:
            return float(raw)
    total = evaluation.get("build_value")
    if total is None:
        total = evaluation.get("path_value")
    if total is None:
        total = evaluation.get("build_value_delta")
    if total is None:
        return None
    return float(total)


def band_for_value(value: float | None, scale: HeatmapScale = DEFAULT_SCALE) -> HeatmapBand:
    if value is None:
        return HeatmapBand.UNKNOWN
    if value < -scale.neutral_abs:
        return HeatmapBand.NEGATIVE
    if abs(value) <= scale.neutral_abs:
        return HeatmapBand.NEUTRAL
    if value < scale.useful_min:
        if value < scale.low_min:
            return HeatmapBand.NEUTRAL
        return HeatmapBand.LOW
    if value < scale.high_min:
        return HeatmapBand.USEFUL
    if value < scale.exceptional_min:
        return HeatmapBand.HIGH
    return HeatmapBand.EXCEPTIONAL


def band_fill_hex(band: HeatmapBand) -> str:
    return BAND_FILL_HEX[band]


def in_band_t(value: float | None, band: HeatmapBand, scale: HeatmapScale = DEFAULT_SCALE) -> float:
    """0–1 position within the named band for gradient only. Does not change the band."""
    if value is None or band in {HeatmapBand.UNKNOWN, HeatmapBand.PENDING, HeatmapBand.NEUTRAL}:
        return 0.0
    if band == HeatmapBand.NEGATIVE:
        return min(1.0, max(0.0, (-float(value) - scale.neutral_abs) / 12.0))
    if band == HeatmapBand.LOW:
        span = scale.useful_min - scale.low_min
        return min(1.0, max(0.0, (float(value) - scale.low_min) / span)) if span else 0.0
    if band == HeatmapBand.USEFUL:
        span = scale.high_min - scale.useful_min
        return min(1.0, max(0.0, (float(value) - scale.useful_min) / span)) if span else 0.0
    if band == HeatmapBand.HIGH:
        span = scale.exceptional_min - scale.high_min
        return min(1.0, max(0.0, (float(value) - scale.high_min) / span)) if span else 0.0
    # exceptional: compress outliers so they do not restyle siblings
    extra = max(0.0, float(value) - scale.exceptional_min)
    return min(1.0, extra / 20.0)


def map_evaluation(
    evaluation: dict,
    *,
    metric: HeatmapMetric | str = HeatmapMetric.VALUE_PER_POINT,
    scale: HeatmapScale = DEFAULT_SCALE,
) -> dict:
    value = heat_value(evaluation, metric)
    band = band_for_value(value, scale)
    return {
        "heatmap_source": HeatmapSource.MY_BUILD_VALUE.value,
        "heatmap_metric": metric.value if isinstance(metric, HeatmapMetric) else str(metric),
        "heat_value": value,
        "band": band.value,
        "fill_hex": band_fill_hex(band),
        "in_band_t": round(in_band_t(value, band, scale), 4),
        "label": BAND_LABEL[band],
    }
