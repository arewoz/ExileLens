"""Deterministic "Why?" explanation for one EvaluationOutcome (M2.3).

One canonical builder shared by the compact tooltip and More Info. It reads only
already-computed, structured comparison data -- guardrails, quality reasons,
measured deltas, resistance states, the item-impact recovery channels and
conflict assessment -- and returns structured reason blocks. It never computes a
score or a verdict, never invents a threshold (materiality reuses
`item_impact.IMPACT_THRESHOLDS` / `guardrails.RES_MATERIAL_DEFICIT_POINTS`), and
never claims which individual item modifier caused an effect: every line states a
build-level measured change only.

Block shape (``priority`` is internal ordering and is never rendered)::

    {"kind": "gain" | "loss" | "tradeoff" | "blocker" | "uncertainty" | "neutral",
     "metric": "primary_offense", "text": "...", "priority": 0, "fact_id": "..."}
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from exilelens.items.guardrails import NOT_VIABLE_CODES, RES_MATERIAL_DEFICIT_POINTS
from exilelens.items.item_impact import IMPACT_THRESHOLDS, negligible_opposition_note
from exilelens.items.presentation_copy import fact_id_for_metric_row

MAX_WHY_REASONS = 3

KIND_GAIN = "gain"
KIND_LOSS = "loss"
KIND_TRADEOFF = "tradeoff"
KIND_BLOCKER = "blocker"
KIND_UNCERTAINTY = "uncertainty"
KIND_NEUTRAL = "neutral"

#: Fact id of the evaluation-quality reason; the compact tooltip's "◐" note already says it.
QUALITY_FACT_ID = "EVALUATION_QUALITY"

_UP = frozenset({"MEANINGFUL_UPGRADE", "MINOR_UPGRADE", "POTENTIAL_UPGRADE"})
_DOWN = frozenset({"MEANINGFUL_DOWNGRADE", "MINOR_DOWNGRADE", "POTENTIAL_DOWNGRADE"})
_QUALITY_LED = frozenset({"UNCERTAIN", "UNSUPPORTED", "NOT_EVALUATED"})

_TITLES = {
    "up": "WHY IT'S AN UPGRADE",
    "down": "WHY KEEP CURRENT?",
    "side": "WHY NOT A CLEAN UPGRADE?",
    "neutral": "WHY IT DOESN'T IMPROVE THE BUILD",
    "blocked": "WHY IT'S NOT VIABLE",
    "quality": "WHY IT'S UNCERTAIN",
}

# Ranking buckets, lower first: resistance cap/requirement consequences, then the
# core decision axes, then recovery, then movement/speed, then the rest.
_B_RESIST, _B_CORE, _B_RECOVERY, _B_MOVEMENT, _B_OTHER = 1, 2, 3, 4, 5

#: delta key -> (player label, bucket, existing materiality threshold in %).
_DELTA_METRICS: dict[str, tuple[str, int, float]] = {
    "primary_offense": ("Damage", _B_CORE, IMPACT_THRESHOLDS.offense_pct),
    "ehp": ("EHP", _B_CORE, IMPACT_THRESHOLDS.defense_pct),
    "worst_max_hit": ("Max Hit", _B_CORE, IMPACT_THRESHOLDS.defense_pct),
    "movement_speed": ("Movement Speed", _B_MOVEMENT, IMPACT_THRESHOLDS.movement_pct),
    "cast_attack_speed": ("Cast/Attack Speed", _B_OTHER, IMPACT_THRESHOLDS.offense_pct),
    "mana": ("Mana", _B_OTHER, IMPACT_THRESHOLDS.defense_pct),
}

#: Each recovery channel keeps its own identity; Life and Energy Shield are never combined.
_RECOVERY_CHANNELS = {
    "LifeRegenRecovery": ("life_regeneration", "Life Regeneration"),
    "EnergyShieldRegenRecovery": ("energy_shield_regeneration", "Energy Shield Regeneration"),
}

_AXIS_WORD = {"primary_offense": "offense", "ehp": "defensive", "worst_max_hit": "defensive"}

_CAP_EVENT_STATES = frozenset({"CAP_LOST", "CAP_REACHED"})


@dataclass(frozen=True)
class _Fact:
    metric: str
    sign: int
    #: Lower-case-start state phrase ("Damage improves by 8.4%", "you lose the Fire Resistance cap").
    clause: str
    bucket: int
    magnitude: float
    material: bool
    fact_id: str
    #: "Damage" etc. when the fact is a plain percentage change (enables "You give up 2.1% EHP").
    label: str = ""
    pct: float | None = None


# ------------------------------------------------------------------------- helpers


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _cap(text: str) -> str:
    return f"{text[:1].upper()}{text[1:]}" if text else text


def _sentence(clause: str) -> str:
    return f"{_cap(clause)}."


def _per_second(value: float) -> str:
    amount = abs(value)
    return f"{amount:.0f}/s" if amount >= 10 else f"{amount:.1f}/s"


def _block(kind: str, metric: str, text: str, fact_id: str = "", **extra: Any) -> dict[str, Any]:
    return {"kind": kind, "metric": metric, "text": text, "priority": 0, "fact_id": fact_id, **extra}


# ------------------------------------------------------------------------- facts


def _delta_facts(outcome: Mapping[str, Any]) -> list[_Fact]:
    facts: list[_Fact] = []
    deltas = {
        str(row.get("key") or ""): row
        for row in (outcome.get("all_deltas") or outcome.get("primary_deltas") or [])
    }
    for key, (label, bucket, threshold) in _DELTA_METRICS.items():
        row = deltas.get(key)
        if not row:
            continue
        if key == "primary_offense" and str(row.get("delta_kind") or "MEASURED") not in {"MEASURED", "MEASURED_ZERO"}:
            continue  # an unverified damage number is never stated as the build's damage change
        pct = _num(row.get("percent_delta"))
        if pct is None or abs(pct) <= IMPACT_THRESHOLDS.noise_pct:
            continue
        sign = 1 if pct > 0 else -1
        clause = f"{label} improves by {abs(pct):.1f}%" if sign > 0 else f"{label} falls {abs(pct):.1f}%"
        facts.append(
            _Fact(key, sign, clause, bucket, abs(pct), abs(pct) >= threshold, f"{key}:{'+' if sign > 0 else '-'}",
                  label=label, pct=abs(pct))
        )
    return facts


def _recovery_facts(outcome: Mapping[str, Any]) -> list[_Fact]:
    axis = ((outcome.get("item_impact") or {}).get("axes") or {}).get("RECOVERY") or {}
    facts: list[_Fact] = []
    for metric in axis.get("metrics") or []:
        channel = _RECOVERY_CHANNELS.get(str(metric.get("key") or ""))
        if channel is None or str(metric.get("support") or "") != "MEASURED":
            continue
        delta = _num(metric.get("absolute_delta"))
        if not delta:
            continue
        pool_pct = _num(metric.get("pool_pct"))
        pct = _num(metric.get("percent_delta"))
        material = (
            pool_pct is not None
            and pool_pct >= IMPACT_THRESHOLDS.recovery_pool_pct
            and (pct is None or abs(pct) >= IMPACT_THRESHOLDS.recovery_pct)
        )
        name, label = channel
        sign = 1 if delta > 0 else -1
        clause = f"{label} increases by {_per_second(delta)}" if sign > 0 else f"{label} falls by {_per_second(delta)}"
        facts.append(_Fact(name, sign, clause, _B_RECOVERY, pool_pct or 0.0, material, f"{name}:{'+' if sign > 0 else '-'}"))
    return facts


def _guardrail_metrics(outcome: Mapping[str, Any]) -> set[str]:
    metrics: set[str] = set()
    for item in outcome.get("guardrails_applied") or []:
        if str(item.get("code") or "").startswith("RES_"):
            metrics.update(part for part in str(item.get("metric") or "").split(",") if part)
    return metrics


def _resistance_facts(outcome: Mapping[str, Any]) -> list[_Fact]:
    facts: list[_Fact] = []
    flagged = _guardrail_metrics(outcome)
    for row in outcome.get("resistances") or []:
        element = str(row.get("element") or "").lower()
        state = str(row.get("state") or "")
        if not element:
            continue
        key = f"{element}_res"
        name = element.title()
        fact_id = fact_id_for_metric_row({"key": key, "cap_state": state}) or f"{key}:{state}"
        deficit_change = None
        before, after = _num(row.get("deficit_current")), _num(row.get("deficit_candidate"))
        if before is not None and after is not None:
            deficit_change = abs(after - before)
        if state == "CAP_LOST":
            clause, sign, material = f"you lose the {name} Resistance cap", -1, True
        elif state == "CAP_REACHED":
            clause, sign, material = f"you reach the {name} Resistance cap", 1, True
        elif state == "BELOW_CAP_WORSENED":
            clause, sign = f"{name} Resistance falls further below the cap", -1
            material = key in flagged or (deficit_change or 0.0) >= RES_MATERIAL_DEFICIT_POINTS
        elif state == "BELOW_CAP_IMPROVED":
            clause, sign = f"{name} Resistance moves closer to the cap", 1
            material = (deficit_change or 0.0) >= RES_MATERIAL_DEFICIT_POINTS
        else:
            continue
        # Cap events outrank deficit movement; larger deficit swings outrank smaller ones.
        magnitude = (1000.0 if state in _CAP_EVENT_STATES else 0.0) + (deficit_change or 0.0)
        facts.append(_Fact(key, sign, clause, _B_RESIST, magnitude, material, fact_id))
    return facts


def _ranked(facts: list[_Fact], sign: int, *, material_only: bool = True) -> list[_Fact]:
    pool = [fact for fact in facts if fact.sign == sign and (fact.material or not material_only)]
    return sorted(pool, key=lambda fact: (fact.bucket, -fact.magnitude))


# ------------------------------------------------------------------------ blocks


def _blockers(outcome: Mapping[str, Any]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in outcome.get("guardrails_applied") or []:
        code = str(item.get("code") or "")
        text = str(item.get("reason") or "").strip()
        if not text or text in seen:
            continue
        if not (item.get("not_viable") or code in NOT_VIABLE_CODES or code == "REQUIRED_DEFENCE_THRESHOLD"):
            continue
        seen.add(text)
        blocks.append(_block(KIND_BLOCKER, str(item.get("metric") or code.lower()), text, code))
    return blocks


def _uncovered_resistance_guardrails(outcome: Mapping[str, Any], facts: list[_Fact]) -> list[dict[str, Any]]:
    """Resistance guardrails whose element has no structured resistance row (synthetic / partial payloads)."""
    covered = {fact.metric for fact in facts}
    blocks: list[dict[str, Any]] = []
    for item in outcome.get("guardrails_applied") or []:
        code = str(item.get("code") or "")
        text = str(item.get("reason") or "").strip()
        metrics = [part for part in str(item.get("metric") or "").split(",") if part]
        if not code.startswith("RES_") or not text or (metrics and all(m in covered for m in metrics)):
            continue
        suffix = "CAP_LOST" if code == "RES_CAP_LOST" else "BELOW_CAP_WORSENED"
        fact_id = f"RES_{metrics[0].replace('_res', '').upper()}_{suffix}" if metrics else code
        blocks.append(_block(KIND_LOSS, metrics[0] if metrics else code.lower(), text, fact_id))
    return blocks


def _quality_blocks(outcome: Mapping[str, Any]) -> list[dict[str, Any]]:
    quality = str(outcome.get("evaluation_quality") or "")
    if not quality or quality == "FULL":
        return []
    reasons = [str(item.get("detail") or "").strip() for item in outcome.get("evaluation_quality_reasons") or []]
    reasons = [reason for reason in reasons if reason]
    if not reasons:
        return []
    detail = reasons[0].rstrip(".")
    blocks = [_block(KIND_UNCERTAINTY, "evaluation_quality", _sentence(detail), QUALITY_FACT_ID)]
    defense = ((outcome.get("item_impact") or {}).get("axes") or {}).get("DEFENSE") or {}
    if quality == "PARTIAL" and str(defense.get("support") or "") == "MEASURED":
        blocks.append(_block(KIND_UNCERTAINTY, "defense", "Defensive changes are still measured."))
    return blocks


def _negligible_block(outcome: Mapping[str, Any]) -> dict[str, Any] | None:
    note = negligible_opposition_note((outcome.get("item_impact") or {}).get("conflict") or {})
    return _block(KIND_NEUTRAL, "negligible_opposition", note) if note else None


def _gain_block(fact: _Fact, *, lead: bool, several: bool) -> dict[str, Any]:
    if lead and several and fact.pct is not None:
        text = f"{fact.label} +{fact.pct:.1f}% is the biggest gain."
    else:
        text = _sentence(fact.clause)
    return _block(KIND_GAIN, fact.metric, text, fact.fact_id)


def _loss_block(fact: _Fact, *, counterweight: bool) -> dict[str, Any]:
    if counterweight and fact.pct is not None:
        text = f"You give up {fact.pct:.1f}% {fact.label}."
    else:
        text = _sentence(fact.clause)
    return _block(KIND_LOSS, fact.metric, text, fact.fact_id)


def _unmerged_recovery_pair(extra: list[_Fact], used: set[str]) -> dict[str, Any] | None:
    """Both recovery channels moved in opposite directions: say both, never as one number."""
    channels = [fact for fact in extra if fact.bucket == _B_RECOVERY and fact.material and fact.metric not in used]
    gains = [fact for fact in channels if fact.sign > 0]
    losses = [fact for fact in channels if fact.sign < 0]
    if not (gains and losses):
        return None
    gain, loss = gains[0], losses[0]
    return _block(KIND_TRADEOFF, gain.metric, f"{_sentence(gain.clause)[:-1]}, but {loss.clause}.",
                  gain.fact_id, counter_metric=loss.metric)


def _fill(blocks: list[dict[str, Any]], extra: list[_Fact], used: set[str]) -> None:
    """Spend any remaining slot on the next most relevant material fact not yet explained."""
    for fact in sorted((f for f in extra if f.material and f.metric not in used), key=lambda f: (f.bucket, -f.magnitude)):
        if len(blocks) >= MAX_WHY_REASONS:
            return
        pair = _unmerged_recovery_pair(extra, used)
        if pair is not None and fact.bucket == _B_RECOVERY:
            blocks.append(pair)
            used.update({pair["metric"], pair["counter_metric"]})
            continue
        blocks.append(_gain_block(fact, lead=False, several=False) if fact.sign > 0 else _loss_block(fact, counterweight=False))
        used.add(fact.metric)


# --------------------------------------------------------------------- public API


def _group(verdict: str) -> str:
    if verdict in _UP:
        return "up"
    if verdict in _DOWN:
        return "down"
    if verdict == "NOT_VIABLE":
        return "blocked"
    if verdict in _QUALITY_LED:
        return "quality"
    return "side"


def build_why_explanation(outcome: Mapping[str, Any] | None) -> dict[str, Any]:
    """Structured Why for one outcome: ``{"verdict", "title", "reasons": [<=3 blocks]}``.

    Empty ``reasons`` means the outcome carries no structured evidence to explain
    (callers keep their own fallback). The verdict is read, never recomputed.
    """
    outcome = outcome or {}
    verdict = str(outcome.get("verdict") or "")
    group = _group(verdict)
    quality_blocks = _quality_blocks(outcome)
    blockers = _blockers(outcome)

    facts = _delta_facts(outcome) + _recovery_facts(outcome) + _resistance_facts(outcome)
    gains = _ranked(facts, 1)
    losses = _ranked(facts, -1)
    used: set[str] = set()
    blocks: list[dict[str, Any]] = []

    if blockers:
        blocks.extend(blockers[:2])
        blocks.extend(quality_blocks[:1])
        group = "blocked"
    elif group == "quality":
        blocks.extend(quality_blocks)
    elif group == "up":
        lead = (gains or _ranked(facts, 1, material_only=False)[:1] or [None])[0]
        if lead is not None:
            blocks.append(_gain_block(lead, lead=True, several=len(gains) > 1))
            used.add(lead.metric)
        if losses:
            blocks.append(_loss_block(losses[0], counterweight=True))
            used.add(losses[0].metric)
    elif group == "down":
        lead = (losses or _ranked(facts, -1, material_only=False)[:1] or [None])[0]
        if lead is not None:
            blocks.append(_loss_block(lead, counterweight=False))
            used.add(lead.metric)
        if gains:
            blocks.append(_block(KIND_GAIN, gains[0].metric, f"{_sentence(gains[0].clause)[:-1]}, but not enough to offset it.",
                                 gains[0].fact_id))
            used.add(gains[0].metric)
        elif len(losses) > 1:
            blocks.append(_loss_block(losses[1], counterweight=False))
            used.add(losses[1].metric)
    else:
        if gains and losses:
            blocks.append(_block(KIND_TRADEOFF, gains[0].metric, f"{_sentence(gains[0].clause)[:-1]}, but {losses[0].clause}.",
                                 gains[0].fact_id, counter_metric=losses[0].metric))
            blocks.append(_block(KIND_TRADEOFF, "tradeoff", "That trade-off keeps this a sidegrade."))
            used.update({gains[0].metric, losses[0].metric})
        elif gains or losses:
            lead = (gains or losses)[0]
            blocks.append(_gain_block(lead, lead=False, several=False) if lead.sign > 0 else _loss_block(lead, counterweight=False))
            used.add(lead.metric)
        elif outcome.get("all_deltas") or outcome.get("item_impact"):
            changed = any(
                (_num(row.get("percent_delta")) or 0.0) != 0.0 or (_num(row.get("absolute_delta")) or 0.0) != 0.0
                for row in outcome.get("all_deltas") or []
            )
            text = (
                "The measured changes are below the meaningful-change threshold."
                if changed
                else "The measured values are unchanged."
            )
            blocks.append(_block(KIND_NEUTRAL, "meaningful_change", text))

    if group in {"up", "down", "side"}:
        negligible = _negligible_block(outcome)
        if negligible is not None and len(blocks) < MAX_WHY_REASONS:
            blocks.append(negligible)
        _fill(blocks, facts, used)
        for extra in _uncovered_resistance_guardrails(outcome, facts):
            if len(blocks) < MAX_WHY_REASONS:
                blocks.append(extra)
        if len(blocks) < MAX_WHY_REASONS and blocks:
            blocks.extend(quality_blocks[: MAX_WHY_REASONS - len(blocks)][:1])

    blocks = blocks[:MAX_WHY_REASONS]
    for index, block in enumerate(blocks):
        block["priority"] = index
    return {"verdict": verdict, "title": _TITLES[group] if blocks else "", "reasons": blocks}
