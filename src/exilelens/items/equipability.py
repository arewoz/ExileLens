"""TRUST-01A: can the loaded character equip the candidate item?

Candidate-own requirement checks built only from Path of Building's own numbers:

* the item's requirements: `item.requirements.level` and the post-local-mod
  `strMod` / `dexMod` / `intMod` (bridge `item_summary`: `level_req`, `req_str`, `req_dex`, `req_int`);
* the loaded character level (`CharacterLevel`, from PoB's `build.characterLevel`);
* the character's attributes with the candidate equipped (`Str` / `Dex` / `Int` of the simulated
  candidate build -- the item's own attribute bonuses count, exactly as in PoB's requirement check).

Nothing is estimated. A requirement PoB did not report is `UNKNOWN`, which is never a failure and
never a pass. Post-swap breakage of *other* equipped items stays with `ATTRIBUTE_REQUIREMENT_LOST`
(`requirement_gates`); this module only answers whether the candidate itself can be worn.
"""

from __future__ import annotations

import math
from typing import Any, Mapping

EQUIP_WARNING_CODE = "EQUIP_REQUIREMENT_NOT_MET"

PASS = "PASS"
FAIL = "FAIL"
UNKNOWN = "UNKNOWN"

EQUIPPABLE = "EQUIPPABLE"
NOT_EQUIPPABLE = "NOT_EQUIPPABLE"
PARTIAL = "PARTIAL"

# (kind, player label, item-summary field, raw metric field)
_ATTRIBUTES = (
    ("strength", "Strength", "req_str", "Str"),
    ("dexterity", "Dexterity", "req_dex", "Dex"),
    ("intelligence", "Intelligence", "req_int", "Int"),
)


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _check(kind: str, status: str, required: float | None, available: float | None, source: str, detail: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "status": status,
        "required": required,
        "available": available,
        "source": source,
        "detail": detail,
    }


def _level_check(item: Mapping[str, Any], raw_current: Mapping[str, Any]) -> dict[str, Any]:
    source = "pob:item.requirements.level vs build.characterLevel"
    required = _number(item.get("level_req"))
    available = _number(raw_current.get("CharacterLevel"))
    if required is None or available is None:
        return _check("level", UNKNOWN, required, available, source, "")
    if required <= available:
        return _check("level", PASS, required, available, source, "")
    detail = f"Requires level {int(required)} · Character is level {int(available)}"
    return _check("level", FAIL, required, available, source, detail)


def _attribute_check(
    kind: str, label: str, item_field: str, metric: str,
    item: Mapping[str, Any], raw_candidate: Mapping[str, Any],
) -> dict[str, Any]:
    source = f"pob:item.requirements.{item_field[4:]}Mod vs output.{metric} (candidate equipped)"
    required = _number(item.get(item_field))
    available = _number(raw_candidate.get(metric))
    if required is None:
        return _check(kind, UNKNOWN, None, available, source, "")
    if required <= 0:
        return _check(kind, PASS, required, available, source, "")
    if available is None:
        return _check(kind, UNKNOWN, required, None, source, "")
    # PoB attributes and requirements are whole numbers; compare as PoB does.
    if required <= available:
        return _check(kind, PASS, required, available, source, "")
    detail = f"Requires {int(required)} {label} · Character has {int(available)}"
    return _check(kind, FAIL, required, available, source, detail)


def build_equipability(
    item: Mapping[str, Any] | None,
    raw_current: Mapping[str, Any] | None,
    raw_candidate: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Structured candidate-own equipability from PoB's item summary and simulated metrics."""
    item = item or {}
    raw_current = raw_current or {}
    raw_candidate = raw_candidate or {}
    checks = [_level_check(item, raw_current)]
    checks.extend(
        _attribute_check(kind, label, item_field, metric, item, raw_candidate)
        for kind, label, item_field, metric in _ATTRIBUTES
    )
    failed = [check for check in checks if check["status"] == FAIL]
    if failed:
        status = NOT_EQUIPPABLE
    elif any(check["status"] == UNKNOWN for check in checks):
        status = PARTIAL
    else:
        status = EQUIPPABLE
    return {
        "status": status,
        "checks": checks,
        "blocking_reasons": [check["detail"] for check in failed],
    }


# Compact copy: the most important failure first, then at most one more.
_COMPACT_MAX_REASONS = 2


def equipability_warnings(equipability: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """One blocking warning (feeds the canonical guardrail) when any candidate-own check FAILs."""
    failed = [check for check in (equipability or {}).get("checks") or [] if check.get("status") == FAIL]
    if not failed:
        return []
    reasons = [str(check["detail"]) for check in failed][:_COMPACT_MAX_REASONS]
    return [
        {
            "code": EQUIP_WARNING_CODE,
            "severity": "critical",
            "metric": ",".join(str(check["kind"]) for check in failed),
            "before": failed[0].get("available"),
            "after": failed[0].get("required"),
            "detail": "; ".join(reasons),
        }
    ]


def failed_attribute_metrics(equipability: Mapping[str, Any] | None) -> set[str]:
    """Attribute metrics (`strength` ...) the candidate itself cannot meet."""
    attributes = {kind for kind, *_ in _ATTRIBUTES}
    return {
        str(check["kind"])
        for check in (equipability or {}).get("checks") or []
        if check.get("status") == FAIL and check.get("kind") in attributes
    }
