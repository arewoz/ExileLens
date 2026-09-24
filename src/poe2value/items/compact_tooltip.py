"""Compression of the finished presentation model into the primary tooltip.

The evaluation produces far more analysis than a player can read while an item is on
the cursor. This module decides what the *primary* tooltip says — the one verdict, a
handful of decision-relevant deltas, the strongest semantic reasons and the critical
warnings — and hands everything else (the score included) to the Companion.

Nothing is computed here. The verdict and score are read from the recommendation's
`EvaluationOutcome`; no second verdict is derived from the score or product verdict.
"""

from __future__ import annotations

import re
from typing import Any

from poe2value.items.companion import build_companion_analysis, prune_companion_duplicates
from poe2value.items.score_bands import score_band, score_text
from poe2value.items.slots import is_jewel_socket_pob_slot

# Ordered ids of what the compact tooltip is allowed to render. No score: it lives
# in More Info (Companion `score` section).
COMPACT_SECTION_IDS = (
    "header",
    "compared",
    "slots",
    "impact",
    "reasons",
    "notes",
    "verdict",
)

# Sections whose content is moved to the Companion. Listing them here (rather than
# clearing fields ad hoc) is what stops two surfaces explaining the same conclusion.
MOVED_TO_COMPANION = (
    "axis_rows",
    "tradeoff_lines",
    "hard_problems",
    "important_mods",
    "why_not_upgrade",
    "build_fixes",
    "compact_notes",
    "multi_profile_row",
    "badges",
)

MAX_IMPACT_ROWS = 5
MIN_IMPACT_ROWS = 3
MAX_REASONS = 3
MAX_NOTES = 2

LARGE_SURVIVABILITY_LOSS_PCT = 10.0
LARGE_DAMAGE_LOSS_PCT = 10.0
MATERIAL_LOSS_PCT = 1.0
MATERIAL_LOSS_ABS = 0.5
LARGE_SPEED_PCT = 5.0

# Reading order after the decision ranker has picked the rows.
_DISPLAY_PRIORITY = (
    "cannot_equip",
    "requirement",
    "primary_offense",
    "cast_attack_speed",
    "ehp",
    "worst_max_hit",
    "lightning_res",
    "fire_res",
    "cold_res",
    "chaos_res",
    "lightning_res_buffer",
    "fire_res_buffer",
    "cold_res_buffer",
    "chaos_res_buffer",
    "life",
    "energy_shield",
    "mana",
    "movement_speed",
)
_DISPLAY_INDEX = {key: index for index, key in enumerate(_DISPLAY_PRIORITY)}

_EMPHASIS_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "muted": 4}

_EHP_COMPONENT_KEYS = frozenset({"life", "energy_shield"})

_NOT_VIABLE_CODES = frozenset(
    {
        "BUILD_INVALID",
        "MAIN_SKILL_INVALID",
        "RESOURCE_FAILURE",
        "RESOURCE_SUSTAIN_LOST",
        "ATTRIBUTE_REQUIREMENT_LOST",
    }
)
_REQUIREMENT_CODES = frozenset({"ATTRIBUTE_REQUIREMENT_LOST", "REQUIRED_DEFENCE_THRESHOLD"})

# Ranker buckets — lower is more important. Not a fixed Damage/EHP/Max Hit trio.
_BUCKET_CANNOT_EQUIP = 0
_BUCKET_REQUIREMENT = 1
_BUCKET_RES_BELOW_CAP = 2
_BUCKET_LARGE_LOSS = 3
_BUCKET_MAJOR_DPS = 4
_BUCKET_MAJOR_DEFENSE = 5
_BUCKET_SPEED = 6
_BUCKET_MOVEMENT = 7
_BUCKET_RESOURCE = 8
_BUCKET_ATTRIBUTE = 9
_BUCKET_OTHER = 10

# Cap states that are themselves a decision, regardless of how small the delta is.
_DECISIVE_CAP_STATES = frozenset(
    {
        "CAP_LOST",
        "CAP_REACHED",
        "CAP_GAINED",
        "BELOW_CAP_WORSENED",
        "BELOW_CAP_IMPROVED",
        "FURTHER_BELOW_CAP",
    }
)

# Raw per-delta warnings: the metric row above already says this, in numbers.
_RAW_DELTA_WARNING_CODES = frozenset(
    {
        "EHP_DOWN",
        "MAX_HIT_DOWN",
        "LIFE_DOWN",
        "ENERGY_SHIELD_DOWN",
        "CHAOS_RES_WORSE",
        "MOVEMENT_LOSS",
        "OFFENSE_DOWN",
    }
)

