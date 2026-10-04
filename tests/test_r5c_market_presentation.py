"""R5-C: how MarketEvidence v1 reads in the compact tooltip and More Info, and what is deliberately absent.

Evidence comes from the synthetic R5-A/B pipeline or is built directly; nothing here touches a network or PoB.
"""

from __future__ import annotations

import re

import pytest

from exilelens.items.compact_tooltip import apply_compact_tooltip
from exilelens.items.market_presentation import market_view, pairing_line
from exilelens.items.more_info import MORE_INFO_SECTION_ORDER, build_more_info
from exilelens.price_check.market_evidence import (
    BandBasis,
    EvidenceStatus,
    Freshness,
    ListedPrice,
    MarketEvidence,
    MarketPrice,
    evidence_from_price_result,
    status_evidence,
)
from exilelens.price_check.price_trust import EstimateState, MarketHeadline
from tests.market_support import compiled_request, make_client, make_provider, scenario_transport

pytestmark = pytest.mark.itemcheck

STRONG = MarketHeadline.STRONG_COMPARABLE_SET
WEAK = MarketHeadline.WEAK_COMPARABLE_SET
SPARSE = MarketHeadline.SPARSE_MARKET
VOLATILE = MarketHeadline.VOLATILE_ESTIMATE
NONE_ = MarketHeadline.NO_TRUSTWORTHY_ESTIMATE


def _ev(headline=STRONG, *, low=30.0, high=36.0, point=33.0, currency="exalted", freshness=Freshness.CURRENT, count=14, price=True,
        listed=None, reason="", reasons=(), coverage=(), basis=BandBasis.CHEAPEST_COMPARABLES, sellers=14) -> dict:
    evidence = MarketEvidence(
        status=EvidenceStatus.AVAILABLE,
        reason=reason,
        league="Synthetic League",
        fetched_at=1.0,
        freshness=freshness,
        headline=headline,
        estimate_state=EstimateState.HIGH_CONFIDENCE if headline is STRONG else EstimateState.ASSISTED_ESTIMATE,
        reasons=tuple(reasons),
        price=MarketPrice(currency, low, high, point) if price else None,
        band_basis=basis if price else None,
        comparable_count=count,
        distinct_sellers=sellers,
        coverage=tuple(coverage),
    )
    if listed is not None:
        evidence = evidence.with_listed(listed)
    return evidence.to_dict()


def _pipeline_evidence(name: str) -> dict:
    result = make_provider(make_client(scenario_transport(name))).lookup(compiled_request())
    return evidence_from_price_result(result, fetched_at=1.0).to_dict()


def _outcome(verdict="MEANINGFUL_UPGRADE", quality="FULL", *, axes=None, conflict="NONE", pattern="IMPROVEMENT") -> dict:
    axes = axes if axes is not None else {
        "OFFENSE": {"material_positive": True, "material_negative": False, "metrics": [{"key": "primary_offense", "percent_delta": 6.8}]},
        "DEFENSE": {"material_positive": False, "material_negative": False, "metrics": [{"key": "ehp", "percent_delta": 0.4}]},
    }
    return {
        "evaluation_quality": quality, "evaluation_quality_reasons": [], "final_score": 62.0, "verdict": verdict,
        "verdict_label": verdict.replace("_", " "), "verdict_class": "upgrade", "quality_label": "", "verdict_reason": "x",
        "guardrails_applied": [], "critical_tradeoffs": [], "resistances": [], "all_deltas": [],
        "item_impact": {"axes": axes, "pattern": pattern, "conflict": {"kind": conflict}},
    }


def _model(evidence=None, outcome=None) -> dict:
    outcome = outcome or _outcome()
    model = {
        "item_name": "Arcane Loop",
        "evaluation_outcome": outcome,
        "rows": [{"key": "primary_offense", "label": "Damage", "percent_delta": 6.8, "absolute_delta": None, "delta_text": "+6.8%",
                  "direction": "positive", "emphasis": "medium", "cap_state": ""}],
        "why_reasons": [],
        "market": market_view(evidence, outcome),
    }
    apply_compact_tooltip(model)
    return model


