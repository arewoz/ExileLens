"""Equipment requirement validation from simulated PoB before/after metrics."""

from __future__ import annotations

from typing import Any

ATTR_FIELDS = (
    ("Str", "strength"),
    ("Dex", "dexterity"),
    ("Int", "intelligence"),
    ("Strength", "strength"),
    ("Dexterity", "dexterity"),
    ("Intelligence", "intelligence"),
)
_ATTR_EPS = 0.05


def _num(raw: dict[str, Any], field: str) -> float | None:
    if field not in raw:
        return None
    value = raw.get(field)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_known(raw: dict[str, Any], *fields: str) -> float | None:
    for field in fields:
        value = _num(raw, field)
        if value is not None:
            return value
    return None


def _attribute_requirement_detail(metric: str, required: float | None, current: float | None) -> str:
    label = metric.title()
    req_text = str(int(round(required))) if required is not None else "?"
    cur_text = str(int(round(current))) if current is not None else "?"
    return f"Requires {req_text} {label} — current {cur_text}"


def attribute_requirement_warnings(
    raw_current: dict[str, Any],
    raw_candidate: dict[str, Any],
) -> list[dict[str, Any]]:
    """Requirement shortfalls on the simulated candidate build (authoritative after swap)."""
    warnings: list[dict[str, Any]] = []
    seen: set[str] = set()
    for field, metric in ATTR_FIELDS:
        if metric in seen:
            continue
        cur = _num(raw_current, field)
        cand = _num(raw_candidate, field)
        req_cur = _first_known(raw_current, f"{field}Req", f"Required{field}")
        req_cand = _first_known(raw_candidate, f"{field}Req", f"Required{field}")
        missing_cur = _num(raw_current, f"Missing{field}")
        missing_cand = _num(raw_candidate, f"Missing{field}")
        if missing_cur is None and cur is not None and req_cur is not None:
            missing_cur = max(0.0, req_cur - cur)
        if missing_cand is None and cand is not None and req_cand is not None:
            missing_cand = max(0.0, req_cand - cand)
        if missing_cand is None:
            continue
        seen.add(metric)
        if missing_cand > _ATTR_EPS:
            required = req_cand if req_cand is not None else req_cur
            warnings.append(
                {
                    "code": "ATTRIBUTE_REQUIREMENT_LOST",
                    "severity": "critical",
                    "metric": metric,
                    "before": cur,
                    "after": cand,
                    "detail": _attribute_requirement_detail(metric, required, cand),
                }
            )
        elif (missing_cur or 0.0) > _ATTR_EPS and missing_cand <= _ATTR_EPS:
            warnings.append(
                {
                    "code": "ATTRIBUTE_REQUIREMENT_REACHED",
                    "severity": "info",
                    "metric": metric,
                    "before": cur,
                    "after": cand,
                    "detail": f"{metric.title()} requirement reached",
                }
            )
    return warnings
