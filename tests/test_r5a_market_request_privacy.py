"""R5-A: what a market request may contain. Structural allowlist, plus canaries planted where private data could leak from.

A request may carry: the league (URL path), the item type/base where supported, rarity, mapped stat ids with value ranges, the
equipment/misc filters the plan needs, the sort and currency ids. It must NOT carry PoB XML, a build name, account or character
identity, clipboard history, other equipped items, telemetry/Patreon identity, local paths, or the item text as an opaque blob.
"""

from __future__ import annotations

import json
import os
import re
import urllib.parse
from pathlib import Path

import pytest

from tests.market_support import (
    LEAGUE,
    FakeClock,
    RING_ITEM,
    compiled_request,
    make_client,
    make_provider,
    scenario_transport,
)

pytestmark = pytest.mark.itemcheck

CANARIES = (
    "SYNTH_CANARY_NAME",
    "SYNTH_CANARY_ACCOUNT_4242",
    "SYNTH_CANARY_CHARACTER",
    "SYNTH_CANARY_BUILD_NAME",
    "SYNTH_CANARY_POB_XML",
    "SYNTH_CANARY_PATREON_ID",
)

ITEM_WITH_CANARIES = (
    "Rarity: RARE\n"
    "SYNTH_CANARY_NAME\n"
    "Sapphire Ring\n"
    "LevelReq: 80\n"
    "Implicits: 1\n"
    "+30% to Cold Resistance\n"
    "+179 to maximum Mana\n"
    "+89 to maximum Energy Shield\n"
    "60% increased Lightning Damage\n"
    "+45% to Fire Resistance\n"
    "40% increased Cast Speed\n"
    "+27% to Chaos Resistance\n"
    "Crafted for SYNTH_CANARY_ACCOUNT_4242 on SYNTH_CANARY_CHARACTER\n"
    "<PathOfBuilding>SYNTH_CANARY_POB_XML</PathOfBuilding> SYNTH_CANARY_BUILD_NAME SYNTH_CANARY_PATREON_ID\n"
)

ALLOWED_HEADERS = {"User-Agent", "Accept", "Content-Type"}
STAT_ID = re.compile(r"^[a-z_]+\.[a-z_]*[a-z0-9_]+$")
IDENT = re.compile(r"^[a-z_]+$")
OPTION = re.compile(r"^[a-z_.0-9]+$")


def _only(keys, allowed, where):
    extra = set(keys) - set(allowed)
    assert not extra, f"unexpected key(s) {sorted(extra)} in {where}: every new request field needs a privacy review"


def _check_value_block(block, where):
    assert isinstance(block, dict)
    _only(block, {"min", "max", "option"}, where)
    for key in ("min", "max"):
        if key in block:
            assert isinstance(block[key], (int, float)) and not isinstance(block[key], bool), where
    if "option" in block:
        assert OPTION.match(str(block["option"])), (where, block["option"])


def assert_search_body_is_allowlisted(body: dict, *, base_type: str | None):
    _only(body, {"query", "sort"}, "body")
    assert body["sort"] == {"price": "asc"}
    query = body["query"]
    _only(query, {"status", "type", "filters", "stats"}, "query")
    assert query["status"] == {"option": "available"}
    if "type" in query:
        assert base_type and query["type"] == base_type, "only the item's own base type may appear as free text"
    filters = query.get("filters", {})
    _only(filters, {"type_filters", "misc_filters", "equipment_filters"}, "filters")
    for group, allowed in (("type_filters", {"category", "rarity"}), ("misc_filters", {"ilvl", "corrupted", "quality"})):
        if group in filters:
            _only(filters[group], {"filters"}, group)
            _only(filters[group]["filters"], allowed, group)
            for name, block in filters[group]["filters"].items():
                _check_value_block(block, f"{group}.{name}")
    if "equipment_filters" in filters:
        _only(filters["equipment_filters"], {"filters"}, "equipment_filters")
        for name, block in filters["equipment_filters"]["filters"].items():
            assert IDENT.match(name), name
            _check_value_block(block, f"equipment_filters.{name}")
    for group in query.get("stats", []):
        _only(group, {"type", "value", "filters"}, "stat group")
        assert group["type"] in {"and", "count", "not", "if", "weight"}
        if "value" in group:
            _check_value_block(group["value"], "stat group value")
        for row in group["filters"]:
            _only(row, {"id", "value", "disabled"}, "stat filter")
            assert STAT_ID.match(row["id"]), row["id"]
            if "value" in row:
                _check_value_block(row["value"], row["id"])


def _text_of(request) -> str:
    body = request.body.decode("utf-8") if request.body else ""
    return " ".join([request.method, request.url, json.dumps(dict(request.headers)), body])