def _all_text(model) -> str:
    market = model.get("market") or {}
    return " ".join(list(model.get("market_lines") or []) + list(market.get("more_info_lines") or []))


# ----------------------------------------------------------------------------------------------------- compact line


def test_strong_market_with_price():
    model = _model(_ev(STRONG))
    assert model["market_lines"] == ["Price ~30–36 Ex · Strong market"] or model["market_lines"][0].startswith("Damage +6.8%")
    plain = market_view(_ev(STRONG), _outcome("SIDEGRADE"))
    assert plain["compact_lines"] == ["Price ~30–36 Ex · Strong market"]


def test_weak_market_with_price():
    assert market_view(_ev(WEAK), _outcome("SIDEGRADE"))["compact_lines"] == ["Price ~30–36 Ex · Limited comparables"]


def test_pipeline_strong_evidence_reads_naturally():
    view = market_view(_pipeline_evidence("strong"), _outcome("SIDEGRADE"))
    assert re.fullmatch(r"Price ~\d+–\d+ Ex · Strong market", view["compact_lines"][0])


def test_sparse_has_no_range_in_the_compact_line_but_the_observed_range_in_more_info():
    view = market_view(_ev(SPARSE, count=3, low=20, high=41), _outcome("SIDEGRADE"))
    assert view["compact_lines"] == ["Sparse market · use cautiously"]
    assert "Only 3 comparable listings were found. Use the observed range cautiously." in view["more_info_lines"]
    assert "Observed ~20–41 Ex" in view["more_info_lines"]
    one = market_view(_ev(SPARSE, count=1, price=False), _outcome("SIDEGRADE"))
    assert "Only 1 comparable listing was found. Use the observed range cautiously." in one["more_info_lines"]
    assert not any(line.startswith("Observed") for line in one["more_info_lines"])


def test_volatile_has_no_price():
    view = market_view(_ev(VOLATILE, price=False, reason="Prices fall into separate groups."), _outcome("SIDEGRADE"))
    assert view["compact_lines"] == ["Volatile market · no reliable price"]
    assert view["more_info_lines"][:2] == ["Volatile market", "No reliable price: prices fall into separate groups."]
    assert "~" not in " ".join(view["compact_lines"])


def test_no_trustworthy_estimate_is_quiet_in_the_compact_view_and_explained_in_more_info():
    view = market_view(_ev(NONE_, price=False, reason="The search could not include everything that defines this item."), _outcome("SIDEGRADE"))
    assert view["compact_lines"] == []
    assert view["more_info_lines"][:2] == ["No trustworthy estimate", "The search could not include everything that defines this item."]


def test_stale_evidence_never_prices():
    stale = _pipeline_evidence("stale")
    assert stale["price"] is None
    view = market_view(stale, _outcome("SIDEGRADE"))
    assert view["compact_lines"] == [] and "Listings are old." in view["more_info_lines"]


# ------------------------------------------------------------------------------------------------------- listed price


@pytest.mark.parametrize(("amount", "word"), [(28, "below"), (33, "within"), (40, "above")])
def test_listed_price_context(amount, word):
    evidence = _ev(STRONG, listed=ListedPrice(float(amount), "Exalted"))
    view = market_view(evidence, _outcome("SIDEGRADE"))
    assert view["compact_lines"] == [f"Listed {amount} Ex · {word} market ~30–36 Ex"]
    assert f"Listed {amount} Ex · {word} the comparable range" in view["more_info_lines"]


@pytest.mark.parametrize(
    "evidence",
    [
        _ev(SPARSE, listed=ListedPrice(40.0, "Exalted")),
        _ev(VOLATILE, price=False, listed=ListedPrice(40.0, "Exalted")),
        _ev(NONE_, price=False, listed=ListedPrice(40.0, "Exalted")),
        _ev(STRONG, freshness=Freshness.STALE, listed=ListedPrice(40.0, "Exalted")),
        _ev(STRONG, listed=ListedPrice(1.0, "Divine")),
    ],
    ids=["sparse", "volatile", "none", "stale", "currency"],
)
def test_no_comparison_is_inferred_when_the_contract_says_not_comparable(evidence):
    view = market_view(evidence, _outcome("SIDEGRADE"))
    text = " ".join(view["compact_lines"] + view["more_info_lines"]).lower()
    for word in ("below", "within", "above", "overpriced", "cheap"):
        assert not re.search(rf"{word}", text.replace("comparable range", ""))
    assert not any(line.startswith("Listed") for line in view["compact_lines"])


