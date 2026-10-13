"""FILTER profile system V2: the five strictness levels, the state matrix, no-build mode, the build modifier and the guarantees that make a
stricter profile strictly quieter. Offline; no PoB, no network, no game.

Contract sources: docs/research/FILTER-PROFILE-STRICTNESS-RESEARCH.md + artifacts/filter_profile_research/proposed_matrix.json (the approved
matrix) and docs/research/FILTER-PROFILE-SYSTEM-V2.md. The ORACLE (`profile_oracle`) restates the matrix semantics independently of the
generated rules; every decision below is the generated filter's first match as the preview simulator reads it.

Run with:  python -m pytest tests/test_filter_profile_system_v2.py -m ""
"""
from __future__ import annotations

import json
import re
import shlex
from dataclasses import replace
from pathlib import Path

import pytest

from exilelens.filters import benchmark08b as bm
from exilelens.filters import profile_oracle as oracle
from exilelens.filters import profile_policy as pp
from exilelens.filters import profile_report as pr
from exilelens.filters.base_match import BaseCondition
from exilelens.filters.build_needs import BuildNeedsSnapshot
from exilelens.filters.inspector import make_item
from exilelens.filters.intel_generate import generate
from exilelens.filters.preview import PreviewItem, preview_decision
from exilelens.filters.profiles import FilterProfileName, FilterThemeName, PROFILES, get_profile
from exilelens.filters.verified_bases import load_base_properties

ROOT = Path(__file__).resolve().parents[1]
LEVELS = list(pp.LEVELS)
RANK = {"SHOW+": 3, "SHOW": 2, "QUIET": 1, "HIDE": 0}
EFFECT_LINES = ("PlayAlertSound", "PlayEffect", "MinimapIcon")


def state_of(decision) -> str:
    """The state a decision lands in: HIDE, or the matrix state of the winning row (the catch-all counts as SHOW+: full V4 attention)."""
    if decision.hidden:
        return "HIDE"
    return "SHOW+" if decision.state in ("SAFETY", "") else decision.state


def effects(rule) -> list[str]:
    return [line.strip() for line in rule.lines if line.strip().startswith(EFFECT_LINES)]


# -- fixtures --------------------------------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def nobuild():
    return BuildNeedsSnapshot.unavailable("General filter", "no build connected")


@pytest.fixture(scope="module")
def spark():
    """A measured build with COMPLETE evidence (Armour / Evasion probes included)."""
    needs = ROOT / "tests" / "fixtures" / "filter_needs" / "filter08c"
    if not needs.exists():
        pytest.skip("measured needs snapshots not present")
    return bm.load_snapshots(needs)["spark_fixture"]


@pytest.fixture(scope="module")
def generated(nobuild, spark):
    """{('no_build'|'spark', level): GenerationResult} for all five levels."""
    return {(key, level): generate(needs, level, "Void Gold", intel=True)
            for key, needs in (("no_build", nobuild), ("spark", spark)) for level in LEVELS}


@pytest.fixture(scope="module")
def sample():
    """Deterministic stratified sample: the legal corpus + floors of the Random Drops pool (maps context, area level 82)."""
    return pr.corpus(legal=700, floors=30, seed=11)


def decisions(rules, items):
    return [preview_decision(rules, item) for item in items]


# -- profile names, default, Endgame ---------------------------------------------------------------------------------------------------
def test_five_profile_names_and_recommended_default():
    assert [p.value for p in FilterProfileName] == ["Relaxed", "Recommended", "Strict", "Very Strict", "Uber Strict"]
    assert list(PROFILES) and {p.value for p in PROFILES} == set(LEVELS)
    assert pp.LEVELS == tuple(LEVELS) and pp.DEFAULT_LEVEL == "Recommended"
    from exilelens.app.settings import AppSettings
    assert AppSettings.from_dict({}).filter_profile == "Recommended"
    for name in LEVELS:
        assert get_profile(name).name.value == name


