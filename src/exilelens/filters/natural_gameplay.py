"""Natural gameplay corpus (FILTER-09): real observations kept as permanent regression cases.

Entries are loaded from ``test_fixtures/natural_gameplay/corpus.json`` and replayed through the generator. The replay never edits an
entry; ``before`` is the same generator without the CRAFT lane, so the pre-fix behaviour stays reproducible from current code.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from exilelens.filters.build_needs import BuildNeedsSnapshot
from exilelens.filters.inspector import make_item
from exilelens.filters.intel_generate import generate
from exilelens.filters.opportunity import BuildOpportunityModel
from exilelens.filters.opportunity_lanes import decide
from exilelens.filters.preview import preview_decision
from exilelens.filters.profiles import PROFILES

CORPUS = Path(__file__).parent / "test_fixtures" / "natural_gameplay" / "corpus.json"
BUILDS = Path(__file__).parent / "test_fixtures" / "builds"
PROFILE_NAMES = ("Relaxed", "Recommended", "Strict", "Very Strict", "Uber Strict")
REQUIRED = ("id", "label", "source", "item", "observed", "matched_rule_before", "expected_user_assessment", "investigation", "final_policy")


@dataclass(frozen=True)
class Replay:
    entry_id: str
    profile: str
    rarity: str
    item_level: int
    before_visible: bool
    before_rule: str
    after_visible: bool
    after_rule: str
    lane_cause: str | None
    lane_levels: dict
    why: str


def load() -> list[dict]:
    data = json.loads(CORPUS.read_text(encoding="utf-8"))
    if data.get("label") != "NATURAL GAMEPLAY EVIDENCE":
        raise ValueError("corpus is not labelled NATURAL GAMEPLAY EVIDENCE")
    for entry in data["entries"]:
        missing = [key for key in REQUIRED if key not in entry]
        if missing:
            raise ValueError(f"{entry.get('id', '?')}: missing {missing}")
        if entry["label"] != "NATURAL GAMEPLAY EVIDENCE":
            raise ValueError(f"{entry['id']}: entry is not labelled NATURAL GAMEPLAY EVIDENCE")
    return data["entries"]


def reference_needs(entry: dict) -> BuildNeedsSnapshot:
    name = entry.get("filter_context", {}).get("reference_build", "spark_fixture")
    canonical = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "filter_needs" / "filter08e" / f"{name}.json"
    path = canonical if canonical.exists() else next(BUILDS.glob(f"{name}*.json"))
    return BuildNeedsSnapshot.from_json(path.read_text(encoding="utf-8"))


def replay(entry: dict, needs: BuildNeedsSnapshot | None = None, profiles=PROFILE_NAMES) -> list[Replay]:
    needs = needs or reference_needs(entry)
    model = BuildOpportunityModel(needs)
    out = []
    for profile in profiles:
        result = generate(needs, profile, intel=True)
        without_craft = [r for r in result.rules if r.category != "CRAFT_OPPORTUNITY"]
        for rarity, ilvl in entry["item"]["tested_as"]:
            item = make_item(entry["item"]["base"], rarity=rarity, item_level=ilvl)
            before, after = preview_decision(without_craft, item), preview_decision(result.rules, item)
            rule = next((r for r in result.rules if r.name == after.rule_name), None)
            lanes = decide(item, profile, model=model, build_shown=bool(rule and rule.category.startswith("BUILD") and not after.hidden))
            out.append(Replay(entry["id"], profile, rarity, ilvl, not before.hidden, before.rule_name, not after.hidden, after.rule_name,
                              lanes.cause.value if lanes.cause else None,
                              {v.lane.value: v.level.value for v in lanes.verdicts}, lanes.why))
    return out