def test_a_listed_note_alone_is_a_plain_fact_in_more_info():
    evidence = _ev(NONE_, price=False, listed=ListedPrice(40.0, "Exalted"))
    assert "Listed 40 Ex" in market_view(evidence, _outcome("SIDEGRADE"))["more_info_lines"]


# ------------------------------------------------------------------------------------------------- absence is normal


@pytest.mark.parametrize(
    "evidence",
    [
        None,
        {},
        status_evidence(EvidenceStatus.DISABLED, "DISABLED_BY_USER").to_dict(),
        status_evidence(EvidenceStatus.UNAVAILABLE, "PROVIDER_NOT_AUTHORIZED").to_dict(),
        status_evidence(EvidenceStatus.RATE_LIMITED, "RATE_LIMITED").to_dict(),
        status_evidence(EvidenceStatus.UNAVAILABLE, "UNIQUE_NOT_PRICED").to_dict(),
        status_evidence(EvidenceStatus.PENDING, "PENDING").to_dict(),
    ],
    ids=["absent", "empty", "disabled", "policy-blocked", "rate-limited", "unique", "pending"],
)
def test_no_usable_evidence_renders_nothing_at_all(evidence):
    assert market_view(evidence, _outcome()) is None
    model = _model(evidence)
    assert model["market_lines"] == []
    assert "market" not in build_more_info(model)["section_ids"]
    text = repr(model).lower()
    for placeholder in ("market: n/a", "price unavailable", "market unavailable", "n/a"):
        assert placeholder not in text


def test_garbage_evidence_never_raises():
    assert market_view({"status": "AVAILABLE", "headline": "STRONG_COMPARABLE_SET", "price": {"low": "x"}}, _outcome()) is None


# --------------------------------------------------------------------------------------------- budget, wording, rules


def test_the_market_lines_never_displace_the_build_impact():
    with_market = _model(_ev(STRONG, listed=ListedPrice(40.0, "Exalted")))
    without = _model(None)
    assert len(with_market["market_lines"]) <= 2
    for key in ("impact_rows", "primary_reasons", "critical_notes", "verdict_headline", "overall_line"):
        assert with_market[key] == without[key], key


def test_the_market_section_follows_build_context_and_is_a_normal_section():
    order = list(MORE_INFO_SECTION_ORDER)
    assert order.index("build_context") + 1 == order.index("market") < order.index("unmodeled")
    from exilelens.items.more_info import ADVANCED_SECTION_IDS

    assert "market" not in ADVANCED_SECTION_IDS


def test_more_info_section_is_restrained_and_ordered():
    model = _model(_ev(STRONG, coverage=("Not included in the search: Chaos resistance. Too many filters.",)))
    section = next(s for s in build_more_info(model)["sections"] if s["id"] == "market")
    assert section["title"] == "MARKET"
    assert section["lines"] == [
        "~30–36 Ex",
        "Strong comparable set · 14 listings",
        "Asking prices of the cheapest comparable listings.",
        "Listings are current.",
        "Not included in the search: Chaos resistance. Too many filters.",
    ]
    full = market_view(_ev(WEAK, count=9, basis=BandBasis.FULL_SAMPLE), _outcome("SIDEGRADE"))["more_info_lines"]
    assert full[2] == "Asking prices of every comparable listing."


def test_coverage_lines_are_capped():
    lines = market_view(_ev(STRONG, coverage=tuple(f"Not included in the search: P{i}." for i in range(8))), _outcome("SIDEGRADE"))["more_info_lines"]
    assert sum(1 for line in lines if line.startswith("Not included")) == 3