def test_the_shipped_matrix_is_the_approved_matrix():
    approved = json.loads((ROOT / "tests" / "fixtures" / "filter_profile_matrix_approved.json").read_text(encoding="utf-8"))
    shipped = json.loads((pp.DATA).read_text(encoding="utf-8"))
    assert shipped["levels"] == approved["levels"] == LEVELS and shipped["default"] == approved["default"] == "Recommended"
    assert shipped["rows"] == approved["rows"] and shipped["protected_floor"] == approved["protected_floor"]
    for name, row in shipped["rows"].items():                          # states are the four of the contract, one per level
        assert set(row) == set(LEVELS) and set(row.values()) <= set(RANK), name


def test_endgame_is_not_a_profile_and_migrates_to_very_strict_once():
    from exilelens.app.settings import AppSettings
    assert "Endgame" not in [p.value for p in FilterProfileName]
    assert get_profile("Endgame").name == FilterProfileName.VERY_STRICT and get_profile("endgame").name == FilterProfileName.VERY_STRICT
    assert pp.normalize_level("Endgame") == ("Very Strict", True)
    migrated = AppSettings.from_dict({"filter_profile": "Endgame"})
    assert migrated.filter_profile == "Very Strict" and migrated.filter_profile_notice == pp.ENDGAME_NOTICE
    assert "Very Strict" in pp.ENDGAME_NOTICE and "automatic" in pp.ENDGAME_NOTICE.lower()
    # an unknown saved value is the default, silently; a current value never produces a notice
    assert AppSettings.from_dict({"filter_profile": "Ultra Mega"}).filter_profile == "Recommended"
    assert AppSettings.from_dict({"filter_profile": "Ultra Mega"}).filter_profile_notice == ""
    assert AppSettings.from_dict({"filter_profile": "Strict"}).filter_profile_notice == ""
    with pytest.raises(ValueError):
        get_profile("Ultra Mega")


def test_no_context_dropdown_is_needed_campaign_is_a_native_condition(generated):
    """Campaign vs maps is expressed by AreaLevel in the filter itself: one dial, no Context selector."""
    source = (ROOT / "src" / "exilelens" / "ui" / "filters_page.py").read_text(encoding="utf-8")
    assert 'QLabel("Context' not in source and 'addItem("Endgame"' not in source and "currentData() == \"Endgame\"" not in source
    text = generated[("no_build", "Strict")].text
    assert re.search(r"AreaLevel <= 64", text) and re.search(r"AreaLevel >= 65", text)


# -- state matrix is the contract ------------------------------------------------------------------------------------------------------
def test_every_generated_rule_belongs_to_one_matrix_row_and_state(generated):
    rows = set(pp.rows()) | {"safety"}
    for (build, level), result in generated.items():
        for rule in result.rules:
            assert rule.row in rows or rule.row.startswith("build_") or rule.row == "known_generic_fallback", (build, level, rule.name, rule.row)
            assert rule.state in {"SHOW+", "SHOW", "QUIET", "HIDE", "SAFETY"}, (build, level, rule.name)
        assert len({r.name for r in result.rules}) == len(result.rules), (build, level)          # unique rule names
        assert result.valid, (build, level)


def test_generated_decisions_equal_the_independent_oracle_in_both_contexts(generated, sample):
    """No-build filter vs the oracle (written from the matrix, not from the generator): every item x level x context agrees."""
    mismatches = []
    for context_area in (30, 82):
        items = [replace(i, area_level=context_area) for i in sample]
        for level in LEVELS:
            rules = generated[("no_build", level)].rules
            for item, decision in zip(items, decisions(rules, items)):
                want = oracle.expected_state(item, level)
                if state_of(decision) != want:
                    mismatches.append((level, context_area, item.name, item.rarity, item.item_level, state_of(decision), want, decision.rule_name))
    assert not mismatches, mismatches[:8]


# -- monotonic strictness --------------------------------------------------------------------------------------------------------
def test_matrix_rows_never_get_more_visible_as_strictness_rises():
    for name, row in pp.rows().items():
        ranks = [RANK[row[level]] for level in LEVELS]
        assert ranks == sorted(ranks, reverse=True), (name, row)


@pytest.mark.parametrize("key", ["no_build", "spark"])
def test_visibility_is_monotone_over_the_whole_item_space(key, nobuild, spark, generated):
    """Exact (rule IR, box algebra over every item): a stricter profile never shows what a looser one hides."""
    from exilelens.filters import profile_contract as pc
    found, narrowed = pc.inversions(key, nobuild if key == "no_build" else spark,
                                    rules={level: generated[(key, level)].rules for level in LEVELS})
    assert not found, [(i.looser, i.stricter, i.looser_rule, i.stricter_rule, i.example) for i in found[:5]]
    assert all(narrowed.get(f"{a}->{b}", 0) > 0 for a, b in zip(LEVELS, LEVELS[1:]))      # every step really removes something


