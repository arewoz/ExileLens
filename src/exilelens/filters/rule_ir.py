"""Rule intermediate representation, static analysis and verified optimisation (FILTER-08D).

Every generated rule is a conjunction of per-property conditions, so over a discretised item space it is a *box* (a cartesian product of
per-axis value sets). That makes first-match analysis exact and cheap: a rule's effective region is its box minus the boxes of the earlier
rules, and every question below (shadowed, dead, duplicate, redundant, protective-shadowed, equivalent) is a box-algebra question.

The item space (``Universe``) is built from the rules themselves plus the verified catalog:
  * ``group``      — verified bases (and special named bases / referenced classes) collapsed into groups that behave identically for
                     every Class / BaseType / base-defence condition under analysis;
  * numeric axes   — item level, quality, sockets, ... sampled at every threshold used by the rules (t-1, t, t+1) so each interval of
                     every comparison has a representative;
  * rarity, unidentified tier, waystone tier, corrupted/mirrored.
Realism: an unidentified tier exists only on Rare items and a waystone tier only on Waystones; the analysis is restricted to that region,
so a "shadowed" verdict over-approximates reachability (it is sound: a reported shadowed rule is shadowed on every real item).

Matching mirrors ``preview._matches_condition`` exactly (it is evaluated, not re-implemented), so IR verdicts agree with the simulator.
"""
from __future__ import annotations

import shlex
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Iterable, Sequence

from exilelens.filters.base_match import BaseCondition, BaseMatch
from exilelens.filters.preview import PreviewItem, _matches_condition, preview_decision
from exilelens.filters.rules import GeneratedRule
from exilelens.filters.verified_bases import SPECIAL_BASES as PINNED_SPECIAL_BASES, load_base_properties, native_class

NON_CONDITION_PREFIX = ("Show", "Hide", "Set", "Play", "MinimapIcon", "Continue", "DisableDropSound", "#")
PROTECTIVE_CATEGORIES = frozenset({"PROTECTIVE", "TRADE_HERO", "TRADE_SPECIAL", "CURRENCY_TOP", "CURRENCY_PREMIUM", "CURRENCY_CRAFT",
                                   "CURRENCY_VALUABLE", "CURRENCY_LOW"})
# axis name -> (item attribute used by preview, default value, (lo, hi) clamp)
NUMERIC = {"ItemLevel": ("item_level", 82, (1, 100)), "AreaLevel": ("area_level", 82, (1, 100)), "Quality": ("quality", 0, (0, 30)),
           "Sockets": ("sockets", 0, (0, 6)), "LinkedSockets": ("linked_sockets", 0, (0, 6)),
           "UnidentifiedItemTier": ("unidentified_item_tier", 0, (0, 5)), "WaystoneTier": ("waystone_tier", 0, (0, 17)),
           "GemLevel": ("gem_level", 0, (0, 21))}
BASE_ATTR = ("BaseArmour", "BaseEvasion", "BaseEnergyShield")
GROUP_KEYS = ("Class", "BaseType", *BASE_ATTR)
BOOL_KEYS = {"Corrupted": "corrupted", "Mirrored": "mirrored"}
RARITIES = ("Normal", "Magic", "Rare", "Unique")
AXES = ("group", "rarity", "ItemLevel", "AreaLevel", "Quality", "Sockets", "LinkedSockets", "UnidentifiedItemTier", "WaystoneTier",
        "GemLevel", "Corrupted", "Mirrored")
AXIS_INDEX = {name: index for index, name in enumerate(AXES)}
Box = tuple[int, ...]


# -- rule IR ----------------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Effect:
    """What a matched rule does to an item (visibility + every style/sound/icon attribute; later duplicate keys override)."""
    action: str                                  # Show | Hide | Default
    style: tuple[tuple[str, str], ...] = ()

    def visible(self) -> bool:
        return self.action != "Hide"


DEFAULT_EFFECT = Effect("Default")


@dataclass(frozen=True)
class IRRule:
    index: int
    name: str
    category: str
    action: str
    conditions: tuple[str, ...]                  # native condition lines, normalised whitespace
    effect: Effect
    provenance: str                              # the rule's evidence text (why it exists)
    justification: str
    unmodelled: tuple[str, ...]                  # condition keys the simulator can never satisfy (rule is dead)
    base_types: frozenset[str]
    protective: bool

    @property
    def is_hide(self) -> bool:
        return self.action == "Hide"

    def signature(self) -> tuple:
        return (self.action, tuple(sorted(self.conditions)), self.effect.style)