_ELEMENT_NAMES = {
    "fire": "Fire",
    "cold": "Cold",
    "lightning": "Lightning",
    "chaos": "Chaos",
}


def _element_of(metric: str) -> str:
    key = str(metric or "").replace("_res", "").replace("_resist", "").lower()
    return _ELEMENT_NAMES.get(key, "")


def _row_magnitude(row: dict[str, Any]) -> float:
    pct = row.get("percent_delta")
    if pct is not None:
        return abs(float(pct))
    try:
        return abs(float(row.get("absolute_delta") or 0.0))
    except (TypeError, ValueError):
        return 0.0


def _is_zero_row(row: dict[str, Any]) -> bool:
    """A row that carries no decision: no cap movement and no measurable delta."""
    if str(row.get("cap_state") or "") in _DECISIVE_CAP_STATES:
        return False
    pct = row.get("percent_delta")
    abs_delta = row.get("absolute_delta")
    if pct is None and abs_delta is None:
        # No numbers to judge by — fall back to the rendered text.
        text = str(row.get("delta_text") or "").strip()
        return text in {"", "0", "0.0%", "+0.0%", "-0.0%", "—"}
    if pct is not None and abs(float(pct)) >= 0.05:
        return False
    try:
        return abs(float(abs_delta or 0.0)) < 0.5
    except (TypeError, ValueError):
        return False


def _is_loss_row(row: dict[str, Any]) -> bool:
    if str(row.get("cap_state") or "") in {"CAP_LOST", "BELOW_CAP_WORSENED", "FURTHER_BELOW_CAP"}:
        return True
    if str(row.get("direction") or "") == "negative":
        return True
    pct = row.get("percent_delta")
    if pct is not None and float(pct) < 0:
        return True
    try:
        return float(row.get("absolute_delta") or 0.0) < 0
    except (TypeError, ValueError):
        return False


def _is_gain_row(row: dict[str, Any]) -> bool:
    if str(row.get("cap_state") or "") in {"CAP_REACHED", "CAP_GAINED", "BELOW_CAP_IMPROVED"}:
        return True
    if str(row.get("direction") or "") == "positive":
        return True
    pct = row.get("percent_delta")
    if pct is not None and float(pct) > 0:
        return True
    try:
        return float(row.get("absolute_delta") or 0.0) > 0
    except (TypeError, ValueError):
        return False


def _is_material_loss(row: dict[str, Any]) -> bool:
    """A loss the player must see — not a rounding wiggle."""
    if not _is_loss_row(row):
        return False
    cap_state = str(row.get("cap_state") or "")
    if cap_state in {"CAP_LOST", "BELOW_CAP_WORSENED", "FURTHER_BELOW_CAP"}:
        return True
    if str(row.get("emphasis") or "") in {"critical", "high"}:
        return True
    if str(row.get("key") or "") in {"cannot_equip", "requirement"}:
        return True
    pct = row.get("percent_delta")
    if pct is not None and abs(float(pct)) >= MATERIAL_LOSS_PCT:
        return True
    try:
        return abs(float(row.get("absolute_delta") or 0.0)) >= MATERIAL_LOSS_ABS
    except (TypeError, ValueError):
        return False


# A build's primary damage output is the other first-class decision axis
# alongside EHP/Max Hit. Several large defensive losses (each individually
# >= LARGE_DAMAGE_LOSS_PCT, landing in the higher-priority "large loss" rank
# bucket) can otherwise fill the whole row budget before a real, measured
# offense change is ever considered, even though it is exactly what
# "-4.9% Spark DPS, -16.1% EHP, -24.1% Max Hit" reads as to a player: four
# facts, not three. Presentation ranking only -- this never promotes an
# unmeasured/estimated number (rows_from_outcome_deltas already refuses to
# render those at all); it only protects a MEASURED row from being dropped
# purely for losing a magnitude contest against larger defensive deltas.
_MATERIAL_OFFENSE_PCT = 3.0


def _is_material_primary_offense(row: dict[str, Any]) -> bool:
    if str(row.get("key") or "") != "primary_offense":
        return False
    if str(row.get("delta_kind") or "MEASURED") not in {"MEASURED", "MEASURED_ZERO"}:
        return False
    return _row_magnitude(row) >= _MATERIAL_OFFENSE_PCT


