"""R5-A: fixture layer integrity, the inert live canary, lazy imports on the disabled-market path, and negative controls for the
privacy allowlist (so a loosened checker cannot pass silently)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests.market_support import FIXTURES, ROOT, error_response, fixture, listing_set
from tests.test_r5a_market_request_privacy import ALLOWED_HEADERS, assert_search_body_is_allowlisted

pytestmark = pytest.mark.itemcheck


# ------------------------------------------------------------------------------------------------------ fixture layer


def test_fixture_files_exist_and_are_valid_json():
    for name in ("listing_sets.json", "leagues.json", "search_ok.json", "fetch_ok.json", "exchange_ok.json", "errors.json", "rate_headers.json"):
        assert isinstance(fixture(name), dict), name
    assert (FIXTURES / "README.md").read_text(encoding="utf-8").lower().count("invented") >= 1


def test_every_required_failure_mode_has_a_fixture():
    errors = fixture("errors.json")
    for key in (
        "bad_request_400",
        "unauthorized_401",
        "forbidden_403",
        "rate_limited_429",
        "server_error_503",
        "malformed_json",
        "non_object_json",
        "missing_query_id",
        "empty_search",
        "fetch_missing_fields",
        "fetch_result_not_list",
    ):
        assert key in errors, key
    assert [errors[k]["status"] for k in ("bad_request_400", "unauthorized_401", "forbidden_403", "rate_limited_429", "server_error_503")] == [
        400, 401, 403, 429, 503,
    ]
    assert error_response("rate_limited_429").headers["Retry-After"] == "37"


def test_every_confidence_scenario_set_is_present_and_small():
    sets = fixture("listing_sets.json")["sets"]
    assert {"strong", "moderate", "sparse", "volatile", "unusable", "concentrated", "outliers", "partial_fx", "stale", "cheap_seller_skew",
            "deep_unbounded"} <= set(sets)
    for name, data in sets.items():
        assert len(data["listings"]) <= 60, f"{name} is not small"
        for price, currency, seller in data["listings"]:
            assert price > 0 and currency and seller
    assert listing_set("stale")["indexed"].startswith("2020")


def test_fixtures_are_synthetic_no_real_names_urls_or_contacts():
    text = " ".join(path.read_text(encoding="utf-8") for path in FIXTURES.glob("*.json"))
    assert "@" not in text and not re.search(r"https?://|www\.", text.lower())
    sellers = {row[2] for data in fixture("listing_sets.json")["sets"].values() for row in data["listings"]}
    assert all(re.fullmatch(r"(Seller|Other|A|B|Hoarder)\d*", name) for name in sellers), sorted(sellers)
    for league in fixture("leagues.json")["result"]:
        assert "Synthetic" in league["id"] or league["id"] == "Standard"


# ------------------------------------------------------------------------------------------------------ inert live canary


def test_the_live_canary_is_inert_while_the_provider_is_unauthorized(monkeypatch):
    from exilelens.ops.market_canary import run_market_canary

    monkeypatch.setenv("EXILELENS_LIVE_MARKET_CANARY", "1")
    for force in (False, True):
        report = run_market_canary(force=force)
        assert report.ran is False
        assert "production-disabled" in " ".join(report.notes)


# ------------------------------------------------------------------------------------------------------- lazy imports


def _fresh_python(code: str) -> str:
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "QT_QPA_PLATFORM": "offscreen"}
    done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def test_importing_the_app_with_market_prices_off_does_not_load_the_trade2_stack():
    out = _fresh_python(
        "import sys, exilelens.app.controller\n"
        "heavy = ('trade2_client', 'transport', 'providers.live_trade2', 'providers.cached_live_trade2', 'providers.market_session_provider')\n"
        "print([m for m in heavy if 'exilelens.price_check.' + m in sys.modules])\n"
    )
    assert out == "[]", f"the live trade2 stack was imported at startup: {out}"


def test_building_the_disabled_provider_chain_does_not_load_the_trade2_stack():
    out = _fresh_python(
        "import sys\n"
        "from exilelens.price_check.factory import build_default_price_check_providers\n"
        "chain = build_default_price_check_providers(live_market_mode='disabled')\n"
        "print([m for m in ('trade2_client', 'transport', 'providers.live_trade2') if 'exilelens.price_check.' + m in sys.modules])\n"
    )
    assert out == "[]"


def test_the_lazy_provider_exports_still_resolve():
    from exilelens.price_check import providers

    assert providers.LiveTradeComparableProvider.provider_id == "live_trade2"
    assert providers.LiveTrade2Provider is providers.LiveTradeComparableProvider
    assert providers.CachedLiveMarketProvider is not None
    with pytest.raises(AttributeError):
        providers.NoSuchProvider  # noqa: B018


# ------------------------------------------------------------------------------- negative controls for the privacy checker


def _good_body() -> dict:
    return {"query": {"status": {"option": "available"}, "stats": [{"type": "count", "value": {"min": 1}, "filters": [
        {"id": "explicit.stat_3489782002", "value": {"min": 80.1}, "disabled": False}]}]}, "sort": {"price": "asc"}}


def test_the_allowlist_accepts_a_compiled_shape_and_rejects_leaks():
    assert_search_body_is_allowlisted(_good_body(), base_type=None)
    leaks = []
    for mutate in (
        lambda b: b["query"].update(term="Arcane Loop rare ring"),
        lambda b: b["query"].update(name="SYNTH_CANARY_NAME"),
        lambda b: b.update(item_text="Rarity: RARE\nArcane Loop"),
        lambda b: b["query"]["stats"][0]["filters"][0].update(id="Arcane Loop; +89 to maximum Energy Shield"),
        lambda b: b["query"]["stats"][0].update(account="SYNTH_CANARY_ACCOUNT_4242"),
        lambda b: b["query"].update(type="A Base That Is Not The Items Own"),
    ):
        body = json.loads(json.dumps(_good_body()))
        mutate(body)
        with pytest.raises(AssertionError):
            assert_search_body_is_allowlisted(body, base_type="Sapphire Ring")
            leaks.append(body)
    assert not leaks


def test_the_header_allowlist_excludes_identity_carrying_headers():
    assert ALLOWED_HEADERS == {"User-Agent", "Accept", "Content-Type"}
    assert not {"Cookie", "Authorization", "Referer", "X-Forwarded-For"} & ALLOWED_HEADERS
