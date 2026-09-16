"""Validate and repair a generated trade2 search body before it is sent.

MARKET-01B12. A malformed query used to reach the server and come back as HTTP 400,
which costs a request from a scarce budget and tells the user nothing. The generator bug
that caused it is fixed, but the class of failure is worth closing structurally: the
query is checked locally, one bad optional feature is dropped rather than the whole
economic query, and if the result still cannot be valid it fails locally as
`INVALID GENERATED TRADE QUERY` instead of as a server error.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Confirmed Trade2 group types. There is no `or` group — alias-OR is COUNT min 1.
# `weight` / `weight2` are known but never the anonymous cold-path default.
VALID_GROUP_TYPES = frozenset({"and", "not", "if", "count", "weight", "weight2"})
COUNT_GROUP_TYPES = frozenset({"count"})
VALID_STATUS_OPTIONS = frozenset({"online", "onlineleague", "any", "available"})
MAX_STAT_FILTERS_PER_GROUP = 40


@dataclass
class QueryValidation:
    """Outcome of validating a search body."""

    body: dict[str, Any]
    repairs: list[str] = field(default_factory=list)
    fatal: str | None = None

    @property
    def ok(self) -> bool:
        return self.fatal is None

    @property
    def repaired(self) -> bool:
        return bool(self.repairs)

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "repairs": list(self.repairs), "fatal": self.fatal}


class InvalidTradeQuery(ValueError):
    """The generated query cannot be made valid locally."""

    def __init__(self, reason: str, repairs: list[str] | None = None) -> None:
        super().__init__(f"INVALID GENERATED TRADE QUERY: {reason}")
        self.reason = reason
        self.repairs = list(repairs or [])


def _is_known_absent_stat_id(stat_id: str) -> bool:
    try:
        from poe2value.price_check.stat_registry import is_catalog_invalid_stat_id
    except Exception:  # pragma: no cover
        return False
    return is_catalog_invalid_stat_id(stat_id)


def _valid_stat_filter(row: Any) -> bool:
    if not isinstance(row, dict):
        return False
    stat_id = row.get("id")
    if not isinstance(stat_id, str) or not stat_id.strip():
        return False
    value = row.get("value")
    if value is None:
        return True
    if not isinstance(value, dict):
        return False
    for key in ("min", "max"):
        if key in value:
            bound = value[key]
            if not isinstance(bound, (int, float)) or isinstance(bound, bool):
                return False
    low, high = value.get("min"), value.get("max")
    if isinstance(low, (int, float)) and isinstance(high, (int, float)) and low > high:
        return False
    return True


def _repair_stats(stats: Any, repairs: list[str]) -> list[dict[str, Any]]:
    """Keep only well-formed groups, dropping individual bad filters."""
    if stats is None:
        return []
    if not isinstance(stats, list):
        repairs.append("stats was not a list; dropped")
        return []

    groups: list[dict[str, Any]] = []
    for entry in stats:
        if not isinstance(entry, dict):
            repairs.append("dropped a non-object stats entry")
            continue

        # A bare filter where a group belongs — the exact shape that produced HTTP 400.
        if "filters" not in entry and "id" in entry:
            if _valid_stat_filter(entry):
                repairs.append("wrapped a bare stat filter in an 'and' group")
                groups.append({"type": "and", "filters": [entry]})
            else:
                repairs.append("dropped a malformed bare stat filter")
            continue

        group_type = str(entry.get("type") or "and").lower()
        if group_type not in VALID_GROUP_TYPES:
            repairs.append(f"replaced unsupported stat group type {group_type!r} with 'and'")
            group_type = "and"

        raw_filters = entry.get("filters")
        if not isinstance(raw_filters, list):
            repairs.append("dropped a stat group whose filters were not a list")
            continue

        kept = []
        for row in raw_filters:
            if not _valid_stat_filter(row):
                repairs.append("dropped one invalid stat filter")
                continue
            stat_id = str(row.get("id") or "")
            if _is_known_absent_stat_id(stat_id):
                repairs.append(f"dropped catalog-absent stat id {stat_id}")
                continue
            kept.append(row)
        if not kept:
            # An empty group is rejected by the server; drop the group, keep the query.
            repairs.append("dropped an empty stat group")
            continue
        if len(kept) > MAX_STAT_FILTERS_PER_GROUP:
            repairs.append("truncated an oversized stat group")
            kept = kept[:MAX_STAT_FILTERS_PER_GROUP]

        group: dict[str, Any] = {"type": group_type, "filters": kept}
        if group_type == "count":
            minimum = _count_minimum(entry, repairs)
            group["value"] = {"min": min(minimum, len(kept))}
        groups.append(group)

    return groups


def _count_minimum(entry: dict[str, Any], repairs: list[str]) -> int:
    """COUNT must use `value.min`. A bare group `min` is repaired, never sent."""
    value = entry.get("value")
    if isinstance(value, dict):
        raw = value.get("min")
        if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw >= 1:
            return int(raw)
        repairs.append("replaced an invalid count value.min with 1")
        return 1
    raw = entry.get("min")
    if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw >= 1:
        repairs.append("moved count min onto value.min")
        return int(raw)
    repairs.append("replaced an invalid 'count' minimum with 1")
    return 1


def count_groups_are_well_formed(body: Any) -> bool:
    """True when every COUNT group uses `value.min` and has no bare group `min`."""
    if not isinstance(body, dict):
        return False
    query = body.get("query")
    if not isinstance(query, dict):
        return False
    stats = query.get("stats") or []
    if not isinstance(stats, list):
        return False
    for entry in stats:
        if not isinstance(entry, dict):
            return False
        if str(entry.get("type") or "").lower() != "count":
            continue
        if "min" in entry:
            return False
        value = entry.get("value")
        if not isinstance(value, dict):
            return False
        minimum = value.get("min")
        if not isinstance(minimum, (int, float)) or isinstance(minimum, bool) or minimum < 1:
            return False
    return True


def validate_trade2_search_body(body: Any) -> QueryValidation:
    """Return a sendable body, repairing what can be repaired.

    Never raises. Callers that want the failure to surface use
    `ensure_valid_trade2_search_body`.
    """
    repairs: list[str] = []
    if not isinstance(body, dict):
        return QueryValidation({}, repairs, fatal="search body is not an object")

    query = body.get("query")
    if not isinstance(query, dict):
        return QueryValidation(dict(body), repairs, fatal="query is missing or not an object")

    cleaned: dict[str, Any] = {}

    status = query.get("status")
    if isinstance(status, dict) and str(status.get("option") or "") in VALID_STATUS_OPTIONS:
        cleaned["status"] = {"option": str(status["option"])}
    else:
        if status is not None:
            repairs.append("replaced an unsupported status option with 'available'")
        cleaned["status"] = {"option": "available"}

    base_type = query.get("type")
    if isinstance(base_type, str) and base_type.strip():
        cleaned["type"] = base_type.strip()
    elif base_type is not None:
        repairs.append("dropped an empty item type")

    name = query.get("name")
    if isinstance(name, str) and name.strip():
        cleaned["name"] = name.strip()
    elif name is not None:
        repairs.append("dropped an empty item name")

    filters = query.get("filters")
    if isinstance(filters, dict) and filters:
        cleaned["filters"] = filters
    elif filters is not None:
        repairs.append("dropped empty filters")

    stats = _repair_stats(query.get("stats"), repairs)
    if stats:
        cleaned["stats"] = stats

    for key, value in query.items():
        if key not in cleaned and key not in {"status", "type", "name", "filters", "stats"}:
            cleaned[key] = value

    if not cleaned.get("type") and not cleaned.get("name") and not cleaned.get("stats"):
        return QueryValidation(
            {"query": cleaned, "sort": body.get("sort") or {"price": "asc"}},
            repairs,
            fatal="query has no item type, name or stat filter to search on",
        )

    result: dict[str, Any] = {"query": cleaned}
    sort = body.get("sort")
    result["sort"] = sort if isinstance(sort, dict) and sort else {"price": "asc"}
    for key, value in body.items():
        if key not in {"query", "sort"}:
            result[key] = value

    if repairs:
        logger.info("trade2 query repaired before send: %s", repairs)
    return QueryValidation(result, repairs)


def ensure_valid_trade2_search_body(body: Any) -> dict[str, Any]:
    """Validated body, or `InvalidTradeQuery` — never an HTTP 400."""
    validation = validate_trade2_search_body(body)
    if not validation.ok:
        raise InvalidTradeQuery(validation.fatal or "unknown", validation.repairs)
    if not count_groups_are_well_formed(validation.body):
        raise InvalidTradeQuery("count group is missing value.min", validation.repairs)
    return validation.body