def impact_marker(row: dict[str, Any]) -> str:
    """Decision marker. Color is extra; the marker itself is required."""
    cap_state = str(row.get("cap_state") or "")
    if cap_state == "CAP_LOST" or str(row.get("key") or "") in {"cannot_equip", "requirement"}:
        return "!"
    if str(row.get("emphasis") or "") == "critical" and _is_loss_row(row):
        return "!"
    if _is_loss_row(row):
        return "▼"
    if _is_gain_row(row):
        return "▲"
    return "~"


def decorate_impact_row(row: dict[str, Any]) -> dict[str, Any]:
    """Attach a marker and strip duplicate ▲/▼ from delta text."""
    decorated = dict(row)
    marker = str(row.get("marker") or "") or impact_marker(row)
    decorated["marker"] = marker
    delta = str(row.get("delta_text") or "").strip()
    for symbol in ("▲", "▼", "!", "~"):
        delta = delta.replace(f" {symbol}", "").replace(symbol, "")
    decorated["delta_text"] = delta.strip()
    return decorated


def _decision_bucket(row: dict[str, Any]) -> int:
    key = str(row.get("key") or "")
    cap_state = str(row.get("cap_state") or "")
    if key == "cannot_equip" or str(row.get("guardrail_code") or "") in _NOT_VIABLE_CODES:
        return _BUCKET_CANNOT_EQUIP
    if key == "requirement" or str(row.get("guardrail_code") or "") in _REQUIREMENT_CODES:
        return _BUCKET_REQUIREMENT
    if key.endswith("_res") and cap_state in {
        "CAP_LOST",
        "BELOW_CAP_WORSENED",
        "FURTHER_BELOW_CAP",
        "BELOW_CAP_IMPROVED",
        "CAP_REACHED",
        "CAP_GAINED",
    }:
        return _BUCKET_RES_BELOW_CAP
    magnitude = _row_magnitude(row)
    if _is_loss_row(row) and (
        magnitude >= LARGE_DAMAGE_LOSS_PCT or str(row.get("emphasis") or "") == "critical"
    ):
        return _BUCKET_LARGE_LOSS
    if key == "primary_offense" and magnitude >= 3.0:
        return _BUCKET_MAJOR_DPS
    if key in {"ehp", "worst_max_hit"} and magnitude >= 3.0:
        return _BUCKET_MAJOR_DEFENSE
    if key == "cast_attack_speed" and magnitude >= LARGE_SPEED_PCT:
        return _BUCKET_SPEED
    if key == "movement_speed":
        return _BUCKET_MOVEMENT
    if key in {"mana", "life", "energy_shield"}:
        return _BUCKET_RESOURCE
    if key in {"strength", "dexterity", "intelligence"}:
        return _BUCKET_ATTRIBUTE
    if key == "cast_attack_speed":
        return _BUCKET_SPEED
    if key == "primary_offense":
        return _BUCKET_MAJOR_DPS
    if key in {"ehp", "worst_max_hit"}:
        return _BUCKET_MAJOR_DEFENSE
    return _BUCKET_OTHER


def _decision_rank(row: dict[str, Any]) -> tuple[int, int, float, int]:
    cap_state = str(row.get("cap_state") or "")
    decisive_cap = 0 if cap_state in _DECISIVE_CAP_STATES else 1
    emphasis = _EMPHASIS_RANK.get(str(row.get("emphasis") or "medium"), 9)
    return (
        _decision_bucket(row),
        decisive_cap,
        emphasis,
        -_row_magnitude(row),
        _DISPLAY_INDEX.get(str(row.get("key") or ""), 99),
    )


def _inject_outcome_loss_candidates(
    candidate_rows: list[dict[str, Any]],
    outcome: dict[str, Any],
) -> list[dict[str, Any]]:
    """Keep presentation._select_rows caps intact; feed outcome losses into compact ranking.

    Material negative EvaluationOutcome deltas and metrics named by critical_tradeoffs
    must reach select_impact_rows, or a full gain-row budget can hide the P0 loss rule.
    """
    existing = {str(row.get("key") or "") for row in candidate_rows}
    outcome_rows = rows_from_outcome_deltas(outcome)
    needed: set[str] = set()
    for row in outcome_rows:
        if _is_material_loss(row):
            key = str(row.get("key") or "")
            if key:
                needed.add(key)
    for item in outcome.get("critical_tradeoffs") or []:
        metric = str(item.get("metric") or "")
        if metric:
            needed.add(metric)
    merged = list(candidate_rows)
    for row in outcome_rows:
        key = str(row.get("key") or "")
        if key and key in needed and key not in existing:
            merged.append(row)
            existing.add(key)
    return merged