@pytest.mark.parametrize("key", ["no_build", "spark"])
def test_sample_decisions_never_gain_visibility_with_strictness(key, generated, sample):
    previous = None
    for level in LEVELS:
        current = [RANK[state_of(d)] for d in decisions(generated[(key, level)].rules, sample)]
        if previous is not None:
            assert all(c <= p for c, p in zip(current, previous)), (key, level)
        previous = current


def test_stricter_profiles_are_also_quieter(generated, sample):
    """Sound and persistent beams never rise with strictness (they only come from SHOW+); minimap icons rise only for a handful of items whose
    winning row changes role at equal state (documented in the profile report), never as a trend."""
    sound, beams, icons = [], [], []
    for level in LEVELS:
        ds = pr.decide_all(generated[("no_build", level)].rules, sample)
        shown = [d for d in ds if not d.hidden]
        sound.append(sum(d.sound for d in shown))
        beams.append(sum(d.beam == "persistent" for d in shown))
        icons.append(sum(d.icon for d in shown))
    assert sound == sorted(sound, reverse=True) and beams == sorted(beams, reverse=True), (sound, beams)
    assert all(b <= a + max(3, a // 50) for a, b in zip(icons, icons[1:])), icons
    assert icons[-1] < icons[0] and sound[-1] < sound[0]


# -- protected value floor -------------------------------------------------------------------------------------------------------------
def test_protected_floor_rows_are_never_hide_in_the_matrix():
    floor = pp.protected_floor()
    assert floor
    for row in floor:
        assert all(pp.state(row, level) != "HIDE" for level in LEVELS), row


@pytest.mark.parametrize("key", ["no_build", "spark"])
def test_protected_items_are_never_hidden_at_any_level_or_context(key, generated, sample):
    floor = set(pp.protected_floor())
    protected = [i for i in sample if floor & set(oracle.rows_of(i))] + [i for i in sample if not oracle.rows_of(i)]
    assert len(protected) > 50
    for area in (30, 82):
        items = [replace(i, area_level=area) for i in protected]
        for level in LEVELS:
            hidden = [i.name for i, d in zip(items, decisions(generated[(key, level)].rules, items)) if d.hidden]
            assert not hidden, (key, level, area, hidden[:5])


# -- campaign --------------------------------------------------------------------------------------------------------------------------
def test_campaign_behaves_like_relaxed_at_every_level(generated, sample):
    campaign = [replace(i, area_level=40) for i in sample]
    baseline = [state_of(d) for d in decisions(generated[("no_build", "Relaxed")].rules, campaign)]
    for level in LEVELS[1:]:
        got = [state_of(d) for d in decisions(generated[("no_build", level)].rules, campaign)]
        assert got == baseline, level
    assert pp.CAMPAIGN_MAX_AREA_LEVEL == 64 and pp.MAPS_MIN_AREA_LEVEL == 65


def test_campaign_hides_only_the_relaxed_column(generated, sample):
    campaign = [replace(i, area_level=40) for i in sample]
    for level in LEVELS:
        for item, d in zip(campaign, decisions(generated[("no_build", level)].rules, campaign)):
            if d.hidden:
                assert oracle.classify(item, "Relaxed").state == "HIDE", (level, item.name)


# -- unknown-item catch-all ------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("key", ["no_build", "spark"])
def test_unknown_items_are_shown_with_a_recognisable_non_jackpot_style(key, generated):
    unknown = PreviewItem("Zorblax Sigil", "future", "Zorblax Relics", "Zorblax Sigil", "Rare", item_level=82)
    for level in LEVELS:
        rules = generated[(key, level)].rules
        assert rules[-1].category == "UNKNOWN_SAFETY" and rules[-1].state == "SAFETY"
        assert [line.strip() for line in rules[-1].lines][0] == "Show"
        assert not [line for line in rules[-1].lines if line.strip().split()[0] in {"Class", "BaseType", "Rarity", "AreaLevel", "ItemLevel"}]
        assert not any(r.lines and r.lines[0].strip() == "Hide" for r in rules[rules.index(rules[-1]):][1:])      # nothing hides below it
        d = preview_decision(rules, unknown)
        assert not d.hidden and d.state == "SAFETY" and d.rule_name == rules[-1].name
        assert d.style_role == "unknown" and d.effect == ""                    # recognisable, never a jackpot beam
        assert "sound" not in d.native_details.lower() or "no sound" in d.native_details.lower() or "sound none" in d.native_details.lower()


def test_every_hide_rule_precedes_the_catch_all_and_hides_only_listed_bases(generated):
    for (build, level), result in generated.items():
        rules = result.rules
        last_hide = max((i for i, r in enumerate(rules) if r.lines and r.lines[0].strip() == "Hide"), default=-1)
        assert last_hide < len(rules) - 1
        for rule in rules:
            if rule.lines and rule.lines[0].strip() == "Hide":
                # every hide names what it hides natively (an exact BaseType list, an area-relative waystone / gem-level band, or a class
                # narrowed by the matrix' own conditions): no Hide is ever unconditional
                conditions = [line.strip() for line in rule.lines[1:] if line.strip() and not line.strip().startswith(
                    ("Set", "Play", "MinimapIcon", "DisableDropSound", "Continue", "AreaLevel", "#"))]
                assert conditions, rule.name
                assert not any(line.strip().startswith("BaseType ") and not line.strip().startswith("BaseType ==") for line in rule.lines)
                # ... and is never classed as a protective rule (FILTER-09 invariant: protective = never hidden)
                assert rule.category != "PROTECTIVE", (build, level, rule.name, rule.category)


# -- no-build mode ---------------------------------------------------------------------------------------------------------------------
def test_no_build_generation_is_valid_general_and_complete(generated):
    for level in LEVELS:
        result = generated[("no_build", level)]
        assert result.valid and result.rules
        assert not any(r.category in {"BUILD_WEAPON", "BUILD_DEFENSE", "BUILD_JEWELLERY", "BUILD_OFFHAND"} for r in result.rules), level
        assert f"Profile: {level}" in result.text
    status = __import__("exilelens.filters.intel_status", fromlist=["x"])
    assert status.GENERAL_HEADLINE == "General filter" and "Connect a PoB build" in status.GENERAL_DETAIL
    assert "degrad" not in (status.GENERAL_HEADLINE + status.GENERAL_DETAIL).lower() and "fail" not in status.GENERAL_DETAIL.lower()


def test_no_build_recommended_is_first_class_against_a_measured_build(generated, sample):
    """Without a build the generic policy keeps every craft / protected / unknown item a build user sees; a build only adds more."""
    base = [state_of(d) for d in decisions(generated[("no_build", "Recommended")].rules, sample)]
    with_build = [state_of(d) for d in decisions(generated[("spark", "Recommended")].rules, sample)]
    assert all(RANK[b] >= RANK[n] for n, b in zip(base, with_build))
    added = sum(RANK[b] > RANK[n] for n, b in zip(base, with_build))
    assert added > 0                                                     # the build is a real modifier ...
    assert sum(s != "HIDE" for s in base) > 0.5 * len(base)              # ... on top of a general filter that stands on its own
    # every craft item the build lane shows is shown without the build as well
    for item, n, d in zip(sample, base, decisions(generated[("spark", "Recommended")].rules, sample)):
        if d.row.startswith("craft_") and not d.hidden:
            assert n != "HIDE", item.name


# -- build contract --------------------------------------------------------------------------------------------------------------------
def test_build_only_reduces_attention_on_measured_irrelevant_generic_equipment(generated, sample):
    for level in LEVELS:
        for area in (30, 82):
            items = [replace(i, area_level=area) for i in sample]
            generic = decisions(generated[("no_build", level)].rules, items)
            built = decisions(generated[("spark", level)].rules, items)
            for item, g, b in zip(items, generic, built):
                if RANK[state_of(b)] < RANK[state_of(g)]:
                    # The approved modifier may quiet a shown generic base, or hide one already quiet.
                    assert b.row == "build_irrelevant_generic_nm", (level, area, item.name, g.rule_name, b.rule_name)
                    if b.hidden and not g.hidden:
                        assert state_of(g) == "QUIET", (level, area, item.name, g.rule_name, b.rule_name)


def test_build_modifier_acts_only_on_measured_irrelevant_layers_and_hides_only_below_show(spark):
    """Controlled counterfactual: Armour / Evasion measured as no response. The modifier quiets at any level, hides only where the generic row
    is already QUIET / HIDE, never touches hybrids, and carries its justification."""
    needs = bm.with_layers(spark, AR="NO_RESPONSE", EV="NO_RESPONSE", ES="STRONG")
    props = load_base_properties()
    from exilelens.filters.rules import generic_sets
    top = set(generic_sets().top_eq)
    pure_ev = next(n for n, r in props.items() if n in top and r["class"] == "Body Armour" and r["evasion"] and not r["armour"]
                   and not r["energy_shield"])
    hybrid = next(n for n, r in props.items() if n in top and r["class"] == "Body Armour" and r["evasion"] and r["energy_shield"]
                  and not r["armour"])
    for level in LEVELS:
        rules = generate(needs, level, "Void Gold", intel=True).rules
        generic = generate(BuildNeedsSnapshot.unavailable("g", "none"), level, "Void Gold", intel=True).rules
        for base, touched in ((pure_ev, True), (hybrid, False)):
            item = make_item(base, rarity="Magic", item_level=70)
            g, b = preview_decision(generic, item), preview_decision(rules, item)
            assert RANK[state_of(b)] <= RANK[state_of(g)]                # quiets or hides, never raises
            if state_of(b) == "HIDE" and state_of(g) != "HIDE":
                assert state_of(g) == "QUIET", (level, base, g.rule_name)
            if not touched:
                assert state_of(b) == state_of(g), (level, base)
            elif state_of(b) != state_of(g):
                rule = next(r for r in rules if r.name == b.rule_name)
                assert rule.justification.startswith("MEASURED BUILD EVIDENCE")
    assert pp.build_modified("SHOW+", "HIDE") == "QUIET" and pp.build_modified("SHOW", "HIDE") == "QUIET"
    assert pp.build_modified("QUIET", "HIDE") == "HIDE" and pp.build_modified("HIDE", "SHOW") == "HIDE"
    assert pp.build_modified("SHOW", "SHOW") == "SHOW" and pp.build_modified("SHOW", "SHOW+") == "SHOW"


def test_build_never_hides_craft_or_campaign_items(spark):
    needs = bm.with_layers(spark, AR="NO_RESPONSE", EV="NO_RESPONSE", ES="STRONG")
    for level in LEVELS:
        rules = generate(needs, level, "Void Gold", intel=True).rules
        for rule in rules:
            if rule.row == "build_irrelevant_generic_nm":
                assert rule.category == "GENERIC_EQUIPMENT"
                assert all(l.strip() != "Hide" or any("AreaLevel >= 65" in x for x in rule.lines) for l in rule.lines[:1]), rule.name
        crafts = [i for i in (make_item("Utility Belt", rarity=r, item_level=82) for r in ("Normal", "Magic"))]
        base = generate(BuildNeedsSnapshot.unavailable("g", "none"), level, "Void Gold", intel=True).rules
        for item in crafts:
            assert state_of(preview_decision(rules, item)) == state_of(preview_decision(base, item))


# -- ladders ---------------------------------------------------------------------------------------------------------------------------
def test_utility_belt_progression_is_craft_policy_not_a_name_special_case(generated):
    expected = {"Relaxed": ("SHOW", "SHOW"), "Recommended": ("SHOW", "SHOW"), "Strict": ("SHOW", "QUIET"),
                "Very Strict": ("QUIET", "HIDE"), "Uber Strict": ("HIDE", "HIDE")}
    for key in ("no_build", "spark"):
        for level, (normal, magic) in expected.items():
            rules = generated[(key, level)].rules
            for rarity, want in (("Normal", normal), ("Magic", magic)):
                got = state_of(preview_decision(rules, make_item("Utility Belt", rarity=rarity, item_level=82)))
                assert got == want, (key, level, rarity, got)
    for module in ("rules.py", "crafting_intel.py", "profile_policy.py", "opportunity_lanes.py"):
        text = (ROOT / "src" / "exilelens" / "filters" / module).read_text(encoding="utf-8")
        assert "Utility Belt" not in re.sub(r'""".*?"""', "", text, flags=re.S).replace("# ", "#"), module


def test_craft_premium_progression(generated):
    premium = pp.rows()["craft_premium_normal_ilvl82"]
    assert [premium[level] for level in LEVELS] == ["SHOW+", "SHOW+", "SHOW+", "SHOW", "SHOW"]
    assert "craft_premium_normal_ilvl82" in pp.protected_floor()
    from exilelens.filters import crafting_intel as ci
    bases = [b for b in load_base_properties() if ci.assess(b).level == ci.CraftLevel.PREMIUM and oracle.rows_of(make_item(b, rarity="Normal"))]
    assert bases
    for base in bases[:25]:
        item = make_item(base, rarity="Normal", item_level=84)
        states = [state_of(preview_decision(generated[("no_build", level)].rules, item)) for level in LEVELS]
        assert [RANK[s] for s in states] == sorted((RANK[s] for s in states), reverse=True)
        assert states[-1] != "HIDE", base                                  # premium Normal ilvl >= 82 survives every level


def test_rare_progression_follows_the_matrix(generated):
    top = next(b for b in load_base_properties() if oracle.rows_of(make_item(b, rarity="Rare", item_level=82)) and
               "eq_rare_top_ilvl82" in oracle.rows_of(make_item(b, rarity="Rare", item_level=82)))
    for item in (make_item(top, rarity="Rare", item_level=82), make_item(top, rarity="Rare", item_level=70)):
        ranks = [RANK[state_of(preview_decision(generated[("no_build", level)].rules, item))] for level in LEVELS]
        assert ranks == sorted(ranks, reverse=True)
        assert [state_of(preview_decision(generated[("no_build", level)].rules, item)) for level in LEVELS] == \
               [oracle.expected_state(item, level) for level in LEVELS]
    # item-level 82 top Rares outlast the rest: still visible at Very Strict, QUIET at Uber Strict (matrix)
    item = make_item(top, rarity="Rare", item_level=82)
    assert state_of(preview_decision(generated[("no_build", "Very Strict")].rules, item)) in ("SHOW", "SHOW+")
    assert state_of(preview_decision(generated[("no_build", "Uber Strict")].rules, item)) == "QUIET"


def test_normal_and_magic_equipment_progression(generated):
    for row in ("eq_normal_top", "eq_magic_top", "eq_normal_low", "eq_magic_low"):
        ranks = [RANK[pp.state(row, level)] for level in LEVELS]
        assert ranks == sorted(ranks, reverse=True) and ranks[-1] == 0 and ranks[0] >= 1, row
    assert pp.state("eq_normal_low", "Recommended") == "HIDE"            # Recommended hides worthless Normal / Magic bases ...
    assert pp.state("eq_normal_top", "Recommended") == "QUIET"           # ... and quiets (never hides) the top generic bases


def _currency_examples() -> list[tuple[str, str]]:
    """One real name per currency tier row (from the tier table the generator itself compiles)."""
    from exilelens.filters.currency_tiers import TIERS as CURRENCY_TIERS
    return [(tier.names[0], tier.row) for tier in CURRENCY_TIERS if tier.names]


def test_currency_progression(generated):
    examples = _currency_examples()
    assert {row for _, row in examples} >= {"currency_mythic", "currency_premium", "currency_valuable", "currency_utility"}
    for name, row in examples:
        item = PreviewItem(name, "Currency", "Stackable Currency", name, "Normal", area_level=82)
        for key in ("no_build", "spark"):
            got = [state_of(preview_decision(generated[(key, level)].rules, item)) for level in LEVELS]
            assert got == [oracle.expected_state(item, level) for level in LEVELS], (key, name, got)
            assert oracle.rows_of(item)[0] == row, (name, oracle.rows_of(item))
            assert got == [pp.state(row, level) for level in LEVELS], (key, name, got)
    # high currency never goes below SHOW+; utility currency is the first to be quieted, hidden only at Uber Strict
    assert all(pp.state("currency_mythic", level) == "SHOW+" for level in LEVELS)
    assert [pp.state("currency_utility", level) for level in LEVELS] == ["SHOW", "SHOW", "SHOW", "QUIET", "HIDE"]
    assert [pp.state("currency_shards_low", level) for level in LEVELS] == ["SHOW", "SHOW", "QUIET", "HIDE", "HIDE"]


def _waystone(tier: int, area: int, template: PreviewItem) -> PreviewItem:
    return replace(template, name=f"Waystone (Tier {tier})", waystone_tier=tier, area_level=area)


def test_waystone_progression_is_relative_to_the_area(generated, sample):
    template = next((i for i in sample if i.item_class == "Waystones"), None) or PreviewItem(
        "Waystone", "Waystone", "Waystones", "Waystone", "Rare", waystone_tier=1)
    assert pp.WAYSTONE_BANDS and pp.WAYSTONE_BANDS[0][0] == 65
    for key in ("no_build", "spark"):
        for area in (65, 68, 71, 74, 77, 80, 82):
            for level in LEVELS:
                rules = generated[(key, level)].rules
                got = [state_of(preview_decision(rules, _waystone(t, area, template))) for t in range(1, 17)]
                assert got == [oracle.expected_state(_waystone(t, area, template), level) for t in range(1, 17)], (key, level, area, got)
                assert all(g != "HIDE" for t, g in zip(range(1, 17), got) if t >= 15), (level, area)          # top tiers never hide
                firsts = [i for i, g in enumerate(got) if g != "HIDE"]
                assert not firsts or all(g != "HIDE" for g in got[firsts[0]:]), (level, area, got)          # lower tiers hide first
    # campaign areas: waystones follow the Relaxed column (nothing hidden)
    camp = [state_of(preview_decision(generated[("no_build", "Uber Strict")].rules, _waystone(t, 40, template))) for t in range(1, 17)]
    assert "HIDE" not in camp


def test_gem_jewel_charm_flask_policy_prefers_quiet_over_hide(generated, sample):
    quiet_first = ("gems_uncut_other", "jewels_magic", "charms_other", "flasks_top", "flasks_other", "charms_top")
    for row in quiet_first:
        states = [pp.state(row, level) for level in LEVELS]
        if "HIDE" in states:                                              # a hide is always preceded by a QUIET step or a campaign lane
            first = states.index("HIDE")
            assert first == 0 or "QUIET" in states[:first] or states[first - 1] in ("SHOW", "QUIET"), (row, states)
    assert all(pp.state("jewels_rare", level) != "HIDE" for level in LEVELS)
    assert all(pp.state("gems_uncut_top", level) in ("SHOW+", "SHOW") for level in LEVELS)
    groups = [i for i in sample if pr.kind_of(i) in ("gems", "jewels", "charms", "flasks")]
    assert groups
    for level in LEVELS:
        rules = generated[("no_build", level)].rules
        for item, d in zip(groups, decisions(rules, groups)):
            assert state_of(d) == oracle.expected_state(item, level), (level, item.name)


# -- native actions of the states ------------------------------------------------------------------------------------------------------
def test_quiet_rules_use_only_quiet_native_actions(generated):
    seen = 0
    for (build, level), result in generated.items():
        for rule in result.rules:
            if rule.state != "QUIET" or rule.lines[0].strip() != "Show":
                continue
            seen += 1
            assert not effects(rule), (build, level, rule.name, effects(rule))       # no beam, no sound, no minimap icon
            assert any(line.strip().startswith("SetFontSize") for line in rule.lines)
            assert not any(line.strip().startswith("PlayAlertSound") for line in rule.lines)
    assert seen > 20


def test_show_rules_carry_no_sound_or_beam_and_only_show_plus_may_have_them(generated):
    for (build, level), result in generated.items():
        for rule in result.rules:
            if rule.lines[0].strip() != "Show":
                continue
            if rule.state in ("SHOW", "QUIET"):
                assert not [e for e in effects(rule) if e.startswith(("PlayAlertSound", "PlayEffect"))], (build, level, rule.name)


def test_quiet_style_is_smaller_and_readable():
    from exilelens.filters.style_system import ROLE_DESIGNS, native_style
    for theme in FilterThemeName:
        for role in ("trade", "craft_relevant", "build_defense", "jewel", "generic", "currency"):
            full, show, quiet = (native_style(theme, role, None, s) for s in ("SHOW+", "SHOW", "QUIET"))
            assert quiet["font_size"] <= show["font_size"] <= full["font_size"], (theme, role)
            assert quiet["font_size"] >= 18                                               # still readable
            assert quiet["text_color"].split()[-1] == "255"                               # text stays fully opaque
    assert "generic" in ROLE_DESIGNS and "unknown" in ROLE_DESIGNS


# -- theme / V4 / FILTER-09 invariants -------------------------------------------------------------------------------------------------
def test_theme_never_changes_visibility(nobuild, generated, sample):
    other = next(t for t in FilterThemeName if t.value != "Void Gold")
    for level in ("Recommended", "Very Strict"):
        base = [state_of(d) for d in decisions(generated[("no_build", level)].rules, sample)]
        alt = [state_of(d) for d in decisions(generate(nobuild, level, other.value, intel=True).rules, sample)]
        assert base == alt, (level, other.value)


@pytest.mark.parametrize("key", ["no_build", "spark"])
def test_exact_basetype_contract_holds_in_every_profile(key, generated):
    for level in LEVELS:
        result = generated[(key, level)]
        for line in result.text.splitlines():
            stripped = line.strip()
            if stripped.startswith("BaseType"):
                assert stripped.startswith("BaseType =="), (level, stripped[:60])
                assert BaseCondition.parse(stripped) is not None
        assert shlex.split("BaseType == \"A B\"")[:2] == ["BaseType", "=="]


def test_visual_v4_stays_the_visual_system(generated):
    """Persistent beams are the top of the vocabulary only; white / red text is reserved; V4 rules keep their documented effect lines."""
    from exilelens.filters.style_system import HERO_RED
    for (build, level), result in generated.items():
        for rule in result.rules:
            if rule.lines[0].strip() != "Show":
                continue
            persistent = [e for e in effects(rule) if e.startswith("PlayEffect") and not e.endswith("Temp")]
            if persistent:
                assert rule.state in ("SHOW+", "SAFETY"), (build, level, rule.name)
    text = generated[("no_build", "Recommended")].text
    assert "PlayEffect" in text and "MinimapIcon" in text and "PlayAlertSound" in text
    assert HERO_RED


def test_old_filter_files_need_no_migration_and_exact_names_survive(generated):
    """A saved file that names the removed profile is just a comment: the header parses, nothing in the generator reads it back."""
    legacy_header = "# Profile: Endgame\n"
    assert get_profile("Endgame").name.value == "Very Strict"
    assert "Profile: Very Strict" in generated[("no_build", "Very Strict")].text and legacy_header not in generated[("no_build", "Very Strict")].text


# -- unique safety correction ----------------------------------------------------------------------------------------------------------
def test_ordinary_uniques_are_never_hidden_by_strictness(generated):
    assert [pp.state("uniques_generic", level) for level in LEVELS] == ["SHOW+", "SHOW", "SHOW", "QUIET", "QUIET"]
    assert all(pp.state("uniques_top", level) == "SHOW+" for level in LEVELS)
    uniques = next(b for b in load_base_properties() if oracle.rows_of(make_item(b, rarity="Unique")) == ["uniques_generic"])
    for key in ("no_build", "spark"):
        for area in (30, 82):
            for level in LEVELS:
                d = preview_decision(generated[(key, level)].rules, replace(make_item(uniques, rarity="Unique"), area_level=area))
                assert not d.hidden, (key, level, area)
    d = preview_decision(generated[("no_build", "Uber Strict")].rules, make_item(uniques, rarity="Unique"))
    assert d.state == "QUIET" and not effects(next(r for r in generated[("no_build", "Uber Strict")].rules if r.name == d.rule_name))


def test_future_market_signal_contract_never_hides_unknown_value():
    for level in LEVELS:
        assert pp.unique_state(level) == pp.unique_state(level, "UNKNOWN") == pp.state("uniques_generic", level) != "HIDE"
        assert pp.unique_state(level, "TRADE_PREMIUM") == "SHOW+"
    assert pp.unique_state("Uber Strict", "VERIFIED_LOW") == "HIDE" and pp.unique_state("Strict", "VERIFIED_LOW") == "SHOW"
