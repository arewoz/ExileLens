from __future__ import annotations

from typing import Any, Callable

from exilelens.analysis.audit import BuildStateAudit
from exilelens.analysis.cache import ProbeCache
from exilelens.analysis.catalog import ProbeCatalog, ProbeDefinition, UNSUPPORTED_PROBE_IDS
from exilelens.analysis.identity import AnalysisBaseline
from exilelens.errors import EngineError, ItemIncompatible, ItemParseFailed, SlotInvalid
from exilelens.items.consequences import build_warnings
from exilelens.items.resist_caps import analyze_resistances
from exilelens.items.value_profiles import ValueProfile, score_profile
from exilelens.metrics import build_metric_profile


def clone_item_with_mod(item_raw: str, line: str) -> str:
    return clone_item_with_mods(item_raw, [line])


def clone_item_with_mods(item_raw: str, lines: list[str]) -> str:
    text = item_raw.rstrip("\n")
    if not text.strip():
        raise ValueError("empty item cannot carry a probe modifier")
    filtered = [line for line in lines if str(line).strip()]
    if not filtered:
        raise ValueError("probe requires at least one modifier line")
    return f"{text}\n" + "\n".join(filtered) + "\n"


def _pct(metric: dict[str, Any] | None) -> float:
    if not metric:
        return 0.0
    value = metric.get("percent_delta")
    return float(value) if value is not None else 0.0


def score_probe_metrics(
    baseline_raw: dict[str, Any],
    probed_raw: dict[str, Any],
    profile: ValueProfile,
    *,
    primary_field: str = "CombinedDPS",
    primary_confidence: str = "high",
) -> dict[str, Any]:
    metric_profile = build_metric_profile(
        baseline_raw,
        probed_raw,
        primary_field=primary_field,
        confidence=primary_confidence,
    )
    resist = analyze_resistances(baseline_raw, probed_raw)
    warnings = build_warnings(metric_profile, resist, baseline_raw, probed_raw)
    value = score_profile(metric_profile, resist, warnings, profile)
    return {
        "metric_profile": metric_profile,
        "resist_caps": resist,
        "warnings": warnings,
        "value": value,
    }


