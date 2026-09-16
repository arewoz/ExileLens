from __future__ import annotations

from typing import Any
from urllib.parse import quote


def trade_site_search_hint(intent: dict[str, Any]) -> str:
    """Human-readable hint for manual trade site search. No API calls."""
    slot = intent.get("slot") or "SLOT"
    required = intent.get("required") or []
    bits = [f"slot={slot}"]
    for row in required[:3]:
        stat = row.get("stat") or row.get("probe_id")
        minimum = row.get("minimum")
        if stat and minimum is not None:
            bits.append(f"{stat}>={minimum}")
    return " · ".join(bits)


def official_trade_site_url(league: str = "Standard", query_hint: str = "") -> str:
    """Open the official PoE2 trade site in a browser — no scraping."""
    base = "https://www.pathofexile.com/trade2/search/poe2/"
    league_slug = quote(league, safe="")
    url = f"{base}{league_slug}"
    if query_hint:
        return f"{url}?q={quote(query_hint)}"
    return url