def test_seller_count_appears_only_when_it_adds_meaning():
    plain = market_view(_ev(STRONG), _outcome("SIDEGRADE"))["more_info_lines"]
    assert not any("seller" in line for line in plain)
    concentrated = market_view(_ev(STRONG, reasons=("SELLER_CONCENTRATED",), sellers=4), _outcome("SIDEGRADE"))["more_info_lines"]
    assert "4 sellers; most listings are from one or two of them." in concentrated


@pytest.mark.parametrize("scenario", ["strong", "sparse", "volatile", "unusable", "stale", "concentrated", "outliers", "partial_fx"])
def test_no_raw_enums_trust_codes_or_forbidden_words_in_any_pipeline_scenario(scenario):
    evidence = _pipeline_evidence(scenario)
    evidence = dict(evidence, listed_price={"amount": 33.0, "currency": "Exalted", "source": "NOTE"})
    view = market_view(evidence, _outcome())
    if view is None:
        return
    text = " ".join(view["compact_lines"] + view["more_info_lines"])
    assert not re.search(r"\b[A-Z][A-Z0-9]+_[A-Z0-9_]+\b", text), text
    lowered = text.lower()
    for forbidden in ("fair value", "true value", "worth", "score", "confidence", "live_trade2", "provider", "overpriced", "bargain",
                      "per currency", "value class", "excellent", "iqr", "mad"):
        assert not re.search(rf"{re.escape(forbidden)}", lowered), (forbidden, text)


def test_a_price_is_never_described_as_what_the_item_is_worth():
    text = _all_text(_model(_ev(STRONG)))
    assert not re.search(r"(worth|value)", text.lower())


# --------------------------------------------------------------------------------------------- impact + price pairing


def test_pairing_offense_and_defense():
    strong = _ev(STRONG)
    assert pairing_line(strong, _outcome()) == "Damage +6.8% · Comparable cost ~33 Ex"
    defensive = _outcome(axes={
        "OFFENSE": {"material_positive": False, "material_negative": False, "metrics": [{"key": "primary_offense", "percent_delta": 0.2}]},
        "DEFENSE": {"material_positive": True, "material_negative": False, "metrics": [{"key": "ehp", "percent_delta": 11.0},
                                                                                         {"key": "worst_max_hit", "percent_delta": 4.0}]},
    })
    assert pairing_line(strong, defensive) == "EHP +11.0% · Comparable cost ~33 Ex"
    assert pairing_line(_ev(WEAK), _outcome()) == "Damage +6.8% · Comparable cost ~33 Ex"


def test_the_pairing_replaces_the_price_line_and_is_one_compact_line():
    assert _model(_ev(STRONG))["market_lines"] == ["Damage +6.8% · Comparable cost ~33 Ex"]
    listed = _model(_ev(STRONG, listed=ListedPrice(40.0, "Exalted")))["market_lines"]
    assert listed == ["Listed 40 Ex · above market ~30–36 Ex", "Damage +6.8% · Comparable cost ~33 Ex"]


@pytest.mark.parametrize(
    ("outcome", "evidence"),
    [
        (_outcome("SIDEGRADE"), _ev(STRONG)),
        (_outcome("POTENTIAL_UPGRADE"), _ev(STRONG)),
        (_outcome("UNCERTAIN"), _ev(STRONG)),
        (_outcome("MINOR_DOWNGRADE"), _ev(STRONG)),
        (_outcome(quality="PARTIAL"), _ev(STRONG)),
        (_outcome(quality="UNSUPPORTED"), _ev(STRONG)),
        (_outcome(conflict="MATERIAL", pattern="TRADEOFF"), _ev(STRONG)),
        (_outcome(axes={"OFFENSE": {"material_positive": True, "material_negative": False, "metrics": [{"key": "primary_offense", "percent_delta": 6.8}]},
                        "DEFENSE": {"material_positive": False, "material_negative": True, "metrics": [{"key": "ehp", "percent_delta": -5.0}]}}), _ev(STRONG)),
        (_outcome(), _ev(SPARSE)),
        (_outcome(), _ev(VOLATILE, price=False)),
        (_outcome(), _ev(NONE_, price=False)),
        (_outcome(), _ev(STRONG, freshness=Freshness.STALE)),
        (_outcome(), _ev(STRONG, price=False)),
        (_outcome(axes={"UTILITY": {"material_positive": True, "material_negative": False, "metrics": [{"key": "movement_speed", "percent_delta": 9.0}]}}),
         _ev(STRONG)),
        (_outcome(axes={}), _ev(STRONG)),
    ],
    ids=["sidegrade", "potential", "uncertain", "downgrade", "partial", "unsupported", "tradeoff", "mixed-axes", "sparse", "volatile", "none",
         "stale", "no-price", "unpaired-axis", "no-axes"],
)
def test_pairing_is_hidden_unless_every_condition_holds(outcome, evidence):
    assert pairing_line(evidence, outcome) == ""