def select_impact_rows(rows: list[dict[str, Any]], *, limit: int = MAX_IMPACT_ROWS) -> list[dict[str, Any]]:
    """The 3-5 metrics with the highest decision importance, in reading order.

    Hard rules: if any material loss exists among the candidates, at least one
    loss row is kept; if a material, measured primary-offense change exists, it
    is kept too, even when several large defensive losses would otherwise fill
    the whole budget first. Zero / irrelevant axes are dropped rather than
    rendered mechanically, unless dropping them would leave nothing at all to
    show.
    """
    candidates = [row for row in rows if not _is_zero_row(row)]
    # EHP already is Life + Energy Shield. Showing all three is one fact read three
    # times; the components stay on More Info's raw PoB figures.
    if any(str(row.get("key")) == "ehp" for row in candidates):
        candidates = [row for row in candidates if str(row.get("key")) not in _EHP_COMPONENT_KEYS]
    if not candidates:
        candidates = list(rows)[:MIN_IMPACT_ROWS]
    ranked = sorted(candidates, key=_decision_rank)
    selected = ranked[:limit]
    ranked_losses = [row for row in ranked if _is_material_loss(row)]
    protected_loss = None
    if ranked_losses and not any(_is_material_loss(row) for row in selected):
        protected_loss = ranked_losses[0]
        selected = selected[:-1] + [protected_loss] if selected else [protected_loss]

    offense_row = next((row for row in ranked if _is_material_primary_offense(row)), None)
    if offense_row is not None and not any(str(row.get("key") or "") == "primary_offense" for row in selected):
        if len(selected) >= limit and selected:
            drop_at = len(selected) - 1
            if protected_loss is not None and selected[drop_at] is protected_loss:
                drop_at = max(0, len(selected) - 2)
            selected = selected[:drop_at] + selected[drop_at + 1 :] + [offense_row]
        else:
            selected = selected + [offense_row]

    selected.sort(key=lambda row: _DISPLAY_INDEX.get(str(row.get("key") or ""), 99))
    return [decorate_impact_row(row) for row in selected]


def rows_from_outcome_deltas(outcome: dict[str, Any]) -> list[dict[str, Any]]:
    """Turn an EvaluationOutcome's deltas into compact-ranker rows. No rescoring."""
    resist_by_key = {
        f"{str(item.get('element') or '').lower()}_res": item
        for item in (outcome.get("resistances") or [])
    }
    rows: list[dict[str, Any]] = []
    for delta in list(outcome.get("all_deltas") or outcome.get("primary_deltas") or []):
        key = str(delta.get("key") or "")
        if not key:
            continue
        delta_kind = str(delta.get("delta_kind") or "MEASURED")
        if key == "primary_offense" and delta_kind in {"UNMEASURED", "UNSUPPORTED", "MISSING"}:
            # Never render an unverified damage number as the build's damage change.
            continue
        if key == "primary_offense" and delta_kind == "ESTIMATED":
            delta = {**delta, "label": f"{delta.get('label') or 'Damage'} (estimate)"}
        resist = resist_by_key.get(key) or {}
        cap_state = str(resist.get("state") or "")
        abs_delta = delta.get("absolute_delta")
        pct = delta.get("percent_delta")
        try:
            abs_value = float(abs_delta) if abs_delta is not None else 0.0
        except (TypeError, ValueError):
            abs_value = 0.0
        direction = str(delta.get("direction") or "neutral")
        if direction == "neutral" and abs_value < 0:
            direction = "negative"
        elif direction == "neutral" and abs_value > 0:
            direction = "positive"
        range_text = ""
        if key.endswith("_res") and resist:
            from poe2value.items.formatting import format_resistance_range

            range_text = format_resistance_range(
                effective_current=resist.get("current"),
                effective_candidate=resist.get("candidate"),
                uncapped_current=resist.get("uncapped_current"),
                uncapped_candidate=resist.get("uncapped_candidate"),
                cap_current=resist.get("cap_current"),
                cap_candidate=resist.get("cap_candidate"),
            )
        rows.append(
            {
                "key": key,
                "label": delta.get("label") or key,
                "absolute_delta": abs_delta,
                "percent_delta": pct,
                "delta_text": _delta_text_from_outcome(delta),
                "range_text": range_text,
                "direction": direction,
                "emphasis": "critical" if cap_state == "CAP_LOST" else "medium",
                "cap_state": cap_state if cap_state in _DECISIVE_CAP_STATES else "",
                "cap_label": "",
                "delta_kind": delta_kind,
            }
        )
    for item in outcome.get("guardrails_applied") or []:
        code = str(item.get("code") or "")
        if code in _NOT_VIABLE_CODES:
            rows.append(
                {
                    "key": "cannot_equip",
                    "label": "Cannot equip",
                    "delta_text": str(item.get("reason") or "Not viable"),
                    "direction": "negative",
                    "emphasis": "critical",
                    "guardrail_code": code,
                    "absolute_delta": -1.0,
                    "percent_delta": None,
                    "marker": "!",
                }
            )
        elif code in _REQUIREMENT_CODES:
            rows.append(
                {
                    "key": "requirement",
                    "label": "Requirement",
                    "delta_text": str(item.get("reason") or "Requirement not met"),
                    "direction": "negative",
                    "emphasis": "critical",
                    "guardrail_code": code,
                    "absolute_delta": -1.0,
                    "percent_delta": None,
                    "marker": "!",
                }
            )
    # Buffer/overcap loss is a build-flexibility tradeoff even when effective
    # resistance stays capped. It has no generic metric delta, so surface the
    # structured resistance row directly.
    for resist in outcome.get("resistances") or []:
        delta = resist.get("buffer_delta")
        if delta is None:
            continue
        try:
            amount = float(delta)
        except (TypeError, ValueError):
            continue
        if abs(amount) < MATERIAL_LOSS_ABS:
            continue
        element = str(resist.get("element") or "").lower()
        rows.append(
            {
                "key": f"{element}_res_buffer",
                "label": f"{_ELEMENT_NAMES.get(element, element.title())} Res Buffer",
                "delta_text": f"{amount:+.0f}",
                "direction": "negative" if amount < 0 else "positive",
                "emphasis": "high" if amount <= -10 else "medium",
                "absolute_delta": amount,
                "percent_delta": None,
            }
        )
    return rows


