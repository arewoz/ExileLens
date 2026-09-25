"""Bounded live trade2 canary. Never part of the default test suite."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from exilelens.ops.models import StageStatus
from exilelens.price_check.comparable_query import build_search_query
from exilelens.price_check.trade2_client import Trade2Client, Trade2Error
from exilelens.price_check.trade2_query import build_trade2_search_body

MAX_HTTP_REQUESTS = 2


@dataclass
class MarketCanaryReport:
    ran: bool
    stages: dict[str, str] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ran": self.ran,
            "stages": self.stages,
            "metrics": self.metrics,
            "notes": self.notes,
            "budget": {"max_http_requests": MAX_HTTP_REQUESTS, "fetch": False},
        }


def canary_enabled() -> bool:
    return os.environ.get("EXILELENS_LIVE_MARKET_CANARY", "").strip().lower() in {"1", "true", "yes"}


def run_market_canary(*, force: bool = False, item_raw: str | None = None) -> MarketCanaryReport:
    if not force and not canary_enabled():
        return MarketCanaryReport(
            ran=False,
            notes=["Set EXILELENS_LIVE_MARKET_CANARY=1 or pass --live. Default suite never calls trade2."],
        )
    stages = {
        "endpoint_reachable": StageStatus.NOT_CHECKED.value,
        "query_accepted": StageStatus.NOT_CHECKED.value,
        "listings_retrieved": StageStatus.NOT_CHECKED.value,
        "schema_parseable": StageStatus.NOT_CHECKED.value,
        "currencies_recognized": StageStatus.NOT_CHECKED.value,
        "rate_limit_handling": StageStatus.NOT_CHECKED.value,
    }
    metrics: dict[str, Any] = {}
    notes = [f"budget={MAX_HTTP_REQUESTS} HTTP requests, fetch skipped"]
    if item_raw is None:
        from exilelens.ops.market_health import load_default_fixtures

        item_raw, _listings = load_default_fixtures()
    client = Trade2Client()
    try:
        league = client.resolve_active_league() or "Standard"
        stages["endpoint_reachable"] = StageStatus.PASS.value
        metrics["league"] = league
    except (Trade2Error, OSError) as exc:
        stages["endpoint_reachable"] = StageStatus.FAIL.value
        notes.append(f"league resolve failed: {exc}")
        status = getattr(exc, "http_status", None)
        stages["rate_limit_handling"] = StageStatus.PASS.value if status == 429 else StageStatus.NOT_CHECKED.value
        return MarketCanaryReport(ran=True, stages=stages, metrics=metrics, notes=notes)

    body = build_trade2_search_body(build_search_query(item_raw, league=league))
    try:
        result = client.search(league, body)
        stages["query_accepted"] = StageStatus.PASS.value
        metrics["search_total"] = result.total
        metrics["result_ids"] = len(result.result_ids)
        stages["listings_retrieved"] = StageStatus.PASS.value if result.result_ids else StageStatus.DEGRADED.value
        stages["schema_parseable"] = StageStatus.PASS.value if result.query_id else StageStatus.FAIL.value
        stages["currencies_recognized"] = StageStatus.NOT_CHECKED.value
        stages["rate_limit_handling"] = StageStatus.PASS.value
        notes.append("listing fetch skipped on purpose")
    except Trade2Error as exc:
        status = getattr(exc, "http_status", None)
        stages["query_accepted"] = StageStatus.DEGRADED.value if status == 429 else StageStatus.FAIL.value
        stages["rate_limit_handling"] = StageStatus.PASS.value if status == 429 else StageStatus.DEGRADED.value
        notes.append(f"search failed: {exc}")
    except OSError as exc:
        stages["query_accepted"] = StageStatus.FAIL.value
        notes.append(f"search transport failed: {exc}")
    return MarketCanaryReport(ran=True, stages=stages, metrics=metrics, notes=notes)
