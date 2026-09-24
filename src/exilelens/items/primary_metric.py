from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PrimaryMetricConfidence(str, Enum):
    HIGH = "high"
    LOW = "low"


class DamageOwner(str, Enum):
    """Semantic owner of the PoB output selected for primary offense."""

    PLAYER = "PLAYER"
    MINION = "MINION"
    TOTEM = "TOTEM"
    SECONDARY_ACTOR = "SECONDARY_ACTOR"


class OffenseKind(str, Enum):
    PRIMARY_DPS = "PRIMARY_DPS"
    SUSTAINED_DPS = "SUSTAINED_DPS"
    HIT_DPS = "HIT_DPS"
    DOT_DPS = "DOT_DPS"
    UNRESOLVED = "UNRESOLVED"


class DamageQuantity(str, Enum):
    HIT_DPS = "HIT_DPS"
    AILMENT_DPS = "AILMENT_DPS"
    SKILL_DOT = "SKILL_DOT"
    HIT_PLUS_AILMENT = "HIT_PLUS_AILMENT"
    MIXED_OUTPUT = "MIXED_OUTPUT"
    AGGREGATE = "AGGREGATE"
    ACTOR_COMBINED_DPS = "ACTOR_COMBINED_DPS"
    UNRESOLVED = "UNRESOLVED"


class MetricScope(str, Enum):
    PRIMARY_SKILL = "PRIMARY_SKILL"
    STAT_SET_PART = "STAT_SET_PART"
    MULTI_SKILL_AGGREGATE = "MULTI_SKILL_AGGREGATE"
    # Legacy alias kept for builds that set offense_metric_scope explicitly.
    FULL_DPS_AGGREGATE = "FULL_DPS_AGGREGATE"


class ValueType(str, Enum):
    PER_HIT = "PER_HIT"
    PER_SECOND = "PER_SECOND"
    AGGREGATE = "AGGREGATE"


class DamageProvenance(str, Enum):
    """Authority and scope of a combat-damage value, not a confidence score."""

    POB_FULL_BUILD = "POB_FULL_BUILD"
    POB_PRIMARY_SKILL = "POB_PRIMARY_SKILL"
    POB_COMPONENT = "POB_COMPONENT"
    UNAVAILABLE = "UNAVAILABLE"


POB_FIELD_LABELS: dict[str, str] = {
    "CombinedDPS": "Combined DPS",
    "TotalDPS": "Total DPS",
    "TotalDot": "Total DoT",
    "FullDotDPS": "Full DoT",
    "FullDPS": "Full DPS",
    "AverageDamage": "Average Damage",
}

_OFFENSE_EPS = 0.5

#: Share of hit DPS above which an unattributable CombinedDPS remainder stops
#: counting as rounding noise. Deliberately well below the 0.15 "negligible DoT"
#: threshold: that one decides which quantity to report, this one decides whether
#: ExileLens can honestly claim it knows what the quantity contains.
_UNEXPLAINED_DELTA_RATIO = 0.05