def to_ir(rules: Sequence[GeneratedRule]) -> list[IRRule]:
    """Rules without a Show/Hide line are ignored by first-match evaluation exactly as the simulator ignores them."""
    out: list[IRRule] = []
    for index, rule in enumerate(rules):
        action = next((line.strip() for line in rule.lines if line.strip() in {"Show", "Hide"}), None)
        if action is None:
            continue
        conditions = tuple(" ".join(line.split()) for line in rule.lines if line.strip() and not line.strip().startswith(NON_CONDITION_PREFIX))
        style: dict[str, str] = {}
        for line in rule.lines:
            parts = line.strip().split(None, 1)
            if parts and parts[0].startswith(("Set", "Play", "MinimapIcon", "DisableDropSound")):
                style[parts[0]] = " ".join(parts[1].split()) if len(parts) > 1 else ""
        keys = [shlex.split(c)[0] for c in conditions if shlex.split(c)]
        known = set(GROUP_KEYS) | set(NUMERIC) | set(BOOL_KEYS) | {"Rarity"}
        base_types: set[str] = set()
        for condition in conditions:
            base_condition = BaseCondition.parse(condition)
            if base_condition is not None:
                base_types.update(base_condition.names)
        evidence = rule.evidence.explain() if rule.evidence else ""
        out.append(IRRule(index, rule.name, rule.category, action, conditions, Effect(action, tuple(sorted(style.items()))), evidence,
                          rule.justification, tuple(k for k in keys if k not in known), frozenset(base_types),
                          rule.category in PROTECTIVE_CATEGORIES))
    return out


# -- universe ---------------------------------------------------------------------------------------------------------------------------
@dataclass
class Group:
    item: PreviewItem                            # representative item (class + base + base defences)
    members: list[str]
    item_class: str

    @property
    def weight(self) -> int:
        return max(1, len(self.members))


