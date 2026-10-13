"""Filter-oriented snapshot of PRODUCTION Build Intelligence (FILTER-08B adapter).

The snapshot is a narrow, read-only projection of ``analyze_build()`` results (Build Fingerprint,
controlled sensitivity profile, Build Priorities). Nothing is re-measured here: no probe is run, no
PoB call is made, and no unit-normalised score is invented. A tested ``+1 Spell Skill Level`` and a
``+50 Energy Shield`` stay different interventions; each signal keeps its tested increment, native
axes, confidence and limits. ``relevance`` is only a coarse CLASS used by the generator's decision
table; it is never an economic value.

The snapshot is JSON-serialisable so filter generation and benchmarks run offline (no PoB, no
network) from a stored measurement, and every decision can cite the measurement it came from.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Mapping

from exilelens.filters import skill_facts

SCHEMA_VERSION = 1

# Thresholds mirror production Build Priorities (analysis/priorities.py) so the classes agree with the
# player-facing Build Priorities screen. Kept literal (not imported) so a production tweak is a visible diff here.
MEANINGFUL_PERCENT = 1.0
RESPONSE_EPSILON = 0.05

_LANES = ("offense", "ehp", "max_hit", "mobility")
_AXIS_KEYS = ("offense", "ehp", "max_hit", "life", "energy_shield", "mana", "armour", "evasion", "movement", "speed")
_RESISTANCE_PROBES = {"fire": "FIRE_RES", "cold": "COLD_RES", "lightning": "LIGHTNING_RES", "chaos": "CHAOS_RES"}
_ATTRIBUTE_PROBES = {"strength": "STRENGTH", "dexterity": "DEXTERITY", "intelligence": "INTELLIGENCE"}
_FAMILY_CATEGORY = {"offense": "offense", "defense": "defense", "resistance": "resistance", "utility": "utility"}
_MAINTENANCE_PROBES = frozenset({*_RESISTANCE_PROBES.values(), *_ATTRIBUTE_PROBES.values()})


class Relevance(str, Enum):
    """Coarse relevance CLASS of one tested stat for this build (ordered only for the decision table)."""
    FIX_FIRST = "FIX_FIRST"            # a hard deficit: resistance cap, attribute requirement, unpayable resource
    STRONG = "STRONG"                  # in a production Build Priorities lane / multi-impact row
    RESPONSIVE = "RESPONSIVE"          # measured response >= 1% on a native axis
    MARGINAL = "MARGINAL"              # measured but small, or a maintenance stat that is currently satisfied
    NO_RESPONSE = "NO_RESPONSE"        # probe applied; PoB reported no response on any tested axis
    NOT_ESTABLISHED = "NOT_ESTABLISHED"  # rejected / unsupported / not run: never evidence of irrelevance

    @property
    def rank(self) -> int:
        return {"FIX_FIRST": 5, "STRONG": 4, "RESPONSIVE": 3, "MARGINAL": 2, "NOT_ESTABLISHED": 1, "NO_RESPONSE": 0}[self.value]


class Coverage(str, Enum):
    """How much of a filter decision can honestly be called personalised."""
    MEASURED = "MEASURED PERSONALIZATION"
    PARTIAL = "PARTIAL PERSONALIZATION"
    FALLBACK = "CONSERVATIVE FALLBACK"
    UNSUPPORTED = "UNSUPPORTED / UNKNOWN"


@dataclass(frozen=True)
class NeedSignal:
    probe_id: str
    label: str
    category: str                      # offense | defense | resistance | utility (catalog family of the INTERVENTION)
    status: str                        # MEASURED | NO_SIGNAL | REJECTED | UNSUPPORTED | ...
    tested_change: str                 # the exact increment that was applied, e.g. "+1 to Level of all Spell Skills"
    responses: Mapping[str, float]     # native axis -> percent at that increment (never mixed across probes)
    confidence: str                    # per-evidence confidence reported by production
    relevance: str                     # Relevance value
    lanes: tuple[str, ...] = ()        # production Build Priorities lanes it appears in
    fix_first: Mapping[str, Any] | None = None
    note: str = ""

    @property
    def relevance_class(self) -> Relevance:
        return Relevance(self.relevance)

    def basis(self) -> str:
        """One factual sentence: what was tested and what PoB reported."""
        if self.status != "MEASURED":
            return (f"Tested {self.tested_change or self.label}: "
                    + ("no measured response" if self.status == "NO_SIGNAL" else "not established")
                    + (f" ({self.note})" if self.note else ""))
        shown = ", ".join(f"{axis} {value:+.1f}%" for axis, value in self.responses.items()
                          if axis in ("offense", "ehp", "max_hit", "movement", "life", "energy_shield", "armour", "evasion", "mana")
                          and abs(value) > RESPONSE_EPSILON)
        return f"Tested {self.tested_change}: {shown or 'no change'} ({self.confidence.title()} confidence)"


@dataclass(frozen=True)
class SkillContext:
    name: str = ""
    skill_id: str = ""
    owner: str = ""                    # PLAYER | MINION (production offense owner)
    mode: str = "UNKNOWN"              # SPELL | ATTACK | MINION | UNKNOWN
    mode_basis: str = "skill not resolved"
    elements: tuple[str, ...] = ()
    types: tuple[str, ...] = ()
    weapon_classes: tuple[str, ...] | None = None   # verified weapon requirement, None = unrestricted/unknown
    verified: bool = False


@dataclass(frozen=True)
class BuildNeedsSnapshot:
    schema_version: int
    label: str
    identity: Mapping[str, Any]
    skill: SkillContext
    offense: Mapping[str, Any]
    signals: tuple[NeedSignal, ...]
    fix_first: tuple[Mapping[str, Any], ...]
    resource_context: Mapping[str, Any]
    equipped: Mapping[str, str]                    # slot -> base type (observed gear)
    observed_defence: Mapping[str, float]          # armour / evasion / energy_shield from the fingerprint
    coverage: Coverage
    coverage_reasons: tuple[str, ...]
    dimension_coverage: Mapping[str, str]
    limitations: tuple[str, ...] = ()
    # Production per-slot "strip explicit modifiers" contribution (offense / EHP percent LOST if the slot's modifiers are
    # removed). Explanation data only: a slot's contribution is not an upgrade priority and never changes a decision.
    slot_contributions: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    measured_at: str = ""   # UTC ISO time the analysis finished (set by the caller; empty for stored benchmark replays)
    signals_by_probe: Mapping[str, NeedSignal] = field(default_factory=dict, compare=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "signals_by_probe", {s.probe_id: s for s in self.signals})

    # -- lookup helpers -------------------------------------------------------------------------
    def signal(self, probe_id: str) -> NeedSignal | None:
        return self.signals_by_probe.get(probe_id)

    def relevance(self, probe_id: str) -> Relevance:
        signal = self.signal(probe_id)
        return signal.relevance_class if signal else Relevance.NOT_ESTABLISHED

    @property
    def evidence_complete(self) -> bool:
        """True only when production tested the standard probe set for this build with adequate confidence.

        Narrowing based on measured evidence (demotions, evidence-gated top bands, measured layer hides, evidence-derived weapon
        classes) is allowed ONLY on complete evidence. Anything less is degraded knowledge, and a loss of knowledge must widen."""
        if not self.has_measurement:
            return False
        tested = {s.probe_id for s in self.signals if s.status in ("MEASURED", "NO_SIGNAL")}
        if not set(required_probes()) <= tested:
            return False
        if self.offense_limited_confidence or any(s.status == "MEASURED" and s.confidence == "LOW" for s in self.signals):
            return False
        lanes = {lane for s in self.signals for lane in s.lanes}
        state, _reasons, _dims = _coverage(self.signals, self.skill, False, "offense" in lanes, bool({"ehp", "max_hit"} & lanes))
        return state == Coverage.MEASURED

    @property
    def offense_limited_confidence(self) -> bool:
        return bool(self.offense.get("limited_confidence"))

    @property
    def has_measurement(self) -> bool:
        return any(s.status == "MEASURED" for s in self.signals)

    # -- serialisation --------------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("signals_by_probe", None)
        data["coverage"] = self.coverage.value
        return data

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=1, sort_keys=True, default=list)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BuildNeedsSnapshot":
        if data.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"Unsupported needs snapshot schema: {data.get('schema_version')}")
        skill = dict(data["skill"])
        if skill.get("weapon_classes") is not None:
            skill["weapon_classes"] = tuple(skill["weapon_classes"])
        skill["elements"] = tuple(skill.get("elements") or ())
        skill["types"] = tuple(skill.get("types") or ())
        signals = _normalise_lanes(tuple(
            NeedSignal(**{**s, "lanes": tuple(s.get("lanes") or ())}) for s in data["signals"]
        ))
        context = SkillContext(**skill)
        stored = Coverage(data["coverage"])
        if any(s.status == "MEASURED" for s in signals):
            # Coverage is derived data: re-derive it from the stored signals so it always follows the current rules.
            lanes = {lane for s in signals for lane in s.lanes}
            stored, reasons, dimensions = _coverage(signals, context, bool(data["offense"].get("limited_confidence")),
                                                    "offense" in lanes, bool({"ehp", "max_hit"} & lanes))
            data = {**data, "coverage_reasons": reasons, "dimension_coverage": dimensions}
        return cls(
            schema_version=SCHEMA_VERSION, label=data["label"], identity=dict(data["identity"]),
            skill=context, offense=dict(data["offense"]), signals=signals,
            fix_first=tuple(data["fix_first"]), resource_context=dict(data["resource_context"]),
            equipped=dict(data["equipped"]), observed_defence=dict(data["observed_defence"]),
            coverage=stored, coverage_reasons=tuple(data["coverage_reasons"]),
            dimension_coverage=dict(data["dimension_coverage"]), limitations=tuple(data.get("limitations") or ()),
            slot_contributions=dict(data.get("slot_contributions") or {}), measured_at=str(data.get("measured_at") or ""),
        )

    @classmethod
    def from_json(cls, text: str) -> "BuildNeedsSnapshot":
        return cls.from_dict(json.loads(text))

    # -- construction ---------------------------------------------------------------------------
    @classmethod
    def unavailable(cls, label: str, reason: str, *, skill_name: str = "", skill_id: str = "",
                    equipped: Mapping[str, str] | None = None) -> "BuildNeedsSnapshot":
        """No measurement: every generator decision must fall back conservatively."""
        profile = skill_facts.lookup(skill_id=skill_id, name=skill_name) if (skill_name or skill_id) else None
        skill_name = skill_name or (profile.name if profile else "")
        return cls(
            schema_version=SCHEMA_VERSION, label=label, identity={}, skill=_skill_context(skill_name, skill_id, "", profile),
            offense={"limited_confidence": True, "confidence": "UNSUPPORTED"}, signals=(), fix_first=(),
            resource_context={}, equipped=dict(equipped or {}), observed_defence={},
            coverage=Coverage.FALLBACK if skill_name else Coverage.UNSUPPORTED,
            coverage_reasons=(reason,), dimension_coverage={"offense": "FALLBACK", "defence": "FALLBACK"},
            limitations=("No Build Intelligence measurement was available for this build.",),
        )

    @classmethod
    def from_analysis(cls, result: Mapping[str, Any], *, label: str = "",
                      equipped: Mapping[str, str] | None = None) -> "BuildNeedsSnapshot":
        """Project one production ``analyze_build()`` result. Pure: no PoB access, no probes."""
        sensitivity = result.get("build_sensitivity") or {}
        priorities = result.get("build_priorities") or {}
        fingerprint = result.get("build_fingerprint") or {}
        identity = dict(sensitivity.get("identity") or priorities.get("identity") or {})
        for key in ("build_path", "build_name"):  # no absolute paths or user directories in stored measurements
            identity[key] = str(identity.get(key) or "").replace(chr(92), "/").split("/")[-1]
        fp_offense = fingerprint.get("offense") or {}
        skill = _skill_context(str(fp_offense.get("skill") or ""), str(fp_offense.get("skill_id") or ""),
                               str(fp_offense.get("owner") or ""),
                               skill_facts.lookup(skill_id=str(fp_offense.get("skill_id") or ""),
                                                  name=str(fp_offense.get("skill") or "")))

        lane_rows: dict[str, list[str]] = {}
        for lane in _LANES:
            for row in priorities.get(lane) or []:
                lane_rows.setdefault(str(row.get("label")), []).append(lane)
        for row in priorities.get("multi_axis") or []:
            lane_rows.setdefault(str(row.get("label")), []).append("multi_axis")

        fix_by_probe = _fix_first_by_probe(priorities.get("fix_first") or [])
        signals = _normalise_lanes(tuple(_signal(raw, lane_rows, fix_by_probe) for raw in sensitivity.get("signals") or []))
        # A fix-first deficit can exist for a probe that was never run; it is still a verified need.
        present = {s.probe_id for s in signals}
        extra = tuple(
            NeedSignal(probe_id=pid, label=str(row.get("title")), category=_category(pid), status="NOT_RUN",
                       tested_change="", responses={}, confidence="HIGH", relevance=Relevance.FIX_FIRST.value,
                       fix_first=dict(row), note="reported by Build Priorities Fix First")
            for pid, row in fix_by_probe.items() if pid not in present
        )
        signals = (*signals, *extra)

        offense_context = dict(priorities.get("offense_context") or sensitivity.get("offense_context") or {})
        limited = bool(priorities.get("offense_limited_confidence")) or str(offense_context.get("confidence", "")).upper() == "LOW"
        defence = fingerprint.get("defense") or {}
        observed = {
            key: float((defence.get(key) or {}).get("value") or 0.0) for key in ("armour", "evasion")
        }
        es = (defence.get("energy_shield") or {}).get("value")
        observed["energy_shield"] = float((es or {}).get("value") if isinstance(es, Mapping) else (es or 0.0))

        coverage, reasons, dimensions = _coverage(signals, skill, limited, bool(priorities.get("offense")),
                                                  bool(priorities.get("ehp") or priorities.get("max_hit")))
        limitations = [
            "Measured stats are responses to a bounded probe catalog at one tested increment each, not a ranking of all PoE2 stats.",
            "The native filter cannot see unidentified modifiers; pool hits are opportunities, not possession.",
        ]
        if limited:
            limitations.append("Offense metric confidence is LOW: offense-derived classes never demote items.")
        if not skill.verified:
            limitations.append("Main skill was not resolved in PoB2 skill facts: weapon requirements are unverified.")
        return cls(
            schema_version=SCHEMA_VERSION, label=label or str(identity.get("build_name") or ""), identity=identity,
            skill=skill, offense={"owner": offense_context.get("owner"), "metric": offense_context.get("metric"),
                                  "confidence": str(offense_context.get("confidence") or "").upper(),
                                  "limited_confidence": limited},
            signals=signals, fix_first=tuple(priorities.get("fix_first") or ()),
            resource_context=dict(priorities.get("resource_context") or {}),
            equipped=dict(equipped or _equipped_from_slots(result)), observed_defence=observed,
            coverage=coverage, coverage_reasons=tuple(reasons), dimension_coverage=dimensions,
            limitations=tuple(limitations), slot_contributions=_slot_contributions(result),
        )


def _normalise_lanes(signals: tuple[NeedSignal, ...]) -> tuple[NeedSignal, ...]:
    """A Build Priorities lane confers STRONG only when it ranks at least two measured candidates.

    A single-row lane (production's mobility lane has exactly one probe) orders nothing: the row is "first" by
    construction, for every build. Such a signal stays measured and responsive but is not promoted to STRONG.
    Multi-impact rows are always meaningful. Idempotent, so stored snapshots are re-normalised on load."""
    sizes: dict[str, int] = {}
    for signal in signals:
        for lane in signal.lanes:
            sizes[lane] = sizes.get(lane, 0) + 1
    out = []
    for signal in signals:
        if signal.relevance == Relevance.STRONG.value and not any(
                lane == "multi_axis" or sizes.get(lane, 0) >= 2 for lane in signal.lanes):
            peak = max((v for k, v in signal.responses.items() if k != "speed"), default=0.0)
            demoted = Relevance.RESPONSIVE if peak >= MEANINGFUL_PERCENT else Relevance.MARGINAL
            signal = NeedSignal(**{**asdict(signal), "relevance": demoted.value, "lanes": tuple(signal.lanes),
                                   "note": (signal.note + "; " if signal.note else "") + "single-candidate lane carries no ranking"})
        out.append(signal)
    return tuple(out)


def _equipped_from_slots(result: Mapping[str, Any]) -> dict[str, str]:
    """Observed gear base names from the production per-slot analysis (no engine access needed)."""
    out = {}
    for slot in result.get("slots") or []:
        base = ((slot.get("current_item") or {}).get("base_name") or "").strip()
        if slot.get("product_slot") and base:
            out[str(slot["product_slot"])] = base
    return out


def _slot_contributions(result: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    out = {}
    for slot in result.get("slots") or []:
        contribution = slot.get("contribution") or {}
        if contribution.get("status") == "ok" and slot.get("product_slot"):
            out[str(slot["product_slot"])] = {
                "offense_percent": contribution.get("offense_percent"), "ehp_percent": contribution.get("ehp_percent"),
                "method": contribution.get("method")}
    return out


def required_probes() -> tuple[str, ...]:
    """The probes production always runs globally (stage 2 + generic) plus the Armour/Evasion pair FILTER requests."""
    from exilelens.analysis.catalog import ProbeCatalog
    catalog = ProbeCatalog()
    return tuple(dict.fromkeys((*catalog.stage2_ids(), *catalog.GLOBAL_GENERIC_IDS, "ARMOUR", "EVASION")))


def _category(probe_id: str) -> str:
    if probe_id in _RESISTANCE_PROBES.values():
        return "resistance"
    if probe_id in _ATTRIBUTE_PROBES.values() or probe_id == "MOVEMENT_SPEED":
        return "utility"
    if probe_id in {"LIFE", "ENERGY_SHIELD", "MANA", "ARMOUR", "EVASION"}:
        return "defense"
    return "offense"


def _skill_context(name: str, skill_id: str, owner: str, profile: skill_facts.SkillProfile | None) -> SkillContext:
    if profile is None:
        return SkillContext(name=name, skill_id=skill_id, owner=owner)
    if owner.upper() == "MINION" or profile.is_minion:
        mode, basis = "MINION", "production offense owner is MINION" if owner.upper() == "MINION" else "PoB2 skill creates minions"
    elif profile.is_spell:
        mode, basis = "SPELL", "PoB2 skill type: Spell"
    elif profile.is_attack:
        mode, basis = "ATTACK", "PoB2 skill type: Attack"
    else:
        mode, basis = "UNKNOWN", "PoB2 skill is neither Spell nor Attack"
    return SkillContext(name=profile.name, skill_id=profile.skill_id, owner=owner, mode=mode, mode_basis=basis,
                        elements=profile.elements, types=tuple(sorted(profile.types)),
                        weapon_classes=profile.weapon_classes, verified=True)


def _fix_first_by_probe(rows: list[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    out: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        kind, title = row.get("kind"), str(row.get("title") or "")
        if kind == "RESISTANCE_CAP":
            probe = _RESISTANCE_PROBES.get(title.split()[0].lower())
        elif kind == "ATTRIBUTE_REQUIREMENT":
            probe = _ATTRIBUTE_PROBES.get(title.lower())
        elif kind == "RESOURCE" and "mana" in title.lower():
            probe = "MANA"
        else:
            probe = None
        if probe:
            out.setdefault(probe, dict(row))
    return out


def _signal(raw: Mapping[str, Any], lane_rows: Mapping[str, list[str]],
            fix_by_probe: Mapping[str, Mapping[str, Any]]) -> NeedSignal:
    probe_id = str(raw.get("probe_id") or "")
    label = str(raw.get("label") or probe_id)
    status = str(raw.get("status") or "")
    probe = raw.get("probe") or {}
    magnitude = probe.get("magnitude")
    tested = str(probe.get("line") or "").strip() or (f"+{magnitude:g} {label}" if isinstance(magnitude, (int, float)) else label)
    responses: dict[str, float] = {}
    for axis in _AXIS_KEYS:
        value = ((raw.get("response") or {}).get(axis) or {}).get("percent")
        if value is not None:
            responses[axis] = round(float(value), 3)
    confidence = str(raw.get("confidence") or "LOW").upper()
    lanes = tuple(dict.fromkeys(lane_rows.get(label, ())))
    # Only a POSITIVE response is a benefit; a negative one (an increment that lowers an axis) is not relevance.
    peak = max((v for k, v in responses.items() if k != "speed"), default=0.0)
    fix = fix_by_probe.get(probe_id)
    note = ""
    if fix:
        relevance = Relevance.FIX_FIRST
        note = str(fix.get("detail") or "")
    elif status == "MEASURED":
        if lanes:
            relevance = Relevance.STRONG
        elif peak >= MEANINGFUL_PERCENT:
            relevance = Relevance.RESPONSIVE
        elif peak > RESPONSE_EPSILON:
            relevance = Relevance.MARGINAL
        elif min((v for k, v in responses.items() if k != "speed"), default=0.0) < -MEANINGFUL_PERCENT:
            # An increment that LOWERS a native axis is unexplained, not evidence of irrelevance: never demote on it.
            relevance, note = Relevance.NOT_ESTABLISHED, "negative response (unexplained); not used as evidence"
        else:
            relevance = Relevance.MARGINAL if probe_id in _MAINTENANCE_PROBES else Relevance.NO_RESPONSE
    elif status == "NO_SIGNAL":
        # A capped resistance or a met attribute requirement shows no response by definition, yet items carrying it
        # keep the cap/requirement when gear changes: maintenance, never evidence of irrelevance.
        if probe_id in _MAINTENANCE_PROBES:
            relevance, note = Relevance.MARGINAL, "currently satisfied; maintenance stat"
        else:
            relevance = Relevance.NO_RESPONSE
    else:
        relevance = Relevance.NOT_ESTABLISHED
        note = status.lower().replace("_", " ")
    return NeedSignal(
        probe_id=probe_id, label=label, category=_category(probe_id), status=status, tested_change=tested,
        responses=responses, confidence=confidence, relevance=relevance.value, lanes=lanes,
        fix_first=dict(fix) if fix else None, note=note,
    )


def _coverage(signals: tuple[NeedSignal, ...], skill: SkillContext, limited: bool,
              lane_offense: bool, lane_defence: bool) -> tuple[Coverage, list[str], dict[str, str]]:
    measured = [s for s in signals if s.status == "MEASURED"]
    tested = {s.probe_id for s in signals if s.status in ("MEASURED", "NO_SIGNAL")}
    layers_tested = {"ARMOUR", "EVASION", "ENERGY_SHIELD"} <= tested
    weapon_basis = ("VERIFIED" if skill.verified and skill.weapon_classes else
                    "VERIFIED_UNRESTRICTED" if skill.verified and skill.mode in ("SPELL", "MINION") and skill.weapon_classes is None
                    else "FALLBACK")
    dimensions = {
        "offense": ("MEASURED" if lane_offense and not limited else "PARTIAL" if lane_offense or any(
            s.category == "offense" for s in measured) else "FALLBACK"),
        "defence": ("MEASURED" if lane_defence and layers_tested else "PARTIAL" if lane_defence or any(
            s.category == "defense" for s in measured) else "FALLBACK"),
        "resistances_attributes": ("MEASURED" if any(s.relevance == Relevance.FIX_FIRST.value for s in signals)
                                   else "PARTIAL" if any(s.category in {"resistance", "utility"} and s.status in {"MEASURED", "NO_SIGNAL"}
                                                         for s in signals) else "FALLBACK"),
        "weapon_class": weapon_basis,
    }
    # Minion builds have verified-unrestricted weapons but no minion-weapon evidence: their weapon classes still fall back.
    if skill.mode == "MINION":
        dimensions["weapon_class"] = "FALLBACK"
    reasons: list[str] = []
    if len(measured) < 3:
        reasons.append(f"only {len(measured)} measured responses")
    if limited:
        reasons.append("offense confidence LOW")
    if not skill.verified:
        reasons.append("main skill not found in PoB2 skill facts")
    if not lane_offense:
        reasons.append("no offense response among tested stats")
    if skill.verified and skill.mode == "MINION":
        reasons.append("weapon mapping fallback (minion skill: no minion-weapon evidence)")
    elif skill.verified and skill.mode == "UNKNOWN":
        reasons.append("main skill is a meta/trigger skill: the triggered skill is not resolved, weapon classes fall back"
                       if ("Meta" in skill.types or "Triggers" in skill.types) else "skill is neither spell nor attack")
    elif skill.verified and skill.mode == "ATTACK" and skill.weapon_classes is None:
        reasons.append("weapon mapping fallback (attack skill without a weapon requirement)")
    if not layers_tested:
        reasons.append("defence direction not measured (Armour/Evasion not tested)")
    if len(measured) < 3:
        state = Coverage.FALLBACK
    elif reasons:
        state = Coverage.PARTIAL
    else:
        state = Coverage.MEASURED
    if not reasons:
        reasons.append("offense and defence lanes measured with adequate confidence")
    return state, reasons, dimensions
