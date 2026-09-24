"""Slice 3 internal: weapon-set-qualified component observations.

Everything here is explicit and lazy: ordinary Item Check
(:func:`exilelens.items.evaluation.evaluate_item`) never calls this module,
never enumerates both weapon sets, and pays zero extra recalculation frames
for its existence.

Concepts:

- :class:`CalculationContext` qualifies *where* a component was measured
  (weapon set 1/2 plus the active skill-set id for cache safety).
- :class:`ContextualComponentReference` composes a
  :class:`ComponentReference` with its context. Effect semantic identity
  itself stays context-independent.
- :class:`PhysicalEvaluationTarget` names the exact physical PoB weapon slot
  a candidate is placed in, without changing public logical-slot semantics.

No function here infers cross-set interaction, trigger relationships,
practical DPS, or whole-build verdicts. Deltas returned are component
evidence only.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from exilelens.items.effect_components import (
    MAX_EFFECTS,
    MAX_WEAPON_CONTEXTS,
    CalculationContext,
    ComponentReference,
    ContextualComponentReference,
    normalize_context_catalog,
)
from exilelens.items.slots import PhysicalEvaluationTarget, ProductSlot

__all__ = [
    "CalculationContext",
    "ContextualComponentReference",
    "PhysicalEvaluationTarget",
    "MAX_EFFECTS",
    "MAX_WEAPON_CONTEXTS",
    "read_component_in_context",
    "list_component_contexts",
    "evaluate_physical_candidate",
    "resolve_physical_target",
]


def resolve_physical_target(
    logical_product_slot: ProductSlot | str, weapon_set: int
) -> PhysicalEvaluationTarget:
    """Map a logical product weapon slot to its exact physical target in one set."""
    return PhysicalEvaluationTarget.from_parts(logical_product_slot, weapon_set)


def _context_from_bridge(payload: Mapping[str, Any] | None, weapon_set: int) -> CalculationContext:
    active_skill_set = ""
    if isinstance(payload, Mapping):
        active_skill_set = str(payload.get("active_skill_set_id") or "")
    return CalculationContext(weapon_set=int(weapon_set), active_skill_set_id=active_skill_set)


def read_component_in_context(
    engine: Any,
    reference: dict[str, Any] | ComponentReference,
    weapon_set: int,
) -> dict[str, Any]:
    """Read one exact component under an explicit weapon-set context.

    Returns the bridge's context-qualified observation
    (``MEASURED`` / ``UNAVAILABLE`` / ``NOT_VALID_IN_CONTEXT``), qualified
    with a :class:`ContextualComponentReference` for cache-safe handling.
    """
    raw = reference.to_dict() if isinstance(reference, ComponentReference) else dict(reference)
    observed = engine.read_effect_metrics(raw, weapon_set=int(weapon_set))
    component = ComponentReference.from_dict(observed.get("reference", raw))
    context = _context_from_bridge(observed.get("context"), int(weapon_set))
    qualified = ContextualComponentReference(component=component, context=context)
    return {**observed, "qualified_reference": qualified.to_dict()}


def list_component_contexts(
    engine: Any,
    references: list[dict[str, Any] | ComponentReference],
    *,
    maximum: int = MAX_EFFECTS,
) -> dict[str, Any]:
    """Explicit bounded diagnostic matrix: effects x weapon sets 1..2.

    Never called by ordinary flow. At most ``maximum`` effects (default 8)
    by at most 2 contexts are read; truncation is reported, not hidden.
    """
    limit = max(1, min(int(maximum), MAX_EFFECTS))
    rows: list[dict[str, Any]] = []
    total = 0
    for raw in list(references)[:limit]:
        reference = raw.to_dict() if isinstance(raw, ComponentReference) else dict(raw)
        for weapon_set in (1, 2):
            total += 1
            observed = engine.read_effect_metrics(reference, weapon_set=weapon_set)
            rows.append(
                {
                    "reference": reference,
                    "context": {"weapon_set": weapon_set},
                    "status": observed.get("status"),
                    "reason": observed.get("reason"),
                    "metrics": observed.get("output"),
                    "frames": observed.get("frames"),
                }
            )
    payload = normalize_context_catalog(
        {"contexts": rows, "total_contexts": total}, maximum=limit
    )
    return payload


def evaluate_physical_candidate(
    engine: Any,
    reference: dict[str, Any] | ComponentReference,
    logical_product_slot: ProductSlot | str,
    weapon_set: int,
    item_raw: str,
) -> dict[str, Any]:
    """Measure one component with a candidate in one exact physical slot/set.

    Returns baseline / candidate / delta / restore plus the physical target
    record. Component evidence only.
    """
    raw = reference.to_dict() if isinstance(reference, ComponentReference) else dict(reference)
    target = resolve_physical_target(logical_product_slot, int(weapon_set))
    result = engine.evaluate_effect_candidate(
        raw,
        weapon_set=target.weapon_set,
        physical_slot=target.physical_pob_slot,
        item_raw=str(item_raw),
    )
    return {**result, "physical_target": target.to_dict()}