@dataclass
class Universe:
    groups: list[Group]
    samples: dict[str, list]                     # axis -> ordered sample values
    group_bits: dict[str, int]                   # condition line -> bitset over groups
    axis_bits: dict[tuple[str, str], int]        # (axis, condition line) -> bitset over axis samples
    realistic: list[Box]
    full: Box
    unreferenced: list[str] = field(default_factory=list)   # BaseType names no verified base / known special matches

    # -- construction
    @staticmethod
    def build(rule_lists: Iterable[Sequence[IRRule]]) -> "Universe":
        lists = [list(rl) for rl in rule_lists]
        lines = sorted({c for rules in lists for r in rules for c in r.conditions})
        thresholds: dict[str, set[int]] = defaultdict(set)
        classes: set[str] = set()
        named: set[str] = set()
        for line in lines:
            parts = shlex.split(line)
            if not parts:
                continue
            key, values = parts[0], parts[1:]
            if key in NUMERIC and values:
                try:
                    thresholds[key].add(int(values[1] if values[0] in {">=", "<=", ">", "<", "="} else values[0]))
                except (IndexError, ValueError):
                    pass
            elif key == "Class":
                classes.update(values)
            elif key == "BaseType":
                base_condition = BaseCondition.parse(line)
                if base_condition is not None and base_condition.match == BaseMatch.EXACT_BASE:
                    named.update(base_condition.names)
        samples: dict[str, list] = {"rarity": list(RARITIES)}
        for key, (_attr, default, (lo, hi)) in NUMERIC.items():
            points = {default}
            if thresholds.get(key):
                points |= {lo, hi}
                for t in thresholds[key]:
                    points |= {t - 1, t, t + 1}
            if key == "UnidentifiedItemTier":
                points |= {0, 1, 5}
            if key == "WaystoneTier":
                points |= {0, 1, 16}
            samples[key] = sorted(p for p in points if lo <= p <= hi)
        samples["Corrupted"] = [False, True] if any(c.startswith("Corrupted") for c in lines) else [False]
        samples["Mirrored"] = [False, True] if any(c.startswith("Mirrored") for c in lines) else [False]

        # candidate group entries
        entries: list[PreviewItem] = []
        props = load_base_properties()
        verified: set[str] = set()
        for base in sorted(props):
            cls = native_class(base)
            if cls is None:
                continue
            verified.add(base)
            rec = props[base]
            entries.append(PreviewItem(base, "", cls, base, base_energy_shield=rec["energy_shield"], base_armour=rec["armour"],
                                       base_evasion=rec["evasion"]))
        for name in sorted(PINNED_SPECIAL_BASES):
            verified.add(name)
            entries.append(PreviewItem(name, "", PINNED_SPECIAL_BASES[name], name))    # the registry's real class (Vaal Siphoner: Incubators)
        for cls in sorted(classes | {"Stackable Currency", "Omen", "Waystones", "Tablet", "Augment", "Quest Items", "Map Fragments",
                                     "Pinnacle Keys", "Unknown", *PINNED_SPECIAL_BASES.values()}):
            entries.append(PreviewItem(f"<{cls}>", "", cls, ""))
        unreferenced = sorted(n for n in named if n not in verified)
        for name in unreferenced:
            entries.append(PreviewItem(name, "", "", name))

        group_lines = [ln for ln in lines if (shlex.split(ln) or [""])[0] in GROUP_KEYS]
        truth: dict[str, list[bool]] = {ln: [_matches_condition(ln, e) for e in entries] for ln in group_lines}
        grouped: dict[tuple, Group] = {}
        for position, entry in enumerate(entries):
            signature = (entry.item_class, tuple(truth[ln][position] for ln in group_lines))
            group = grouped.get(signature)
            if group is None:
                grouped[signature] = Group(entry, [entry.base_type or entry.name], entry.item_class)
            else:
                group.members.append(entry.base_type or entry.name)
        groups = list(grouped.values())
        group_bits: dict[str, int] = {}
        for ln in group_lines:
            bits = 0
            for index, group in enumerate(groups):
                if _matches_condition(ln, group.item):
                    bits |= 1 << index
            group_bits[ln] = bits

        axis_bits: dict[tuple[str, str], int] = {}
        for ln in lines:
            parts = shlex.split(ln)
            key = parts[0] if parts else ""
            if key == "Rarity":
                axis, template = "rarity", lambda v: PreviewItem("", "", "", rarity=v)
            elif key in NUMERIC:
                axis, template = key, (lambda v, attr=NUMERIC[key][0]: PreviewItem("", "", "", **{attr: v}))
            elif key in BOOL_KEYS:
                axis, template = key, (lambda v, attr=BOOL_KEYS[key]: PreviewItem("", "", "", **{attr: v}))
            else:
                continue
            values = samples[axis]
            bits = 0
            for index, value in enumerate(values):
                if _matches_condition(ln, template(value)):
                    bits |= 1 << index
            axis_bits[(axis, ln)] = bits

        universe = Universe(groups, samples, group_bits, axis_bits, [], (), unreferenced)
        universe.full = universe._full_box()
        universe.realistic = universe._realistic()
        return universe

    # -- boxes
    def _axis_size(self, axis: str) -> int:
        return len(self.groups) if axis == "group" else len(self.samples[axis])

    def _full_box(self) -> Box:
        return tuple((1 << self._axis_size(axis)) - 1 for axis in AXES)

    def _realistic(self) -> list[Box]:
        waystone_groups = sum(1 << i for i, g in enumerate(self.groups) if g.item_class.casefold() == "waystones")
        other_groups = self.full[0] & ~waystone_groups
        samples = self.samples
        rarity = {name: 1 << i for i, name in enumerate(samples["rarity"])}
        unid_zero = sum(1 << i for i, v in enumerate(samples["UnidentifiedItemTier"]) if v == 0)
        way_zero = sum(1 << i for i, v in enumerate(samples["WaystoneTier"]) if v == 0)

        def make(groups: int, rar: int, unid: int, waystone: int) -> Box:
            box = list(self.full)
            box[0], box[AXIS_INDEX["rarity"]] = groups, rar
            box[AXIS_INDEX["UnidentifiedItemTier"]], box[AXIS_INDEX["WaystoneTier"]] = unid, waystone
            return tuple(box)

        not_rare = rarity["Normal"] | rarity["Magic"] | rarity["Unique"]
        return [b for b in (make(other_groups, not_rare, unid_zero, way_zero),
                            make(other_groups, rarity["Rare"], self.full[AXIS_INDEX["UnidentifiedItemTier"]], way_zero),
                            make(waystone_groups, self.full[AXIS_INDEX["rarity"]], unid_zero, self.full[AXIS_INDEX["WaystoneTier"]]))
                if not is_empty(b)]

    def box_of(self, rule: IRRule) -> Box:
        if rule.unmodelled:
            return tuple(0 for _ in AXES)
        box = list(self.full)
        for line in rule.conditions:
            key = (shlex.split(line) or [""])[0]
            if key in GROUP_KEYS:
                box[0] &= self.group_bits[line]
            elif key == "Rarity":
                box[AXIS_INDEX["rarity"]] &= self.axis_bits[("rarity", line)]
            elif key in NUMERIC or key in BOOL_KEYS:
                box[AXIS_INDEX[key]] &= self.axis_bits[(key, line)]
        return tuple(box)

    # -- measures
    def group_weight(self, mask: int) -> int:
        total, index = 0, 0
        while mask:
            if mask & 1:
                total += self.groups[index].weight
            mask >>= 1
            index += 1
        return total

    def volume(self, box: Box) -> int:
        """Base-weighted volume: bases x (rarity x numeric samples ...)."""
        v = self.group_weight(box[0])
        for mask in box[1:]:
            v *= bin(mask).count("1")
        return v

    def bases_in(self, boxes: Iterable[Box]) -> set[str]:
        mask = 0
        for box in boxes:
            mask |= box[0]
        names: set[str] = set()
        for index, group in enumerate(self.groups):
            if mask >> index & 1:
                names.update(group.members)
        return names

    def example(self, box: Box) -> PreviewItem:
        """A concrete item from the box (lowest set bit of every axis)."""
        def first(mask: int) -> int:
            return (mask & -mask).bit_length() - 1
        group = self.groups[first(box[0])]
        values = {NUMERIC[a][0]: self.samples[a][first(box[AXIS_INDEX[a]])] for a in NUMERIC}
        values.update({BOOL_KEYS[a]: self.samples[a][first(box[AXIS_INDEX[a]])] for a in BOOL_KEYS})
        return PreviewItem(group.members[0], "", group.item_class, group.item.base_type, self.samples["rarity"][first(box[1])],
                           base_energy_shield=group.item.base_energy_shield, base_armour=group.item.base_armour,
                           base_evasion=group.item.base_evasion, **values)