def detect_breakpoints(resist: dict[str, Any], probe_id: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    element = None
    if probe_id.endswith("_RES") and probe_id != "CHAOS_RES":
        element = probe_id.replace("_RES", "").lower()
    elif probe_id == "CHAOS_RES":
        element = "chaos"
    if not element:
        return events
    info = (resist.get("elements") or {}).get(element) or {}
    state = info.get("state")
    if state in {"CAP_REACHED", "CAP_GAINED"}:
        current = info.get("current")
        cap = info.get("cap_candidate") or info.get("cap_current")
        deficit = None
        if current is not None and cap is not None:
            deficit = max(0.0, float(cap) - float(current))
        events.append(
            {
                "code": "CAP_REACHED",
                "element": element,
                "at": deficit,
                "state": state,
                "label": "CAP RESTORED",
            }
        )
    elif state == "CAP_LOST":
        events.append({"code": "CAP_LOST", "element": element, "state": state, "label": "CAP LOST"})
    return events


def _linearity(samples: list[dict[str, Any]]) -> str:
    if len(samples) < 2:
        return "unknown"
    slopes = []
    for sample in samples:
        mag = float(sample["magnitude"])
        delta = float(((sample.get("value") or {}).get("score_delta") or 0.0))
        if mag == 0:
            continue
        slopes.append(delta / mag)
    if len(slopes) < 2:
        return "unknown"
    avg = sum(slopes) / len(slopes)
    if avg == 0:
        return "flat"
    spread = max(abs(s - avg) for s in slopes)
    if spread > max(0.08, abs(avg) * 0.35):
        return "NON_LINEAR"
    return "linear"


class ProbeEngine:
    def __init__(
        self,
        engine: Any,
        catalog: ProbeCatalog | None = None,
        cache: ProbeCache | None = None,
    ) -> None:
        self.engine = engine
        self.catalog = catalog or ProbeCatalog()
        self.cache = cache or ProbeCache()
        self.pob_recalcs = 0
        self.probe_times_ms: list[float] = []

    def apply_probe_item(self, item_raw: str, definition: ProbeDefinition, magnitude: float) -> str:
        return clone_item_with_mod(item_raw, definition.line(magnitude))

    def run_probe(
        self,
        *,
        slot: str,
        item_raw: str,
        probe_id: str,
        magnitude: float,
        baseline: AnalysisBaseline,
        profile: ValueProfile,
        primary_field: str = "CombinedDPS",
        primary_confidence: str = "high",
        context: str | None = None,
    ) -> dict[str, Any]:
        if probe_id in UNSUPPORTED_PROBE_IDS or self.catalog.is_unsupported(probe_id):
            return {
                "probe_id": probe_id,
                "status": "UNSUPPORTED_PROBE",
                "magnitude": magnitude,
                "confidence": "UNSUPPORTED",
                "label": "MARGINAL VALUE",
            }
        definition = self.catalog.get(probe_id)
        if definition is None:
            return {
                "probe_id": probe_id,
                "status": "INVALID_PROBE",
                "magnitude": magnitude,
                "confidence": "UNSUPPORTED",
            }

        cache_key = self.cache.key(
            fingerprint=baseline.fingerprint,
            generation=baseline.generation,
            probe_id=probe_id,
            magnitude=magnitude,
            context=baseline.context,
        )
        cached = self.cache.get(cache_key)
        if cached is not None:
            scored = score_probe_metrics(
                cached["baseline_raw"],
                cached["probed_raw"],
                profile,
                primary_field=primary_field,
                primary_confidence=primary_confidence,
            )
            return {**cached["raw_result"], **scored, "cache_hit": True, "label": "MARGINAL VALUE"}

        probed_raw_item = self.apply_probe_item(item_raw, definition, magnitude)
        import time

        started = time.perf_counter()
        try:
            evaluation = self.engine.evaluate_candidate(slot, probed_raw_item, context=context or baseline.context)
        except (ItemParseFailed, ItemIncompatible, SlotInvalid, EngineError) as exc:
            return {
                "probe_id": probe_id,
                "status": "REJECTED",
                "magnitude": magnitude,
                "confidence": "UNSUPPORTED",
                "error": getattr(exc, "code", type(exc).__name__),
                "message": str(exc),
            }
        elapsed_ms = (time.perf_counter() - started) * 1000
        self.pob_recalcs += 1
        self.probe_times_ms.append(elapsed_ms)

        restore = evaluation.get("restore") or {}
        if not restore.get("pass"):
            return {
                "probe_id": probe_id,
                "status": "RESTORE_FAILED",
                "magnitude": magnitude,
                "confidence": "UNSUPPORTED",
                "restore": restore,
            }

        scored = score_probe_metrics(
            evaluation["baseline"]["metrics"],
            evaluation["candidate"]["metrics"],
            profile,
            primary_field=primary_field,
            primary_confidence=primary_confidence,
        )
        breakpoints = detect_breakpoints(scored["resist_caps"], probe_id)
        offense_pct = _pct(scored["metric_profile"].get("primary_offense"))
        ehp_pct = _pct(scored["metric_profile"].get("ehp"))
        score_delta = float(scored["value"]["score_delta"])
        per_unit = None
        if magnitude:
            per_unit = round(score_delta / float(magnitude), 4)
        metrics_changed = (
            abs(offense_pct) > 0.001
            or abs(ehp_pct) > 0.001
            or bool(breakpoints)
            or any(abs(float(v.get("absolute_delta") or 0)) > 0.01 for v in scored["metric_profile"].values() if isinstance(v, dict))
        )
        confidence = definition.confidence.upper() if metrics_changed else "LOW"
        status = "ok" if metrics_changed else "NO_SIGNAL"
        result = {
            "probe_id": probe_id,
            "status": status,
            "family": definition.family,
            "label": "MARGINAL VALUE",
            "display_name": definition.label,
            "magnitude": magnitude,
            "unit": definition.unit,
            "line": definition.line(magnitude),
            "slot": slot,
            "offense_percent": round(offense_pct, 3),
            "ehp_percent": round(ehp_pct, 3),
            "score_delta": score_delta,
            "marginal_value_per_unit": per_unit,
            "breakpoints": breakpoints,
            "confidence": confidence,
            "restore": restore,
            "fingerprint": {
                "baseline": evaluation["baseline"]["fingerprint_hash"],
                "restored": evaluation["restored"]["fingerprint_hash"],
                "match": evaluation["baseline"]["fingerprint_hash"] == evaluation["restored"]["fingerprint_hash"],
            },
            "elapsed_ms": elapsed_ms,
            "cache_hit": False,
            "universal": False,
        }
        result.update(scored)
        self.cache.put(
            cache_key,
            {
                "baseline_raw": evaluation["baseline"]["metrics"],
                "probed_raw": evaluation["candidate"]["metrics"],
                "raw_result": {k: v for k, v in result.items() if k not in {"metric_profile", "resist_caps", "warnings", "value"}},
            },
        )
        return result

    def sample_nonlinear(
        self,
        *,
        slot: str,
        item_raw: str,
        probe_id: str,
        baseline: AnalysisBaseline,
        profile: ValueProfile,
        should_yield: Callable[[], bool] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        definition = self.catalog.require(probe_id)
        samples = []
        skipped = None
        for magnitude in definition.magnitudes:
            if should_yield and should_yield():
                skipped = "yielded"
                break
            samples.append(
                self.run_probe(
                    slot=slot,
                    item_raw=item_raw,
                    probe_id=probe_id,
                    magnitude=magnitude,
                    baseline=baseline,
                    profile=profile,
                    **kwargs,
                )
            )
        return {
            "probe_id": probe_id,
            "samples": samples,
            "linearity": _linearity([s for s in samples if s.get("status") == "ok"]),
            "skipped": skipped,
        }
