"""Rule generator: compiles the approved profile matrix (`profile_policy`) into native PoE2 filter rules.

Profile system V2. Every generated rule belongs to ONE matrix row and carries its state (SHOW+ / SHOW / QUIET / HIDE). Rules are ordered by
state, most visible first, so first-match gives an item the MOST VISIBLE state among the rows it belongs to (a premium craft base that is also
a Rare top base takes the better of the two). Context is automatic: every row is emitted once for the campaign (AreaLevel <= 64, the Relaxed
column at every level) and once for maps (AreaLevel >= 65, the chosen level) whenever the two states differ.

Lanes (independent evidence, never merged into one score):
  GENERAL    verified-base quality tiers (build-independent): Normal / Magic / Rare equipment, jewellery, unidentified tiers
  CRAFT      substrate quality from verified catalog + affix pools (crafting_intel), independent of the build
  BUILD      measured Build Intelligence; ADDS opportunities, may quiet / hide only build-irrelevant generic Normal / Magic equipment where the
             generic row already let go (profile_policy.build_modified)
  PROTECTED  currency ladder, specials, quest, uniques, waystones, tablets: named rows
  SAFETY     explicit catch-all for anything no row classifies (unknown base, new class): shown, never silently hidden
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Dict, List, Optional

from exilelens.filters import native_bases
from exilelens.filters import profile_policy as pp
from exilelens.filters.base_match import base_line
from exilelens.filters.currency_tiers import TIERS as CURRENCY_TIERS
from exilelens.filters.decision import DecisionEvidence, MarketContext, evidence_for_rule
from exilelens.filters.priorities import BASE_TIERS, SKILL_WEAPON_CLASSES, SLOT_EQUIPMENT_CLASSES, get_weapon_classes_for_skill
from exilelens.filters.profiles import BaseTier, DefenseLayer, FilterProfile, FilterTheme, ProductSlot, SlotPriority, get_theme
from exilelens.filters.style_system import HIDDEN_DROP_SOUND, native_style

# Endgame build-opportunity rules need the top modifier tier of a measured stat family to unlock at this item level or higher.
OPPORTUNITY_MIN_UNLOCK = 75

# What counts as a BUILD-relevant base (the build lane): tiers T1-T3 of the measured build at these item-level gates. One definition at every
# strictness level; the level only changes the STATE of the build_relevant_base row.
BUILD_RELEVANT_TIERS = frozenset({BaseTier.T1, BaseTier.T2, BaseTier.T3})
BUILD_TIER_GATES = {BaseTier.T1: 82, BaseTier.T2: 75, BaseTier.T3: 68}

# The KNOWN_GENERIC fallback layer: not a matrix row (the approved matrix is unchanged) but a fixed, documented SHOW. Classes with their own
# rows (jewels, charms, flasks) are not part of it.
KNOWN_GENERIC_ROW = "known_generic_fallback"
KNOWN_GENERIC_PRIORITY = 9000
KNOWN_GENERIC_HANDLED_CLASSES = frozenset({"Jewels", "Charms", "Flasks"})

JEWELLERY_CLASSES = frozenset({"Rings", "Amulets", "Belts"})
# Normal / Magic craft rows sit before the generic equipment rows (600+): on an exact state tie the craft style (which carries the craft
# minimap icon) is the one that shows, so a stricter profile never ADDS an icon merely because the generic row stopped competing. The same
# reasoning places the unidentified-tier rows (UNID_PRIORITY) after the build rows, which hold the icon on a SHOW tie.
CRAFT_NM_PRIORITY = 594
UNID_PRIORITY = 608
# ... but only among rows that SHOW: in the QUIET / HIDE bands the original order stays, so a hidden item is still attributed to its generic row
_LEGACY_PRIORITY = {CRAFT_NM_PRIORITY: 620, CRAFT_NM_PRIORITY + 1: 621, CRAFT_NM_PRIORITY + 2: 625, UNID_PRIORITY: 100, UNID_PRIORITY + 1: 101}


def _band(rule: "GeneratedRule") -> float:
    """Precedence band: state order (most visible first); the KNOWN_GENERIC fallback sits after every HIDE and before the unknown safety."""
    if rule.row == KNOWN_GENERIC_ROW:
        return 3.5
    return _STATE_BAND.get(rule.state, 0)


def _tie_priority(rule: "GeneratedRule") -> int:
    if rule.state in ("SHOW+", "SHOW", "SAFETY"):
        return rule.priority
    return _LEGACY_PRIORITY.get(rule.priority, rule.priority)

TOP_ILVL = 82                       # eq_rare_top_ilvl82 / flasks_top / charms_top item level
TOP_QUALITY = 10                    # flasks_top / charms_top quality
EXCEPTIONAL_UNIQUE_QUALITY = 21     # uniques_top: above the normal 20 % ceiling
# gems_uncut_top: GemLevel >= 19 always; a lower level counts while the area is the one it is useful in (highest AreaLevel per gem level)
GEM_TOP_LEVEL = 19
GEM_AREA_APPROPRIATE = {14: 65, 15: 69, 16: 73, 17: 77, 18: 79}

_SHOW_ONLY_CATEGORIES = frozenset({"PROTECTIVE", "TRADE_HERO", "TRADE_SPECIAL", "CURRENCY_TOP", "CURRENCY_PREMIUM", "CURRENCY_CRAFT",
                                   "CURRENCY_VALUABLE", "CURRENCY_LOW", "CURRENCY_UTILITY"})
_STATE_BAND = {"SHOW+": 0, "SHOW": 1, "QUIET": 2, "HIDE": 3, "SAFETY": 4}
_PURE_LAYERS = (("armour", "ARMOUR", "BaseArmour", "Armour"), ("evasion", "EVASION", "BaseEvasion", "Evasion"),
                ("energy_shield", "ENERGY_SHIELD", "BaseEnergyShield", "EnergyShield"))
_HIDDEN_LABEL = ("\tSetFontSize 18", "\tSetTextColor 100 105 105 180", "\tSetBackgroundColor 20 22 22 40")


def _names(bases) -> str:
    return " ".join(f'"{b}"' for b in sorted(bases))


@dataclass
class GeneratedRule:
    """A generated filter rule with metadata."""
    category: str
    name: str
    lines: List[str]
    priority: int  # Lower = higher precedence WITHIN a state band
    slot: Optional[ProductSlot] = None
    base_types: List[str] = field(default_factory=list)
    tier: Optional[BaseTier] = None
    evidence: DecisionEvidence | None = None
    # FILTER-08B provenance (empty for rules without build intelligence).
    decisions: tuple = ()
    class_reasons: tuple = ()
    coverage: Any = None
    # Why a visibility REDUCTION exists: the matrix row and level that say so (profile system V2).
    justification: str = ""
    # Profile system V2: the matrix row, the state it has in this rule's context, the V4 role that styles it.
    row: str = ""
    state: str = ""
    role: str = ""


@dataclass(frozen=True)
class _GenericSets:
    top_eq: tuple[str, ...]      # non-jewellery bases with global tier T1 / T2
    low_eq: tuple[str, ...]
    top_jw: tuple[str, ...]      # ring / amulet / belt bases with global tier T1
    low_jw: tuple[str, ...]


@lru_cache(maxsize=1)
def generic_sets() -> _GenericSets:
    """Build-independent partition of every verified equipment base by its GLOBAL quality tier (observed gear never changes it: a build may
    only ADD through its own lane)."""
    from exilelens.filters.opportunity import ROLE_BY_CLASS, global_quality_tier
    from exilelens.filters.verified_bases import load_base_properties, native_class
    top_eq, low_eq, top_jw, low_jw = [], [], [], []
    for base in sorted(load_base_properties()):
        cls = native_class(base)
        if cls not in ROLE_BY_CLASS:
            continue
        tier, _ = global_quality_tier(base, cls, ())
        if cls in JEWELLERY_CLASSES:
            (top_jw if tier == BaseTier.T1 else low_jw).append(base)
        else:
            (top_eq if tier in (BaseTier.T1, BaseTier.T2) else low_eq).append(base)
    return _GenericSets(tuple(top_eq), tuple(low_eq), tuple(top_jw), tuple(low_jw))


@lru_cache(maxsize=1)
def all_verified_bases() -> tuple[str, ...]:
    from exilelens.filters.verified_bases import load_base_properties, native_class
    return tuple(sorted(b for b in load_base_properties() if native_class(b)))


class RuleGenerator:
    """Generates filter rules from the profile matrix, the verified catalog and (optionally) a measured build."""

    def __init__(
        self,
        slot_priorities: Dict[ProductSlot, SlotPriority],
        profile: FilterProfile,
        main_skill: str,
        defense_layer: DefenseLayer,
        intel: Any = None,
        cooperate=None,
    ):
        self.intel = intel  # IntelContext (FILTER-08B) or None: no build, the general filter
        self._cooperate = cooperate
        self.slot_priorities = slot_priorities
        self.profile = profile
        self.main_skill = main_skill
        self.defense_layer = defense_layer
        self.policy = pp.ProfilePolicy(profile.name.value)
        self.weapon_classes = get_weapon_classes_for_skill(main_skill)
        self.theme: FilterTheme = get_theme(profile.theme)
        self._seen_base_type_slot: set = set()
        # (rule, name, reason) of every declared base the native registry kept out of a rule: diagnostics, never silent
        self.excluded_bases: List[tuple] = []

    def _bt(self, quoted: str) -> str:
        """A BaseType condition for an already-quoted list of base identities: always EXACT_BASE (see base_match), and only ever native
        ground-valid names. A name that provably has no ground identity (PoB synthetic, non-ground object, stale) is left out and recorded in
        `excluded_bases`; a name the registry cannot establish (AMBIGUOUS / UNKNOWN) blocks generation (NativeBaseTypeBlocked)."""
        valid, excluded = native_bases.partition_for_emission(re.findall(r'"([^"]+)"', quoted))
        self.excluded_bases.extend(("(grouped BaseType rule)", name, reason) for name, reason in excluded)
        return base_line(valid)

    # -- states -------------------------------------------------------------------------------------------------------------------------
    @property
    def build_active(self) -> bool:
        """The BUILD lane exists only with a measured Build Intelligence snapshot; without one the general filter is the whole filter."""
        return self.intel is not None and self.intel.needs.has_measurement

    def _contexts(self, row: str) -> tuple[tuple[str, str | None], ...]:
        return self.policy.contexts(row)

    def _derived_contexts(self, fn) -> tuple[tuple[str, str | None], ...]:
        """Contexts for a state computed from several rows: fn(state_of_row) is evaluated for maps and for the campaign."""
        maps, camp = fn(self.policy.state), fn(self.policy.campaign)
        if maps == camp:
            return ((maps, None),)
        return ((camp, f"AreaLevel <= {pp.CAMPAIGN_MAX_AREA_LEVEL}"), (maps, f"AreaLevel >= {pp.MAPS_MIN_AREA_LEVEL}"))

    def _apply_theme_style(self, lines: List[str], role: str, tier: BaseTier | None = None, state: str = "SHOW+") -> List[str]:
        """Visual V4 treatment of a role under a state as native actions. Every visible state carries the text / plaque actions: the game's
        own label is never the outcome for a known item (FILTER-THEMED-VISIBILITY-COVERAGE)."""
        style = native_style(self.profile.theme, role, tier, state)
        out = list(lines)
        for action, key in (("SetFontSize", "font_size"), ("SetTextColor", "text_color"), ("SetBorderColor", "border_color"),
                            ("SetBackgroundColor", "bg_color")):
            out.append(f"\t{action} {style[key]}")
        if "minimap_icon" in style:
            out.append(f"\tMinimapIcon {style['minimap_icon']}")
        if "play_effect" in style:
            out.append(f"\tPlayEffect {style['play_effect']}")
        if "sound" in style:
            out.append(f"\tPlayAlertSound {style['sound']}")
        return out

    def _emit(self, contexts, body: List[str], role: str, *, category: str, name: str, priority: int, row: str, tier: BaseTier | None = None,
              base_types=(), **meta) -> List[GeneratedRule]:
        """One rule per context: conditions (+ the AreaLevel bound), the state's V4 style or a Hide."""
        out = []
        for state, area in contexts:
            hide = state == "HIDE"
            lines = ["Hide" if hide else "Show", *body]
            if area:
                lines.append(f"\t{area}")
            suffix = "" if area is None else (" [campaign]" if "<=" in area else " [maps]")
            if hide:
                lines.extend(_HIDDEN_LABEL)
                meta_here = {**meta, "justification": meta.get("justification") or f"profile matrix: {row} is HIDE at {self.profile.name.value}"}
            else:
                lines = self._apply_theme_style(lines, role, tier, state)
                meta_here = dict(meta)
            # a Hide is never "protective": the rule IR (and a reader of the filter) reads PROTECTIVE categories as Show rules
            cat = "HIDDEN_CLUTTER" if hide and category in _SHOW_ONLY_CATEGORIES else category
            out.append(GeneratedRule(category=cat, name=name + suffix, lines=lines, priority=priority,
                                     base_types=[b for b in base_types if native_bases.is_ground_base(b)],
                                     tier=tier, row=row, state=state, role=role, **meta_here))
        return out

    # -- build lane helpers (FILTER-08B) ----------------------------------------------------------------------------------------------
    def _tier_groups(self, priority: SlotPriority):
        """Yield (tier, item-level gate, shift, bases) of the BUILD-relevant bases. Inclusion follows the build tier; the gate follows the
        base's quality tier. Bases with different evidence (promoted / neutral / demoted) never share a rule."""
        groups: Dict[tuple, List[str]] = defaultdict(list)
        for base, tier in priority.base_tiers.items():
            if tier not in BUILD_RELEVANT_TIERS:
                continue
            quality = priority.quality_tiers.get(base, tier)
            gate = BUILD_TIER_GATES.get(quality, BUILD_TIER_GATES.get(tier, 68))
            decision = priority.decisions.get(base)
            if self.intel is not None and (self.intel.widen or (self.intel.needs.has_measurement and not self.intel.needs.evidence_complete)):
                gate = min(gate, OPPORTUNITY_MIN_UNLOCK)     # missing knowledge: show from the lowest top-tier unlock level
            if (decision is not None and decision.unlock_level and decision.unlock_level >= OPPORTUNITY_MIN_UNLOCK
                    and (decision.shift > 0 or (decision.role in ("weapon", "offhand") and self.intel is not None
                                                and self.intel.needs.has_measurement))):
                gate = min(gate, decision.unlock_level)
            groups[(tier, gate, decision.shift if decision else 0)].append(base)
        order = [BaseTier.T1, BaseTier.T2, BaseTier.T3, BaseTier.T4]
        for (tier, gate, shift) in sorted(groups, key=lambda key: (order.index(key[0]), key[1], -key[2])):
            yield tier, gate, shift, groups[(tier, gate, shift)]

    @staticmethod
    def _gate_suffix(tier: BaseTier, gate: int, shift: int = 0) -> str:
        suffix = "" if gate == BUILD_TIER_GATES.get(tier, 68) else f"_g{gate}"
        return suffix + {1: "_up", -1: "_down"}.get(shift, "")

    @staticmethod
    def _provenance(priority: SlotPriority, bases: List[str]) -> dict:
        return {
            "decisions": tuple(priority.decisions[b] for b in sorted(bases) if b in priority.decisions),
            "class_reasons": tuple(priority.class_reasons),
            "coverage": priority.coverage,
        }

    def _personalised_weapons(self, priority: SlotPriority) -> bool:
        """True when weapon classes came from verified/measured evidence instead of a skill-name fallback."""
        from exilelens.filters.opportunity import EvidenceKind
        return any(r.kind in (EvidenceKind.VERIFIED_BASE_FACT, EvidenceKind.MEASURED_BUILD_RESPONSE) for r in priority.class_reasons)

    # -- generation -------------------------------------------------------------------------------------------------------------------
    def generate_all(self) -> List[GeneratedRule]:
        """Every rule, ordered by state (most visible first), then by priority."""
        rules: List[GeneratedRule] = []
        rules.extend(self._generate_currency_rules())
        rules.extend(self._generate_progression_rules())
        rules.extend(self._generate_unique_rules())
        rules.extend(self._generate_waystone_rules())
        rules.extend(self._generate_secondary_rules())
        rules.extend(self._generate_weapon_rules())        # verified skill weapon class (a fact, not a measurement) or measured
        if self.build_active:
            rules.extend(self._generate_defense_rules())
            rules.extend(self._generate_jewellery_rules())
            rules.extend(self._generate_belt_rules())
            rules.extend(self._generate_offhand_rules())
            rules.extend(self._generate_build_opportunity_rules())
        rules.extend(self._generate_equipment_rules())
        rules.extend(self._generate_craft_rules())
        rules.extend(self._generate_known_generic_rules())
        rules.extend(self._generate_safety_rule())
        rules.sort(key=lambda r: (_band(r), _tie_priority(r)))
        # Hidden loot makes no drop sound, so the alert vocabulary stands out (an action line: visibility is unchanged)
        for rule in rules:
            if rule.lines and rule.lines[0].strip() == "Hide" and HIDDEN_DROP_SOUND not in (line.strip() for line in rule.lines):
                rule.lines.append("\t" + HIDDEN_DROP_SOUND)
        market = MarketContext()  # No verified generation-time provider is configured.
        for rule in rules:
            mapped = self.main_skill in SKILL_WEAPON_CLASSES
            if self.intel is not None and rule.category in {"BUILD_WEAPON", "BUILD_OFFHAND"}:
                from exilelens.filters.opportunity import EvidenceKind
                mapped = any(r.kind in (EvidenceKind.VERIFIED_BASE_FACT, EvidenceKind.MEASURED_BUILD_RESPONSE) for r in rule.class_reasons)
            rule.evidence = evidence_for_rule(rule, market, skill=self.main_skill, skill_mapped=mapped)
        return rules

    # -- currency ---------------------------------------------------------------------------------------------------------------------
    def _generate_currency_rules(self) -> List[GeneratedRule]:
        """The V4 currency ladder: one rule per tier of currency_tiers, state from the tier's matrix row.

        A tier's names are partitioned through the native registry first: a name that is not ground-valid is left out (and recorded in
        `excluded_bases`), and a name whose real native Class is not `Stackable Currency` goes into its own rule with that Class."""
        rules: List[GeneratedRule] = []
        for tier in CURRENCY_TIERS:
            valid, rejected = native_bases.partition_for_emission(tier.names)
            self.excluded_bases.extend((tier.rule_name, name, reason) for name, reason in rejected)
            by_class: Dict[str, List[str]] = defaultdict(list)
            for name in valid:
                by_class[native_bases.entry_of(name).native_class].append(name)
            for cls in sorted(by_class, key=lambda c: (c != "Stackable Currency", c)):
                names = tuple(by_class[cls])
                body = [f'	Class "{cls}"', base_line(names)]
                suffix = "" if cls == "Stackable Currency" else f" ({cls})"
                rules += self._emit(self._contexts(tier.row), body, tier.role, category=tier.category, name=tier.rule_name + suffix,
                                    priority=tier.priority, row=tier.row, base_types=names)
        return rules

    # -- named progression classes ----------------------------------------------------------------------------------------------------
    def _generate_progression_rules(self) -> List[GeneratedRule]:
        rules: List[GeneratedRule] = []
        rules += self._emit(self._contexts("special_endgame"), ['\tClass "Omen" "Pinnacle Keys" "Map Fragments"'], "special",
                            category="TRADE_SPECIAL", name="Special trade categories", priority=5, row="special_endgame")
        rules += self._emit(self._contexts("augments_top"), ['\tClass "Augment"'], "socketable", category="PROTECTIVE", name="Socketables",
                            priority=20, row="augments_top")
        rules += self._emit(self._contexts("tablets"), ['\tClass "Tablet"'], "tablet", category="PROTECTIVE", name="Tablets", priority=22,
                            row="tablets")
        rules += self._emit(self._contexts("quest_items"), ['\tClass "Quest Items" "Instance Local Items"'], "quest", category="PROTECTIVE",
                            name="QuestItems", priority=40, row="quest_items")
        return rules

    def _generate_unique_rules(self) -> List[GeneratedRule]:
        """uniques_top = observable exceptional states; every other unique on a verified base is generic (see profile_policy.KNOWN_GAPS)."""
        rules: List[GeneratedRule] = []
        for suffix, condition in (("Corrupted", "\tCorrupted True"), ("Mirrored", "\tMirrored True"),
                                  ("OverQuality", f"\tQuality >= {EXCEPTIONAL_UNIQUE_QUALITY}")):
            rules += self._emit(self._contexts("uniques_top"), ["\tRarity Unique", condition], "unique", category="PROTECTIVE",
                                name=f"UniquesTop_{suffix}", priority=30, row="uniques_top")
        rules += self._emit(self._contexts("uniques_generic"), ["\tRarity Unique", base_line(all_verified_bases())], "unique",
                            category="PROTECTIVE", name="Uniques", priority=31, row="uniques_generic")
        return rules

    def _generate_waystone_rules(self) -> List[GeneratedRule]:
        """Waystone tiers x area bands, compiled from the four waystone rows: an effective state per (context, tier) is the most visible of
        the rows that apply, then equal states are merged into native WaystoneTier / AreaLevel ranges."""
        def role_for(tier: int) -> str:
            return "waystone_high" if tier >= 15 else "waystone_mid" if tier >= 11 else "waystone"

        def rows_for(tier: int, far: bool) -> list[str]:
            rows = ["waystones_far_below_area" if far else "waystones_near_area"]
            if 11 <= tier <= 14:
                rows.append("waystones_t11_14")
            if tier >= 15:
                rows.append("waystones_t15_16")
            return rows

        tiers = range(1, 17)
        contexts = [("campaign", (1, pp.CAMPAIGN_MAX_AREA_LEVEL), None, self.policy.campaign)]
        for lo, hi, far_max in pp.WAYSTONE_BANDS:
            contexts.append((f"maps {lo}-{hi or 'up'}", (lo, hi), far_max, self.policy.state))
        grouped: dict[tuple, list[tuple]] = defaultdict(list)       # (state, role, tier lo, tier hi) -> [(area lo, area hi)]
        for _label, (a_lo, a_hi), far_max, get in contexts:
            effective = {}
            for tier in tiers:
                far = far_max is not None and tier <= far_max
                candidates = rows_for(tier, far)
                winner = max(candidates, key=lambda r: pp.VISIBILITY_RANK[get(r)])
                effective[tier] = (get(winner), winner, role_for(tier))
            run_start = tiers[0]
            for tier in list(tiers)[1:] + [None]:
                if tier is not None and effective[tier] == effective[run_start]:
                    continue
                last = tier - 1 if tier is not None else tiers[-1]
                state, winner, role = effective[run_start]
                grouped[(state, role, winner, run_start, last)].append((a_lo, a_hi))
                run_start = tier
        rules: List[GeneratedRule] = []
        for (state, role, winner, t_lo, t_hi), bands in sorted(grouped.items(), key=lambda kv: (-pp.VISIBILITY_RANK[kv[0][0]], kv[0][3], kv[0][4])):
            merged: list[list] = []
            for a_lo, a_hi in sorted(bands):
                if merged and merged[-1][1] is not None and a_lo == merged[-1][1] + 1:
                    merged[-1][1] = a_hi
                else:
                    merged.append([a_lo, a_hi])
            for a_lo, a_hi in merged:
                body = ['\tClass "Waystones"', f"\tWaystoneTier >= {t_lo}"]
                if t_hi < 16:
                    body.append(f"\tWaystoneTier <= {t_hi}")
                if a_lo > 1:
                    body.append(f"\tAreaLevel >= {a_lo}")
                if a_hi is not None:
                    body.append(f"\tAreaLevel <= {a_hi}")
                label = f"Waystones_T{t_lo}-{t_hi}_AL{a_lo}-{a_hi if a_hi is not None else 'up'}"
                rules += self._emit(((state, None),), body, role, category="PROTECTIVE", name=label, priority=46 + t_lo, row=winner)
        return rules

    def _generate_secondary_rules(self) -> List[GeneratedRule]:
        """Jewels, charms, flasks and uncut gems: progression rows with weak personalization evidence (QUIET before HIDE)."""
        rules: List[GeneratedRule] = []
        rules += self._emit(self._contexts("jewels_rare"), ['\tClass "Jewels"', "\tRarity Rare"], "jewel", category="PROTECTIVE",
                            name="Jewels_Rare", priority=54, row="jewels_rare")
        rules += self._emit(self._contexts("jewels_magic"), ['\tClass "Jewels"', "\tRarity Normal Magic"], "jewel", category="PROTECTIVE",
                            name="Jewels_Magic", priority=55, row="jewels_magic")
        for cls, role, prefix in (("Charms", "charm", "charms"), ("Flasks", "generic", "flasks")):
            for label, extra in (("Quality", f"\tQuality >= {TOP_QUALITY}"), ("ItemLevel", f"\tItemLevel >= {TOP_ILVL}")):
                rules += self._emit(self._contexts(f"{prefix}_top"), [f'\tClass "{cls}"', extra], role, category="PROTECTIVE",
                                    name=f"{cls}_Top_{label}", priority=56, row=f"{prefix}_top")
            rules += self._emit(self._contexts(f"{prefix}_other"), [f'\tClass "{cls}"'], role, category="PROTECTIVE",
                                name=f"{cls}_Other", priority=57, row=f"{prefix}_other")
        gem_class = '\tClass "Uncut Skill Gems" "Uncut Support Gems" "Uncut Spirit Gems"'
        top = self._contexts("gems_uncut_top")
        rules += self._emit(top, [gem_class, f"\tGemLevel >= {GEM_TOP_LEVEL}"], "gem", category="PROTECTIVE", name="UncutGems_Top_L19",
                            priority=58, row="gems_uncut_top")
        for level, area in sorted(GEM_AREA_APPROPRIATE.items()):
            rules += self._emit(top, [gem_class, f"\tGemLevel = {level}", f"\tAreaLevel <= {area}"], "gem", category="PROTECTIVE",
                                name=f"UncutGems_Top_L{level}", priority=58, row="gems_uncut_top")
        rules += self._emit(self._contexts("gems_uncut_other"), [gem_class], "gem", category="PROTECTIVE", name="UncutGems", priority=59,
                            row="gems_uncut_other")
        return rules

    # -- build lane (measured Build Intelligence) -------------------------------------------------------------------------------------
    def _build_rule(self, category: str, name: str, body: List[str], role: str, tier: BaseTier, priority: int, slot: ProductSlot | None,
                    bases: List[str], provenance: dict) -> List[GeneratedRule]:
        return self._emit(self._contexts("build_relevant_base"), body, role, category=category, name=name, priority=priority,
                          row="build_relevant_base", tier=tier, slot=slot, base_types=bases, **provenance)

    def _generate_weapon_rules(self) -> List[GeneratedRule]:
        rules: List[GeneratedRule] = []
        for slot in (ProductSlot.WEAPON_1, ProductSlot.WEAPON_2):
            priority = self.slot_priorities.get(slot)
            if not priority:
                continue
            # evidence precedence: verified / measured weapon classes (intel path) or the curated, verified skill map (legacy path)
            mapped = self._personalised_weapons(priority) if self.intel is not None else self.main_skill in SKILL_WEAPON_CLASSES
            if not mapped and not (self.intel is not None and self.intel.widen):
                continue                      # no evidence, no build rule: the broad "unmapped skill" fallback lane is retired ...
            # ... except under data drift: widening may only ADD visibility, so the broad candidate classes stay (LOW, as before)
            for tier, min_ilvl, shift, bases in self._tier_groups(priority):
                body = [self._bt(_names(bases)), f"\tItemLevel >= {min_ilvl}"]
                rules += self._build_rule("BUILD_WEAPON", f"Weapon_{slot.value}_{tier.value}{self._gate_suffix(tier, min_ilvl, shift)}", body,
                                          "build_weapon" if mapped else "fallback_weapon", tier, 200 + int(tier.value[1]) * 10, slot, bases,
                                          self._provenance(priority, bases))
        return rules

    def _generate_defense_rules(self) -> List[GeneratedRule]:
        rules: List[GeneratedRule] = []
        for slot in (ProductSlot.HELMET, ProductSlot.BODY_ARMOUR, ProductSlot.GLOVES, ProductSlot.BOOTS):
            priority = self.slot_priorities.get(slot)
            eq_classes = SLOT_EQUIPMENT_CLASSES.get(slot, [])
            if not priority or not eq_classes:
                continue
            for tier, min_ilvl, shift, bases in self._tier_groups(priority):
                body = [f'\tClass "{eq_classes[0]}"', self._bt(_names(bases)), f"\tItemLevel >= {min_ilvl}"]
                rules += self._build_rule("BUILD_DEFENSE", f"Defense_{slot.value}_{tier.value}{self._gate_suffix(tier, min_ilvl, shift)}", body,
                                          "build_defense", tier, 300 + int(tier.value[1]) * 10, slot, bases, self._provenance(priority, bases))
        return rules

    def _generate_jewellery_rules(self) -> List[GeneratedRule]:
        rules: List[GeneratedRule] = []
        for slot in (ProductSlot.AMULET, ProductSlot.RING_1, ProductSlot.RING_2):
            priority = self.slot_priorities.get(slot)
            eq_classes = SLOT_EQUIPMENT_CLASSES.get(slot, [])
            if not priority or not eq_classes:
                continue
            for tier, min_ilvl, shift, bases in self._tier_groups(priority):
                body = [f'\tClass "{eq_classes[0]}"', self._bt(_names(bases)), f"\tItemLevel >= {min_ilvl}"]
                rules += self._build_rule("BUILD_JEWELLERY", f"Jewellery_{slot.value}_{tier.value}{self._gate_suffix(tier, min_ilvl, shift)}", body,
                                          "build_jewellery", tier, 400 + int(tier.value[1]) * 10, slot, bases, self._provenance(priority, bases))
        return rules

    def _generate_belt_rules(self) -> List[GeneratedRule]:
        """FILTER-08E: belts whose verified IMPLICIT supports a STRONG / FIX_FIRST measured family (the belt implicit is always present on
        the base, so BaseType is an exact proxy). It only ever ADDS visibility."""
        from exilelens.filters.build_needs import Coverage
        from exilelens.filters.opportunity import EvidenceKind, Reason
        from exilelens.filters.verified_bases import load_base_properties, native_class
        intel = self.intel
        if intel is None or not intel.needs.has_measurement:
            return []
        model = intel.model
        chosen = {}
        for base in load_base_properties():
            if native_class(base) != "Belts":
                continue
            decision = model.decide(base, "Belts")
            if any(h.source == "IMPLICIT" and h.relevance.rank >= 4 for h in decision.hits):
                chosen[base] = decision
        if not chosen:
            return []
        bases = sorted(chosen)
        facts = "; ".join(sorted({f"{h.family.replace('_', ' ').lower()} ({h.relevance.value.lower()})"
                                  for d in chosen.values() for h in d.hits if h.source == "IMPLICIT" and h.relevance.rank >= 4}))
        provenance = {"decisions": tuple(chosen[b] for b in bases),
                      "class_reasons": (Reason(EvidenceKind.VERIFIED_BASE_FACT, f"Belt implicit (always present on the base) supports: {facts}"),),
                      "coverage": Coverage.PARTIAL}
        return self._build_rule("BUILD_JEWELLERY", "Belt_Implicit", ['\tClass "Belts"', self._bt(_names(bases)), "\tRarity Magic Rare"],
                                "build_jewellery", BaseTier.T2, 425, ProductSlot.BELT, bases, provenance)

    def _generate_offhand_rules(self) -> List[GeneratedRule]:
        rules: List[GeneratedRule] = []
        for slot in (ProductSlot.OFFHAND_1, ProductSlot.OFFHAND_2):
            priority = self.slot_priorities.get(slot)
            if not priority:
                continue
            for tier, min_ilvl, shift, bases in self._tier_groups(priority):
                body = [self._bt(_names(bases)), f"\tItemLevel >= {min_ilvl}"]
                rules += self._build_rule("BUILD_OFFHAND", f"Offhand_{slot.value}_{tier.value}{self._gate_suffix(tier, min_ilvl, shift)}", body,
                                          "build_offhand", tier, 500 + int(tier.value[1]) * 10, slot, bases, self._provenance(priority, bases))
        return rules

    def _generate_build_opportunity_rules(self) -> List[GeneratedRule]:
        """Relevant high-item-level opportunities for MEASURED, base-specific evidence: a pool opportunity (the top tier of a stat family the
        build responds to strongly), shown from the item level where it unlocks. Runs at every strictness level (it only adds)."""
        if not self.build_active:
            return []
        from exilelens.filters.build_needs import Relevance
        roles = ((ProductSlot.WEAPON_1, "BUILD_WEAPON", "build_weapon", 250, "Weapon"), (ProductSlot.OFFHAND_1, "BUILD_OFFHAND", "build_offhand", 550, "Offhand"),
                 (ProductSlot.HELMET, "BUILD_DEFENSE", "build_defense", 350, "Defense"), (ProductSlot.BODY_ARMOUR, "BUILD_DEFENSE", "build_defense", 351, "Defense"),
                 (ProductSlot.GLOVES, "BUILD_DEFENSE", "build_defense", 352, "Defense"), (ProductSlot.BOOTS, "BUILD_DEFENSE", "build_defense", 353, "Defense"),
                 (ProductSlot.AMULET, "BUILD_JEWELLERY", "build_jewellery", 450, "Jewellery"),
                 (ProductSlot.RING_1, "BUILD_JEWELLERY", "build_jewellery", 451, "Jewellery"))
        rules: List[GeneratedRule] = []
        for slot, category, role, priority_value, label in roles:
            priority = self.slot_priorities.get(slot)
            if not priority:
                continue
            groups: Dict[int, List[str]] = defaultdict(list)
            for base, decision in priority.decisions.items():
                if decision.shift <= 0:
                    continue
                strong = [h.top_level for h in decision.hits
                          if h.source == "POOL" and not h.universal and h.top_level and h.relevance.rank >= Relevance.STRONG.rank]
                if strong and min(strong) >= OPPORTUNITY_MIN_UNLOCK:
                    groups[min(strong)].append(base)
            for unlock, bases in sorted(groups.items()):
                eq_class = SLOT_EQUIPMENT_CLASSES.get(slot, [""])[0] if category in {"BUILD_DEFENSE", "BUILD_JEWELLERY"} else ""
                body = ([f'\tClass "{eq_class}"'] if eq_class else []) + [self._bt(_names(bases)), f"\tItemLevel >= {unlock}"]
                rules += self._build_rule(category, f"Opportunity_{label}_{slot.value}_i{unlock}", body, role, BaseTier.T1, priority_value, slot,
                                          sorted(bases), self._provenance(priority, bases))
        return rules

    # -- general + craft equipment ----------------------------------------------------------------------------------------------------
    def _irrelevant_bases(self) -> Dict[str, str]:
        """Build-irrelevant generic Normal / Magic equipment: base -> the measurement that says so. Bases whose PURE defence layer production
        MEASURED as no response (probe run, HIGH / MEDIUM confidence, another layer responds). Empty without complete evidence or when data
        drift widens."""
        if not self.build_active:
            return {}
        from exilelens.filters.build_needs import Relevance
        from exilelens.filters.verified_bases import load_base_properties, native_class
        needs = self.intel.needs
        if self.intel.widen or not needs.evidence_complete:
            return {}
        relevance = {key: needs.relevance(probe) for key, probe, _, _ in _PURE_LAYERS}
        if any(r == Relevance.NOT_ESTABLISHED for r in relevance.values()):
            return {}
        if not any(r.rank >= Relevance.RESPONSIVE.rank for r in relevance.values()):
            return {}
        silent = {key: needs.signal(probe).basis() for key, probe, _, _ in _PURE_LAYERS
                  if relevance[key] == Relevance.NO_RESPONSE and needs.signal(probe) is not None
                  and needs.signal(probe).confidence in ("HIGH", "MEDIUM")}
        out: Dict[str, str] = {}
        for base, record in load_base_properties().items():
            if native_class(base) not in ("Body Armours", "Helmets", "Gloves", "Boots", "Shields"):
                continue
            present = [k for k in ("armour", "evasion", "energy_shield") if record.get(k)]
            if len(present) == 1 and present[0] in silent:
                out[base] = silent[present[0]]
        return out

    def _generate_equipment_rules(self) -> List[GeneratedRule]:
        sets = generic_sets()
        irrelevant = self._irrelevant_bases()
        rules: List[GeneratedRule] = []

        def split(bases, row) -> tuple[list[str], list[str]]:
            """Bases the build modifier changes (in at least one context) vs the rest."""
            def changed(base: str) -> bool:
                return base in irrelevant and any(
                    pp.build_modified(get(row), get("build_irrelevant_generic_nm")) != get(row) for get in (self.policy.state, self.policy.campaign))
            return [b for b in bases if not changed(b)], [b for b in bases if changed(b)]

        # Normal / Magic top and low equipment (the build modifier applies to the build-irrelevant part only)
        for key, bases, role, label, priority in (("top", sets.top_eq, "trade", "Top", 600), ("low", sets.low_eq, "generic", "Low", 601)):
            row_n, row_m = f"eq_normal_{key}", f"eq_magic_{key}"
            keep, drop = split(bases, row_n)
            if any(pp.state(row_n, lv) != pp.state(row_m, lv) for lv in pp.LEVELS):    # the matrix pairs them; split per rarity if it stops
                raise RuntimeError(f"{row_n} / {row_m} must share a state at every level (profile matrix)")
            if keep:
                rules += self._emit(self._contexts(row_n), ["\tRarity Normal Magic", self._bt(_names(keep))], role, category="GENERIC_EQUIPMENT",
                                    name=f"Generic_NM_{label}", priority=priority, row=row_n, base_types=keep)
            if drop:
                contexts = self._derived_contexts(lambda get, r=row_n: pp.build_modified(get(r), get("build_irrelevant_generic_nm")))
                basis = sorted({irrelevant[b] for b in drop})[0]
                rules += self._emit(contexts, ["\tRarity Normal Magic", self._bt(_names(drop))], role, category="GENERIC_EQUIPMENT",
                                    name=f"Generic_NM_{label}_BuildIrrelevant", priority=priority, row="build_irrelevant_generic_nm",
                                    base_types=drop, justification=f"MEASURED BUILD EVIDENCE: {basis}")
        # Rare equipment
        rules += self._emit(self._contexts("eq_rare_low"), ["\tRarity Rare", self._bt(_names(sets.low_eq))], "generic_rare", category="GENERIC_EQUIPMENT",
                            name="Generic_Rare_Low", priority=602, row="eq_rare_low", base_types=sets.low_eq)
        rules += self._emit(self._contexts("eq_rare_top"), ["\tRarity Rare", self._bt(_names(sets.top_eq))], "trade", category="TRADE_BASES",
                            name="Trade_Rare_Top", priority=603, row="eq_rare_top", base_types=sets.top_eq)
        rules += self._emit(self._contexts("eq_rare_top_ilvl82"), ["\tRarity Rare", self._bt(_names(sets.top_eq)), f"\tItemLevel >= {TOP_ILVL}"],
                            "trade", category="TRADE_BASES", name="Trade_Rare_Top_i82", priority=604, row="eq_rare_top_ilvl82",
                            base_types=sets.top_eq)
        # Jewellery
        rules += self._emit(self._contexts("jewellery_low_generic"), ["\tRarity Normal Magic", self._bt(_names(sets.low_jw))], "generic",
                            category="GENERIC_EQUIPMENT", name="Generic_Jewellery_Low", priority=605, row="jewellery_low_generic",
                            base_types=sets.low_jw)
        rules += self._emit(self._contexts("jewellery_premium_base"), ["\tRarity Normal Magic", self._bt(_names(sets.top_jw))], "trade",
                            category="TRADE_BASES", name="Trade_Jewellery_Premium", priority=606, row="jewellery_premium_base",
                            base_types=sets.top_jw)
        jewellery = tuple(sorted({*sets.low_jw, *sets.top_jw}))
        rules += self._emit(self._contexts("jewellery_rare"), ["\tRarity Rare", self._bt(_names(jewellery))], "trade", category="TRADE_BASES",
                            name="Trade_Jewellery_Rare", priority=607, row="jewellery_rare", base_types=jewellery)
        # Unidentified rare tiers (any equipment base, known or not)
        rules += self._emit(self._contexts("eq_rare_unid_t5"), ["\tRarity Rare", "\tUnidentifiedItemTier >= 5"], "high_unid",
                            category="HIGH_VALUE_UNID", name="Unidentified_T5", priority=UNID_PRIORITY, row="eq_rare_unid_t5")
        rules += self._emit(self._contexts("eq_rare_unid_t3_4"), ["\tRarity Rare", "\tUnidentifiedItemTier >= 3", "\tUnidentifiedItemTier <= 4"],
                            "high_unid", category="HIGH_VALUE_UNID", name="Unidentified_T3_T4", priority=UNID_PRIORITY + 1, row="eq_rare_unid_t3_4")
        return rules

    def _generate_craft_rules(self) -> List[GeneratedRule]:
        """CRAFT lane (FILTER-09): bases grouped by (craft level, item-level breakpoint); the rows split Normal / Magic / Rare and ilvl 82."""
        from exilelens.filters import crafting_intel as ci
        from exilelens.filters.opportunity import EvidenceKind, ROLE_BY_CLASS, Reason
        from exilelens.filters.verified_bases import load_base_properties, native_class
        widened = self.intel is not None and self.intel.widen
        premium: Dict[int, List[str]] = defaultdict(list)
        relevant: Dict[int, List[str]] = defaultdict(list)
        low: List[str] = []
        unknown: List[str] = []
        for index, base in enumerate(load_base_properties()):
            if self._cooperate is not None and index % 64 == 0:
                self._cooperate()
            if native_class(base) not in ROLE_BY_CLASS:
                continue
            assessment = ci.assess(base)
            if assessment.level == ci.CraftLevel.LOW:
                low.append(base)
            elif assessment.level == ci.CraftLevel.UNKNOWN:
                unknown.append(base)
            else:
                gate = ci.breakpoint_gate(assessment, widened=widened)
                if gate is not None:
                    (premium if assessment.level == ci.CraftLevel.PREMIUM else relevant)[gate].append(base)
        rules: List[GeneratedRule] = []
        guard = ["\tMirrored False", "\tCorrupted False"]

        def reason(level: str, count: int, gate: int) -> tuple:
            return (Reason(EvidenceKind.CRAFTING_OPPORTUNITY, f"{level} crafting substrate ({count} bases) from item level {gate}; "
                           f"{ci.policy_note(self.profile.name.value)}" + (" (pinned data may be stale: one policy step wider)" if widened else "")),)

        for gate, bases in sorted(premium.items()):
            bases = sorted(bases)
            names = self._bt(_names(bases))
            meta = {"class_reasons": reason("PREMIUM", len(bases), gate)}
            if gate < ci.PREMIUM_ILVL:
                rules += self._emit(self._contexts("craft_premium_below_ilvl82"),
                                    ["\tRarity Normal Magic", names, f"\tItemLevel >= {gate}", f"\tItemLevel <= {ci.PREMIUM_ILVL - 1}", *guard],
                                    "craft_premium", category="CRAFT_OPPORTUNITY", name=f"Craft_PREMIUM_below82_i{gate}", priority=CRAFT_NM_PRIORITY,
                                    row="craft_premium_below_ilvl82", base_types=bases, **meta)
            top = max(gate, ci.PREMIUM_ILVL)
            for rarity in ("Normal", "Magic"):
                rules += self._emit(self._contexts(f"craft_premium_{rarity.lower()}_ilvl82"),
                                    [f"\tRarity {rarity}", names, f"\tItemLevel >= {top}", *guard], "craft_premium",
                                    category="CRAFT_OPPORTUNITY", name=f"Craft_PREMIUM_{rarity}_g{gate}_i{top}", priority=CRAFT_NM_PRIORITY + 1,
                                    row=f"craft_premium_{rarity.lower()}_ilvl82", base_types=bases, **meta)
            rules += self._emit(self._contexts("craft_any_rare"), ["\tRarity Rare", names, f"\tItemLevel >= {gate}", *guard], "craft_premium",
                                category="CRAFT_OPPORTUNITY", name=f"Craft_PREMIUM_Rare_i{gate}", priority=622, row="craft_any_rare",
                                base_types=bases, **meta)
        for gate, bases in sorted(relevant.items()):
            bases = sorted(bases)
            names = self._bt(_names(bases))
            meta = {"class_reasons": reason("RELEVANT", len(bases), gate)}
            for rarity in ("Normal", "Magic"):
                rules += self._emit(self._contexts(f"craft_relevant_{rarity.lower()}"),
                                    [f"\tRarity {rarity}", names, f"\tItemLevel >= {gate}", *guard], "craft_relevant",
                                    category="CRAFT_OPPORTUNITY", name=f"Craft_RELEVANT_{rarity}_i{gate}", priority=CRAFT_NM_PRIORITY + 2,
                                    row=f"craft_relevant_{rarity.lower()}", base_types=bases, **meta)
            rules += self._emit(self._contexts("craft_any_rare"), ["\tRarity Rare", names, f"\tItemLevel >= {gate}", *guard], "craft_relevant",
                                category="CRAFT_OPPORTUNITY", name=f"Craft_RELEVANT_Rare_i{gate}", priority=626, row="craft_any_rare",
                                base_types=bases, **meta)
        low_meta = {"class_reasons": (Reason(EvidenceKind.CRAFTING_OPPORTUNITY, "LOW crafting substrate: no top band, generic implicit or "
                                                                                 "intrinsic strength (pinned catalog)"),)}
        rules += self._emit(self._contexts("craft_low"), ["\tRarity Normal Magic", self._bt(_names(low))], "craft_relevant",
                            category="CRAFT_OPPORTUNITY", name="Craft_LOW", priority=630, row="craft_low", base_types=sorted(low), **low_meta)
        unknown_meta = {"class_reasons": (Reason(EvidenceKind.CRAFTING_OPPORTUNITY, "crafting value UNKNOWN (special-mechanic base or no pool "
                                                                                     "data): kept quietly visible by the matrix, never guessed"),)}
        rules += self._emit(self._contexts("craft_unknown"), ["\tRarity Normal Magic", self._bt(_names(unknown))], "craft_relevant",
                            category="CRAFT_OPPORTUNITY", name="Craft_UNKNOWN", priority=631, row="craft_unknown", base_types=sorted(unknown),
                            **unknown_meta)
        return rules

    # -- known generic (KNOWN but unspecialised) ---------------------------------------------------------------------------------------
    def _generate_known_generic_rules(self) -> List[GeneratedRule]:
        """KNOWN_GENERIC: a verified ground base of a class no matrix row owns (today the Trap bases) is a KNOWN item with no specialisation.
        It is shown (visibility is what the safety catch-all gave it before) with the restrained generic treatment of the active theme, never
        with the UNKNOWN treatment: known-but-unspecialised and genuinely unknown are different states with different provenance."""
        from exilelens.filters.opportunity import ROLE_BY_CLASS
        from exilelens.filters.verified_bases import load_base_properties, native_class
        by_class: Dict[str, List[str]] = defaultdict(list)
        for base in load_base_properties():
            cls = native_class(base)
            if cls and cls not in ROLE_BY_CLASS and cls not in KNOWN_GENERIC_HANDLED_CLASSES:
                by_class[cls].append(base)
        rules: List[GeneratedRule] = []
        for cls in sorted(by_class):
            bases = sorted(by_class[cls])
            rules += self._emit((("SHOW", None),), [f'	Class "{cls}"', self._bt(_names(bases))], "generic", category="GENERIC_EQUIPMENT",
                                name=f"Known_Generic_{cls.replace(' ', '')}", priority=KNOWN_GENERIC_PRIORITY, row=KNOWN_GENERIC_ROW,
                                base_types=bases)
        return rules

    # -- safety -----------------------------------------------------------------------------------------------------------------------
    def _generate_safety_rule(self) -> List[GeneratedRule]:
        """The unknown-item catch-all: everything no row classified (a new base after a patch, a new item class, unnamed currency) is SHOWN
        with a recognisable, non-jackpot style. It is the last rule, after every Hide, so a known family keeps its own styling and an item is
        never hidden merely because the snapshot does not know it."""
        lines = self._apply_theme_style(["Show"], "unknown", None, "SHOW+")
        return [GeneratedRule(category="UNKNOWN_SAFETY", name="Unknown / unclassified items (SAFETY)", lines=lines, priority=9999,
                              row="unknown_new_items", state="SAFETY", role="unknown")]