def is_empty(box: Box) -> bool:
    return any(mask == 0 for mask in box)


def intersect(a: Box, b: Box) -> Box:
    return tuple(x & y for x, y in zip(a, b))


def subtract(a: Box, b: Box) -> list[Box]:
    """a minus b as disjoint boxes."""
    if is_empty(intersect(a, b)):
        return [a]
    out: list[Box] = []
    prefix = list(a)
    for axis, (x, y) in enumerate(zip(a, b)):
        rest = x & ~y
        if rest:
            piece = list(prefix)
            piece[axis] = rest
            out.append(tuple(piece))
        prefix[axis] = x & y
        if prefix[axis] == 0:
            break
    return out


def subtract_all(boxes: list[Box], cutters: Iterable[Box]) -> list[Box]:
    for cutter in cutters:
        if not boxes:
            break
        boxes = [piece for box in boxes for piece in subtract(box, cutter)]
    return boxes


# -- analysis ---------------------------------------------------------------------------------------------------------------------------
@dataclass
class RegionMap:
    """First-match decision map: disjoint boxes, each owned by the rule that matches first (or the game default)."""
    rules: list[IRRule]
    universe: Universe
    boxes: list[Box]                             # per rule: its full box
    owned: list[list[Box]]                       # per rule: realistic first-match region
    default_region: list[Box]

    def entries(self) -> Iterable[tuple[Box, IRRule | None]]:
        for rule, region in zip(self.rules, self.owned):
            for box in region:
                yield box, rule
        for box in self.default_region:
            yield box, None


def region_map(rules: Sequence[IRRule], universe: Universe) -> RegionMap:
    ir = list(rules)
    boxes = [universe.box_of(r) for r in ir]
    owned: list[list[Box]] = []
    for k, box in enumerate(boxes):
        pieces = [p for p in (intersect(box, real) for real in universe.realistic) if not is_empty(p)]
        pieces = subtract_all(pieces, (boxes[j] for j in range(k) if not is_empty(intersect(box, boxes[j]))))
        owned.append(pieces)
    rest = list(universe.realistic)
    rest = subtract_all(rest, (b for b in boxes if not is_empty(b)))
    return RegionMap(ir, universe, boxes, owned, rest)