@dataclass(frozen=True)
class PrimarySkill:
    """PoB's selected main skill: the socket group the build's calcs are run for.

    Identity comes from the skill itself (granted effect), never from the group's
    free-text label, which players usually leave empty.
    """

    name: str = ""
    skill_id: str = ""
    group: int | None = None
    group_label: str = ""
    source: str = ""
    slot: str = ""
    stat_set: str = ""
    stat_set_key: str = ""
    stat_set_count: int = 0
    stat_set_resolved: bool = False
    part_name: str = ""
    part_key: str = ""
    part_count: int = 0
    part_resolved: bool = False
    stage_count: int | None = None
    stage_explicit: bool = False
    calculation_mode: str = ""
    actor_id: str = ""
    actor_skill: str = ""
    damage_owner: DamageOwner = DamageOwner.PLAYER
    output_table: str = "mainOutput"
    show_average: bool = False

    @property
    def known(self) -> bool:
        return bool(self.skill_id or self.name)

    @property
    def item_granted(self) -> bool:
        return self.source.startswith("Item:")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "skill_id": self.skill_id,
            "group": self.group,
            "group_label": self.group_label,
            "source": self.source or "gem",
            "slot": self.slot,
            "stat_set": self.stat_set,
            "stat_set_key": self.stat_set_key,
            "stat_set_count": self.stat_set_count,
            "stat_set_resolved": self.stat_set_resolved,
            "part_name": self.part_name,
            "part_key": self.part_key,
            "part_count": self.part_count,
            "part_resolved": self.part_resolved,
            "stage_count": self.stage_count,
            "stage_explicit": self.stage_explicit,
            "calculation_mode": self.calculation_mode,
            "actor_id": self.actor_id,
            "actor_skill": self.actor_skill,
            "damage_owner": self.damage_owner.value,
            "output_table": self.output_table,
            "show_average": self.show_average,
        }

    @classmethod
    def from_build_info(cls, build_info: dict[str, Any] | None) -> "PrimarySkill":
        build_info = build_info or {}
        identity = build_info.get("main_skill_identity") or {}
        group = identity.get("index", build_info.get("main_socket_group"))
        raw_owner = str(identity.get("damage_owner") or DamageOwner.PLAYER.value)
        try:
            damage_owner = DamageOwner(raw_owner)
        except ValueError:
            damage_owner = DamageOwner.SECONDARY_ACTOR
        return cls(
            name=str(identity.get("skill_name") or build_info.get("main_skill") or ""),
            skill_id=str(identity.get("skill_id") or ""),
            group=int(group) if isinstance(group, (int, float)) else None,
            group_label=str(identity.get("display_label") or identity.get("label") or ""),
            source=str(identity.get("source") or ""),
            slot=str(identity.get("slot") or ""),
            stat_set=str(identity.get("stat_set") or ""),
            stat_set_key=str(identity.get("stat_set_key") or ""),
            stat_set_count=int(identity.get("stat_set_count") or 0),
            stat_set_resolved=bool(identity.get("stat_set_resolved")),
            part_name=str(identity.get("part_name") or ""),
            part_key=str(identity.get("part_key") or ""),
            part_count=int(identity.get("part_count") or 0),
            part_resolved=bool(identity.get("part_resolved")),
            stage_count=int(identity["stage_count"]) if isinstance(identity.get("stage_count"), (int, float)) else None,
            stage_explicit=bool(identity.get("stage_explicit")),
            calculation_mode=str(identity.get("calculation_mode") or ""),
            actor_id=str(identity.get("actor_id") or ""),
            actor_skill=str(identity.get("actor_skill") or ""),
            damage_owner=damage_owner,
            output_table=str(identity.get("output_table") or "mainOutput"),
            show_average=bool(identity.get("show_average")),
        )


@dataclass(frozen=True)
class PrimaryMetricSelection:
    metric_key: str
    pob_field: str
    reason: str
    confidence: PrimaryMetricConfidence
    selected: OffenseKind = OffenseKind.PRIMARY_DPS
    raw_source_fields: tuple[str, ...] = ("CombinedDPS",)
    skill: PrimarySkill = field(default_factory=PrimarySkill)
    source_field: str = "CombinedDPS"
    semantic_quantity: DamageQuantity = DamageQuantity.HIT_DPS
    metric_scope: MetricScope = MetricScope.PRIMARY_SKILL
    value_type: ValueType = ValueType.PER_SECOND
    ailment: str = ""
    full_dps_skill_count: int | None = None
    full_dps_status: str = "NOT_CONFIGURED"

    @property
    def damage_owner(self) -> DamageOwner:
        return self.skill.damage_owner

    @property
    def provenance(self) -> DamageProvenance:
        if self.selected == OffenseKind.UNRESOLVED:
            return DamageProvenance.UNAVAILABLE
        if self.metric_scope in {MetricScope.MULTI_SKILL_AGGREGATE, MetricScope.FULL_DPS_AGGREGATE}:
            return DamageProvenance.POB_FULL_BUILD
        return DamageProvenance.POB_PRIMARY_SKILL

    def to_dict(self) -> dict[str, Any]:
        damage_reference = build_damage_reference(self)
        return {
            "metric_key": self.metric_key,
            "pob_field": self.pob_field,
            "reason": self.reason,
            "confidence": self.confidence.value,
            "low_confidence": self.confidence == PrimaryMetricConfidence.LOW,
            "selected": self.selected.value,
            "raw_source_fields": list(self.raw_source_fields),
            "metric_source": self.damage_owner.value,
            "provenance": self.provenance.value,
            "output_table": self.skill.output_table,
            "source_field": self.source_field,
            "metric_path": self.pob_field,
            "semantic_quantity": self.semantic_quantity.value,
            "metric_scope": self.metric_scope.value,
            "value_type": self.value_type.value,
            "ailment": self.ailment,
            "stat_set_key": self.skill.stat_set_key,
            "part_key": self.skill.part_key,
            "stage_count": self.skill.stage_count,
            "calculation_mode": self.skill.calculation_mode,
            "skill_name": self.skill.name,
            "primary_skill": self.skill.to_dict(),
            "full_dps_skill_count": self.full_dps_skill_count,
            "full_dps_status": self.full_dps_status,
            "damage_reference": damage_reference,
        }


