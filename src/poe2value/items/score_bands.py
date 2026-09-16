"""Numeric reading of the canonical 0-100 candidate score.

This module publishes numbers and internal band ids only. It never publishes a
verdict word: the one player-facing verdict is `EvaluationOutcome.verdict`
(`poe2value.items.evaluation_outcome`), classified from the same final score.
"""

from __future__ import annotations

from poe2value.items.value_profiles import rating_band


def score_band(rating: float) -> str:
    """Internal band id for a 0-100 rating (not a player-facing label)."""
    return rating_band(float(rating)).value


def score_text(rating: float) -> str:
    return f"{float(rating):.0f} / 100"
