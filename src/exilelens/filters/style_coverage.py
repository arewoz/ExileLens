"""Themed-visibility coverage: does every item the filter keeps visible get an explicit ExileLens treatment?

Product invariant (FILTER-THEMED-VISIBILITY-COVERAGE): an item that stays visible must match an explicit ExileLens rule that carries the V4
text / plaque actions. The game's own label is never the outcome for a known item.

Outcomes of one item evaluated against a generated rule list (first match, exactly as the preview and the game read it):

  EXPLICIT_STYLED_SHOW        a Show rule matched and carries SetFontSize / SetTextColor / SetBorderColor / SetBackgroundColor
  EXPLICIT_HIDE               a Hide rule matched
  UNKNOWN_SAFETY              the SAFETY catch-all matched an item NO matrix row classifies (a genuinely unknown / new item)
  KNOWN_IN_UNKNOWN_SAFETY     the SAFETY catch-all matched an item the oracle DOES classify (known item mistreated as unknown)
  UNSTYLED_VISIBLE_FALLTHROUGH  visible with the game's default label: either no rule matched at all, or a Show rule matched that lacks
                              the text / plaque actions

The target is zero for the last two.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from exilelens.filters.preview import PreviewItem, _matches_condition, _parsed_rule

REQUIRED_ACTIONS = ("SetFontSize", "SetTextColor", "SetBorderColor", "SetBackgroundColor")
_NON_CONDITION_PREFIXES = ("Show", "Hide", "Set", "Play", "MinimapIcon", "Continue", "DisableDropSound")

EXPLICIT_STYLED_SHOW = "EXPLICIT_STYLED_SHOW"
EXPLICIT_HIDE = "EXPLICIT_HIDE"
UNKNOWN_SAFETY = "UNKNOWN_SAFETY"
KNOWN_IN_UNKNOWN_SAFETY = "KNOWN_IN_UNKNOWN_SAFETY"
UNSTYLED_NO_RULE = "UNSTYLED_VISIBLE_FALLTHROUGH:no_rule"
UNSTYLED_NO_ACTIONS = "UNSTYLED_VISIBLE_FALLTHROUGH:show_without_style"
OUTCOMES = (EXPLICIT_STYLED_SHOW, EXPLICIT_HIDE, UNKNOWN_SAFETY, KNOWN_IN_UNKNOWN_SAFETY, UNSTYLED_NO_RULE, UNSTYLED_NO_ACTIONS)


def first_match(rules, item: PreviewItem):
    """The first rule whose conditions the item satisfies (the native first-match contract; no Continue is generated)."""
    for rule in rules:
        action, conditions = _parsed_rule(tuple(rule.lines))
        if action is None:
            continue
        if all(_matches_condition(line, item) for line in conditions):
            return rule, action
    return None, None


def styled_actions(rule) -> frozenset[str]:
    return frozenset(line.split()[0] for line in (l.strip() for l in rule.lines) if line and line.split()[0] in REQUIRED_ACTIONS)


def has_required_style(rule) -> bool:
    return len(styled_actions(rule)) == len(REQUIRED_ACTIONS)


@dataclass(frozen=True)
class Verdict:
    outcome: str
    rule: str
    state: str
    role: str
    row: str


def judge(rules, item: PreviewItem, *, known: bool) -> Verdict:
    """`known` = the independent oracle classifies the item (some matrix row owns it)."""
    rule, action = first_match(rules, item)
    if rule is None:
        return Verdict(UNSTYLED_NO_RULE, "", "", "", "")
    state = getattr(rule, "state", "") or ""
    role = getattr(rule, "role", "") or ""
    row = getattr(rule, "row", "") or ""
    if action == "Hide":
        return Verdict(EXPLICIT_HIDE, rule.name, state, role, row)
    if state == "SAFETY" or role == "unknown":
        return Verdict(KNOWN_IN_UNKNOWN_SAFETY if known else UNKNOWN_SAFETY, rule.name, state, role, row)
    if not has_required_style(rule):
        return Verdict(UNSTYLED_NO_ACTIONS, rule.name, state, role, row)
    return Verdict(EXPLICIT_STYLED_SHOW, rule.name, state, role, row)


def is_failure(outcome: str) -> bool:
    return outcome in (KNOWN_IN_UNKNOWN_SAFETY, UNSTYLED_NO_RULE, UNSTYLED_NO_ACTIONS)


def evaluate(rules, items, known_flags) -> list[Verdict]:
    return [judge(rules, item, known=known) for item, known in zip(items, known_flags)]


def family(item: PreviewItem) -> str:
    """Coarse item family for the report."""
    cls = item.item_class
    if cls == "Stackable Currency" or cls == "Incubators":
        return "currency"
    if cls in ("Waystones",):
        return "waystone"
    if cls in ("Rings", "Amulets", "Belts"):
        return "jewellery"
    if cls in ("Jewels",):
        return "jewel"
    if cls in ("Charms", "Flasks", "Life Flasks", "Mana Flasks"):
        return "flask_charm"
    if "Gem" in cls:
        return "gem"
    if cls in ("Omen", "Tablet", "Augment", "Map Fragments", "Pinnacle Keys", "Quest Items", "Instance Local Items"):
        return "special"
    if item.base_type and cls:
        return "equipment"
    return "other"


def summarise(items, verdicts) -> dict:
    """Counts by outcome, by rarity x outcome and by family x outcome."""
    total: Counter = Counter()
    by_rarity: dict[str, Counter] = defaultdict(Counter)
    by_family: dict[str, Counter] = defaultdict(Counter)
    by_state: Counter = Counter()
    by_row: Counter = Counter()
    failures: dict[str, Counter] = defaultdict(Counter)
    for item, verdict in zip(items, verdicts):
        total[verdict.outcome] += 1
        by_rarity[item.rarity or "-"][verdict.outcome] += 1
        by_family[family(item)][verdict.outcome] += 1
        by_state[verdict.state or "-"] += 1
        if verdict.row in ("known_generic_fallback", "unknown_new_items"):
            by_row[verdict.row] += 1
        if is_failure(verdict.outcome):
            failures[verdict.outcome][f"{verdict.rule or '(no rule)'} | {item.rarity} | {family(item)}"] += 1
    unstyled = total[UNSTYLED_NO_RULE] + total[UNSTYLED_NO_ACTIONS]
    return {
        "states": len(items), "outcomes": {o: total[o] for o in OUTCOMES},
        "unstyled_visible_fallthrough": unstyled, "known_in_unknown_safety": total[KNOWN_IN_UNKNOWN_SAFETY],
        "by_rarity": {k: dict(v) for k, v in sorted(by_rarity.items())}, "by_family": {k: dict(v) for k, v in sorted(by_family.items())},
        "by_state": dict(by_state), "fallback_rows": dict(by_row),
        "failure_examples": {o: dict(c.most_common(12)) for o, c in failures.items()},
    }


def qa_fixture(rules) -> list[tuple[str, PreviewItem]]:
    """Representative QA scene modelled on the real-game screenshot (a generic Rare Body Armour, Unidentified Tier 2, among BUILD / CRAFT /
    unique / unknown neighbours). BUILD and CRAFT picks come from the rules themselves, so the fixture always exists for the rules it audits."""
    from exilelens.filters.verified_bases import load_base_properties, native_class

    def first_base(category: str, cls: str | None = None) -> str | None:
        for rule in rules:
            if rule.category == category and rule.base_types and not any(l.strip() == "Hide" for l in rule.lines):
                for base in rule.base_types:
                    if cls is None or native_class(base) == cls:
                        return base
        return None

    props = load_base_properties()

    def rare(base: str, *, unid: int = 0, ilvl: int = 80, rarity: str = "Rare", area_level: int = 30) -> PreviewItem:
        record = props[base]
        return PreviewItem(f"{base} [{rarity}]", "themed visibility QA", native_class(base), base, rarity,
                           item_level=max(ilvl, int(record["required_level"])), area_level=area_level, unidentified_item_tier=unid,
                           base_energy_shield=record["energy_shield"], base_armour=record["armour"], base_evasion=record["evasion"])

    items: list[tuple[str, PreviewItem]] = [("generic_rare_body_armour_unid_t2", rare("Soldier Cuirass", unid=2)),
                                            ("generic_rare_body_armour_identified", rare("Soldier Cuirass")),
                                            ("quiet_rare_in_maps", rare("Soldier Cuirass", unid=2, area_level=82))]
    build = first_base("BUILD_DEFENSE", "Body Armours")
    if build:
        items.append(("build_relevant_armour", rare(build, unid=1)))
    craft = first_base("CRAFT_OPPORTUNITY", "Body Armours") or first_base("CRAFT_OPPORTUNITY")
    if craft:
        items.append(("craft_relevant", rare(craft, rarity="Normal")))
    weapon = next((b for b in sorted(props) if native_class(b) == "One Hand Swords"), None)
    if weapon:
        items.append(("generic_rare_weapon", rare(weapon)))
    items.append(("unique", rare("Utility Belt", rarity="Unique")))
    items.append(("unknown_safety", PreviewItem("Unseen Relic [Rare]", "themed visibility QA", "Body Armours", "Unseen Relic", "Rare",
                                                item_level=80, area_level=30)))
    return items