def pob_field_label(pob_field: str) -> str:
    return POB_FIELD_LABELS.get(pob_field, pob_field.replace("DPS", " DPS").replace("Dot", " DoT").strip())


def _meaningful_stat_set(skill_name: str, stat_set: str) -> str:
    part = (stat_set or "").strip()
    if not part:
        return ""
    if part.casefold() == (skill_name or "").strip().casefold():
        return ""
    return part


def build_damage_reference(selection: PrimaryMetricSelection | dict[str, Any]) -> dict[str, Any]:
    if isinstance(selection, PrimaryMetricSelection):
        skill = selection.skill
        scope = selection.metric_scope
        pob_field = selection.pob_field
        full_dps_skill_count = selection.full_dps_skill_count
        provenance = selection.provenance.value
        full_dps_status = selection.full_dps_status
    else:
        primary_skill = selection.get("primary_skill") or {}
        skill_name = str(selection.get("skill_name") or primary_skill.get("name") or "")
        skill = PrimarySkill(
            name=skill_name,
            skill_id=str(primary_skill.get("skill_id") or ""),
            group=primary_skill.get("group"),
            group_label=str(primary_skill.get("group_label") or ""),
            source=str(primary_skill.get("source") or ""),
            slot=str(primary_skill.get("slot") or ""),
            stat_set=str(primary_skill.get("stat_set") or ""),
        )
        scope = MetricScope(str(selection.get("metric_scope") or MetricScope.PRIMARY_SKILL.value))
        pob_field = str(selection.get("pob_field") or "CombinedDPS")
        count = selection.get("full_dps_skill_count")
        full_dps_skill_count = int(count) if count is not None else None
        provenance = str(selection.get("provenance") or (
            DamageProvenance.POB_FULL_BUILD.value
            if scope in {MetricScope.FULL_DPS_AGGREGATE, MetricScope.MULTI_SKILL_AGGREGATE}
            else DamageProvenance.POB_PRIMARY_SKILL.value
        ))
        full_dps_status = str(selection.get("full_dps_status") or "")

    return {
        "scope": scope.value,
        "skill_name": skill.name,
        "stat_set": skill.stat_set,
        "pob_field": pob_field,
        "metric_label": pob_field_label(pob_field),
        "full_dps_skill_count": full_dps_skill_count,
        "provenance": provenance,
        "full_dps_status": full_dps_status,
    }


def format_damage_reference_lines(damage_reference: dict[str, Any] | None) -> list[str]:
    damage_reference = damage_reference or {}
    scope = str(damage_reference.get("scope") or MetricScope.PRIMARY_SKILL.value)
    metric_label = str(damage_reference.get("metric_label") or "").strip()

    if scope in {MetricScope.FULL_DPS_AGGREGATE.value, MetricScope.MULTI_SKILL_AGGREGATE.value}:
        lines = ["Full DPS aggregate"]
        count = damage_reference.get("full_dps_skill_count")
        if count:
            lines.append(f"{int(count)} included skills")
        if metric_label:
            lines.append(metric_label)
        return lines

    skill_name = str(damage_reference.get("skill_name") or "").strip()
    stat_set = _meaningful_stat_set(skill_name, str(damage_reference.get("stat_set") or ""))
    lines: list[str] = []
    if skill_name and stat_set:
        lines.append(f"{skill_name} → {stat_set}")
    elif skill_name:
        lines.append(skill_name)
    if metric_label:
        lines.append(metric_label)
    if lines and damage_reference.get("provenance") == DamageProvenance.POB_PRIMARY_SKILL.value:
        lines.append("Selected PoB skill — not full build DPS")
        if damage_reference.get("full_dps_status") == "NOT_CONFIGURED":
            lines.append("Full build DPS is not configured in PoB")
    elif damage_reference.get("provenance") == DamageProvenance.UNAVAILABLE.value:
        lines.append("Damage unavailable from PoB")
    return lines


