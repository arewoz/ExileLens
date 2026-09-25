from __future__ import annotations

import re
from typing import Any

from exilelens.market.models import CandidateListing, MarketQueryPlan

_STAT_HINTS = {
    "fire_res": [r"fire resistance", r"to fire res"],
    "cold_res": [r"cold resistance", r"to cold res"],
    "lightning_res": [r"lightning resistance", r"to lightning res"],
    "chaos_res": [r"chaos resistance", r"to chaos res"],
    "cast_speed": [r"cast speed"],
    "attack_speed": [r"attack speed"],
    "life": [r"maximum life", r"to life"],
    "energy_shield": [r"maximum energy shield", r"to energy shield"],
    "mana": [r"maximum mana", r"to mana"],
    "movement_speed": [r"movement speed"],
    "lightning_damage": [r"lightning damage"],
    "fire_damage": [r"fire damage"],
    "cold_damage": [r"cold damage"],
}


def _text_blob(listing: CandidateListing) -> str:
    return listing.item_raw.lower()


def _matches_stat(text: str, stat: str) -> bool:
    patterns = _STAT_HINTS.get(stat, [stat.replace("_", " ")])
    return any(re.search(pat, text) for pat in patterns)


def _intent_score(listing: CandidateListing, plan: MarketQueryPlan) -> float:
    text = _text_blob(listing)
    score = 0.0
    for filt in plan.filters:
        tier = filt.get("tier")
        stat = str(filt.get("stat") or filt.get("probe_id") or "").lower()
        probe = str(filt.get("probe_id") or "").lower()
        key = stat or probe.replace("_res", "_res")
        if tier == "REQUIRED" and _matches_stat(text, key):
            score += 12.0
        elif tier == "HIGH_VALUE" and _matches_stat(text, key):
            score += 6.0
        elif tier == "USEFUL" and _matches_stat(text, key):
            score += 2.0
        elif tier == "AVOID" and _matches_stat(text, key):
            score -= 4.0
    if listing.label:
        label = listing.label.lower()
        if "upgrade" in label or "cap" in label:
            score += 3.0
        if "downgrade" in label or "trap" in label:
            score -= 2.0
    return score


def prefilter_candidates(
    listings: list[CandidateListing],
    plan: MarketQueryPlan,
    *,
    limit: int | None = None,
) -> list[CandidateListing]:
    """Broad, recall-oriented prefilter — not aggressive."""
    cap = limit or plan.prefilter_limit
    if len(listings) <= cap:
        return list(listings)
    ranked = sorted(listings, key=lambda row: _intent_score(row, plan), reverse=True)
    return ranked[:cap]
