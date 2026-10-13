"""Conservative failure injection (FILTER-08D).

Each scenario breaks one input of the Build Intelligence pipeline and then checks the contract for failures:

  1. no crash — unless the scenario MUST block (incompatible data), where the error must be explicit (DataIncompatible);
  2. the filter is never narrower than its reference — a lost input must widen, never hide:
       floor     the no-knowledge filter for the same skill (knowledge about the build was lost);
       baseline  the unfailed filter (an input failed but the measurement stayed complete and every decision still has its evidence);
       either    an item may be hidden only if the unfailed filter OR the no-knowledge filter hides it (a lookup that PROMOTES bases failed:
                 the result may fall back to the floor, but it must not invent a hide that neither knowledge level would make);
  3. protected item kinds stay visible;
  4. the degradation is visible: ``degraded_notes`` / ``describe`` carry a non-empty, user-facing explanation where the dashboard has
     a place to show it.

``run_all`` returns one ``InjectionResult`` per scenario; the report records what was actually observed, not what is expected.
"""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass, replace
from typing import Callable, Sequence
from unittest import mock

from exilelens.filters import intel_status
from exilelens.filters.build_needs import BuildNeedsSnapshot, SkillContext
from exilelens.filters.data_drift import DataIncompatible, DataState, DataStatus
from exilelens.filters.intel_generate import fingerprint_from_needs, generate
from exilelens.filters.legal_corpus import CorpusCase
from exilelens.filters.preview import PreviewItem, preview_decision

PROFILES_CHECKED = ("Recommended", "Strict")


@dataclass
class InjectionResult:
    scenario: str
    description: str
    crashed: bool
    blocked_explicitly: bool
    narrower_than_reference: int      # items hidden that the reference shows (must be 0); see ``reference``
    reference: str                    # "floor" | "baseline" | "either" (see module docstring)
    protected_hidden: int             # protected items hidden (must be 0)
    visible_notice: str               # what the user is told
    changed_items: int                # items whose visibility differs from the unfailed baseline
    notes: str = ""

    @property
    def passed(self) -> bool:
        if self.crashed:
            return False
        if self.blocked_explicitly:
            return bool(self.visible_notice)
        return self.narrower_than_reference == 0 and self.protected_hidden == 0

    def to_dict(self) -> dict[str, object]:
        return {**self.__dict__, "passed": self.passed}


def _hidden(needs: BuildNeedsSnapshot, profile: str, items: Sequence[PreviewItem], *, status: DataStatus | None = None,
            fingerprint=None) -> list[bool]:
    result = generate(needs, profile, intel=True, data_status=status or DataStatus(DataState.CURRENT, ()), fingerprint=fingerprint)
    return [preview_decision(result.rules, item).hidden for item in items]


def _floor(needs: BuildNeedsSnapshot) -> BuildNeedsSnapshot:
    """No measurement, but the SAME skill knowledge as the failed input (a lost weapon requirement is lost for the floor too)."""
    return replace(BuildNeedsSnapshot.unavailable("floor", "failure injection floor", skill_id=needs.skill.skill_id, skill_name=needs.skill.name,
                                                  equipped=dict(needs.equipped)),
                   skill=needs.skill)


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    prepare: Callable[[BuildNeedsSnapshot], BuildNeedsSnapshot]
    patches: tuple[tuple[str, object], ...] = ()
    status: DataStatus | None = None
    reference: str = "floor"
    # Items the scenario made UNVERIFIABLE (their base is gone from the data). They may only be hidden by class-level rules justified
    # by verified incompatibility, never by a base rule, so they are counted separately instead of in the narrowing check.
    unverifiable: Callable[[PreviewItem], bool] | None = None
    notice: Callable[[BuildNeedsSnapshot, DataStatus | None], str] = lambda needs, status: ""


def _notes(needs, status):
    return "; ".join(intel_status.degraded_notes(needs, status))


def _no_weapon_requirement(needs: BuildNeedsSnapshot) -> BuildNeedsSnapshot:
    return replace(needs, skill=replace(needs.skill, weapon_classes=None, verified=False))


def _unsupported_skill(needs: BuildNeedsSnapshot) -> BuildNeedsSnapshot:
    return replace(needs, skill=SkillContext(name="Skill That Does Not Exist", skill_id="Nonexistent", mode="UNKNOWN", mode_basis="unsupported"))


