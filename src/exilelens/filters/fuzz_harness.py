"""Deterministic property/fuzz harness over the generated legal corpus (FILTER-08D).

It drives the whole pipeline — BuildNeedsSnapshot -> opportunity model -> slot resolver -> rule generator -> serializer ->
validator -> native-rule simulator — with real measured builds and systematically degraded or randomised variants, and checks
INVARIANTS rather than examples. Everything is seeded: the same seed gives the same variants, items and verdicts.

Invariants (ids are stable; a failing case is minimised and persisted as a regression fixture):
  A  theme never changes visibility                      B  protected categories are never hidden
  C  every serialised Class/BaseType is verified          D  unsupported/unmeasured intelligence never adds MEASURED/UNEXPLAINED hides
  E  degraded knowledge never goes below the no-knowledge floor   F  measured relevance is only claimed with measured provenance
  G  rules only test natively observable properties       H  no rule-IR defect (dead / unreachable / protective shadowed by Hide)
  I  identical inputs give identical rules
  J  rules SHA ignores metadata (time, names)             K  every reduction vs the conservative baseline has allowed provenance
  M  widening (drift) never hides more than normal mode   P  profile chain is monotonic (see profile_contract.py; all five levels)
  N  CRAFT lane realised: a PREMIUM/RELEVANT substrate the matrix gives a visible state (crafting_intel.craft_state) is never hidden,
     whatever the build evidence says (BUILD_LOW, measured NO_RESPONSE, missing / incomplete Build Intelligence and missing market data
     never erase the CRAFT lane)
  Q  the verified optimiser invents no CRAFT_OPPORTUNITY base, keeps lane provenance, and a base that leaves the lane is still shown
  R  the theme never changes a CRAFT_OPPORTUNITY rule's bases or conditions
  S  BaseType semantics: every base list is exact (`==`), and an exact rule never matches a different catalog base whose name merely
     contains a listed name (Runeforged / Runemastered variants, `Ring` inside `Amethyst Ring`, ...)
"""
from __future__ import annotations

import hashlib
import json
import random
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Iterable, Sequence

from exilelens.filters import benchmark08b as bm
from exilelens.filters.build_needs import BuildNeedsSnapshot, NeedSignal, Relevance, SkillContext
from exilelens.filters.data_drift import DataState, DataStatus
from exilelens.filters.intel_generate import GenerationResult, filter_body_sha256, fingerprint_from_needs, generate
from exilelens.filters.legal_corpus import CorpusCase, Legality
from exilelens.filters.preview import PreviewItem, preview_decision
from exilelens.filters.profiles import FilterThemeName
from exilelens.filters.validation import VALID_CLASSES
from exilelens.filters.verified_bases import load_base_properties

PROFILES = bm.PROFILES
from exilelens.filters.currency_tiers import ALL_NAMES as _CURRENCY_NAMES  # noqa: E402
REGRESSION_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "filter08d_regressions"
OBSERVABLE = frozenset({"Class", "BaseType", "Rarity", "ItemLevel", "AreaLevel", "Quality", "Sockets", "LinkedSockets", "UnidentifiedItemTier",
                        "WaystoneTier", "GemLevel", "BaseArmour", "BaseEvasion", "BaseEnergyShield", "Corrupted", "Mirrored"})
