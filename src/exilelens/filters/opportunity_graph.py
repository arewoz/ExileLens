"""Versioned, inspectable Item Opportunity Graph (FILTER-08D).

BUILD NEED -> STAT FAMILY -> MODIFIER FAMILY -> ELIGIBLE CLASS -> ELIGIBLE BASE -> ITEM LEVEL / REQUIREMENT -> NATIVE PROXY

Every edge carries a provenance. There is NO numeric score anywhere: an edge exists or it does not, and its attributes are the
verified facts or the measured increments it rests on. Missing edges are never inferred to raise coverage: a probe production did not
run creates no NEED node, a family a base cannot roll creates no edge.

Built at generation time from a ``BuildNeedsSnapshot`` plus the pinned PoB2 datasets; nothing here touches PoB, the network or the
game. The native filter still only observes Class / BaseType / ItemLevel / Rarity / Quality / UnidentifiedItemTier / defence
values: the PROXY edges say exactly which of those a recommendation can use, and that the modifier itself is not observable.
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping

from exilelens.filters import affix_pools as pools
from exilelens.filters import skill_facts
from exilelens.filters.build_needs import BuildNeedsSnapshot, Relevance
from exilelens.filters.data_drift import GENERATOR_SCHEMA
from exilelens.filters.opportunity import ROLE_BY_CLASS, ROLE_CATEGORIES, BuildOpportunityModel, _MAINTENANCE_PROBES, _shared_layers
from exilelens.filters.priorities import EXTENDED_WEAPON_CLASSES, SKILL_WEAPON_CLASSES
from exilelens.filters.verified_bases import load_base_properties, native_class

GRAPH_SCHEMA = 1
NATIVE_OBSERVABLES = ("Class", "BaseType", "ItemLevel", "Rarity", "Quality", "UnidentifiedItemTier", "BaseArmour", "BaseEvasion",
                      "BaseEnergyShield")
_LAYER_PROBES = {"armour": "ARMOUR", "evasion": "EVASION", "energy_shield": "ENERGY_SHIELD"}


class Provenance(str, Enum):
    VERIFIED_BASE_DATA = "verified game/base data"
    VERIFIED_MODIFIER_POOL = "verified modifier-pool data"
    BI_MEASUREMENT = "production Build Intelligence measurement"
    COMPATIBILITY_REQUIREMENT = "compatibility requirement"
    CURATED_FALLBACK = "curated fallback"
    HEURISTIC = "heuristic"
    UNKNOWN = "unknown"


class EdgeKind(str, Enum):
    NEED_TO_FAMILY = "need->family"
    FAMILY_TO_CLASS = "family->class"
    FAMILY_TO_BASE = "family->base"          # the base's pool can roll the family (attrs: item levels of eligible tiers)
    BASE_IMPLICIT = "base->implicit family"  # always present on the base
    BASE_INTRINSIC = "base->intrinsic defence"
    SKILL_CLASS = "skill->weapon class"
    BASE_PROXY = "base->native proxy"
    BASE_MARKET = "base->market signal"
    BASE_CRAFT = "base->craft substrate"     # FILTER-09: build-independent crafting value (breadth, breakpoints), never a need edge


@dataclass(frozen=True)
class Edge:
    kind: EdgeKind
    source: str
    target: str
    provenance: Provenance
    attrs: tuple[tuple[str, Any], ...] = ()

    def get(self, key: str, default: Any = None) -> Any:
        return dict(self.attrs).get(key, default)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind.value, "from": self.source, "to": self.target, "provenance": self.provenance.value, **dict(self.attrs)}


def _attrs(**kw: Any) -> tuple[tuple[str, Any], ...]:
    return tuple(sorted((k, tuple(v) if isinstance(v, list) else v) for k, v in kw.items()))


@dataclass(frozen=True)
class MarketSignal:
    """Generation-time market context with provenance. Never a price, never required, never fetched here."""
    level: str = "UNKNOWN"          # LIVE | CACHED | HEURISTIC | UNKNOWN
    source: str = ""
    observed_at: str = ""


@dataclass(frozen=True)
class Support:
    """One reason a base is an opportunity for one measured stat family."""
    need: str                       # probe id
    family: str
    relation: str                   # DIRECT | NARROWED
    source: str                     # POOL | IMPLICIT | INTRINSIC
    relevance: str
    tested_change: str
    first_level: int | None
    top_level: int | None
    universal: bool                 # every base of the class can roll it (class-level information only)
    provenance: tuple[str, ...]
    confidence: str = ""
    category: str = ""              # offense | defense | resistance | utility (the kind of tested intervention)


@dataclass(frozen=True)
class BaseOpportunity:
    base: str
    native_class: str
    required_level: int
    supports: tuple[Support, ...]
    proxy: tuple[str, ...]          # the native conditions a rule can use
    measured: bool                  # at least one supporting need is a HIGH/MEDIUM-confidence production measurement

    @property
    def strongest(self) -> str:
        order = ("FIX_FIRST", "STRONG", "RESPONSIVE", "MARGINAL")
        return min((s.relevance for s in self.supports), key=lambda r: order.index(r) if r in order else 9, default="")

    def unlock_level(self, family: str | None = None) -> int | None:
        levels = [s.top_level for s in self.supports if s.top_level and (family is None or s.family == family)]
        return min(levels) if levels else None


class OpportunityGraph:
    """Immutable per-build graph with query methods. Construct with ``OpportunityGraph.build``."""

    def __init__(self, edges: list[Edge], meta: Mapping[str, Any], needs: BuildNeedsSnapshot) -> None:
        self.edges = edges
        self.meta = dict(meta)
        self.needs = needs
        self._by_kind: dict[EdgeKind, list[Edge]] = defaultdict(list)
        self._from: dict[str, list[Edge]] = defaultdict(list)
        self._to: dict[str, list[Edge]] = defaultdict(list)
        for edge in edges:
            self._by_kind[edge.kind].append(edge)
            self._from[edge.source].append(edge)
            self._to[edge.target].append(edge)

    # ---- construction -------------------------------------------------------------------------------------------------------
    @classmethod
    def build(cls, needs: BuildNeedsSnapshot, *, market: Mapping[str, MarketSignal] | None = None) -> "OpportunityGraph":
        edges: list[Edge] = []
        model = BuildOpportunityModel(needs)
        definitions = pools.family_definitions()
        # 1. NEED -> FAMILY: only for probes the production analysis actually reported; narrowed families only when applicable.
        needed: dict[str, str] = {}
        for signal in needs.signals:
            fix_first_need = signal.relevance == Relevance.FIX_FIRST.value        # a verified deficit, even if no probe was run
            if signal.status not in ("MEASURED", "NO_SIGNAL") and not fix_first_need:
                continue
            for family, definition in definitions.items():
                if definition["probe_id"] != signal.probe_id or not model.applicable(family):
                    continue
                needed[family] = signal.probe_id
                edges.append(Edge(EdgeKind.NEED_TO_FAMILY, f"need:{signal.probe_id}", f"family:{family}", Provenance.BI_MEASUREMENT,
                                  _attrs(relevance=signal.relevance, status=signal.status, confidence=signal.confidence,
                                         tested_change=signal.tested_change, relation=definition["relation"],
                                         lanes=list(signal.lanes), category=signal.category)))
        # 2. FAMILY -> CLASS / BASE from the verified pools; implicit and intrinsic edges from verified base data.
        properties = load_base_properties()
        class_totals: dict[str, int] = defaultdict(int)
        class_able: dict[tuple[str, str], int] = defaultdict(int)
        for base, record in properties.items():
            native = native_class(base)
            if native is None:
                continue
            class_totals[native] += 1
            if record["class"] == "Quiver" and not model.bow_context:
                continue        # a quiver serves bow users: no build evidence applies without a verified/equipped bow
            base_pools = pools.pools_for(base)
            universal = pools.universal_families(record["class"])
            for family, pool in base_pools.items():
                if family not in needed:
                    continue
                class_able[(family, native)] += 1
                edges.append(Edge(EdgeKind.FAMILY_TO_BASE, f"family:{family}", f"base:{base}", Provenance.VERIFIED_MODIFIER_POOL,
                                  _attrs(first_level=pool.first_level, top_level=pool.top_level, tiers=len(pool.levels),
                                         universal=family in universal, native_class=native)))
            for family in pools.implicit_families(base):
                if family in needed:
                    edges.append(Edge(EdgeKind.BASE_IMPLICIT, f"base:{base}", f"family:{family}", Provenance.VERIFIED_BASE_DATA,
                                      _attrs(implicit=record["implicit"], always_present=True)))
            shared = _shared_layers(record["class"])
            for key, probe in _LAYER_PROBES.items():
                if record.get(key) and needs.signal(probe) is not None and needs.signal(probe).status in ("MEASURED", "NO_SIGNAL"):
                    edges.append(Edge(EdgeKind.BASE_INTRINSIC, f"base:{base}", f"need:{probe}", Provenance.VERIFIED_BASE_DATA,
                                      _attrs(layer=key, value=record[key], universal=key in shared)))
        for (family, native), count in sorted(class_able.items()):
            edges.append(Edge(EdgeKind.FAMILY_TO_CLASS, f"family:{family}", f"class:{native}", Provenance.VERIFIED_MODIFIER_POOL,
                              _attrs(bases_able=count, bases_in_class=class_totals[native])))
        # 3. SKILL -> CLASS: verified weapon requirement first, curated map only as an explicitly labelled fallback.
        skill = needs.skill
        if skill.weapon_classes:
            for cls_name in skill.weapon_classes:
                edges.append(Edge(EdgeKind.SKILL_CLASS, f"skill:{skill.name}", f"class:{cls_name}", Provenance.COMPATIBILITY_REQUIREMENT,
                                  _attrs(source="PoB2 skill weapon requirement", supported=cls_name in ROLE_BY_CLASS)))
        elif skill.name and SKILL_WEAPON_CLASSES.get(skill.name):
            for cls_name in SKILL_WEAPON_CLASSES[skill.name]:
                edges.append(Edge(EdgeKind.SKILL_CLASS, f"skill:{skill.name}", f"class:{cls_name}", Provenance.CURATED_FALLBACK,
                                  _attrs(source="curated skill map")))
        # 4. BASE -> native proxy (what a rule may test) and optional market signal.
        for base in properties:
            native = native_class(base)
            if native in ROLE_BY_CLASS:
                edges.append(Edge(EdgeKind.BASE_PROXY, f"base:{base}", f"proxy:{native}", Provenance.VERIFIED_BASE_DATA,
                                  _attrs(conditions=["Class", "BaseType", "ItemLevel", "Rarity", "Quality"], required_level=record_level(properties, base),
                                         modifier_observable=False)))
        # 4b. BASE -> general crafting value: independent of every need. Only PREMIUM / RELEVANT substrates get an edge, so the
        #     graph says "this base is worth a look as a substrate" separately from "this base serves the measured build".
        from exilelens.filters import crafting_intel as craft_intel
        for base in properties:
            if native_class(base) not in ROLE_BY_CLASS:
                continue
            assessment = craft_intel.assess(base)
            if assessment.level not in (craft_intel.CraftLevel.PREMIUM, craft_intel.CraftLevel.RELEVANT):
                continue
            edges.append(Edge(EdgeKind.BASE_CRAFT, f"base:{base}", "craft", Provenance.VERIFIED_MODIFIER_POOL
                              if assessment.confidence == "VERIFIED" else Provenance.VERIFIED_BASE_DATA,
                              _attrs(level=assessment.level.value, band=assessment.band, implicit=assessment.implicit.value,
                                     intrinsic=assessment.intrinsic, breadth=assessment.breadth, groups=list(assessment.groups),
                                     breakpoints=dict(assessment.breakpoints), build_independent=True)))
        for base, signal in (market or {}).items():
            edges.append(Edge(EdgeKind.BASE_MARKET, f"base:{base}", "market", Provenance.HEURISTIC if signal.level in ("HEURISTIC", "UNKNOWN")
                              else Provenance.UNKNOWN, _attrs(level=signal.level, source=signal.source, observed_at=signal.observed_at)))
        meta = {"graph_schema": GRAPH_SCHEMA, "generator_schema": GENERATOR_SCHEMA, "build": needs.label,
                "baseline_fingerprint": str((needs.identity or {}).get("baseline_fingerprint") or ""), "coverage": needs.coverage.value,
                "skill": needs.skill.name, "data": _data_versions()}
        return cls(edges, meta, needs)

    # ---- queries --------------------------------------------------------------------------------------------------------------
    def need_edges(self, min_rank: int = Relevance.STRONG.rank) -> list[Edge]:
        return [e for e in self._by_kind[EdgeKind.NEED_TO_FAMILY]
                if Relevance(e.get("relevance")).rank >= min_rank and (e.get("status") == "MEASURED" or e.get("relevance") == "FIX_FIRST")]

    def opportunities(self, *, min_relevance: Relevance = Relevance.STRONG, base_specific_only: bool = True,
                      classes: Iterable[str] | None = None, decision_policy: bool = False) -> list[BaseOpportunity]:
        """Bases that can plausibly support a measured stat family of at least ``min_relevance``.

        ``base_specific_only`` drops class-universal pool families (every base of the class can roll them: no per-base information).
        ``decision_policy`` applies the generator's policy that resistances/attributes are maintenance stats (they identify a need
        only as a FIX_FIRST deficit); the raw graph keeps every measured edge."""
        wanted = set(classes) if classes else None
        needs_by_family = {e.target: e for e in self.need_edges(min_relevance.rank)
                           if not (decision_policy and e.source[5:] in _MAINTENANCE_PROBES and e.get("relevance") != "FIX_FIRST")}
        collected: dict[str, list[Support]] = defaultdict(list)
        for family_node, need_edge in needs_by_family.items():
            for edge in self._from[family_node]:
                if edge.kind != EdgeKind.FAMILY_TO_BASE:
                    continue
                if base_specific_only and edge.get("universal"):
                    continue
                base = edge.target.split(":", 1)[1]
                collected[base].append(self._support(need_edge, edge, "POOL"))
        for family_node, need_edge in needs_by_family.items():
            for edge in self._to[family_node]:
                if edge.kind == EdgeKind.BASE_IMPLICIT:
                    collected[edge.source.split(":", 1)[1]].append(self._support(need_edge, edge, "IMPLICIT"))
        for family_node, need_edge in needs_by_family.items():
            for edge in self._to[f"need:{family_node[7:]}"]:
                if edge.kind == EdgeKind.BASE_INTRINSIC and not (base_specific_only and edge.get("universal")):
                    collected[edge.source.split(":", 1)[1]].append(
                        Support(need=need_edge.source[5:], family=family_node[7:], relation="DIRECT", source="INTRINSIC",
                                relevance=need_edge.get("relevance"), tested_change=need_edge.get("tested_change"), first_level=None,
                                top_level=None, universal=False, provenance=(Provenance.BI_MEASUREMENT.value, edge.provenance.value),
                                confidence=str(need_edge.get("confidence") or ""), category=str(need_edge.get("category") or "")))
        out = []
        properties = load_base_properties()
        for base, supports in collected.items():
            native = native_class(base) or ""
            if wanted is not None and native not in wanted:
                continue
            if decision_policy:
                role = ROLE_BY_CLASS.get(native)
                supports = [x for x in supports if role is None or x.category in ROLE_CATEGORIES[role]]
                if not supports:
                    continue
            out.append(BaseOpportunity(base, native, int(properties[base]["required_level"]), tuple(supports),
                                       NATIVE_OBSERVABLES[:5], any(s.confidence in ("HIGH", "MEDIUM") for s in supports)))
        return sorted(out, key=lambda o: (-len(o.supports), o.base))

    def _support(self, need_edge: Edge, edge: Edge, source: str) -> Support:
        return Support(need=need_edge.source.split(":", 1)[1], family=need_edge.target.split(":", 1)[1] if source == "POOL" else edge.target.split(":", 1)[1],
                       relation=need_edge.get("relation"), source=source, relevance=need_edge.get("relevance"),
                       tested_change=need_edge.get("tested_change"), first_level=edge.get("first_level"), top_level=edge.get("top_level"),
                       universal=bool(edge.get("universal")),
                       provenance=(Provenance.BI_MEASUREMENT.value, edge.provenance.value), confidence=str(need_edge.get("confidence") or ""),
                       category=str(need_edge.get("category") or ""))

    def why(self, base: str) -> list[str]:
        """Human-readable chain for one base: which measured need, which verified fact, what a native rule may observe."""
        lines = []
        record = load_base_properties().get(base)
        if record is None:
            return [f"{base}: not in the verified base catalog (unknown: no edges are inferred)"]
        lines.append(f"{base} — {native_class(base)}, required level {record['required_level']} [{Provenance.VERIFIED_BASE_DATA.value}]")
        found = False
        for family_node, need_edge in ((e.target, e) for e in self._by_kind[EdgeKind.NEED_TO_FAMILY]):
            for edge in self._from[family_node]:
                if edge.kind == EdgeKind.FAMILY_TO_BASE and edge.target == f"base:{base}":
                    found = True
                    lines.append(f"eligible opportunity for {family_node[7:]} (need {need_edge.source[5:]}: {need_edge.get('tested_change')}; "
                                 f"{need_edge.get('relevance')}, {need_edge.get('confidence')} confidence) from item level {edge.get('first_level')}, "
                                 f"top tier {edge.get('top_level')}{' [class-universal]' if edge.get('universal') else ''} "
                                 f"[{need_edge.provenance.value} + {edge.provenance.value}]")
        for edge in self._from[f"base:{base}"]:
            if edge.kind == EdgeKind.BASE_IMPLICIT:
                found = True
                lines.append(f"implicit grants {edge.target[7:]} (always present) [{edge.provenance.value}]")
            elif edge.kind == EdgeKind.BASE_INTRINSIC:
                lines.append(f"intrinsic {edge.get('layer')} {edge.get('value')} bears on {edge.target[5:]} [{edge.provenance.value}]")
            elif edge.kind == EdgeKind.BASE_PROXY:
                lines.append(f"native proxy: {', '.join(edge.get('conditions'))}; the modifier itself is NOT observable [{edge.provenance.value}]")
        if not found:
            lines.append("no measured need reaches this base through a verified edge (no evidence either way)")
        return lines

    def unlock_levels(self, base: str) -> dict[str, tuple[int, int]]:
        """family -> (first item level, top-tier item level) for measured families this base can roll."""
        out = {}
        for edge in self._to[f"base:{base}"]:
            if edge.kind == EdgeKind.FAMILY_TO_BASE and edge.source in {e.target for e in self._by_kind[EdgeKind.NEED_TO_FAMILY]}:
                out[edge.source[7:]] = (edge.get("first_level"), edge.get("top_level"))
        return out

    def is_measured(self, base: str) -> bool:
        """True when the base is reachable from a MEASURED need only through production-measured + verified edges."""
        opp = next((o for o in self.opportunities(min_relevance=Relevance.MARGINAL, base_specific_only=False) if o.base == base), None)
        return bool(opp and opp.measured)

    def craft(self, base: str) -> dict[str, Any] | None:
        """General (build-independent) crafting value of a base, or None when it is not a PREMIUM / RELEVANT substrate."""
        edge = next((e for e in self._from[f"base:{base}"] if e.kind == EdgeKind.BASE_CRAFT), None)
        return None if edge is None else {k: v for k, v in edge.attrs}

    def market(self, base: str) -> MarketSignal:
        edge = next((e for e in self._from[f"base:{base}"] if e.kind == EdgeKind.BASE_MARKET), None)
        return MarketSignal(edge.get("level"), edge.get("source"), edge.get("observed_at")) if edge else MarketSignal()

    def summary(self) -> dict[str, Any]:
        counts: dict[str, int] = defaultdict(int)
        by_prov: dict[str, int] = defaultdict(int)
        for edge in self.edges:
            counts[edge.kind.value] += 1
            by_prov[edge.provenance.value] += 1
        return {**self.meta, "edges": len(self.edges), "by_kind": dict(counts), "by_provenance": dict(by_prov)}

    def to_json(self, *, include_proxy_edges: bool = False) -> str:
        edges = [e.to_dict() for e in self.edges if include_proxy_edges or e.kind != EdgeKind.BASE_PROXY]
        return json.dumps({"meta": self.meta, "summary": self.summary(), "edges": edges}, indent=1, sort_keys=True)


def record_level(properties: Mapping[str, Mapping[str, Any]], base: str) -> int:
    return int(properties[base]["required_level"])


def _data_versions() -> dict[str, Any]:
    from exilelens.filters.data_drift import check
    status = check()
    return {"state": status.state.value, **{k: status.versions.get(k) for k in ("pob_version", "pob_commit", "game_version_hint")}}
