"""Deterministic adaptive market search guidance (not AI)."""

from __future__ import annotations

from typing import Any

from exilelens.market_assist.models import CaptureQueueState, MarketCaptureObservation, MarketCaptureSession

_EVIDENCE_POB = "pob_probe"
_EVIDENCE_SESSION = "session_correlation"
_EVIDENCE_INTENT = "search_intent_only"

_HYSTERESIS_MARGIN = 0.15


def _intent_prior(search_intent: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not search_intent:
        return []
    rows: list[dict[str, Any]] = []
    for tier_key in ("required", "high_value", "useful"):
        for row in search_intent.get(tier_key) or []:
            probe_id = str(row.get("probe_id") or row.get("stat") or "")
            if not probe_id:
                continue
            rows.append(
                {
                    "stat": probe_id,
                    "display": row.get("display_name") or probe_id.replace("_", " ").title(),
                    "tier": row.get("tier") or tier_key.upper(),
                    "score": float(row.get("score_delta") or row.get("marginal_value") or 0.0),
                    "evidence": _EVIDENCE_INTENT,
                    "confidence": str(row.get("confidence") or "medium"),
                }
            )
    rows.sort(key=lambda r: (-r["score"], r["stat"]))
    return rows


def _session_correlations(observations: list[MarketCaptureObservation]) -> dict[str, float]:
    """Correlate stat presence in strong vs weak session items."""
    strong: list[dict[str, Any]] = []
    weak: list[dict[str, Any]] = []
    for row in observations:
        if row.queue_state is not CaptureQueueState.EVALUATED or not row.evaluation:
            continue
        delta = float(row.evaluation.get("build_value_delta") or 0.0)
        comparison = row.evaluation.get("comparison") or {}
        metrics = (comparison.get("candidate") or {}).get("metrics") or {}
        payload = {"delta": delta, "metrics": metrics}
        if delta >= 3.0:
            strong.append(payload)
        elif delta <= 0.5:
            weak.append(payload)

    if len(strong) < 2:
        return {}

    stat_keys = ("CombinedDPS", "TotalEHP", "maximum Mana", "Cast Speed", "FireResist", "ColdResist", "LightningResist")
    scores: dict[str, float] = {}
    for key in stat_keys:
        strong_vals = [float((row["metrics"].get(key) or 0)) for row in strong if key in row["metrics"]]
        weak_vals = [float((row["metrics"].get(key) or 0)) for row in weak if key in row["metrics"]]
        if not strong_vals:
            continue
        strong_avg = sum(strong_vals) / len(strong_vals)
        weak_avg = sum(weak_vals) / len(weak_vals) if weak_vals else 0.0
        lift = strong_avg - weak_avg
        if lift > 0 and (weak_avg == 0 or lift / max(abs(weak_avg), 1.0) >= 0.05):
            scores[key] = lift
    return scores


def _confounding_filter(
    prior: list[dict[str, Any]],
    session_scores: dict[str, float],
    probe_scores: dict[str, float],
) -> list[dict[str, Any]]:
    """Drop stats that appear on all strong items but probe shows negligible marginal value."""
    merged: dict[str, dict[str, Any]] = {}
    for row in prior:
        merged[row["stat"]] = dict(row)

    for stat, lift in session_scores.items():
        probe = probe_scores.get(stat, 0.0)
        if lift > 0 and probe < 0.5:
            continue
        current = merged.get(stat)
        score = lift + probe * 2.0
        if current:
            if score > current["score"] * (1.0 + _HYSTERESIS_MARGIN):
                current["score"] = score
                current["evidence"] = _EVIDENCE_SESSION
        else:
            merged[stat] = {
                "stat": stat,
                "display": stat.replace("_", " ").title(),
                "tier": "USEFUL",
                "score": score,
                "evidence": _EVIDENCE_SESSION,
                "confidence": "medium",
            }

    for stat, probe in probe_scores.items():
        if probe <= 0:
            continue
        current = merged.get(stat)
        if current and probe <= current["score"] * _HYSTERESIS_MARGIN:
            continue
        if current:
            blended = current["score"] * 0.6 + probe * 0.4
            if blended > current["score"] * (1.0 + _HYSTERESIS_MARGIN):
                current["score"] = blended
                current["evidence"] = _EVIDENCE_POB
        else:
            merged[stat] = {
                "stat": stat,
                "display": stat.replace("_", " ").title(),
                "tier": "USEFUL",
                "score": probe,
                "evidence": _EVIDENCE_POB,
                "confidence": "medium",
            }

    ranked = sorted(merged.values(), key=lambda r: (-float(r["score"]), r["stat"]))
    return ranked[:8]


class AdaptiveMarketGuidance:
    """Search guidance from SearchIntent + session evidence + bounded PoB probes."""

    def __init__(self) -> None:
        self._last_guidance: dict[str, Any] = {}

    def compute(
        self,
        session: MarketCaptureSession,
        *,
        probe_scores: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        prior = _intent_prior(session.search_intent)
        session_scores = _session_correlations(session.observations)
        probes = probe_scores or {}
        ranked = _confounding_filter(prior, session_scores, probes)
        next_search = ranked[:4]
        if len(next_search) < 2 and prior:
            for row in prior:
                if row["stat"] not in {item["stat"] for item in next_search}:
                    next_search.append(row)
                if len(next_search) >= 2:
                    break

        guidance = {
            "next_search": [
                {
                    "stat": row["stat"],
                    "display": row["display"],
                    "priority": index + 1,
                    "evidence": row["evidence"],
                    "confidence": row["confidence"],
                    "action": f"Filter for {row['display']}",
                }
                for index, row in enumerate(next_search[:4])
            ],
            "prior_count": len(prior),
            "session_observations": len(session.observations),
            "evaluated": session.evaluated_count,
            "hysteresis_applied": bool(self._last_guidance),
        }
        if self._last_guidance:
            prev_stats = [row.get("stat") for row in self._last_guidance.get("next_search") or []]
            new_stats = [row.get("stat") for row in guidance.get("next_search") or []]
            if prev_stats == new_stats:
                guidance["stable"] = True
        self._last_guidance = guidance
        return guidance

    def clipboard_hint(self, guidance: dict[str, Any]) -> str:
        rows = guidance.get("next_search") or []
        if not rows:
            return "Search broadly — no guidance yet."
        parts = [str(row.get("display") or row.get("stat")) for row in rows[:4]]
        return "NEXT SEARCH: " + ", ".join(parts)
