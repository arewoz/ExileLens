"""Filter decision inspector (FILTER-08D): "why is this item shown / hidden?" for every profile, offline.

Pure functions over a stored ``BuildNeedsSnapshot`` (no PoB, no Qt). The CLI wrapper is ``tools/filter_inspect.py``.

For each requested profile the inspector regenerates the filter, evaluates the item with the same first-match simulator as the
preview, and reports: visibility, the matched rule and its category, the rule's native conditions and effects, the
evidence/provenance text, the reduction justification when hidden, the data/intelligence state, and the opportunity-graph facts for
the base (which stat families make it an opportunity, from which source, at what confidence). With ``compare`` it also shows what
a second build would do with the same item.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

from exilelens.filters import benchmark08b as bm
from exilelens.filters.build_needs import BuildNeedsSnapshot, Relevance
from exilelens.filters.data_drift import DataStatus
from exilelens.filters.intel_generate import GenerationResult, filter_body_sha256, generate
from exilelens.filters.opportunity_graph import OpportunityGraph
from exilelens.filters.preview import PreviewItem, preview_decision
from exilelens.filters.verified_bases import load_base_properties, native_class

PROFILE_NAMES = bm.PROFILES


@dataclass
class ProfileVerdict:
    profile: str
    visible: bool
    rule: str
    category: str
    rule_lines: tuple[str, ...]
    effects: str
    reason: str
    provenance: str
    justification: str
    sections: tuple[tuple[str, str], ...]
    rules_sha: str
    # FILTER-09: independent lanes (BUILD / CRAFT / TRADE / PROTECTED / FALLBACK) and the reference combination for this profile
    lanes: tuple[dict, ...] = ()
    lane_decision: str = ""
    lane_visible: bool | None = None


@dataclass
class Inspection:
    item: PreviewItem
    build: str
    coverage: str
    evidence_complete: bool
    data_state: str
    base_known: bool
    graph_facts: list[str]
    verdicts: list[ProfileVerdict]
    compared: "Inspection | None" = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        data = {k: v for k, v in self.__dict__.items() if k not in ("item", "compared", "verdicts")}
        data["item"] = {k: getattr(self.item, k) for k in ("name", "item_class", "base_type", "rarity", "item_level", "quality",
                                                            "unidentified_item_tier", "waystone_tier")}
        data["verdicts"] = [v.__dict__ for v in self.verdicts]
        if self.compared is not None:
            data["compared"] = self.compared.to_dict()
        return data


def make_item(base: str, *, rarity: str = "Rare", item_level: int = 82, quality: int = 0, unidentified_tier: int = 0,
              item_class: str = "") -> PreviewItem:
    record = load_base_properties().get(base)
    cls = item_class or native_class(base) or ""
    if record is None:
        return PreviewItem(base, "inspector", cls, base, rarity, item_level=item_level, quality=quality, unidentified_item_tier=unidentified_tier)
    return PreviewItem(base, "inspector", cls, base, rarity, item_level=item_level, quality=quality, unidentified_item_tier=unidentified_tier,
                       base_energy_shield=record["energy_shield"], base_armour=record["armour"], base_evasion=record["evasion"])


def _lanes(item: PreviewItem, profile: str, model, *, build_shown: bool = False,
           widen: bool = False) -> tuple[tuple[dict, ...], str, bool | None]:
    from exilelens.filters.opportunity_lanes import Lane, decide
    reference = decide(item, profile, model=model, build_shown=build_shown, widen=widen)
    present = {v.lane: v for v in reference.verdicts}
    rows = []
    for lane in (Lane.BUILD, Lane.CRAFT, Lane.TRADE, Lane.PROTECTED, Lane.FALLBACK):
        v = present.get(lane)
        rows.append({"lane": lane.value, "level": v.level.value if v else "NOT APPLICABLE", "precision": v.precision.value if v else "-",
                     "reason": v.reason if v else "no evidence from this lane applies to the item", "source": v.source if v else "-",
                     "confidence": v.confidence if v else "-", "native_proxy": list(v.proxy) if v else [],
                     "policy": v.policy if v else "", "provenance": list(v.provenance) if v else []})
    cause = reference.cause.value if reference.cause else "none"
    text = (f"{'SHOW' if reference.visible else 'HIDE'} · cause {cause}"
            + (f" (supported by {', '.join(l.value for l in reference.supporting)}; emphasis +{reference.emphasis_bonus})" if reference.supporting else "")
            + f" — {reference.why}")
    return tuple(rows), text, reference.visible


def _verdict(needs: BuildNeedsSnapshot, result: GenerationResult, item: PreviewItem, profile: str, model=None) -> ProfileVerdict:
    decision = preview_decision(result.rules, item)
    rule = next((r for r in result.rules if r.name == decision.rule_name), None)
    justification = ""
    if decision.hidden:
        legacy = generate(needs, profile, intel=False)
        if not preview_decision(legacy.rules, item).hidden:           # a reduction relative to the legacy filter needs a justification
            justification = bm.reduction_justification(item, needs, result, matched_rule=decision.rule_name)
        else:
            justification = "not a reduction: the legacy (build-independent) filter hides it as well"
    widen = bool(result.intel is not None and result.intel.widen)
    lanes, lane_text, lane_visible = (_lanes(item, profile, model, build_shown=bool(rule and rule.category.startswith("BUILD")
                                                                                     and not decision.hidden), widen=widen)
                                      if model is not None else ((), "", None))
    return ProfileVerdict(profile, not decision.hidden, decision.rule_name, rule.category if rule else "(none)",
                          tuple(line.strip() for line in rule.lines) if rule else (), decision.native_details, decision.reason,
                          decision.provenance, str(justification), tuple(decision.sections), filter_body_sha256(result.text),
                          lanes, lane_text, lane_visible)


def inspect(needs: BuildNeedsSnapshot, item: PreviewItem, *, profiles: Sequence[str] = PROFILE_NAMES, data_status: DataStatus | None = None,
            compare: BuildNeedsSnapshot | None = None) -> Inspection:
    results = {p: generate(needs, p, intel=True, data_status=data_status) for p in profiles}
    from exilelens.filters.opportunity import BuildOpportunityModel
    model = BuildOpportunityModel(needs)
    graph = OpportunityGraph.build(needs)
    facts: list[str] = []
    if item.base_type:
        for opportunity in graph.opportunities(min_relevance=Relevance.RESPONSIVE, base_specific_only=False):
            if opportunity.base == item.base_type:
                facts.extend(f"{s.family} ({s.relation}, {s.source}, {s.relevance}, via {s.need}; "
                             f"levels {s.first_level}-{s.top_level})" for s in opportunity.supports[:6])
                break
    base_known = item.base_type in load_base_properties()
    status = next(iter(results.values())).data_status
    inspection = Inspection(item, needs.label, needs.coverage.value, needs.evidence_complete,
                            status.state.value if status else "UNKNOWN", base_known, facts,
                            [_verdict(needs, results[p], item, p, model) for p in profiles])
    if not base_known and item.base_type:
        inspection.notes.append("The base is not in the verified catalog: no build rule can name it, only class-level rules apply.")
    if not facts and base_known:
        inspection.notes.append("No measured stat family makes this base an opportunity for this build (see the verdict's rule for why it is "
                                "still shown or hidden).")
    if compare is not None:
        inspection.compared = inspect(compare, item, profiles=profiles, data_status=data_status)
    return inspection


def render(inspection: Inspection, *, indent: str = "") -> str:
    item = inspection.item
    out = [f"{indent}{inspection.build}  [{inspection.coverage}; evidence {'complete' if inspection.evidence_complete else 'INCOMPLETE'}; "
           f"data {inspection.data_state}]",
           f"{indent}Item: {item.item_class} / {item.base_type or item.name} / {item.rarity} i{item.item_level} q{item.quality}"
           + (f" unid-tier {item.unidentified_item_tier}" if item.unidentified_item_tier else "")]
    if inspection.graph_facts:
        out.append(f"{indent}Build opportunity facts:")
        out.extend(f"{indent}  - {fact}" for fact in inspection.graph_facts)
    out.extend(f"{indent}Note: {note}" for note in inspection.notes)
    for v in inspection.verdicts:
        out.append(f"{indent}{v.profile:<12} {'SHOW' if v.visible else 'HIDE'}  <- {v.rule} [{v.category}]  {v.effects}")
        if not v.sections:
            out.append(f"{indent}{'':<12} {v.reason}")
        if v.justification:
            out.append(f"{indent}{'':<12} reduction justification: {v.justification}")
        for label, text in v.sections:
            out.append(f"{indent}{'':<12} {label}: {text}")
        for lane in v.lanes:
            if lane["level"] == "NOT APPLICABLE":
                continue
            out.append(f"{indent}{'':<12} LANE {lane['lane']:<9} {lane['level']} ({lane['precision']}; {lane['confidence']}) "
                       f"{lane['reason'][:110]} [source: {lane['source']}; native: {', '.join(lane['native_proxy']) or 'none'}]")
        if v.lane_decision:
            out.append(f"{indent}{'':<12} LANE DECISION: {v.lane_decision}")
    if inspection.compared is not None:
        out.append("")
        out.append(f"{indent}--- compared with ---")
        out.append(render(inspection.compared, indent=indent))
        out.append(f"{indent}Differences:")
        for a, b in zip(inspection.verdicts, inspection.compared.verdicts):
            if a.visible != b.visible or a.rule != b.rule:
                out.append(f"{indent}  {a.profile}: {'SHOW' if a.visible else 'HIDE'} ({a.rule})  vs  {'SHOW' if b.visible else 'HIDE'} ({b.rule})")
    return "\n".join(out)


def load_needs(path: str | Mapping) -> BuildNeedsSnapshot:
    import json
    from pathlib import Path
    if isinstance(path, Mapping):
        return BuildNeedsSnapshot.from_dict(dict(path))
    return BuildNeedsSnapshot.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
