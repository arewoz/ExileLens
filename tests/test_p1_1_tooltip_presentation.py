"""P1.1 — Tooltip Presentation Polish: deterministic presentation-layer regression coverage.

Covers the compact Item Check tooltip's compression policy (`items.compact_tooltip`),
the verdict-reason copy it depends on (`items.evaluation_outcome`,
`items.presentation_copy`), and the truthfulness boundary of the UNCERTAIN/PARTIAL
one-line explanation added in P1.1. These are presentation-only unit tests: no PoB
worker, no real evaluation, deterministic dict fixtures only.
"""

from __future__ import annotations

import pytest

from exilelens.items import compact_tooltip
from exilelens.items.compact_tooltip import (
    MAX_NOTES,
    MAX_REASONS,
    apply_compact_tooltip,
    select_impact_rows,
    verdict_headline,
)
from exilelens.items.evaluation_outcome import SCORE_SCALE, decide_verdict, EvaluationQuality
from exilelens.items.presentation_copy import verdict_subtitle

pytestmark = pytest.mark.itemcheck


# --------------------------------------------------------------------------- helpers


def _outcome(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "evaluation_quality": "FULL",
        "evaluation_quality_reasons": [],
        "final_score": 62.0,
        "verdict": "MEANINGFUL_UPGRADE",
        "verdict_label": "MEANINGFUL UPGRADE",
        "verdict_class": "upgrade",
        "quality_label": "",
        "verdict_reason": "Net score +12.0 against the current item.",
        "guardrails_applied": [],
        "critical_tradeoffs": [],
        "resistances": [],
        "all_deltas": [],
    }
    base.update(overrides)
    return base


def _impact_row(key: str, *, pct: float, emphasis: str = "medium") -> dict[str, object]:
    return {
        "key": key,
        "label": key.replace("_", " ").title(),
        "percent_delta": pct,
        "absolute_delta": None,
        "delta_text": f"{pct:+.1f}%",
        "direction": "positive" if pct > 0 else "negative",
        "emphasis": emphasis,
        "cap_state": "",
    }


# ----------------------------------------------------------------- BV / score wording


def test_default_verdict_reason_never_says_build_value() -> None:
    """The common, no-guardrail verdict reason used to read 'Net build value +X...'.

    Product feedback flagged 'BV'/'Build Value' terminology as unclear. The text is
    still the same truthful net-score-change fact; only the wording changed.
    """
    decision = decide_verdict(75.0, [], EvaluationQuality.FULL)
    assert "build value" not in decision.reason.lower()
    assert "Net score" in decision.reason
    expected_delta = 75.0 - SCORE_SCALE.equivalent
    assert f"{expected_delta:+.1f}" in decision.reason


def test_no_change_subtitle_never_says_build_value() -> None:
    text = verdict_subtitle("NO_CHANGE", {}, {})
    assert "build value" not in text.lower()
    assert "score" in text.lower()


def test_compact_surface_never_exposes_score_or_build_value_text() -> None:
    """End-to-end: the compact tooltip model must not leak score/BV wording anywhere
    a player reads by default (headline, reasons, notes)."""
    model = {
        "item_name": "Vaal Regalia",
        "evaluation_outcome": _outcome(),
        "rows": [_impact_row("primary_offense", pct=11.4)],
        "why_reasons": [{"explanation": "+11% Spell Damage from higher Energy Shield rolls"}],
    }
    apply_compact_tooltip(model)
    surface_text = " ".join(
        [
            str(model.get("verdict_headline") or ""),
            str(model.get("overall_line") or ""),
            " ".join(line["text"] for line in model.get("primary_reasons") or []),
            " ".join(model.get("critical_notes") or []),
        ]
    ).lower()
    assert "build value" not in surface_text
    assert "bv" not in surface_text.split()
    # And the score itself must not render in the compact surface at all.
    assert model["value"] is None
    assert model["build_value_line"] == ""


# ------------------------------------------------------------------- UNCERTAIN/PARTIAL


def test_quality_note_empty_for_full_quality() -> None:
    model = {"evaluation_outcome": _outcome(evaluation_quality="FULL")}
    assert compact_tooltip._quality_note(model) == ""