def _full_dps_skills(build_info: dict[str, Any] | None) -> list[str]:
    build_info = build_info or {}
    skills = build_info.get("full_dps_skills")
    if isinstance(skills, list):
        return [str(item) for item in skills if str(item).strip()]
    return []


def _main_skill_offense_zero(metrics: dict[str, Any] | None) -> bool:
    if not metrics:
        return True
    for field_name in ("CombinedDPS", "TotalDPS", "TotalDot", "FullDotDPS"):
        if _num(metrics, field_name) > _OFFENSE_EPS:
            return False
    return True


def _num(metrics: dict[str, Any] | None, field: str) -> float:
    if not metrics:
        return 0.0
    value = metrics.get(field)
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def resolve_primary_metric(
    build_info: dict[str, Any] | None,
    metrics: dict[str, Any] | None = None,
) -> PrimaryMetricSelection:
    """Pick the PoB output field that measures the build's main skill.

    PoB's main-skill outputs (CombinedDPS / TotalDPS / TotalDot ...) are computed for
    the selected main socket group only, so they are already skill-specific. Confidence
    is high when PoB identifies that skill; a missing group label is not uncertainty.
    """
    build_info = build_info or {}
    skill = PrimarySkill.from_build_info(build_info)
    known = skill.known
    prefix = "Minion." if skill.damage_owner == DamageOwner.MINION else ""

    def metric_path(field: str) -> str:
        return f"{prefix}{field}"

    combined = _num(metrics, metric_path("CombinedDPS"))
    full = _num(metrics, metric_path("FullDPS"))
    total_hit = _num(metrics, metric_path("TotalDPS"))
    total_dot = _num(metrics, metric_path("TotalDot"))
    full_dot = _num(metrics, metric_path("FullDotDPS"))
    average = _num(metrics, metric_path("AverageDamage"))
    ailments = {name: _num(metrics, metric_path(field)) for name, field in
                (("IGNITE", "IgniteDPS"), ("POISON", "PoisonDPS"), ("BLEED", "BleedDPS"))}
    ailment_total = sum(ailments.values())
    show_average = bool((build_info.get("main_skill_identity") or {}).get("show_average"))
    sources = tuple(
        metric_path(name)
        for name in ("CombinedDPS", "FullDPS", "TotalDPS", "TotalDot", "FullDotDPS", "AverageDamage")
    )
    full_dps_skills = _full_dps_skills(build_info)
    if not full_dps_skills:
        # FullDPS/FullDotDPS require explicitly included PoB groups. Neither
        # is a substitute for the selected skill's native output.
        full = 0.0
        full_dot = 0.0
    full_dps_status = (
        "NOT_CONFIGURED" if not full_dps_skills
        else "NO_POB_VALUE" if metrics is None or "FullDPS" not in metrics
        else "CONFIGURED_ZERO" if _num(metrics, "FullDPS") <= _OFFENSE_EPS
        else "CONFIGURED"
    )

    def select(
        field: str,
        reason: str,
        confidence: PrimaryMetricConfidence,
        kind: OffenseKind,
        quantity: DamageQuantity = DamageQuantity.HIT_DPS,
        scope: MetricScope = MetricScope.PRIMARY_SKILL,
        value_type: ValueType = ValueType.PER_SECOND,
        ailment: str = "",
        full_dps_skill_count: int | None = None,
    ) -> PrimaryMetricSelection:
        return PrimaryMetricSelection(
            metric_key="primary_offense",
            pob_field=metric_path(field),
            reason=reason,
            confidence=confidence,
            selected=kind,
            raw_source_fields=sources,
            skill=skill,
            source_field=field,
            semantic_quantity=quantity,
            metric_scope=scope,
            value_type=value_type,
            ailment=ailment,
            full_dps_skill_count=full_dps_skill_count,
            full_dps_status=full_dps_status,
        )

    identified = PrimaryMetricConfidence.HIGH if known else PrimaryMetricConfidence.LOW

    explicit_full_scope = str(build_info.get("offense_metric_scope") or "") == MetricScope.FULL_DPS_AGGREGATE.value
    if (
        skill.damage_owner == DamageOwner.PLAYER
        and full_dps_skills and "FullDPS" in (metrics or {})
        and (explicit_full_scope or len(full_dps_skills) >= 1)
    ):
        return select(
            "FullDPS",
            "loaded PoB includes groups in its FullDPS aggregate; practical rotation is not inferred",
            identified,
            OffenseKind.SUSTAINED_DPS,
            DamageQuantity.AGGREGATE,
            MetricScope.MULTI_SKILL_AGGREGATE,
            ValueType.AGGREGATE,
            full_dps_skill_count=len(full_dps_skills) or None,
        )

    if skill.damage_owner == DamageOwner.MINION:
        if combined > 0:
            return select(
                "CombinedDPS",
                f"selected skill is calculated in {skill.output_table}; using its CombinedDPS",
                identified,
                OffenseKind.PRIMARY_DPS,
                DamageQuantity.ACTOR_COMBINED_DPS,
            )
        return select(
            "CombinedDPS",
            f"selected skill belongs to {skill.damage_owner.value}, but {skill.output_table}.CombinedDPS is unavailable",
            PrimaryMetricConfidence.LOW,
            OffenseKind.UNRESOLVED,
        )

    if metrics is not None and combined <= 0 and full <= 0 and total_hit <= 0 and total_dot <= 0 and full_dot <= 0 and ailment_total <= 0:
        return select(
            "CombinedDPS",
            "no usable offensive PoB outputs (CombinedDPS/FullDPS/TotalDPS/DoT all ~0)",
            PrimaryMetricConfidence.LOW,
            OffenseKind.UNRESOLVED,
            DamageQuantity.UNRESOLVED,
        )

    if (
        _main_skill_offense_zero(metrics)
        and full > _OFFENSE_EPS
        and len(full_dps_skills) >= 2
    ):
        return select(
            "FullDPS",
            f"main skill has no offense output; using FullDPS aggregate ({len(full_dps_skills)} flagged skills)",
            identified,
            OffenseKind.SUSTAINED_DPS,
            DamageQuantity.AGGREGATE,
            MetricScope.MULTI_SKILL_AGGREGATE,
            ValueType.AGGREGATE,
            full_dps_skill_count=len(full_dps_skills),
        )

    # PoB's showAverage output is per hit even when the selected skill has an
    # ailment. Never compare that CombinedDPS as a per-second quantity.
    if (show_average or (combined > 0 and total_hit > combined)) and combined > 0 and abs(combined - average) <= max(1e-6, average * 1e-6):
        return select("TotalDPS", "showAverage: CombinedDPS is AverageDamage per hit", identified,
                      OffenseKind.HIT_DPS)

    if ailment_total > 0 and total_dot > 0 and skill.damage_owner == DamageOwner.PLAYER:
        return select("CombinedDPS", "selected output mixes skill-native DoT and damaging ailments; scope unresolved",
                      PrimaryMetricConfidence.LOW, OffenseKind.UNRESOLVED,
                      DamageQuantity.MIXED_OUTPUT, MetricScope.STAT_SET_PART)

    if ailment_total > 0 and skill.damage_owner == DamageOwner.PLAYER:
        dominant = max(ailments, key=ailments.get)
        # For an ailment-dominant stat set the isolated PoB ailment output is
        # authoritative; this keeps hit-up/ailment-down tradeoffs visible.
        if ailments[dominant] > total_hit:
            field = f"{dominant.title()}DPS"
            return select(field, f"selected stat set is {dominant.lower()}-dominant in PoB output",
                          identified, OffenseKind.DOT_DPS, DamageQuantity.AILMENT_DPS,
                          MetricScope.STAT_SET_PART, ailment=dominant)
        if combined > 0:
            return select("CombinedDPS", "PoB combines selected hit and damaging ailment",
                          identified, OffenseKind.PRIMARY_DPS, DamageQuantity.HIT_PLUS_AILMENT,
                          MetricScope.STAT_SET_PART)

    dot = max(total_dot, full_dot)
    hit = total_hit if total_hit > 0 else combined
    if dot > 0 and hit > 0 and dot >= hit * 0.6 and combined > 0 and dot >= combined * 0.45:
        field = "FullDotDPS" if full_dot >= total_dot else "TotalDot"
        aggregate = field == "FullDotDPS"
        return select(field, f"DoT output dominates hit DPS; using {field}",
                      PrimaryMetricConfidence.LOW if aggregate else identified, OffenseKind.DOT_DPS,
                      DamageQuantity.AGGREGATE if aggregate else DamageQuantity.SKILL_DOT,
                      MetricScope.MULTI_SKILL_AGGREGATE if aggregate else MetricScope.STAT_SET_PART,
                      ValueType.AGGREGATE if aggregate else ValueType.PER_SECOND)

    if total_hit > 0 and dot < hit * 0.15:
        # "Negligible DoT" is inferred from the itemised outputs only (TotalDot and
        # the damaging ailments). When PoB's CombinedDPS is materially larger than
        # the hit plus everything we can itemise, the remainder is real damage we
        # cannot attribute; selecting TotalDPS here would silently drop it and
        # claim normal confidence. PoB still provides a valid combined quantity, so
        # report that, flagged unresolved rather than downgraded to unmeasured.
        #
        # Accounting rule: PoB's CombinedDPS sums *disjoint* components -- hit
        # (TotalDPS), the skill's own DoT (TotalDot) and each damaging ailment.
        # Corpus evidence, BUILD_DAMAGE_COMPOSITION_AUDIT: CombinedDPS 287,827 =
        # IgniteDPS 269,092 + hit TotalDPS 18,735. Named ailments are therefore not
        # nested inside TotalDot, so subtracting both does not double-count.
        #
        # ailment_total is provably 0 here for players: every ailment_total > 0
        # path returns earlier (mixed DoT+ailment, then ailment-dominant), and
        # minions return earlier still. It stays in the sum so the arithmetic
        # remains correct if that ordering ever changes.
        unexplained = combined - total_hit - total_dot - ailment_total
        # Strictly greater: a remainder exactly at the threshold is treated as
        # explained, keeping the boundary on the conservative side.
        if combined > total_hit and unexplained > max(
            _OFFENSE_EPS, total_hit * _UNEXPLAINED_DELTA_RATIO
        ):
            # Deliberately identical to the mixed DoT+ailment branch above: both
            # mean "PoB gave us a usable combined number whose composition we
            # cannot account for". Same confidence, scope, quantity and kind, so
            # downstream presentation cannot tell them apart by provenance.
            return select(
                "CombinedDPS",
                "CombinedDPS exceeds hit plus the itemised DoT/ailment outputs; "
                "the remainder is not explained by the PoB fields ExileLens reads",
                PrimaryMetricConfidence.LOW,
                OffenseKind.UNRESOLVED,
                DamageQuantity.MIXED_OUTPUT,
                MetricScope.STAT_SET_PART,
            )
        return select("TotalDPS", "DoT contribution is negligible; using hit DPS", identified, OffenseKind.HIT_DPS)

    if dot > 0 and hit <= 0:
        field = "FullDotDPS" if full_dot >= total_dot else "TotalDot"
        aggregate = field == "FullDotDPS"
        return select(field, f"main skill deals damage over time only; using {field}",
                      PrimaryMetricConfidence.LOW if aggregate else identified, OffenseKind.DOT_DPS,
                      DamageQuantity.AGGREGATE if aggregate else DamageQuantity.SKILL_DOT,
                      MetricScope.MULTI_SKILL_AGGREGATE if aggregate else MetricScope.STAT_SET_PART,
                      ValueType.AGGREGATE if aggregate else ValueType.PER_SECOND)

    if known and (hit > 0 or dot > 0):
        return select(
            "CombinedDPS",
            "mixed hit/DoT output; using selected PoB combined quantity",
            PrimaryMetricConfidence.HIGH,
            OffenseKind.PRIMARY_DPS,
            DamageQuantity.HIT_PLUS_AILMENT, MetricScope.STAT_SET_PART,
        )
    if known:
        return select(
            "CombinedDPS",
            f"unsupported build archetype for dedicated resolver; falling back to CombinedDPS ({skill.name})",
            PrimaryMetricConfidence.LOW,
            OffenseKind.PRIMARY_DPS,
        )
    return select(
        "CombinedDPS",
        "main skill unavailable; falling back to CombinedDPS",
        PrimaryMetricConfidence.LOW,
        OffenseKind.PRIMARY_DPS,
    )
