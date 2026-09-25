from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EvaluationLimitationDefinition:
    """Expected evaluation limitation — not an application fault."""

    code: str
    title: str
    explanation: str
    user_guidance: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "title": self.title,
            "explanation": self.explanation,
            "user_guidance": self.user_guidance,
            "kind": "evaluation_limitation",
        }


_EVALUATION_LIMITATIONS: tuple[EvaluationLimitationDefinition, ...] = (
    EvaluationLimitationDefinition(
        "OFFENSE_UNSUPPORTED",
        "Unsupported main-skill comparison",
        "Path of Building cannot model the selected main-skill comparison for this build.",
        "Treat the verdict as informational only; validate in Path of Building.",
    ),
    EvaluationLimitationDefinition(
        "OFFENSE_UNAVAILABLE",
        "Damage not reported",
        "Path of Building did not report damage for the main skill.",
        "Check the skill setup; ExileLens will not invent a directional damage verdict.",
    ),
    EvaluationLimitationDefinition(
        "OFFENSE_MECHANICS_PARTIAL",
        "Partial mechanic coverage",
        "Some build mechanics are not fully measured for this comparison.",
        "Use UNCERTAIN-style guidance; verify important mechanics manually.",
    ),
    EvaluationLimitationDefinition(
        "OFFENSE_FALLBACK_COMPONENT",
        "Fallback damage component",
        "Part of the damage estimate relies on a fallback path in Path of Building.",
        "Treat small deltas with extra caution.",
    ),
    EvaluationLimitationDefinition(
        "OFFENSE_COMPOSITION_PARTIAL",
        "Partial damage composition",
        "Not every damage component could be attributed for this item.",
        "Prefer qualitative tradeoffs over precise upgrade/downgrade calls.",
    ),
    EvaluationLimitationDefinition(
        "PRIMARY_METRIC_LOW_CONFIDENCE",
        "Low-confidence primary metric",
        "The main comparison metric could not be identified with confidence.",
        "Review the build's primary skill and configuration in Path of Building.",
    ),
    EvaluationLimitationDefinition(
        "EHP_UNAVAILABLE",
        "Effective hit pool unavailable",
        "Path of Building did not report effective hit pool for this comparison.",
        "Defensive tradeoffs may be incomplete in the presentation.",
    ),
    EvaluationLimitationDefinition(
        "MAX_HIT_UNAVAILABLE",
        "Maximum hit unavailable",
        "Maximum hit taken was not reported.",
        "Do not infer tankiness from missing data.",
    ),
    EvaluationLimitationDefinition(
        "RESISTANCE_UNAVAILABLE",
        "Resistance values missing",
        "One or more resistance axes were not reported.",
        "Check resist caps manually if they matter for this item.",
    ),
    EvaluationLimitationDefinition(
        "UNRESOLVED_SLOT",
        "Slot unresolved",
        "The replacement slot could not be resolved for this evaluation.",
        "Equip the item in Path of Building and try again.",
    ),
    EvaluationLimitationDefinition(
        "REPLACEMENT_NOT_APPLIED",
        "Replacement not applied",
        "Path of Building did not equip the candidate in the selected slot.",
        "Retry after confirming the slot in Path of Building.",
    ),
    EvaluationLimitationDefinition(
        "NO_METRICS",
        "No metrics returned",
        "Path of Building returned no metrics for this comparison.",
        "Copy the item again after the build is ready.",
    ),
    EvaluationLimitationDefinition(
        "INVALID_METRICS",
        "Invalid metrics",
        "Path of Building returned non-finite values for required metrics.",
        "Reload the build; if it persists, copy diagnostics.",
    ),
)

EVALUATION_LIMITATION_CATALOG: dict[str, EvaluationLimitationDefinition] = {
    row.code: row for row in _EVALUATION_LIMITATIONS
}


def describe_evaluation_limitation(code: str) -> EvaluationLimitationDefinition | None:
    return EVALUATION_LIMITATION_CATALOG.get(str(code or "").strip())
