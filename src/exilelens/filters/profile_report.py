"""Profile system V2 measurements (offline, read-only): one corpus through every strictness level, with and without a build.

Used by `scripts/filter_profile_v2_report.py` and the contract tests. Nothing here feeds generation.

Corpus = the stratified legal corpus (FILTER-08D generator) + floors of the Random Drops pool (realistic names, stacks, gems, specials), in the
MAPS context (area level 82) unless a function says otherwise. Every item is classified by the ORACLE (`profile_oracle`, independent of the
generated rules); a decision is the generated filter's first match as the preview simulator reads it.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from pathlib import Path

from exilelens.filters import profile_policy as pp
from exilelens.filters.preview import PreviewItem

LEVELS = pp.LEVELS
RANK = {**pp.VISIBILITY_RANK, "SAFETY": pp.VISIBILITY_RANK["SHOW+"]}
EQUIPMENT_FAMILY_PREFIXES = ("eq_", "jewellery_")


def corpus(legal: int = 4000, floors: int = 150, seed: int = 5) -> list[PreviewItem]:
    """Deterministic corpus (unique item states). Unidentified tiers exist only on equipment."""
    from exilelens.filters import legal_corpus as lc
    from exilelens.filters.opportunity import ROLE_BY_CLASS
    from exilelens.filters.scene_pool import random_scene_items
    items = [case.item for case in lc.sample(legal, seed)]
    for number in range(floors):
        items.extend(random_scene_items(10_000 + number))
    seen, out = set(), []
    for item in items:
        if item.unidentified_item_tier and item.item_class not in ROLE_BY_CLASS:
            continue
        key = (item.name, item.item_class, item.base_type, item.rarity, item.item_level, item.quality, item.unidentified_item_tier,
               item.waystone_tier, item.gem_level, item.stack_size)
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def family_of(item: PreviewItem) -> str:
    """Filter-independent family label (the oracle's winning row at Relaxed; 'unknown' when no row classifies the item)."""
    from exilelens.filters.profile_oracle import UNKNOWN_ROW, classify
    c = classify(item, "Relaxed")
    return c.rows[0] if c.rows else UNKNOWN_ROW


def kind_of(item: PreviewItem) -> str:
    """Coarse group used in the reports."""
    from exilelens.filters.profile_oracle import classify
    rows = classify(item, "Relaxed").rows
    first = rows[0]
    if first.startswith("currency_"):
        return "currency"
    if first.startswith("waystones_"):
        return "waystones"
    if first.startswith("eq_normal") or first.startswith("eq_magic") or first == "jewellery_low_generic" or first == "jewellery_premium_base":
        return "equipment_normal_magic"
    if first.startswith("eq_rare") or first == "jewellery_rare":
        return "equipment_rare"
    if first.startswith(("gems_", "jewels_", "charms_", "flasks_")):
        return first.split("_")[0]
    if first.startswith("uniques_"):
        return "uniques"
    return first


@dataclass(frozen=True)
class Decision:
    hidden: bool
    state: str          # SHOW+ | SHOW | QUIET | HIDE | SAFETY
    row: str
    rule: str
    sound: bool
    beam: str           # "" | persistent | temp
    icon: bool
    font: int

    @property
    def visible_state(self) -> str:
        return "HIDE" if self.hidden else self.state


def decide_all(rules, items) -> list[Decision]:
    from exilelens.filters.preview import preview_decision
    out = []
    for item in items:
        d = preview_decision(rules, item)
        beam = "" if not d.effect else ("temp" if d.effect.endswith("Temp") else "persistent")
        out.append(Decision(d.hidden, "HIDE" if d.hidden else (d.state or "SHOW"), d.row, d.rule_name, "sound " in d.native_details, beam,
                            bool(d.minimap_icon), d.font_size))
    return out


def load_builds(root: Path) -> dict[str, object]:
    from exilelens.filters import benchmark08b as bm
    from exilelens.filters.build_needs import BuildNeedsSnapshot
    builds: dict[str, object] = {"no_build": BuildNeedsSnapshot.unavailable("No build", "no build connected")}
    canonical = bm.load_snapshots(root / "tests" / "fixtures" / "filter_needs" / "filter08e")
    complete = bm.load_snapshots(root / "tests" / "fixtures" / "filter_needs" / "filter08c")
    # the standard-complete measurement (Armour / Evasion probes included): the build modifier needs COMPLETE evidence to act at all
    builds["spark"] = complete.get("spark_fixture", canonical["spark_fixture"])
    for label, key in (("bow", "core04_bow_quiver"), ("melee", "core04_melee_weapon"), ("minion", "core04_minion_actor")):
        if key in complete:
            builds[label] = complete[key]
    return builds


def effects_in_rules(rules) -> dict[str, int]:
    """Counts of attention effects in the generated rules (Show rules only)."""
    counts = Counter()
    for rule in rules:
        lines = [line.strip() for line in rule.lines]
        if not lines or lines[0] != "Show":
            continue
        for line in lines:
            if line.startswith("PlayAlertSound "):
                counts["sound_rules"] += 1
            elif line.startswith("PlayEffect "):
                counts["temp_beam_rules" if line.endswith("Temp") else "persistent_beam_rules"] += 1
            elif line.startswith("MinimapIcon "):
                counts["minimap_rules"] += 1
    return dict(counts)


def summarize(items, decisions) -> dict:
    """Per-level numbers for one (build, level)."""
    states = Counter(d.visible_state if d.state != "SAFETY" else "SHOW+" for d in decisions)
    visible = [(i, d) for i, d in zip(items, decisions) if not d.hidden]
    by_kind: dict[str, Counter] = defaultdict(Counter)
    for item, d in zip(items, decisions):
        by_kind[kind_of(item)]["n"] += 1
        by_kind[kind_of(item)]["visible"] += not d.hidden
        by_kind[kind_of(item)][d.visible_state if d.state != "SAFETY" else "SHOW+"] += 1
    return {
        "items": len(items), "visible": len(visible), "hidden": len(items) - len(visible),
        "states": dict(states),
        "attention": {"sound_items": sum(d.sound for _, d in visible), "persistent_beam_items": sum(d.beam == "persistent" for _, d in visible),
                      "temp_beam_items": sum(d.beam == "temp" for _, d in visible), "minimap_items": sum(d.icon for _, d in visible)},
        "kinds": {k: dict(v) for k, v in sorted(by_kind.items())},
    }


def transition(items, a: list[Decision], b: list[Decision]) -> dict:
    """Everything that changes between two adjacent levels for the same build and corpus."""
    flows = Counter()
    families_hidden, families_quieted, families_effects = Counter(), Counter(), Counter()
    inversions = []
    build_changed = craft_changed = 0
    attention_removed = Counter()
    for item, x, y in zip(items, a, b):
        sx, sy = ("SHOW+" if x.state == "SAFETY" else x.visible_state), ("SHOW+" if y.state == "SAFETY" else y.visible_state)
        if sx != sy:
            flows[f"{sx} -> {sy}"] += 1
            if RANK[sy] > RANK[sx]:
                inversions.append((item.name, item.item_class, item.rarity, x.rule, y.rule, sx, sy))
        fam = family_of(item)
        if sy == "HIDE" and sx != "HIDE":
            families_hidden[fam] += 1
        elif sy == "QUIET" and sx not in ("QUIET", "HIDE"):
            families_quieted[fam] += 1
        if not x.hidden and not y.hidden:
            lost = (x.sound and not y.sound) + (x.beam != "" and y.beam == "") + (x.icon and not y.icon)
            if lost:
                families_effects[fam] += 1
                attention_removed["items"] += 1
                attention_removed["sound"] += x.sound and not y.sound
                attention_removed["beam"] += x.beam != "" and y.beam == ""
                attention_removed["minimap"] += x.icon and not y.icon
        if x.row != y.row or sx != sy:
            if x.row.startswith("build_") or y.row.startswith("build_"):
                build_changed += 1
            if x.row.startswith("craft_") or y.row.startswith("craft_"):
                craft_changed += 1
    total_change = sum(flows.values())
    return {
        "state_flows": dict(flows.most_common()), "changed_decisions": total_change, "changed_pct": round(100 * total_change / len(items), 2),
        "newly_quiet": sum(v for k, v in flows.items() if k.endswith("-> QUIET")),
        "newly_hidden": sum(v for k, v in flows.items() if k.endswith("-> HIDE")),
        "attention_removed": dict(attention_removed), "families_newly_hidden": dict(families_hidden.most_common(14)),
        "families_newly_quiet": dict(families_quieted.most_common(14)), "families_losing_effects": dict(families_effects.most_common(14)),
        "build_cases_affected": build_changed, "craft_cases_affected": craft_changed, "inversions": len(inversions),
        "inversion_examples": inversions[:5],
    }


def save(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")