SEVERITY = {"DEAD": "DEFECT", "CONTRADICTORY": "DEFECT", "UNREACHABLE": "DEFECT", "PROTECTIVE_NEVER_MATCHES": "DEFECT",
            "PROTECTIVE_SHADOWED_BY_HIDE": "DEFECT", "SHADOWED": "WARN", "DUPLICATE": "WARN", "REDUNDANT": "WARN", "HIDE_TOO_BROAD": "WARN",
            "SHOW_PREEMPTED_BY_HIDE": "WARN", "PARTIALLY_SHADOWED": "INFO"}


@dataclass
class RuleFinding:
    kind: str
    rule: str
    category: str
    index: int
    detail: str
    related: tuple[str, ...] = ()

    @property
    def severity(self) -> str:
        return SEVERITY.get(self.kind, "INFO")


@dataclass
class AnalysisReport:
    rule_count: int
    findings: list[RuleFinding]
    hide_rules: list[dict]
    unreferenced_base_types: list[str]
    protective_checked: int

    def count(self, kind: str) -> int:
        return sum(1 for f in self.findings if f.kind == kind)

    def defects(self) -> list[RuleFinding]:
        return [f for f in self.findings if f.severity == "DEFECT"]

    def summary(self) -> dict[str, object]:
        return {"rules": self.rule_count, "findings": dict(sorted(Counter(f.kind for f in self.findings).items())),
                "by_severity": dict(sorted(Counter(f.severity for f in self.findings).items())),
                "protective_rules_checked": self.protective_checked, "hide_rules": len(self.hide_rules),
                "unreferenced_base_types": len(self.unreferenced_base_types)}


