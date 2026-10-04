"""Shared offline harness for the R5-A market tests: synthetic fixtures + a scriptable fake transport. No network, no PoB."""

from __future__ import annotations

import json
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from exilelens.price_check.cache import PriceCheckCache, TimedResponseCache
from exilelens.price_check.models import CompiledPriceCheckRequest, LeagueContext, LeagueStatus
from exilelens.price_check.rate_limit import RateLimitState
from exilelens.price_check.rate_policy import TradePolicyRegistry
from exilelens.price_check.trade2_client import Trade2Client
from exilelens.price_check.transport import TransportRequest, TransportResponse

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "market"
LEAGUE = "Synthetic League"
RING_ITEM = ROOT / "fixtures" / "items" / "core04_offense_ring.txt"


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def listing_set(name: str) -> dict[str, Any]:
    return fixture("listing_sets.json")["sets"][name]


def error_response(name: str) -> TransportResponse:
    row = fixture("errors.json")[name]
    return TransportResponse(int(row["status"]), dict(row["headers"]), str(row["body"]).encode("utf-8"))


def json_response(payload: Any, status: int = 200, headers: dict[str, str] | None = None) -> TransportResponse:
    return TransportResponse(status, headers or {}, json.dumps(payload).encode("utf-8"))


def expand_listings(specs: list[list[Any]], *, indexed: str = "2099-01-01T00:00:00Z", start: int = 0) -> list[dict[str, Any]]:
    """[price, currency, seller] -> a trade2-shaped fetch row (synthetic item: a rare Sapphire Ring)."""
    rows = []
    for offset, (price, currency, seller) in enumerate(specs):
        rows.append({
            "id": f"syn{start + offset:03d}",
            "listing": {"indexed": indexed, "account": {"name": seller}, "price": {"type": "~price", "amount": price, "currency": currency}},
            "item": {"rarity": "Rare", "typeLine": "Sapphire Ring", "explicitMods": ["+89 to maximum Energy Shield", "40% increased Cast Speed"]},
        })
    return rows


class FakeClock:
    """Injected monotonic clock: nothing in the market tests sleeps for real."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@dataclass
class FakeTransport:
    """Records every request; answers from `handler(request)`. The handler may return a TransportResponse or raise/return an exception."""

    handler: Callable[[TransportRequest], Any]
    requests: list[TransportRequest] = field(default_factory=list)

    def __call__(self, request: TransportRequest) -> TransportResponse:
        self.requests.append(request)
        outcome = self.handler(request)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def paths(self) -> list[str]:
        return [urllib.parse.urlparse(r.url).path for r in self.requests]

    def count(self, fragment: str) -> int:
        return sum(1 for r in self.requests if fragment in r.url)


def scenario_transport(name: str | None = None, *, specs: list[list[Any]] | None = None, total: int | None = None,
                       indexed: str = "2099-01-01T00:00:00Z") -> FakeTransport:
    """A synthetic trade2: one search (ids for the scenario), fetch by id (<=10 per call), exchange and leagues from fixtures."""
    data = listing_set(name) if name else {"total": total or len(specs or []), "listings": specs or []}
    indexed = data.get("indexed", indexed)
    rows = expand_listings(data["listings"], indexed=indexed)
    by_id = {row["id"]: row for row in rows}
    search_body = {"id": "synthetic-query-0001", "total": int(total if total is not None else data["total"]), "result": [r["id"] for r in rows]}

    def handler(request: TransportRequest):
        path = urllib.parse.urlparse(request.url).path
        if "/search/" in path:
            return json_response(search_body)
        if "/fetch/" in path:
            ids = path.rsplit("/", 1)[1].split(",")
            return json_response({"result": [by_id[i] for i in ids if i in by_id]})
        if "/exchange/" in path:
            return json_response(fixture("exchange_ok.json"))
        if path.endswith("/data/leagues"):
            return json_response(fixture("leagues.json"))
        return TransportResponse(404, {}, b"{}")

    return FakeTransport(handler)


def make_client(transport: Callable[[TransportRequest], TransportResponse], *, clock: Callable[[], float] | None = None) -> Trade2Client:
    """A client that shares no process-global state with any other test."""
    from exilelens.price_check.currency_fx import reset_fx_cache

    reset_fx_cache()
    registry = TradePolicyRegistry(clock) if clock is not None else TradePolicyRegistry()
    return Trade2Client(
        transport=transport,
        rate_limit_state=RateLimitState(),
        query_cache=TimedResponseCache(ttl_seconds=90.0),
        listing_cache=TimedResponseCache(ttl_seconds=120.0),
        policy_registry=registry,
    )


def make_provider(client: Trade2Client):
    from exilelens.price_check.market_session import MarketSessionCache
    from exilelens.price_check.providers.live_trade2 import LiveTradeComparableProvider
    from exilelens.price_check.signature_store import MarketSignatureStore

    return LiveTradeComparableProvider(
        client=client, cache=PriceCheckCache(), league=LEAGUE, session=MarketSessionCache(), signature_store=MarketSignatureStore(),
    )


def compiled_request(item_text: str | None = None, *, league: str = LEAGUE) -> CompiledPriceCheckRequest:
    from exilelens.items.metadata import parse_lightweight_metadata
    from exilelens.items.raw_input import RawItemInput
    from exilelens.price_check.market_plan import compile_plan, plan_for_item

    text = item_text if item_text is not None else RING_ITEM.read_text(encoding="utf-8")
    meta = parse_lightweight_metadata(RawItemInput.from_text(text))
    plan = plan_for_item(text, category=meta.category, base_type=meta.base_type, rarity=meta.rarity, item_level=meta.ilvl,
                         quality=meta.quality, corrupted=meta.corrupted)
    compiled = compile_plan(plan)
    return CompiledPriceCheckRequest(item_raw=text, content_hash="synthetic-hash", league=LeagueContext(league=league, status=LeagueStatus.KNOWN),
                                     request_id=1, compiled_query=compiled, plan=plan, generation=1)


def walk_strings(value: Any):
    if isinstance(value, dict):
        for key, inner in value.items():
            yield str(key)
            yield from walk_strings(inner)
    elif isinstance(value, (list, tuple)):
        for inner in value:
            yield from walk_strings(inner)
    elif isinstance(value, str):
        yield value