FORBIDDEN_CLAIMS = ("has your best stat", "this item has", "contains the stat", "rolled")
CURRENT = DataStatus(DataState.CURRENT, ())
ALL_INVARIANTS = ("A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "M", "P", "N", "Q", "R", "S")


# -- variants ------------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Variant:
    name: str
    needs: BuildNeedsSnapshot
    kind: str                   # real | degraded | random | unmeasured
    parent: BuildNeedsSnapshot | None = None


def _swap(needs: BuildNeedsSnapshot, **changes) -> BuildNeedsSnapshot:
    return replace(needs, **changes)


def degrade(needs: BuildNeedsSnapshot, rng: random.Random) -> tuple[str, BuildNeedsSnapshot]:
    """Remove knowledge from a measured snapshot (never adds any)."""
    mode = rng.choice(("drop_signals", "lower_confidence", "unknown_skill", "offense_only", "no_signals"))
    signals = list(needs.signals)
    if mode == "drop_signals":
        keep = [s for s in signals if rng.random() > 0.4]
        return mode, _swap(needs, signals=tuple(keep))
    if mode == "lower_confidence":
        return mode, _swap(needs, signals=tuple(replace(s, confidence="LOW") if rng.random() < 0.6 else s for s in signals))
    if mode == "unknown_skill":
        return mode, _swap(needs, skill=SkillContext())
    if mode == "offense_only":
        return mode, _swap(needs, signals=tuple(s for s in signals if s.category == "offense"))
    return mode, _swap(needs, signals=())


def randomise(needs: BuildNeedsSnapshot, rng: random.Random) -> BuildNeedsSnapshot:
    """Valid-but-arbitrary evidence: random relevance classes and confidences (a stress of the semantic space, not a real build)."""
    out = []
    for s in needs.signals:
        relevance = rng.choice(list(Relevance)).value
        status = "MEASURED" if relevance not in ("NOT_ESTABLISHED", "NO_RESPONSE") else rng.choice(("MEASURED", "NO_SIGNAL", "REJECTED"))
        out.append(replace(s, relevance=relevance, status=status, confidence=rng.choice(("HIGH", "MEDIUM", "LOW"))))
    return _swap(needs, signals=tuple(out))


def make_variants(bases: dict[str, BuildNeedsSnapshot], seed: int, per_base: int = 2) -> list[Variant]:
    rng = random.Random(seed)
    variants: list[Variant] = []
    for label, needs in sorted(bases.items()):
        variants.append(Variant(f"{label}|real", needs, "real"))
        for index in range(per_base):
            mode, degraded = degrade(needs, rng)
            variants.append(Variant(f"{label}|degraded:{mode}:{index}", degraded, "degraded", needs))
        variants.append(Variant(f"{label}|random", randomise(needs, rng), "random"))
        variants.append(Variant(f"{label}|unmeasured", BuildNeedsSnapshot.unavailable(f"{label}:unmeasured", "fuzz: no measurement",
                                                                                         skill_id=needs.skill.skill_id, skill_name=needs.skill.name), "unmeasured"))
    variants.append(Variant("unknown-skill|unmeasured", BuildNeedsSnapshot.unavailable("unknown", "fuzz: unresolved skill"), "unmeasured"))
    return variants


# -- evaluation ----------------------------------------------------------------------------------------------------------------------
class Evaluator:
    """Caches generations and decisions so a large invariant sweep stays affordable."""

    def __init__(self, items: Sequence[PreviewItem]) -> None:
        self.items = list(items)
        self._results: dict[tuple, GenerationResult] = {}
        self._hidden: dict[tuple, tuple[bool, ...]] = {}

    @staticmethod
    def key(needs: BuildNeedsSnapshot) -> str:
        return hashlib.sha1(needs.to_json().encode("utf-8")).hexdigest()[:16]

    def result(self, needs, profile: str, *, intel: bool = True, theme: str = "Void Gold", status: DataStatus = CURRENT,
               fingerprint=None) -> GenerationResult:
        key = (self.key(needs), profile, intel, theme, status.state, id(fingerprint) if fingerprint else 0)
        if key not in self._results:
            self._results[key] = generate(needs, profile, theme, intel=intel, data_status=status, fingerprint=fingerprint)
        return self._results[key]

    def hidden(self, needs, profile: str, *, intel: bool = True, theme: str = "Void Gold", status: DataStatus = CURRENT) -> tuple[bool, ...]:
        key = (self.key(needs), profile, intel, theme, status.state)
        if key not in self._hidden:
            rules = self.result(needs, profile, intel=intel, theme=theme, status=status).rules
            self._hidden[key] = tuple(preview_decision(rules, item).hidden for item in self.items)
        return self._hidden[key]


@dataclass(frozen=True)
class Violation:
    invariant: str
    variant: str
    profile: str
    case_id: str
    detail: str


# -- invariant checks (each returns violations for one variant) --------------------------------------------------------------------------------
def check_A(ev: Evaluator, v: Variant, cases, profiles=("Recommended", "Uber Strict")) -> list[Violation]:
    themes = [t.value for t in FilterThemeName]
    out = []
    for profile in profiles:
        reference = ev.hidden(v.needs, profile, theme=themes[0])
        for theme in themes[1:]:
            other = ev.hidden(v.needs, profile, theme=theme)
            for index, (a, b) in enumerate(zip(reference, other)):
                if a != b:
                    out.append(Violation("A", v.name, profile, cases[index].id, f"{themes[0]} vs {theme}"))
    return out


def check_B(ev: Evaluator, v: Variant, cases, profiles=PROFILES) -> list[Violation]:
    """Protected kinds are never hidden, EXCEPT where the approved profile matrix says HIDE for that item's row at that level (utility
    currency and generic uniques at Uber Strict): that is documented policy, checked by the oracle, not an error."""
    from exilelens.filters.profile_oracle import matrix_hides
    out = []
    for profile in profiles:
        for case, hidden in zip(cases, ev.hidden(v.needs, profile)):
            if case.protected and hidden and not matrix_hides(case.item, profile):
                out.append(Violation("B", v.name, profile, case.id, f"protected {case.kind} hidden"))
    return out


def check_C(ev: Evaluator, v: Variant, cases, profiles=PROFILES) -> list[Violation]:
    out, bases = [], set(load_base_properties())
    for profile in profiles:
        result = ev.result(v.needs, profile)
        if not result.valid:
            out.append(Violation("C", v.name, profile, "-", "validator: " + "; ".join(result.errors[:2])))
        for match in re.finditer(r'^\s*BaseType\s+(.*)$', result.text, re.M):
            for name in re.findall(r'"([^"]+)"', match.group(1)):
                if name not in bases and name not in ("Hinekora's Lock",) and name not in _CURRENCY_NAMES \
                        and not re.search(r"(Orb|Omen)", name):
                    out.append(Violation("C", v.name, profile, "-", f"unverified BaseType {name}"))
        for match in re.finditer(r'^\s*Class\s+(.*)$', result.text, re.M):
            for name in re.findall(r'"([^"]+)"', match.group(1)):
                if name not in VALID_CLASSES:
                    out.append(Violation("C", v.name, profile, "-", f"unverified Class {name}"))
    return out


def check_D(ev: Evaluator, v: Variant, cases, profiles=PROFILES) -> list[Violation]:
    if v.kind != "unmeasured":
        return []
    out = []
    for profile in profiles:
        result = ev.result(v.needs, profile)
        new = ev.hidden(v.needs, profile)
        old = ev.hidden(v.needs, profile, intel=False)
        for index, (a, b) in enumerate(zip(old, new)):
            if not a and b:
                why = bm.reduction_justification(ev.items[index], v.needs, result, matched_rule=preview_decision(result.rules, ev.items[index]).rule_name)
                if why in (bm.MEASURED_BUILD_EVIDENCE, bm.UNEXPLAINED):
                    out.append(Violation("D", v.name, profile, cases[index].id, f"unsupported intelligence hid an item: {why}"))
    return out


def check_E(ev: Evaluator, v: Variant, cases, profiles=PROFILES) -> list[Violation]:
    """Degraded knowledge never hides more than the unmeasured conservative baseline for the same (possibly unknown) skill.

    Evidence may ADD visibility (promotions, unlock gates) above that baseline, so losing evidence can legitimately remove those
    additions; what it must never do is take the filter below the no-knowledge floor."""
    if v.kind != "degraded":
        return []
    skill = v.needs.skill
    floor = BuildNeedsSnapshot.unavailable("floor", "fuzz: no-knowledge baseline", skill_id=skill.skill_id, skill_name=skill.name,
                                           equipped=dict(v.needs.equipped))       # same observed gear, no measurement (as the dashboard builds it)
    out = []
    for profile in profiles:
        baseline, child = ev.hidden(floor, profile), ev.hidden(v.needs, profile)
        for index, (b, c) in enumerate(zip(baseline, child)):
            if c and not b:
                out.append(Violation("E", v.name, profile, cases[index].id, "degraded knowledge hid an item the no-knowledge baseline shows"))
    return out


def check_F(ev: Evaluator, v: Variant, cases, profiles=PROFILES) -> list[Violation]:
    out = []
    for profile in profiles:
        for rule in ev.result(v.needs, profile).rules:
            evidence = rule.evidence
            if evidence is None or not evidence.coverage:
                continue
            claims_measured = evidence.coverage.startswith(("MEASURED", "PARTIAL")) and any(d.shift != 0 for d in rule.decisions)
            if claims_measured:
                if not v.needs.has_measurement:
                    out.append(Violation("F", v.name, profile, rule.name, "measured relevance claimed without any measurement"))
                    continue
                for decision in rule.decisions:
                    for hit in decision.hits:
                        signal = v.needs.signal(hit.probe_id)
                        if decision.shift != 0 and signal is None:
                            out.append(Violation("F", v.name, profile, rule.name, f"{hit.family}: no signal behind the claim"))
            if "(measured)" in evidence.build_relevance and not v.needs.has_measurement:
                out.append(Violation("F", v.name, profile, rule.name, "text says measured without a measurement"))
    return out


def check_G(ev: Evaluator, v: Variant, cases, profiles=PROFILES) -> list[Violation]:
    out = []
    for profile in profiles:
        for rule in ev.result(v.needs, profile).rules:
            for line in rule.lines:
                keyword = line.strip().split(" ", 1)[0]
                if keyword in ("Show", "Hide") or keyword.startswith(("Set", "Play", "Minimap", "Continue", "Disable", "Enable", "Custom")):
                    continue
                if keyword not in OBSERVABLE:
                    out.append(Violation("G", v.name, profile, rule.name, f"condition {keyword} is not natively observable here"))
            if rule.evidence:
                text = " ".join([rule.evidence.build_relevance, rule.evidence.item_potential, *rule.evidence.details]).lower()
                for phrase in FORBIDDEN_CLAIMS:
                    if phrase in text:
                        out.append(Violation("G", v.name, profile, rule.name, f"explanation claims an unobservable property: '{phrase}'"))
    return out


def check_I(ev: Evaluator, v: Variant, cases, profiles=("Recommended", "Strict")) -> list[Violation]:
    out = []
    for profile in profiles:
        first = ev.result(v.needs, profile).text
        second = generate(v.needs, profile, data_status=CURRENT).text
        if first != second:
            out.append(Violation("I", v.name, profile, "-", "two generations of identical inputs differ"))
    return out


def check_J(ev: Evaluator, v: Variant, cases, profiles=("Recommended", "Uber Strict")) -> list[Violation]:
    out = []
    for profile in profiles:
        reference = filter_body_sha256(ev.result(v.needs, profile).text)
        fp = fingerprint_from_needs(v.needs, class_name="Elsewhere", ascendancy="Other")
        fp = replace(fp, build_name="renamed", generated_at=fp.generated_at.replace(year=2031))
        other = filter_body_sha256(generate(v.needs, profile, data_status=CURRENT, fingerprint=fp).text)
        if other != reference:
            out.append(Violation("J", v.name, profile, "-", "rules SHA depends on metadata"))
    return out


def check_K(ev: Evaluator, v: Variant, cases, profiles=PROFILES) -> list[Violation]:
    out = []
    for profile in profiles:
        result = ev.result(v.needs, profile)
        new, old = ev.hidden(v.needs, profile), ev.hidden(v.needs, profile, intel=False)
        for index, (a, b) in enumerate(zip(old, new)):
            if not a and b:
                rule = preview_decision(result.rules, ev.items[index]).rule_name
                why = bm.reduction_justification(ev.items[index], v.needs, result, matched_rule=rule)
                if why == bm.UNEXPLAINED:
                    out.append(Violation("K", v.name, profile, cases[index].id, f"reduction vs legacy without allowed provenance (rule {rule})"))
    return out


def check_M(ev: Evaluator, v: Variant, cases, profiles=("Recommended", "Strict")) -> list[Violation]:
    out = []
    stale = DataStatus(DataState.STALE_SNAPSHOT, ("fuzz",))
    for profile in profiles:
        normal, widened = ev.hidden(v.needs, profile), ev.hidden(v.needs, profile, status=stale)
        for index, (n, w) in enumerate(zip(normal, widened)):
            if w and not n:
                out.append(Violation("M", v.name, profile, cases[index].id, "widened (drift) mode hid an item normal mode shows"))
    return out


def check_H(ev: Evaluator, v: Variant, cases, profiles=PROFILES) -> list[Violation]:
    """No rule-IR defect: nothing dead/contradictory/unreachable, protective rules reachable and never shadowed by a Hide."""
    from exilelens.filters import rule_ir
    out = []
    for profile in profiles:
        report = rule_ir.analyse(ev.result(v.needs, profile).rules)
        for finding in report.defects():
            out.append(Violation("H", v.name, profile, finding.rule, f"{finding.kind}: {finding.detail}"))
    return out


def check_P(ev: Evaluator, v: Variant, cases, profiles=None) -> list[Violation]:
    """Profile chain on the concrete corpus: a stricter profile never shows what a looser one hides (see profile_contract)."""
    from exilelens.filters.profile_contract import CHAIN
    out = []
    for looser, stricter in zip(CHAIN, CHAIN[1:]):
        a, b = ev.hidden(v.needs, looser), ev.hidden(v.needs, stricter)
        for index, (hidden_loose, hidden_strict) in enumerate(zip(a, b)):
            if hidden_loose and not hidden_strict:
                out.append(Violation("P", v.name, f"{looser}->{stricter}", cases[index].id, "stricter profile shows an item the looser one hides"))
    return out


def check_N(ev: Evaluator, v: Variant, cases, profiles=PROFILES) -> list[Violation]:
    from exilelens.filters import crafting_intel as ci
    out = []
    for profile in profiles:
        hidden = ev.hidden(v.needs, profile)
        for index, case in enumerate(cases):
            item = case.item
            if item.rarity not in ("Normal", "Magic") or item.corrupted or item.mirrored or not item.base_type:
                continue
            assessment = ci.assess(item.base_type)
            if assessment.level not in (ci.CraftLevel.PREMIUM, ci.CraftLevel.RELEVANT):
                continue
            state = ci.craft_state(assessment, item.rarity, item.item_level, profile, campaign=item.area_level <= 64)
            if state is not None and state != "HIDE" and hidden[index]:
                out.append(Violation("N", v.name, profile, case.id,
                                     f"{assessment.level.value} substrate {item.base_type} {item.rarity} i{item.item_level} hidden "
                                     f"(the matrix gives it {state})"))
    return out


def check_Q(ev: Evaluator, v: Variant, cases, profiles=("Recommended", "Strict")) -> list[Violation]:
    from exilelens.filters import rule_ir
    out = []
    for profile in profiles:
        rules = ev.result(v.needs, profile).rules
        optimised, _ = rule_ir.optimise(rules)
        before = {b for r in rules if r.category == "CRAFT_OPPORTUNITY" for b in r.base_types}
        after = {b for r in optimised if r.category == "CRAFT_OPPORTUNITY" for b in r.base_types}
        if after - before:
            out.append(Violation("Q", v.name, profile, "-", f"optimiser invented CRAFT lane bases: {sorted(after - before)[:3]}"))
        if any(not r.class_reasons for r in optimised if r.category == "CRAFT_OPPORTUNITY"):
            out.append(Violation("Q", v.name, profile, "-", "optimiser dropped CRAFT lane provenance"))
        # a base may leave the lane only because an earlier rule already shows it: the decision must be unchanged
        from exilelens.filters import crafting_intel as ci
        from exilelens.filters.inspector import make_item
        for base in sorted(before - after)[:40]:
            gate = ci.breakpoint_gate(ci.assess(base))
            if gate is None:
                continue
            for rarity in ("Normal", "Magic", "Rare"):
                item = make_item(base, rarity=rarity, item_level=max(gate, 82))
                if preview_decision(optimised, item).hidden != preview_decision(rules, item).hidden:
                    out.append(Violation("Q", v.name, profile, base, f"optimiser changed the decision for {base} {rarity}"))
    return out


def check_R(ev: Evaluator, v: Variant, cases, profiles=("Recommended", "Uber Strict")) -> list[Violation]:
    themes = [t.value for t in FilterThemeName]
    out = []

    def signature(result):
        return sorted((r.name, tuple(r.base_types), tuple(line.strip() for line in r.lines
                                                           if not line.strip().startswith(("Set", "Play", "MinimapIcon", "DisableDropSound"))))
                      for r in result.rules if r.category == "CRAFT_OPPORTUNITY")

    for profile in profiles:
        reference = signature(ev.result(v.needs, profile, theme=themes[0]))
        for theme in themes[1:]:
            if signature(ev.result(v.needs, profile, theme=theme)) != reference:
                out.append(Violation("R", v.name, profile, "-", f"CRAFT lane rules differ between {themes[0]} and {theme}"))
    return out


def check_S(ev: Evaluator, v: Variant, cases, profiles=("Recommended", "Uber Strict", "Relaxed")) -> list[Violation]:
    from exilelens.filters.base_collisions import collisions
    from exilelens.filters.base_match import BaseCondition, BaseMatch
    from exilelens.filters.preview import _matches_condition
    out = []
    outers: dict[str, list[str]] = defaultdict(list)
    for pair in collisions():
        outers[pair.inner.casefold()].append(pair.outer)
    for profile in profiles:
        for rule in ev.result(v.needs, profile).rules:
            marked = any(l.strip() == "# PARTIAL_BASE_PATTERN" for l in rule.lines)
            for line in rule.lines:
                condition = BaseCondition.parse(line.strip())
                if condition is None:
                    continue
                if condition.match != BaseMatch.EXACT_BASE:
                    if not marked:
                        out.append(Violation("S", v.name, profile, rule.name, "partial BaseType list without an explicit marker"))
                    continue
                listed = {n.casefold() for n in condition.names}
                for name in listed:
                    for outer in outers.get(name, ()):
                        if outer.casefold() not in listed and _matches_condition(line.strip(), PreviewItem(outer, "", "", outer)):
                            out.append(Violation("S", v.name, profile, rule.name, f"exact rule listing {name!r} matches {outer!r}"))
    return out


CHECKS: dict[str, Callable] = {"A": check_A, "B": check_B, "C": check_C, "D": check_D, "E": check_E, "F": check_F, "G": check_G,
                               "H": check_H, "I": check_I, "J": check_J, "K": check_K, "M": check_M, "P": check_P,
                               "N": check_N, "Q": check_Q, "R": check_R, "S": check_S}


# -- runner / minimiser ---------------------------------------------------------------------------------------------------------------------
@dataclass
class FuzzReport:
    seed: int
    variants: int
    items: int
    profiles: int
    generations: int
    decisions: int
    invariants: dict[str, int] = field(default_factory=dict)      # invariant -> number of checks performed
    violations: list[Violation] = field(default_factory=list)

    def summary(self) -> dict:
        by = Counter(v.invariant for v in self.violations)
        return {"seed": self.seed, "variants": self.variants, "items": self.items, "profiles": self.profiles, "generations": self.generations,
                "decisions": self.decisions, "violations": dict(sorted(by.items())), "invariants_checked": sorted(self.invariants)}


def run(bases: dict[str, BuildNeedsSnapshot], corpus: Sequence[CorpusCase], *, seed: int = 1, per_base: int = 2,
        invariants: Iterable[str] = ALL_INVARIANTS, variant_limit: int | None = None,
        sweep_items: int = 1500) -> tuple[FuzzReport, Evaluator, list[Variant]]:
    cases = list(corpus)
    ev = Evaluator([c.item for c in cases])
    variants = make_variants(bases, seed, per_base)
    if variant_limit:
        variants = random.Random(seed).sample(variants, min(variant_limit, len(variants)))
    report = FuzzReport(seed, len(variants), len(cases), len(PROFILES), 0, 0)
    wanted = list(invariants)
    theme_cases = cases[:sweep_items]
    theme_ev = Evaluator([c.item for c in theme_cases])
    for variant in variants:
        for inv in wanted:
            if inv == "A":
                found = check_A(theme_ev, variant, theme_cases)
            else:
                found = CHECKS[inv](ev, variant, cases)
            report.invariants[inv] = report.invariants.get(inv, 0) + 1
            report.violations.extend(found)
    report.generations = len(ev._results) + len(theme_ev._results)
    report.decisions = len(ev._hidden) * len(cases) + len(theme_ev._hidden) * len(theme_cases)
    return report, ev, variants


def _single(case: CorpusCase) -> list[CorpusCase]:
    return [case]


def violates(variant: Variant, violation: Violation, case: CorpusCase) -> bool:
    ev = Evaluator([case.item])
    found = CHECKS[violation.invariant](ev, variant, [case], profiles=(violation.profile,))
    return any(f.invariant == violation.invariant for f in found)


def minimise(variant: Variant, violation: Violation, case: CorpusCase) -> tuple[Variant, CorpusCase]:
    """Shrink a failing (needs, item) pair: drop signals one by one, then simplify the item, while the violation persists."""
    current = variant
    changed = True
    while changed:
        changed = False
        for signal in list(current.needs.signals):
            trial_needs = replace(current.needs, signals=tuple(s for s in current.needs.signals if s is not signal))
            trial = Variant(current.name, trial_needs, current.kind, current.parent)
            if violates(trial, violation, case):
                current, changed = trial, True
                break
    item = case.item
    for field_name, simple in (("quality", 0), ("unidentified_item_tier", 0), ("item_level", 82), ("rarity", "Magic")):
        trial_item = replace(item, **{field_name: simple})
        trial_case = replace(case, item=trial_item)
        if getattr(item, field_name) != simple and violates(current, violation, trial_case):
            item, case = trial_item, trial_case
    return current, case


def persist(variant: Variant, violation: Violation, case: CorpusCase, directory: Path = REGRESSION_DIR) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    item = case.item
    payload = {"invariant": violation.invariant, "profile": violation.profile, "detail": violation.detail, "variant_kind": variant.kind,
               "needs": variant.needs.to_dict(), "parent_needs": variant.parent.to_dict() if variant.parent else None,
               "item": {k: getattr(item, k) for k in ("name", "category", "item_class", "base_type", "rarity", "item_level", "quality",
                                                      "unidentified_item_tier", "waystone_tier", "base_energy_shield", "base_armour", "base_evasion")},
               "case_id": case.id, "protected": case.protected, "legality": case.legality.value}
    digest = hashlib.sha1(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:10]
    path = directory / f"{violation.invariant}_{digest}.json"
    path.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_regression(path: Path) -> tuple[Variant, Violation, CorpusCase]:
    data = json.loads(path.read_text(encoding="utf-8"))
    needs = BuildNeedsSnapshot.from_dict(data["needs"])
    parent = BuildNeedsSnapshot.from_dict(data["parent_needs"]) if data.get("parent_needs") else None
    item = PreviewItem(**data["item"])
    case = CorpusCase(data["case_id"], item, Legality(data["legality"]), "regression fixture", "equipment", data["protected"])
    return Variant(path.stem, needs, data["variant_kind"], parent), Violation(data["invariant"], path.stem, data["profile"], data["case_id"], data["detail"]), case