def analyse(rules: Sequence[GeneratedRule] | Sequence[IRRule], *, universe: Universe | None = None) -> AnalysisReport:
    ir = list(rules) if rules and isinstance(rules[0], IRRule) else to_ir(rules)       # type: ignore[arg-type]
    universe = universe or Universe.build([ir])
    rmap = region_map(ir, universe)
    findings: list[RuleFinding] = []
    by_signature: dict[tuple, IRRule] = {}
    real_volume = lambda box: sum(universe.volume(p) for p in (intersect(box, real) for real in universe.realistic) if not is_empty(p))  # noqa: E731

    for k, rule in enumerate(ir):
        box = rmap.boxes[k]
        if rule.unmodelled:
            findings.append(RuleFinding("DEAD", rule.name, rule.category, rule.index,
                                        "condition(s) the matcher never satisfies: " + ", ".join(rule.unmodelled)))
            continue
        if is_empty(box):
            findings.append(RuleFinding("CONTRADICTORY", rule.name, rule.category, rule.index, "its conditions cannot all hold on any item"))
            continue
        full_volume, owned_volume = real_volume(box), sum(universe.volume(p) for p in rmap.owned[k])
        covering = tuple(ir[j].name for j in range(k) if not is_empty(intersect(box, rmap.boxes[j])))
        signature = rule.signature()
        if signature in by_signature:
            findings.append(RuleFinding("DUPLICATE", rule.name, rule.category, rule.index,
                                        f"identical conditions and effect to earlier rule {by_signature[signature].name}",
                                        (by_signature[signature].name,)))
        else:
            by_signature[signature] = rule
        if full_volume == 0:
            findings.append(RuleFinding("UNREACHABLE", rule.name, rule.category, rule.index, "matches only combinations that cannot exist"))
        elif owned_volume == 0:
            if signature in by_signature and by_signature[signature] is not rule:
                continue                                  # already reported as DUPLICATE
            findings.append(RuleFinding("SHADOWED", rule.name, rule.category, rule.index,
                                        f"every item it matches is matched by an earlier rule ({len(covering)} overlapping)", covering[:6]))
        elif owned_volume < full_volume:
            findings.append(RuleFinding("PARTIALLY_SHADOWED", rule.name, rule.category, rule.index,
                                        f"{owned_volume}/{full_volume} of its region is reachable ({100 * owned_volume // full_volume}%)", covering[:6]))
        if owned_volume and _redundant(k, rmap):
            findings.append(RuleFinding("REDUNDANT", rule.name, rule.category, rule.index,
                                        "removing it would leave every decision and style unchanged (a later rule produces the same effect)"))

    hide_rules: list[dict] = []
    protective_checked = 0
    for k, rule in enumerate(ir):
        box = rmap.boxes[k]
        if rule.protective and not is_empty(box):
            protective_checked += 1
            if not rmap.owned[k]:
                findings.append(RuleFinding("PROTECTIVE_NEVER_MATCHES", rule.name, rule.category, rule.index,
                                            "a protective rule never produces a first match"))
            for j in range(k):
                if ir[j].is_hide and not is_empty(intersect(box, rmap.boxes[j])):
                    findings.append(RuleFinding("PROTECTIVE_SHADOWED_BY_HIDE", rule.name, rule.category, rule.index,
                                                f"hide rule {ir[j].name} precedes and overlaps this protective rule", (ir[j].name,)))
        if not rule.is_hide and not is_empty(box):
            hiding = [ir[j].name for j in range(k) if ir[j].is_hide and not is_empty(intersect(box, rmap.boxes[j]))]
            if hiding and not rule.protective:
                findings.append(RuleFinding("SHOW_PREEMPTED_BY_HIDE", rule.name, rule.category, rule.index,
                                            "an earlier Hide rule takes part of the region this Show rule would match", tuple(hiding[:4])))
        if rule.is_hide and rmap.owned[k]:
            owned = rmap.owned[k]
            rarities = set()
            for p in owned:
                rarities |= {universe.samples["rarity"][i] for i in range(len(RARITIES)) if p[1] >> i & 1}
            bases = universe.bases_in(owned)
            later_shows = [ir[j].name for j in range(k + 1, len(ir)) if not ir[j].is_hide and not is_empty(intersect(box, rmap.boxes[j]))]
            hide_rules.append({"rule": rule.name, "category": rule.category, "bases_hidden": len(bases), "rarities": sorted(rarities),
                               "justification": rule.justification or "(none recorded)", "later_show_rules_it_pre-empts": later_shows[:8],
                               "pre-empted_show_rule_count": len(later_shows), "rare_hidden": "Rare" in rarities})
            if "Rare" in rarities and "Unique" in rarities:
                findings.append(RuleFinding("HIDE_TOO_BROAD", rule.name, rule.category, rule.index,
                                            "hides Rare and Unique items without a rarity restriction"))
    return AnalysisReport(len(ir), findings, hide_rules, universe.unreferenced, protective_checked)


def _redundant(k: int, rmap: RegionMap) -> bool:
    """True when every first match of rule k would fall through to a later rule with an identical effect."""
    rule = rmap.rules[k]
    remaining = list(rmap.owned[k])
    if not remaining:
        return False
    for j in range(k + 1, len(rmap.rules)):
        later = rmap.rules[j]
        cutter = rmap.boxes[j]
        if is_empty(cutter):
            continue
        hit = [p for p in (intersect(box, cutter) for box in remaining) if not is_empty(p)]
        if hit and later.effect != rule.effect:
            return False
        remaining = subtract_all(remaining, [cutter])
        if not remaining:
            return True
    return rule.effect == DEFAULT_EFFECT          # fell through every later rule to the game default


# -- equivalence ------------------------------------------------------------------------------------------------------------------------
CATEGORIES = ("VISIBILITY", "STYLING", "MATCHED_RULE", "PROVENANCE")


@dataclass
class Diff:
    category: str
    a_rule: str
    b_rule: str
    a_hidden: bool
    b_hidden: bool
    bases: int
    volume: int
    example: PreviewItem
    a_category: str = ""
    b_category: str = ""


@dataclass
class EquivalenceReport:
    diffs: list[Diff]
    total_volume: int
    seconds: float

    def by_category(self) -> dict[str, int]:
        return {c: sum(d.volume for d in self.diffs if d.category == c) for c in CATEGORIES}

    def equivalent(self, *, strict: bool = False) -> bool:
        """Visibility and styling must match; strict also requires identical matched rules and provenance."""
        wanted = CATEGORIES if strict else ("VISIBILITY", "STYLING")
        return not any(d.category in wanted for d in self.diffs)

    def summary(self) -> dict[str, object]:
        by = self.by_category()
        return {"diff_regions": len(self.diffs), "volume_by_category": by, "total_volume": self.total_volume,
                "visibility_or_style_equivalent": self.equivalent(), "strictly_identical": self.equivalent(strict=True),
                "seconds": round(self.seconds, 2)}