def _delta_text_from_outcome(delta: dict[str, Any]) -> str:
    pct = delta.get("percent_delta")
    if pct is not None:
        try:
            return f"{float(pct):+.1f}%"
        except (TypeError, ValueError):
            pass
    abs_delta = delta.get("absolute_delta")
    if abs_delta is not None:
        try:
            return f"{float(abs_delta):+.1f}"
        except (TypeError, ValueError):
            return str(abs_delta)
    return ""


def _reason_lines(model: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    """Up to three strongest semantic reasons, and the title that frames them."""
    edge = model.get("current_edge") or {}
    edge_lines = [
        {"text": str(line.get("text") if isinstance(line, dict) else line).strip()}
        for line in (edge.get("lines") or [])
    ]
    edge_lines = [line for line in edge_lines if line["text"]]
    if edge_lines:
        return str(edge.get("title") or "WHY CURRENT ITEM WINS"), edge_lines[:MAX_REASONS]

    keep = [
        {"text": str(item.get("explanation") or "").strip()}
        for item in (model.get("why_not_upgrade") or [])
    ]
    keep = [line for line in keep if line["text"]]
    if keep:
        title = str(model.get("why_section_title") or "") or "WHY CURRENT ITEM WINS"
        return title, keep[:MAX_REASONS]

    gains = [
        {"text": str(item.get("explanation") or item.get("text") or "").strip()}
        for item in (model.get("why_reasons") or [])
    ]
    gains = [line for line in gains if _is_win_reason(line["text"])]
    if gains:
        return "WHY THIS ITEM WINS", gains[:MAX_REASONS]
    return "", []


# A bare axis delta — "-1.0% Offense", "+8.2% Defence" — is exactly what the BUILD
# IMPACT rows above already say, in the same numbers.
_BARE_AXIS_DELTA = re.compile(r"^[+\-−]?\d+(\.\d+)?%\s+\w+$")


def _is_win_reason(text: str) -> bool:
    """A reason the *candidate* wins: present, positive, and not a restated delta."""
    text = str(text or "").strip()
    if not text:
        return False
    if _BARE_AXIS_DELTA.match(text):
        return False
    # Upstream falls back to the worst trade-off when it has no improvement to name.
    # A line that opens with a loss is not a reason the item wins.
    return not text.lstrip("• ").startswith(("-", "−"))


def _quality_note(model: dict[str, Any]) -> str:
    """One truthful line for why an UNCERTAIN/PARTIAL/UNSUPPORTED result is what it is.

    Sourced from `EvaluationOutcome.evaluation_quality_reasons` — the same
    evidence-backed detail More Info shows — never an invented explanation and
    never an internal code or exception name. Empty when the evaluation is FULL
    quality, so an ordinary confident result never grows this line.
    """
    outcome = model.get("evaluation_outcome") or {}
    quality = str(outcome.get("evaluation_quality") or "")
    if not quality or quality == "FULL":
        return ""
    reasons = [
        str(item.get("detail") or "").strip() for item in outcome.get("evaluation_quality_reasons") or []
    ]
    reasons = [reason for reason in reasons if reason]
    if not reasons:
        return ""
    detail = reasons[0]
    return f"◐ {detail[0].upper()}{detail[1:]}" if detail else ""


def _semantic_notes(model: dict[str, Any], impact_rows: list[dict[str, Any]]) -> list[str]:
    """Short semantic warnings — never a restatement of a delta already shown."""
    notes: list[str] = []

    def add(text: str) -> None:
        if text and text not in notes:
            notes.append(text)

    # Why the result is uncertain/partial comes first: it reframes everything else
    # in the tooltip, so it must not be crowded out by the MAX_NOTES budget.
    add(_quality_note(model))

    # A cap break is the single most decision-relevant thing a tooltip can say, so it
    # is derived from the metric rows too: presentation dedupe legitimately drops the
    # RES_CAP_LOST *warning* once a row claims the same fact, and the semantic note
    # must still survive that.
    for row in list(model.get("rows") or []):
        if str(row.get("cap_state") or "") != "CAP_LOST":
            continue
        element = _element_of(row.get("key") or "")
        add(f"⚠ Breaks {element} Resistance cap" if element else "⚠ Breaks a resistance cap")

    for group in model.get("warning_groups") or []:
        for item in group.get("items") or []:
            code = str(item.get("code") or "")
            if code in _RAW_DELTA_WARNING_CODES:
                continue
            element = _element_of(item.get("metric") or "")
            if code == "RES_CAP_LOST":
                add(f"⚠ Breaks {element} Resistance cap" if element else "⚠ Breaks a resistance cap")
            elif code == "RES_DEFICIT_WORSENED":
                add(
                    f"⚠ {element} Resistance falls further below cap"
                    if element
                    else "⚠ Resistance falls further below cap"
                )
            elif code == "MAIN_SKILL_INVALID":
                add("⚠ Main skill can no longer be used")
            elif code == "BUILD_INVALID":
                add("⚠ Build does not resolve with this item")
            elif code == "RESOURCE_FAILURE":
                add("⚠ Resource reservation fails")

    for row in impact_rows:
        key = str(row.get("key") or "")
        pct = row.get("percent_delta")
        if pct is None:
            continue
        if key == "ehp" and float(pct) <= -LARGE_SURVIVABILITY_LOSS_PCT:
            add("⚠ Large survivability loss")
        if (
            key == "primary_offense"
            and str(row.get("delta_kind") or "MEASURED") in {"MEASURED", "MEASURED_ZERO"}
            and float(pct) <= -LARGE_DAMAGE_LOSS_PCT
        ):
            add("⚠ Large damage loss")

    return notes[:MAX_NOTES]


def _compared_with_line(model: dict[str, Any]) -> str:
    compared = model.get("compared_against") or {}
    parts = [
        str(compared.get("name") or "").strip(),
        str(compared.get("base_type") or "").strip(),
    ]
    label = ", ".join(part for part in parts if part)
    if not label:
        label = str(model.get("baseline_line") or "").strip()
    return f"Compared with: {label}" if label else ""


def _replacement_choices(model: dict[str, Any]) -> list[dict[str, Any]]:
    choices = list(model.get("replacement_choices") or [])
    if choices:
        return choices
    options = list((model.get("slot_options") or {}).get("options") or [])
    return options


def replacing_line(model: dict[str, Any]) -> str:
    """`Replacing: {item}`, or `Best: Ring 2 — {name}` when more than one legal slot.

    Jewel sockets are dynamic, per-build tree-node ids ("Jewel 11184") -- that
    is internal identity, never player copy (raw ids stay in Copy
    diagnostics). A jewel candidate with several legal placements instead gets
    a single best-fit line plus a truthful count of how many sockets were
    checked, never a socket-by-socket listing.

    Two-hand weapon candidates that would clear an equipped offhand are
    disclosed as a paired change: "Replacing: X (also removes offhand Y)".
    """
    outcome = model.get("evaluation_outcome") or {}
    choices = _replacement_choices(model)
    paired_offhand_cleared = model.get("paired_offhand_cleared")
    paired_offhand_slot = model.get("paired_offhand_slot") or ""
    paired_offhand_name = str(model.get("paired_offhand_name") or "").strip()
    if paired_offhand_cleared and paired_offhand_slot:
        # Production evaluation carries the verified removed item directly.
        # Retain choice/outcome fallbacks for older and synthetic callers.
        if not paired_offhand_name:
            for choice in choices:
                if choice.get("slot") == paired_offhand_slot:
                    paired_offhand_name = str(choice.get("replacing_item") or choice.get("item_name") or "").strip()
                    break
        if not paired_offhand_name:
            # Fallback: check the outcome's replacing_item if it matches the offhand slot
            if outcome.get("replacement_slot") == paired_offhand_slot:
                paired_offhand_name = str(outcome.get("replacing_item") or "").strip()

    if len(choices) > 1:
        best = next((item for item in choices if item.get("selected") or item.get("best")), choices[0])
        slot = str(best.get("slot") or outcome.get("replacement_slot") or "").strip()
        is_jewel = is_jewel_socket_pob_slot(slot)
        checked = f" · Checked {len(choices)} jewel sockets" if is_jewel else ""
        if best.get("empty") or best.get("replacing_empty_slot") or outcome.get("replacing_empty_slot"):
            if is_jewel:
                return f"Best fit: Empty jewel socket{checked}"
            return f"Best: {slot} — Equip to empty slot" if slot else "Equip to empty slot"
        name = str(
            best.get("replacing_item")
            or best.get("item_name")
            or outcome.get("replacing_item")
            or ""
        ).strip()
        if name:
            if is_jewel:
                return f"Best fit: Replacing {name}{checked}"
            suffix = f" (also removes {paired_offhand_name})" if paired_offhand_cleared and paired_offhand_name else ""
            return f"Best: {slot} — {name}{suffix}" if slot else f"Replacing: {name}{suffix}"
        if is_jewel:
            return f"Best fit found{checked}"
        return f"Best: {slot}" if slot else ""
    if outcome.get("replacing_empty_slot"):
        slot = str(outcome.get("replacement_slot") or "").strip()
        if is_jewel_socket_pob_slot(slot):
            return "Equip to empty jewel socket"
        return f"Equip to empty {slot}" if slot else "Equip to empty slot"
    name = str(outcome.get("replacing_item") or "").strip()
    if not name:
        compared = model.get("compared_against") or {}
        name = str(compared.get("name") or "").strip()
    if name:
        suffix = f" (also removes {paired_offhand_name})" if paired_offhand_cleared and paired_offhand_name else ""
        return f"Replacing: {name}{suffix}"
    compared = _compared_with_line(model)
    if paired_offhand_cleared and paired_offhand_name:
        return f"{compared} (also removes {paired_offhand_name})" if compared else f"Also removes {paired_offhand_name}"
    return compared


def slot_verdict_lines(model: dict[str, Any]) -> list[dict[str, Any]]:
    """One line per legal replacement when more than one slot is in play.

    Never for jewel sockets: raw node ids ("Jewel 11184") are not player
    copy, and a full per-socket listing is exactly the "dump the evaluated
    socket list" presentation `replacing_line()`'s single best-fit + count
    summary exists to avoid. Suppressed entirely here rather than relabeled,
    since ordinal "Socket N" labels would still imply an ordering/identity
    PoB does not actually expose.
    """
    choices = _replacement_choices(model)
    if len(choices) < 2:
        return []
    if is_jewel_socket_pob_slot(str(choices[0].get("slot") or "")):
        return []
    lines: list[dict[str, Any]] = []
    for choice in choices:
        slot = str(choice.get("slot") or "").strip()
        if not slot:
            continue
        empty = bool(choice.get("empty") or choice.get("replacing_empty_slot"))
        if empty:
            text = f"{slot}: Equip to empty slot"
        else:
            label = str(choice.get("verdict_label") or "").strip() or str(choice.get("verdict") or "").replace("_", " ")
            text = f"{slot}: {label}" if label else slot
        lines.append(
            {
                "slot": slot,
                "text": text,
                "empty": empty,
                "best": bool(choice.get("selected") or choice.get("best")),
                "verdict": str(choice.get("verdict") or ""),
                "final_score": choice.get("final_score"),
            }
        )
    return lines


def verdict_headline(model: dict[str, Any]) -> str:
    """The one verdict line: `MINOR UPGRADE`, or `POTENTIAL UPGRADE · Partial evaluation`."""
    outcome = model.get("evaluation_outcome") or {}
    label = str(outcome.get("verdict_label") or model.get("verdict_label") or model.get("verdict") or "").strip()
    if str(outcome.get("verdict") or "") == "UNCERTAIN":
        return f"{label} · Partial comparison" if label else "UNCERTAIN · Partial comparison"
    if str(outcome.get("evaluation_quality") or "") == "PARTIAL":
        quality = str(outcome.get("quality_label") or "").strip()
        if label and quality:
            return f"{label} · {quality}"
    return label


def apply_compact_tooltip(model: dict[str, Any]) -> None:
    """Compress `model` in place into the primary tooltip, moving detail to the Companion.

    Idempotent: applying it twice leaves the model unchanged.
    """
    if model.get("compact_surface"):
        return

    model["companion"] = build_companion_analysis(model)

    outcome = model.get("evaluation_outcome") or {}
    if outcome:
        rating = outcome.get("final_score")
    else:
        rating = (model.get("value") or {}).get("rating")
        if rating is None:
            rating = model.get("rating")
    # Score is carried for More Info only; the compact surface never renders it.
    if rating is not None:
        rating = float(rating)
        model["score_value"] = rating
        model["score_text"] = score_text(rating)
        model["score_band"] = score_band(rating)
    else:
        model["score_value"] = None
        model["score_text"] = ""
        model["score_band"] = ""
    headline = verdict_headline(model)
    model["verdict_headline"] = headline
    # Compact never shows a score. The one verdict is painted as the headline;
    # `overall_line` keeps the same string for the (hidden) verdict band / tests.
    model["score_headline"] = ""
    model["score_class"] = str(model.get("verdict_class") or outcome.get("verdict_class") or "")

    candidate_rows = list(model.get("rows") or [])
    if outcome:
        extra = [
            row
            for row in rows_from_outcome_deltas(outcome)
            if (
                str(row.get("key") or "") in {"cannot_equip", "requirement", "cast_attack_speed"}
                or str(row.get("key") or "").endswith("_res_buffer")
            )
            and not any(str(existing.get("key") or "") == row["key"] for existing in candidate_rows)
        ]
        candidate_rows = extra + candidate_rows
        candidate_rows = _inject_outcome_loss_candidates(candidate_rows, outcome)
    impact_rows = select_impact_rows(candidate_rows)
    reasons_title, reasons = _reason_lines(model)
    notes = _semantic_notes(model, impact_rows)
    choices = _replacement_choices(model)
    slot_lines = slot_verdict_lines(model)
    replace_line = replacing_line(model)

    model["impact_title"] = "BUILD IMPACT"
    model["impact_rows"] = impact_rows
    model["primary_reasons_title"] = reasons_title
    model["primary_reasons"] = reasons
    model["critical_notes"] = notes
    model["replacing_line"] = replace_line
    model["compared_with_line"] = replace_line
    model["slot_verdict_lines"] = slot_lines
    model["replacement_choices"] = choices
    profile_label = str(
        (model.get("value") or {}).get("profile_label")
        or model.get("profile_indicator")
        or ""
    ).strip()
    model["profile_line"] = f"Profile: {profile_label}" if profile_label else ""
    # The score (and Build Value delta, which is the same number minus 50) is More Info.
    model["build_value_line"] = ""
    model["overall_line"] = headline

    # The tooltip renders `impact_rows`; companion still reads the uncompressed copy
    # it captured above.
    model["rows"] = impact_rows
    for field in MOVED_TO_COMPANION:
        model[field] = []
    model["upgrade_path"] = {}
    model["risk_summary"] = {}
    model["current_edge"] = {}
    model["why_reasons"] = []
    model["best_use"] = None
    model["slot_options"] = {}
    model["slot_alternate_line"] = ""
    model["best_slot_headline"] = ""
    model["offense_summary"] = ""
    model["warnings"] = []
    model["warning_groups"] = []
    model["value"] = None
    model["recommendation_tag"] = ""
    model["verdict_explanation"] = ""
    model["why_section_title"] = ""
    # The Companion expands on the tooltip; it never restates it.
    shown = [line["text"] for line in reasons] + list(notes)
    prune_companion_duplicates(model["companion"], shown)

    model["sections"] = [{"id": section_id, "visible": True} for section_id in COMPACT_SECTION_IDS]
    model["section_ids"] = list(COMPACT_SECTION_IDS)
    # Rebuild More Info after compact fields (replacing line, impact rows, choices)
    # are in place so KEY IMPACT matches the compact ranker.
    from poe2value.items.more_info import build_more_info

    model["more_info"] = build_more_info(model)
    model["compact_surface"] = True