def _run_pipeline_requests():
    transport = scenario_transport(specs=[[31 + i, "exalted" if i % 2 else "divine", f"Seller{i:02d}"] for i in range(14)], total=40)
    clock = FakeClock()
    client = make_client(transport, clock=clock)
    request = compiled_request(ITEM_WITH_CANARIES)
    make_provider(client).lookup(request)
    clock.advance(600.0)  # the lookup already used the exchange/search windows; the direct calls below are paced by the same policy
    client.exchange_rate(LEAGUE, "divine", "exalted")
    client.list_leagues()
    return transport, request


def test_requests_carry_only_allowlisted_fields():
    transport, request = _run_pipeline_requests()
    seen = {"search": 0, "fetch": 0, "exchange": 0, "leagues": 0}
    base_type = request.plan.base.base_type
    for sent in transport.requests:
        parsed = urllib.parse.urlparse(sent.url)
        assert parsed.scheme == "https" and parsed.netloc.endswith("pathofexile.com")
        assert set(sent.headers) <= ALLOWED_HEADERS, set(sent.headers) - ALLOWED_HEADERS
        if "/search/" in parsed.path:
            seen["search"] += 1
            assert parsed.path == "/api/trade2/search/poe2/" + urllib.parse.quote(LEAGUE, safe="") and not parsed.query
            assert_search_body_is_allowlisted(json.loads(sent.body), base_type=base_type)
        elif "/fetch/" in parsed.path:
            seen["fetch"] += 1
            assert sent.method == "GET" and sent.body is None
            ids = parsed.path.rsplit("/", 1)[1].split(",")
            assert all(re.fullmatch(r"syn\d{3}", item) for item in ids)  # opaque listing ids returned by the search, nothing of ours
            assert set(urllib.parse.parse_qs(parsed.query)) == {"query"}
        elif "/exchange/" in parsed.path:
            seen["exchange"] += 1
            payload = json.loads(sent.body)
            _only(payload, {"query", "sort", "engine"}, "exchange body")
            _only(payload["query"], {"status", "have", "want"}, "exchange query")
            for currency in payload["query"]["have"] + payload["query"]["want"]:
                assert IDENT.match(currency), currency  # currency ids only
        elif parsed.path.endswith("/data/leagues"):
            seen["leagues"] += 1
            assert sent.body is None and not parsed.query
        else:
            pytest.fail(f"unexpected request path {parsed.path}")
    assert seen["search"] == 1 and seen["fetch"] >= 1 and seen["exchange"] >= 1 and seen["leagues"] == 1


def test_no_private_canary_reaches_any_request():
    transport, _ = _run_pipeline_requests()
    assert transport.requests
    blob = " ".join(_text_of(sent) for sent in transport.requests)
    for canary in CANARIES:
        assert canary not in blob, f"{canary} leaked into a market request"
    assert "PathOfBuilding" not in blob and "<" not in blob


def test_the_item_text_is_never_sent_as_an_opaque_blob():
    transport, request = _run_pipeline_requests()
    blob = " ".join(_text_of(sent) for sent in transport.requests)
    assert request.item_raw not in blob
    for sent in transport.requests:
        if sent.body:
            assert "\\n" not in sent.body.decode("utf-8"), "a multi-line text field was sent"
            assert "Rarity:" not in sent.body.decode("utf-8")
    # No individual long free-text mod line either: only mapped stat ids and numbers.
    body = json.loads(next(s for s in transport.requests if "/search/" in s.url).body)
    assert not any(len(text) > 60 for text in _strings(body))


def _strings(value):
    if isinstance(value, dict):
        for key, inner in value.items():
            yield str(key)
            yield from _strings(inner)
    elif isinstance(value, list):
        for inner in value:
            yield from _strings(inner)
    elif isinstance(value, str):
        yield value


def test_no_local_path_or_machine_identity_reaches_a_request():
    transport, _ = _run_pipeline_requests()
    blob = " ".join(_text_of(sent) for sent in transport.requests).lower()
    for private in {str(Path.home()), os.getcwd(), str(Path(RING_ITEM).resolve().parents[2]), os.environ.get("USERPROFILE", ""),
                    os.environ.get("USERNAME", ""), os.environ.get("COMPUTERNAME", "")}:
        if private and len(private) > 3:
            assert private.lower() not in blob, f"{private!r} appeared in a market request"
    assert "c:\\" not in blob and "c:/" not in blob


def test_the_name_of_a_rare_is_not_sent():
    """Rare names are not a searchable property; the query uses the mapped stats and category instead."""
    transport, _ = _run_pipeline_requests()
    search = json.loads(next(s for s in transport.requests if "/search/" in s.url).body)
    assert "name" not in search["query"]
    assert "SYNTH_CANARY_NAME" not in json.dumps(search)