def _effect(rule: IRRule | None) -> Effect:
    return DEFAULT_EFFECT if rule is None else rule.effect


def compare(rules_a: Sequence[GeneratedRule] | Sequence[IRRule], rules_b: Sequence[GeneratedRule] | Sequence[IRRule],
            *, max_examples: int = 4000) -> EquivalenceReport:
    """Exact comparison of two rule lists over the joint item space."""
    started = time.time()
    a = list(rules_a) if rules_a and isinstance(rules_a[0], IRRule) else to_ir(rules_a)       # type: ignore[arg-type]
    b = list(rules_b) if rules_b and isinstance(rules_b[0], IRRule) else to_ir(rules_b)       # type: ignore[arg-type]
    universe = Universe.build([a, b])
    map_a, map_b = region_map(a, universe), region_map(b, universe)
    entries_b = list(map_b.entries())
    diffs: list[Diff] = []
    total = 0
    for box_a, rule_a in map_a.entries():
        total += universe.volume(box_a)
        for box_b, rule_b in entries_b:
            common = intersect(box_a, box_b)
            if is_empty(common):
                continue
            ea, eb = _effect(rule_a), _effect(rule_b)
            if ea.visible() != eb.visible():
                category = "VISIBILITY"
            elif ea != eb:
                category = "STYLING"
            elif (rule_a.name if rule_a else "") != (rule_b.name if rule_b else ""):
                category = "MATCHED_RULE"
            elif (rule_a.provenance if rule_a else "") != (rule_b.provenance if rule_b else ""):
                category = "PROVENANCE"
            else:
                continue
            if len(diffs) < max_examples:
                diffs.append(Diff(category, rule_a.name if rule_a else "(default)", rule_b.name if rule_b else "(default)", not ea.visible(),
                                  not eb.visible(), len(universe.bases_in([common])), universe.volume(common), universe.example(common),
                                  rule_a.category if rule_a else "", rule_b.category if rule_b else ""))
    return EquivalenceReport(diffs, total, time.time() - started)


def compare_on_items(rules_a: Sequence[GeneratedRule], rules_b: Sequence[GeneratedRule], items: Sequence[PreviewItem]) -> dict[str, object]:
    """Concrete cross-check on a corpus: counts visibility / style / matched-rule / provenance differences."""
    counts: Counter[str] = Counter()
    examples: dict[str, str] = {}
    for item in items:
        da, db = preview_decision(list(rules_a), item), preview_decision(list(rules_b), item)
        if da.hidden != db.hidden:
            key = "VISIBILITY"
        elif da.stylesheet != db.stylesheet or da.native_details != db.native_details:
            key = "STYLING"
        elif da.rule_name != db.rule_name:
            key = "MATCHED_RULE"
        elif da.provenance != db.provenance:
            key = "PROVENANCE"
        else:
            continue
        counts[key] += 1
        examples.setdefault(key, f"{item.name}: {da.rule_name} -> {db.rule_name}")
    return {"items": len(items), "diffs": dict(counts), "examples": examples}


# -- optimisation -----------------------------------------------------------------------------------------------------------------------
@dataclass
class OptimisationReport:
    rules_before: int
    rules_after: int
    removed_shadowed: int
    removed_duplicate: int
    merged: int
    verified: bool
    seconds: float
    equivalence: dict[str, object] = field(default_factory=dict)

    def summary(self) -> dict[str, object]:
        return {"rules_before": self.rules_before, "rules_after": self.rules_after, "removed_shadowed": self.removed_shadowed,
                "removed_duplicate": self.removed_duplicate, "merged_basetype_lists": self.merged, "verified_equivalent": self.verified,
                "seconds": round(self.seconds, 2), "equivalence": self.equivalence}


