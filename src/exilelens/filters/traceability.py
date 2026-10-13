"""Build Priority -> filter relevance traceability (FILTER-08E).

For every measured need of a build this answers, from the data and the generated rules rather than from prose:

    probe -> verified modifier family -> eligible classes/bases -> item levels -> native proxy (what a rule may test) -> generated rule

and classifies the need:

  A  AFFECTS NATIVE RULES      at least one generated BUILD rule exists because of it (a base is promoted, or a rule is gated/included by it)
  B  EMPHASIS ONLY             verified bases can roll/imply the family, but no rule is created or changed by it (it only appears in the
                               explanation / opportunity graph, or is class-level information with no base-specific advantage)
  C  CANNOT BE TRANSLATED      no verified base carries the family, or the need was not established, so no ground rule can honestly use it
  D  IRRELEVANT TO GROUND LOOT PoB measured no response (or policy treats it as a satisfied maintenance stat): nothing to translate

Every trace also states what a native filter can NOT claim: unidentified rolls are unobservable, so a rule never says an item HAS a stat.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from exilelens.filters import affix_pools as pools
from exilelens.filters.build_needs import BuildNeedsSnapshot, Relevance
from exilelens.filters.opportunity import _MAINTENANCE_PROBES
from exilelens.filters.opportunity_graph import OpportunityGraph

CLASSES = {"A": "AFFECTS NATIVE RULES", "B": "EMPHASIS ONLY", "C": "CANNOT BE TRANSLATED SAFELY", "D": "IRRELEVANT TO GROUND-FILTER DECISIONS"}
LIMIT = "Unidentified modifiers are not observable: a rule can name a base and an item level, never claim the item contains this stat."


@dataclass
class Trace:
    probe: str
    category: str
    relevance: str
    confidence: str
    families: tuple[str, ...]
    classification: str
    why: str
    eligible_classes: tuple[str, ...] = ()
    eligible_bases: int = 0
    sources: dict[str, int] = field(default_factory=dict)          # POOL / IMPLICIT / INTRINSIC -> base count
    item_levels: tuple[int | None, int | None] = (None, None)      # lowest first level, highest top tier level among eligible pools
    native_proxy: tuple[str, ...] = ()
    rules: dict[str, tuple[str, ...]] = field(default_factory=dict)  # profile -> promoted/including BUILD rule names
    limitation: str = LIMIT

    def chain(self) -> str:
        lo, hi = self.item_levels
        parts = [f"{self.probe} [{self.relevance}, {self.confidence}]"]
        parts.append("families " + (", ".join(self.families) if self.families else "none verified"))
        if self.eligible_bases:
            parts.append(f"{self.eligible_bases} eligible bases in {', '.join(self.eligible_classes)} ({', '.join(f'{k} {v}' for k, v in sorted(self.sources.items()))})")
            if lo is not None or hi is not None:
                parts.append(f"item level {lo}-{hi}")
            parts.append("native proxy " + " + ".join(self.native_proxy))
        for profile, names in self.rules.items():
            if names:
                parts.append(f"{profile}: {', '.join(names[:3])}" + (f" (+{len(names) - 3})" if len(names) > 3 else ""))
        parts.append(f"=> {self.classification} {CLASSES[self.classification]}: {self.why}")
        return " -> ".join(parts)


def trace(needs: BuildNeedsSnapshot, rules_by_profile: Mapping[str, Sequence]) -> list[Trace]:
    graph = OpportunityGraph.build(needs)
    inverse: dict[str, list[str]] = defaultdict(list)
    for family in pools.family_definitions():
        inverse[pools.family_probe(family)].append(family)
    supports: dict[str, list] = defaultdict(list)
    for opportunity in graph.opportunities(min_relevance=Relevance.MARGINAL, base_specific_only=False):
        for support in opportunity.supports:
            supports[support.need].append((opportunity, support))
    out: list[Trace] = []
    for signal in needs.signals:
        probe = signal.probe_id
        families = tuple(sorted(inverse.get(probe, ())))
        relevance = signal.relevance_class
        entries = supports.get(probe, [])
        bases = {o.base for o, _ in entries}
        classes = tuple(sorted({o.native_class for o, _ in entries}))
        sources: dict[str, set[str]] = defaultdict(set)
        for o, s in entries:
            sources[s.source].add(o.base)
        firsts = [s.first_level for _, s in entries if s.first_level is not None]
        tops = [s.top_level for _, s in entries if s.top_level is not None]
        proxy = ()
        if bases:
            proxy = ("Class", "BaseType") + (("ItemLevel",) if tops else ())
        promoted: dict[str, tuple[str, ...]] = {}
        informed: dict[str, tuple[str, ...]] = {}
        for profile, rules in rules_by_profile.items():
            names, info = [], []
            for rule in rules:
                if not rule.category.startswith("BUILD"):
                    continue
                for decision in rule.decisions or ():
                    hits = [h for h in decision.hits if h.probe_id == probe]
                    if hits and decision.shift > 0:
                        names.append(rule.name)
                        break
                    if hits:
                        info.append(rule.name)
                        break
            promoted[profile], informed[profile] = tuple(dict.fromkeys(names)), tuple(dict.fromkeys(info))
        any_promoted = any(promoted.values())
        any_informed = any(informed.values())
        if signal.status == "NO_SIGNAL" and relevance != Relevance.FIX_FIRST:
            if relevance == Relevance.NO_RESPONSE:
                cls, why = "D", "PoB reported no response on any tested axis; it is not a need and only a confident demotion may use it"
            else:
                cls, why = "C", "the measurement could not be established (unsupported / not run), which is never evidence about the build"
        elif relevance == Relevance.NOT_ESTABLISHED:
            cls, why = "C", "not established: no ground rule may use a need that was never measured"
        elif relevance == Relevance.NO_RESPONSE:
            cls, why = "D", "measured no response: not a need; may only support a confident, evidence-gated demotion"
        elif not families or not bases:
            cls, why = "C", "no verified modifier family / base can carry this stat on the ground, so there is nothing for a native rule to name"
        elif any_promoted:
            cls, why = "A", "verified bases that can roll or imply it are promoted into build rules"
        elif probe in _MAINTENANCE_PROBES and relevance != Relevance.FIX_FIRST:
            cls, why = "D", "a satisfied maintenance stat (resistance/attribute at cap): it identifies a need only as a FIX_FIRST deficit"
        elif any_informed:
            cls, why = "B", "appears in rule explanations and class-level context only; no base gains an advantage from it"
        else:
            cls, why = "B", "verified bases can roll it, but the decision policy creates no rule from it (emphasis in the graph and explanations only)"
        if relevance == Relevance.FIX_FIRST and cls in ("A", "B"):
            why += "; a Fix First deficit may widen which bases are worth inspecting but cannot claim any item contains the fix"
        out.append(Trace(probe, signal.category, relevance.value, signal.confidence, families, cls, why, classes, len(bases),
                         {k: len(v) for k, v in sources.items()}, (min(firsts) if firsts else None, max(tops) if tops else None), proxy, promoted))
    return out


def summarise(traces: Sequence[Trace]) -> dict[str, int]:
    counts = {k: 0 for k in CLASSES}
    for t in traces:
        counts[t.classification] += 1
    return counts
