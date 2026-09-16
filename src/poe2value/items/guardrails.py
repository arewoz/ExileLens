"""The one guardrail table for item scoring and the item verdict.

`value_profiles.score_profile` and the `EvaluationOutcome` policy both read this
module, so a guardrail can never cap the number without also bounding the verdict
(the verdict is classified from the capped number) or vice versa.

A guardrail is an explicit score ceiling, not a hidden weight. Ceilings are placed
inside verdict bands on purpose:

* `NOT_VIABLE_*` ceilings sit in the severe band and additionally force the
  categorical `NOT VIABLE` verdict.
* `MINOR_UPGRADE_CEILING` sits just below the meaningful-upgrade threshold
  (`SCORE_SCALE.useful`), so strong raw damage can at most read as a minor upgrade
  while an important resistance is materially below cap.
* `SIDEGRADE_CEILING` sits just below the minor-upgrade band (`SCORE_SCALE.minor_upgrade`),
  so an elemental cap break can never read as a green upgrade on Balanced.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

# Kept as literals so this module has no import-time dependency on value_profiles
# (which imports it). tests/unit/test_evaluation_outcome.py pins them to SCORE_SCALE.
MINOR_UPGRADE_CEILING = 59.0  # < SCORE_SCALE.useful (60) → at most MINOR UPGRADE
SIDEGRADE_CEILING = 52.9  # < SCORE_SCALE.minor_upgrade (53) → at most SIDEGRADE
CAP_LOSS_DOWNGRADE_CEILING = 47.0  # == SCORE_SCALE.minor_downgrade → cap loss + max-hit loss
NOT_VIABLE_CEILING = 25.0  # == SCORE_SCALE.severe
LEGACY_MILD_DEFICIT_CEILING = 72.0

# Candidate deficit (points below cap) from which an elemental resistance that gets
# worse is "materially below cap" and blocks MEANINGFUL UPGRADE.
RES_MATERIAL_DEFICIT_POINTS = 5.0

ELEMENTAL = ("fire", "cold", "lightning")


@dataclass(frozen=True)
class GuardrailRule:
    code: str
    score_ceiling: float
    not_viable: bool
    reason: str


GUARDRAIL_RULES: dict[str, GuardrailRule] = {
    rule.code: rule
    for rule in (
        GuardrailRule("BUILD_INVALID", 0.0, True, "The build does not resolve with this item."),
        GuardrailRule("MAIN_SKILL_INVALID", 15.0, True, "The main skill can no longer be used."),
        GuardrailRule("RESOURCE_FAILURE", NOT_VIABLE_CEILING, True, "Mana cost per second exceeds regeneration."),
        GuardrailRule("RESOURCE_SUSTAIN_LOST", NOT_VIABLE_CEILING, True, "Mana cost per second exceeds regeneration."),
        GuardrailRule("ATTRIBUTE_REQUIREMENT_LOST", NOT_VIABLE_CEILING, True, "Attribute requirements are not met."),
        GuardrailRule("RES_CAP_LOST", SIDEGRADE_CEILING, False, "{element} resistance cap lost."),
        GuardrailRule(
            "RES_DEFICIT_WORSENED_MATERIAL",
            MINOR_UPGRADE_CEILING,
            False,
            "{element} Resistance, already below cap, gets worse.",
        ),
        GuardrailRule(
            "RES_DEFICIT_WORSENED",
            LEGACY_MILD_DEFICIT_CEILING,
            False,
            "{element} Resistance, already below cap, gets slightly worse.",
        ),
        GuardrailRule(
            "REQUIRED_DEFENCE_THRESHOLD",
            MINOR_UPGRADE_CEILING,
            False,
            "A required defence threshold is lost.",
        ),
    )
}

NOT_VIABLE_CODES = frozenset(code for code, rule in GUARDRAIL_RULES.items() if rule.not_viable)


@dataclass(frozen=True)
class AppliedGuardrail:
    code: str
    score_ceiling: float
    not_viable: bool
    reason: str
    metric: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _elements_in(resist: dict[str, Any] | None, state: str) -> list[dict[str, Any]]:
    return [
        dict(info)
        for info in ((resist or {}).get("elements") or {}).values()
        if str((info or {}).get("state") or "") == state
    ]


def _element_label(infos: list[dict[str, Any]]) -> str:
    names = [str(info.get("element") or "").title() for info in infos if info.get("element")]
    return " / ".join(names) or "A"


def _warning_detail(warnings: Iterable[dict[str, Any]] | None, code: str) -> str | None:
    for item in warnings or []:
        if str(item.get("code") or "") == code:
            detail = str(item.get("detail") or "").strip()
            if detail:
                return detail
    return None


def _cap_loss_ceiling(
    resist: dict[str, Any] | None,
    present: set[str],
    metrics: dict[str, Any] | None,
) -> float:
    if "MAX_HIT_DOWN" in present:
        return CAP_LOSS_DOWNGRADE_CEILING
    lost = _elements_in(resist, "CAP_LOST")
    for info in lost:
        element = str(info.get("element") or "")
        if not element:
            continue
        max_hit = (metrics or {}).get(f"{element}_max_hit") or {}
        if float(max_hit.get("absolute_delta") or 0.0) < -0.5:
            return CAP_LOSS_DOWNGRADE_CEILING
    return SIDEGRADE_CEILING


def evaluate_guardrails(
    codes: Iterable[str],
    resist: dict[str, Any] | None = None,
    *,
    warnings: Iterable[dict[str, Any]] | None = None,
    metrics: dict[str, Any] | None = None,
) -> list[AppliedGuardrail]:
    """Guardrails triggered by warning / threshold codes, most severe ceiling first.

    `codes` is the union of `consequences.build_warnings` codes and hard-constraint
    threshold codes. `resist` decides materiality of a worsened resistance deficit.
    Optional `warnings` supplies player-facing detail (e.g. requirement shortfall).
    """
    present = {str(code) for code in codes if code}
    applied: list[AppliedGuardrail] = []

    def add(
        code: str,
        *,
        metric: str = "",
        element: str = "",
        score_ceiling: float | None = None,
        reason: str | None = None,
    ) -> None:
        rule = GUARDRAIL_RULES[code]
        resolved_reason = (reason or rule.reason).replace("{element}", element or "A")
        ceiling = score_ceiling if score_ceiling is not None else rule.score_ceiling
        applied.append(AppliedGuardrail(code, ceiling, rule.not_viable, resolved_reason, metric))

    for code in ("BUILD_INVALID", "MAIN_SKILL_INVALID"):
        if code in present:
            add(code)
    if "ATTRIBUTE_REQUIREMENT_LOST" in present:
        add("ATTRIBUTE_REQUIREMENT_LOST", reason=_warning_detail(warnings, "ATTRIBUTE_REQUIREMENT_LOST"))
    # One resource failure, however many sources report it.
    if "RESOURCE_FAILURE" in present:
        add("RESOURCE_FAILURE", metric="mana_sustain")
    elif "RESOURCE_SUSTAIN_LOST" in present:
        add("RESOURCE_SUSTAIN_LOST", metric="mana_sustain")

    if "RES_CAP_LOST" in present:
        lost = _elements_in(resist, "CAP_LOST")
        cap_ceiling = _cap_loss_ceiling(resist, present, metrics)
        add(
            "RES_CAP_LOST",
            metric=",".join(f"{i.get('element')}_res" for i in lost),
            element=_element_label(lost),
            score_ceiling=cap_ceiling,
        )

    if "RES_DEFICIT_WORSENED" in present:
        worsened = _elements_in(resist, "BELOW_CAP_WORSENED")
        material = [
            info
            for info in worsened
            if str(info.get("element") or "") in ELEMENTAL
            and float(info.get("candidate_deficit") or 0.0) >= RES_MATERIAL_DEFICIT_POINTS
        ]
        if material:
            add(
                "RES_DEFICIT_WORSENED_MATERIAL",
                metric=",".join(f"{i.get('element')}_res" for i in material),
                element=_element_label(material),
            )
        else:
            add(
                "RES_DEFICIT_WORSENED",
                metric=",".join(f"{i.get('element')}_res" for i in worsened),
                element=_element_label(worsened),
            )

    if "REQUIRED_DEFENCE_THRESHOLD" in present:
        add("REQUIRED_DEFENCE_THRESHOLD", metric="ehp")

    applied.sort(key=lambda item: item.score_ceiling)
    return applied


def apply_score_ceilings(raw_score: float, applied: Iterable[AppliedGuardrail]) -> float:
    score = float(raw_score)
    for guardrail in applied:
        score = min(score, guardrail.score_ceiling)
    return round(score, 1)