def optimise(rules: Sequence[GeneratedRule]) -> tuple[list[GeneratedRule], OptimisationReport]:
    """Shrink the rule list WITHOUT changing any decision, style, matched rule or provenance, and prove it.

    Only two transformations are applied, both exact:
      * remove a rule whose entire box is covered by earlier boxes (it can never be the first match) — includes exact duplicates;
      * merge a rule into an earlier rule that is identical except for its BaseType list, provided no rule in between overlaps the moved
        rule with a different effect. Merged rules keep the earlier rule's name/evidence, so a merge is applied only when the two
        rules carry the same name, category, evidence and justification.
    The result is verified with the exact box comparison in STRICT mode; if that fails the ORIGINAL list is returned."""
    started = time.time()
    original = list(rules)
    ir = to_ir(original)
    universe = Universe.build([ir])
    boxes = {r.index: universe.box_of(r) for r in ir}
    keep: list[GeneratedRule] = []
    covered_before: list[Box] = []
    shadowed = duplicate = 0
    seen_signature: set[tuple] = set()
    by_index = {r.index: r for r in ir}
    for index, rule in enumerate(original):
        info = by_index.get(index)
        if info is None:
            keep.append(rule)
            continue
        box = boxes[index]
        if not info.unmodelled and not is_empty(box):
            remaining = subtract_all([box], covered_before)
            if not remaining:
                if info.signature() in seen_signature:
                    duplicate += 1
                else:
                    shadowed += 1
                continue                                   # fully covered by earlier rules: never a first match
        seen_signature.add(info.signature())
        keep.append(rule)
        if not info.unmodelled and not is_empty(box):
            covered_before.append(box)
    merged = 0
    after_merge = _merge_base_types(keep, universe)
    merged = len(keep) - len(after_merge)
    optimised = after_merge
    equivalence = compare(original, optimised) if optimised != original else None
    verified = equivalence is None or equivalence.equivalent(strict=True)
    report = OptimisationReport(len(original), len(optimised), shadowed, duplicate, merged, verified, time.time() - started,
                                equivalence.summary() if equivalence else {"identical": True})
    if not verified:
        return original, report
    return optimised, report


def _merge_base_types(rules: list[GeneratedRule], universe: Universe) -> list[GeneratedRule]:
    """Fold rules identical except BaseType into the earlier one when order cannot matter (see optimise())."""
    positions = {r.index: r for r in to_ir(rules)}      # keyed by position in `rules`
    skeleton: dict[tuple, int] = {}
    drop: set[int] = set()
    extra: dict[int, list[str]] = defaultdict(list)
    for position, rule in enumerate(rules):
        info = positions.get(position)
        if info is None or info.unmodelled or not rule.base_types or is_empty(universe.box_of(info)):
            continue
        base_lines = [c for c in info.conditions if not c.startswith("BaseType")]
        # exact and partial BaseType lists mean different things (see base_match): never fold one into the other
        exact = tuple(sorted(c.match.value for c in (BaseCondition.parse(x) for x in info.conditions) if c is not None))
        key = (exact, info.action, tuple(sorted(base_lines)), info.effect.style, rule.category, rule.name, info.provenance, info.justification)
        first = skeleton.get(key)
        if first is None:
            skeleton[key] = position
            continue
        mover_box = universe.box_of(info)
        blocked = False
        for between in range(first + 1, position):
            other = positions.get(between)
            if other is None or between in drop:
                continue
            if other.effect != info.effect and not is_empty(intersect(mover_box, universe.box_of(other))):
                blocked = True
                break
        if blocked:
            continue
        drop.add(position)
        extra[first].extend(b for b in rule.base_types if b not in rules[first].base_types and b not in extra[first])
    if not drop:
        return rules
    out: list[GeneratedRule] = []
    for position, rule in enumerate(rules):
        if position in drop:
            continue
        if position in extra:
            rule = _with_base_types(rule, list(rule.base_types) + extra[position])
        out.append(rule)
    return out


def _with_base_types(rule: GeneratedRule, base_types: list[str]) -> GeneratedRule:
    from dataclasses import replace
    lines = []
    replaced = False
    for line in rule.lines:
        if line.strip().startswith("BaseType"):
            indent = line[: len(line) - len(line.lstrip())]
            previous = BaseCondition.parse(line.strip())
            kind = previous.match if previous is not None else BaseMatch.EXACT_BASE
            lines.append(BaseCondition(kind, tuple(base_types)).serialize(indent))
            replaced = True
        else:
            lines.append(line)
    return replace(rule, lines=lines, base_types=base_types) if replaced else rule


optimize_rules = lambda rules: optimise(rules)[0]  # noqa: E731  (name used by intel_generate)