def _unknown_mode(needs: BuildNeedsSnapshot) -> BuildNeedsSnapshot:
    return replace(needs, skill=replace(needs.skill, mode="UNKNOWN", weapon_classes=None, elements=(), types=(), verified=False))


def _partial_calc(needs: BuildNeedsSnapshot) -> BuildNeedsSnapshot:
    return replace(needs, signals=needs.signals[: max(1, len(needs.signals) // 2)])


def _low_confidence(needs: BuildNeedsSnapshot) -> BuildNeedsSnapshot:
    return replace(needs, signals=tuple(replace(s, confidence="LOW") for s in needs.signals))


class _Call:
    """Marks a patch value that must be computed when the scenario runs and used as the replacement's return/side effect."""
    def __init__(self, factory: Callable) -> None:
        self.factory = factory


def _dropped() -> set[str]:
    from exilelens.filters.verified_bases import load_base_properties
    return {base for index, base in enumerate(sorted(load_base_properties())) if index % 3 == 0}


def _without_third() -> Callable:
    from exilelens.filters.verified_bases import load_base_properties
    gone = _dropped()
    trimmed = {base: record for base, record in load_base_properties().items() if base not in gone}
    return lambda: trimmed


def _native_without_third() -> Callable:
    from exilelens.filters.verified_bases import native_class
    gone = _dropped()
    return lambda base: None if base in gone else native_class(base)


SCENARIOS: tuple[Scenario, ...] = (
    Scenario("missing_bi", "No Build Intelligence for the build", lambda n: BuildNeedsSnapshot.unavailable(n.label, "no BI", skill_name=n.skill.name),
             notice=lambda n, s: intel_status.describe(None, state=intel_status.IntelState.NOT_ANALYZED).headline),
    Scenario("stale_analysis", "The build changed after the analysis", lambda n: BuildNeedsSnapshot.unavailable(n.label, "build changed", skill_name=n.skill.name),
             notice=lambda n, s: intel_status.describe(None, state=intel_status.IntelState.STALE).headline),
    Scenario("failed_analysis", "The analysis raised an error", lambda n: BuildNeedsSnapshot.unavailable(n.label, "analysis failed", skill_name=n.skill.name),
             notice=lambda n, s: intel_status.describe(None, state=intel_status.IntelState.FAILED, error="PoB timeout").headline),
    Scenario("incomplete_fingerprint", "The observed-gear fingerprint is empty", lambda n: replace(n, equipped={}),
             notice=lambda n, s: "", reference="either"),
    Scenario("unknown_skill", "The main skill is not in the skill data", _unsupported_skill, notice=lambda n, s: _skill_notice(n)),
    Scenario("unresolved_skill_mode", "The skill mode could not be resolved", _unknown_mode, notice=lambda n, s: _skill_notice(n)),
    Scenario("missing_family_mapping", "No modifier family is mapped for any base", lambda n: n,
             patches=(("exilelens.filters.affix_pools.pools_for", {}), ("exilelens.filters.affix_pools.implicit_families", ()),
                      ("exilelens.filters.affix_pools.universal_families", frozenset())), notice=lambda n, s: "", reference="either"),
    Scenario("missing_base_metadata", "Base metadata is missing for every third verified base", lambda n: n,
             patches=(("exilelens.filters.opportunity.load_base_properties", _Call(_without_third)),
                      ("exilelens.filters.opportunity.native_class", _Call(_native_without_third))),
             notice=lambda n, s: "", reference="either", unverifiable=lambda item: item.base_type in _dropped()),
    Scenario("stale_snapshot", "The data snapshot is older than the game", lambda n: n,
             status=DataStatus(DataState.STALE_SNAPSHOT, ("injected",)), notice=_notes),
    Scenario("unverified_newer_game", "The installed game is newer than the verified data", lambda n: n,
             status=DataStatus(DataState.UNVERIFIED_NEWER_GAME, ("injected",)), notice=_notes),
    Scenario("unknown_data_state", "The data state could not be determined", lambda n: n,
             status=DataStatus(DataState.UNKNOWN, ("injected",)), notice=_notes),
    Scenario("incompatible_data", "The data schema is incompatible with the generator", lambda n: n,
             status=DataStatus(DataState.INCOMPATIBLE_DATA, ("injected",)), notice=_notes),
    Scenario("partial_pob_calc", "Only half of the probes returned", _partial_calc, notice=lambda n, s: _notes(n, s)),
    Scenario("low_confidence_measurement", "Every measured signal has LOW confidence", _low_confidence, notice=lambda n, s: _notes(n, s)),
    Scenario("unknown_weapon_requirement", "The skill's weapon requirement is not known", _no_weapon_requirement, notice=lambda n, s: "",
             reference="either"),   # falls back to the legacy curated skill map, exactly what the same skill gets without any measurement
    Scenario("market_unavailable", "No market data is available", lambda n: n, notice=lambda n, s: "Market: HEURISTIC (no live price used)",
             reference="baseline"),
)


def _skill_notice(needs: BuildNeedsSnapshot) -> str:
    return intel_status.describe(needs, state=intel_status.IntelState.CURRENT).text if needs.has_measurement else ""


def run_scenario(scenario: Scenario, needs: BuildNeedsSnapshot, cases: Sequence[CorpusCase]) -> InjectionResult:
    items = [c.item for c in cases]
    protected = [i for i, c in enumerate(cases) if c.protected]
    failed = scenario.prepare(needs)
    status = scenario.status or DataStatus(DataState.CURRENT, ())
    floor = _floor(failed if failed.skill.name else needs)
    crashed = blocked = False
    narrower = protected_hidden = changed = unverifiable_hidden = 0
    degraded_text = ""
    note = ""
    try:
        with ExitStack() as stack:
            baseline = {p: _hidden(needs, p, items) for p in PROFILES_CHECKED}
            for target, value in scenario.patches:
                if isinstance(value, _Call):
                    stack.enter_context(mock.patch(target, side_effect=value.factory()))
                else:
                    stack.enter_context(mock.patch(target, return_value=value))
            fp = fingerprint_from_needs(failed) if scenario.name == "incomplete_fingerprint" else None
            if fp is not None:
                fp = replace(fp, equipped={}, main_skill="Unknown", main_skill_gem="Unknown")
            try:
                shown = generate(failed, "Recommended", intel=True, data_status=status, fingerprint=fp).degradations
                if shown:
                    from exilelens.filters import degradation
                    degraded_text = "; ".join([degradation.COMPACT, *degradation.lines(shown)])
            except DataIncompatible:
                pass
            for profile in PROFILES_CHECKED:
                try:
                    got = _hidden(failed, profile, items, status=status, fingerprint=fp)
                except DataIncompatible as exc:
                    blocked, note = True, str(exc)
                    break
                if scenario.reference == "baseline":
                    reference = baseline[profile]
                elif scenario.reference == "either":
                    low = _hidden(floor, profile, items)
                    reference = [a or b for a, b in zip(baseline[profile], low)]
                else:
                    reference = _hidden(floor, profile, items)
                exempt = [bool(scenario.unverifiable and scenario.unverifiable(item)) for item in items]
                narrower += sum(1 for g, f, e in zip(got, reference, exempt) if g and not f and not e)
                unverifiable_hidden += sum(1 for g, f, e in zip(got, reference, exempt) if g and not f and e)
                protected_hidden += sum(1 for i in protected if got[i])
                changed += sum(1 for g, b in zip(got, baseline[profile]) if g != b)
    except Exception as exc:                       # noqa: BLE001 - recorded, not hidden
        crashed, note = True, f"{type(exc).__name__}: {exc}"
    if unverifiable_hidden:
        note = (note + "; " if note else "") + f"{unverifiable_hidden} item(s) of bases missing from the data hidden by class-level rules"
    notice = scenario.notice(failed, status) or (note if blocked else "")
    if not notice and not blocked and not crashed:
        notice = degraded_text

    if blocked and not notice:
        notice = note
    return InjectionResult(scenario.name, scenario.description, crashed, blocked, narrower, scenario.reference, protected_hidden, notice,
                           changed, note)


def run_all(needs: BuildNeedsSnapshot, cases: Sequence[CorpusCase]) -> list[InjectionResult]:
    return [run_scenario(s, needs, cases) for s in SCENARIOS]