def test_no_ratio_or_combined_score_exists_anywhere_in_the_market_strings():
    lines = _model(_ev(STRONG, listed=ListedPrice(40.0, "Exalted")))["market_lines"] + market_view(_ev(STRONG), _outcome())["more_info_lines"]
    text = " ".join(lines)
    assert "/" not in text and "per " not in text.lower() and "÷" not in text


# ------------------------------------------------------------------------------------------------------ painted panel


def test_the_panel_paints_market_lines_in_place_and_hides_them_when_absent():
    from PySide6.QtWidgets import QApplication

    from exilelens.ui.overlay_presentation import ItemOverlayPanel

    QApplication.instance() or QApplication([])
    panel = ItemOverlayPanel()
    panel.render_presentation(_model(None))
    assert panel._market_line.isHidden() and panel._market_line.text() == ""
    first = [w.text() for w in panel._why_widgets]
    panel.render_presentation(_model(_ev(STRONG)))  # evidence arrives later: same panel, same rendering path
    assert panel._market_line.text() == "Damage +6.8% · Comparable cost ~33 Ex" and not panel._market_line.isHidden()
    assert [w.text() for w in panel._why_widgets] == first, "only the market line changed"
    panel.render_presentation(_model(None))
    assert panel._market_line.isHidden() and panel._market_line.text() == ""


# ------------------------------------------------------------------------------------------- the old value system is gone


def test_no_power_per_currency_or_value_class_survives_in_production_code():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src" / "exilelens"
    banned = ("power_per_currency", "PowerValueClass", "PPC_CLASS_THRESHOLDS", "EXCELLENT_VALUE", "GOOD_VALUE", "FAIR_VALUE", "BAD_VALUE",
              "VALUE / COST", "Power / Cost", "BEST VALUE SO FAR", "Best value:", "BEST_VALUE", "compute_power", "classify_power")
    offenders = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        offenders += [f"{path.name}: {token}" for token in banned if token in text]
    assert offenders == []


def test_old_payloads_with_the_removed_fields_load_without_crashing():
    from exilelens.items.presentation import _build_price_block
    from exilelens.market.models import CandidateEvaluation
    from exilelens.market_assist.models import MarketCaptureSession

    legacy = {"manual_price": {"amount": 5, "currency": "Exalted"}, "power_per_currency": {"classification": "GOOD_VALUE", "power_per_currency": 7.0}}
    block = _build_price_block(legacy, value_profile="BALANCED")
    assert block["label"] == "5 Exalted" and block["source"] == "manual"
    assert not {"classification", "classification_label", "power_per_currency", "is_best_value"} & set(block)
    session = MarketCaptureSession.from_dict({"session_id": "s", "best_value_observation_id": "x", "observations": []})
    assert not hasattr(session, "best_value_observation_id")
    assert CandidateEvaluation.__dataclass_fields__.get("power_per_currency") is None


def test_manual_price_remains_a_plain_fact():
    from exilelens.items.price import ManualPrice, parse_manual_price

    assert parse_manual_price(12, "Divine") == ManualPrice(12.0, "Divine", "MANUAL")
