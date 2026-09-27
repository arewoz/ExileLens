"""Item Check wiring for the Way of the Stonefist glove transformation (CORPUS-02C).

Kept separate from ``evaluation.py`` so the evaluation pipeline only asks three
questions: does the build transform gloves, what does PoB measure for the
candidate, and what does PoB measure for the equipped gloves.
"""

from __future__ import annotations

import logging
from typing import Any

from exilelens.items.stonefist import FISTS, TransformResult, transformer_for
from exilelens.items.stonefist_rolls import BOUND_RULES

logger = logging.getLogger(__name__)

__all__ = [
    "TransformResult", "effective_item", "equipped_gloves_transform", "safe_transform",
    "stonefist_applies", "transform_report", "unresolved_reasons",
]


def stonefist_applies(build_info: dict[str, Any]) -> bool:
    return any(
        isinstance(t, dict) and t.get("slot") == "Gloves" and t.get("transformed_base") == FISTS
        for t in (build_info.get("item_base_transforms") or [])
    )


def safe_transform(engine: Any, item_raw: str, bound: str = "none", alternative: int | None = None) -> TransformResult:
    try:
        return transformer_for(engine, BOUND_RULES[bound]).transform(engine, item_raw, alternative)
    except Exception as exc:  # noqa: BLE001 - an item PoB cannot parse is handled by the normal path
        logger.info("stonefist transform unavailable: %s", exc)
        return TransformResult(ok=False, unresolved=[f"the item could not be read for transformation ({exc})"])


def equipped_gloves_transform(engine: Any, override_raw: str | None) -> TransformResult | None:
    """The equipped gloves as the character wears them, or None when there are none."""
    raw = override_raw
    if raw is None:
        try:
            equipment = engine.get_equipment() or {}
        except Exception:  # noqa: BLE001
            logger.exception("could not read equipped gloves for the Stonefist transformation")
            return TransformResult(ok=False, unresolved=["the equipped gloves could not be read"])
        entry = next(
            (e for e in (equipment.get("equipment") or []) if isinstance(e, dict) and e.get("slot") == "Gloves"),
            None,
        )
        if not entry or not entry.get("equipped"):
            return None
        raw = str(entry.get("raw") or "")
    if not raw:
        return None
    return safe_transform(engine, raw)


def effective_item(item: dict[str, Any], transform: TransformResult | None) -> dict[str, Any]:
    """The item as PoB measured it: the transformed base when the transformation applied."""
    if transform is None or not transform.ok or not transform.base_name:
        return item
    return {**item, "base_type": transform.base_name}


def unresolved_reasons(*transforms: TransformResult | None) -> list[str]:
    reasons: list[str] = []
    for transform in transforms:
        if transform is not None and not transform.ok:
            reasons.extend(r for r in transform.unresolved if r not in reasons and r != "not a glove item")
    return reasons


def transform_report(
    pob_slot: str, candidate: TransformResult | None, baseline: TransformResult | None,
) -> dict[str, Any] | None:
    if pob_slot != "Gloves" or (candidate is None and baseline is None):
        return None
    return {
        "candidate": candidate.to_dict() if candidate is not None else None,
        "baseline": baseline.to_dict() if baseline is not None else None,
    }