def test_quality_note_surfaces_truthful_partial_reason() -> None:
    model = {
        "evaluation_outcome": _outcome(
            evaluation_quality="PARTIAL",
            evaluation_quality_reasons=[
                {"code": "OFFENSE_UNAVAILABLE", "detail": "the main skill's damage change could not be measured"}
            ],
        )
    }
    note = compact_tooltip._quality_note(model)
    assert note.startswith("◐ ")
    assert "damage change could not be measured" in note
    # Capitalized, and not an internal code leaking through.
    assert "OFFENSE_UNAVAILABLE" not in note


def test_uncertain_verdict_headline_reads_as_uncertain_not_a_weak_score() -> None:
    outcome = _outcome(
        verdict="UNCERTAIN",
        verdict_label="UNCERTAIN",
        evaluation_quality="PARTIAL",
        quality_label="Partial evaluation",
    )
    headline = verdict_headline({"evaluation_outcome": outcome})
    assert headline == "UNCERTAIN · Partial comparison"


def test_uncertain_result_includes_reason_in_compact_notes() -> None:
    """The important truthfulness requirement: UNCERTAIN must not look like a silent
    weak upgrade/downgrade — the compact surface must carry a one-line reason."""
    model = {
        "item_name": "Unset Ring",
        "evaluation_outcome": _outcome(
            verdict="UNCERTAIN",
            verdict_label="UNCERTAIN",
            final_score=50.0,
            evaluation_quality="PARTIAL",
            quality_label="Partial evaluation",
            evaluation_quality_reasons=[
                {"code": "OFFENSE_UNAVAILABLE", "detail": "main damage could not be measured for this build"}
            ],
            verdict_reason="Partial comparison: main damage could not be measured for this build.",
        ),
        "rows": [],
    }
    apply_compact_tooltip(model)
    assert model["verdict_headline"] == "UNCERTAIN · Partial comparison"
    notes = model["critical_notes"]
    assert notes, "UNCERTAIN result must carry at least one explanatory note"
    assert any("main damage could not be measured" in note.lower() for note in notes)


def test_quality_note_takes_priority_within_max_notes_budget() -> None:
    """The uncertainty reason must survive the MAX_NOTES cap even when a resistance
    cap-break warning also wants a slot."""
    model = {
        "evaluation_outcome": _outcome(
            evaluation_quality="PARTIAL",
            evaluation_quality_reasons=[{"code": "OFFENSE_UNAVAILABLE", "detail": "damage could not be measured"}],
        ),
        "rows": [{"key": "fire_res", "cap_state": "CAP_LOST"}],
    }
    notes = compact_tooltip._semantic_notes(model, [])
    assert len(notes) <= MAX_NOTES
    assert notes[0].startswith("◐")
    assert "damage could not be measured" in notes[0].lower()


# ------------------------------------------------------------------------- "Why" caps


def test_primary_reasons_capped_at_three() -> None:
    model = {
        "evaluation_outcome": _outcome(),
        "why_reasons": [{"explanation": f"+{n}% Some Win Reason {n}"} for n in range(1, 6)],
        "rows": [],
    }
    apply_compact_tooltip(model)
    assert len(model["primary_reasons"]) <= MAX_REASONS
    assert len(model["primary_reasons"]) == 3


# ------------------------------------------------------------------- impact selection


def test_select_impact_rows_keeps_a_material_loss_even_when_budget_is_full_of_gains() -> None:
    """A SIDEGRADE/TRADEOFF result (damage up, defense down) must not collapse to an
    all-gain view: at least one material loss row must survive selection."""
    rows = [_impact_row("primary_offense", pct=8.0)]
    rows += [_impact_row(f"gain_{n}", pct=2.0) for n in range(4)]
    rows.append({**_impact_row("ehp", pct=-12.0), "emphasis": "critical"})
    selected = select_impact_rows(rows, limit=5)
    assert any(row["key"] == "ehp" for row in selected)


def test_select_impact_rows_respects_row_limit() -> None:
    rows = [_impact_row(f"metric_{n}", pct=float(n + 1)) for n in range(10)]
    selected = select_impact_rows(rows, limit=5)
    assert len(selected) <= 5


# ------------------------------------------------------------------------- rounding


def test_delta_text_from_outcome_rounds_to_one_decimal() -> None:
    delta = {"percent_delta": 8.734829}
    text = compact_tooltip._delta_text_from_outcome(delta)
    assert text == "+8.7%"
    assert "8.734829" not in text
