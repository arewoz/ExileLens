"""Client side of the canonical cloud contract (``events.v1.json``).

The same JSON drives the Worker's validator (``cloud/src/contract.ts``), the transparency UI and the
tests. The algorithm below is deliberately identical to the Worker's; ``cloud/contract/fixtures.json``
pins both to the same results. Validation is fail-closed: anything the schema does not name is rejected,
there is no free-text or metadata escape hatch.
"""

from __future__ import annotations

import json
import re
from calendar import timegm
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from time import strptime
from typing import Any

SCHEMA_FILE = "events.v1.json"
HOUR_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:00Z")


@lru_cache(maxsize=1)
def schema() -> dict[str, Any]:
    path = Path(__file__).with_name(SCHEMA_FILE)
    return json.loads(path.read_text(encoding="utf-8"))


def limits() -> dict[str, int]:
    return dict(schema()["limits"])


def _resolve(spec: dict[str, Any]) -> dict[str, Any]:
    if "ref" in spec:
        return schema()["types"][spec["ref"]]
    return spec


@lru_cache(maxsize=None)
def _compile(regex: str) -> re.Pattern[str]:
    return re.compile(regex)


class Invalid(Exception):
    """Carries the stable rejection code shared with the Worker."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _is_int(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, float) and value.is_integer()  # JSON 1.0 == 1 in the JavaScript validator


def check_value(spec: dict[str, Any], value: Any) -> None:
    """Raise ``Invalid("invalid_value")`` for a bad scalar/list; nested objects raise their own code."""
    spec = _resolve(spec)
    kind = spec["kind"]
    if kind == "enum":
        ok = isinstance(value, str) and value in spec["values"]
    elif kind == "bool":
        ok = isinstance(value, bool)
    elif kind == "int":
        ok = _is_int(value) and spec["min"] <= value <= spec["max"]
    elif kind == "pattern":
        ok = isinstance(value, str) and len(value) <= spec["max_len"] and _compile(spec["regex"]).fullmatch(value) is not None
    elif kind == "list":
        if not isinstance(value, list) or len(value) > spec["max_items"]:
            raise Invalid("invalid_value")
        for row in value:
            if not isinstance(row, dict):
                raise Invalid("invalid_value")
            validate_object(spec["item"], row)  # unknown_prop / missing_prop / invalid_value propagate
        return
    else:
        raise ValueError(f"unknown spec kind {kind!r}")
    if not ok:
        raise Invalid("invalid_value")


def valid_value(spec: dict[str, Any], value: Any) -> bool:
    try:
        check_value(spec, value)
    except Invalid:
        return False
    return True


def validate_object(spec: dict[str, Any], value: Any) -> None:
    """unknown_prop → missing_prop → invalid_value, in that order."""
    if not isinstance(value, dict):
        raise Invalid("invalid_value")
    props = spec["props"]
    for key in value:
        if key not in props:
            raise Invalid("unknown_prop")
    for key in spec.get("required", []):
        if key not in value:
            raise Invalid("missing_prop")
    for key, item in value.items():
        check_value(props[key], item)


def hour_to_epoch(text: str) -> int:
    try:
        return timegm(strptime(text, "%Y-%m-%dT%H:00Z"))
    except ValueError as exc:  # pattern-valid but not a real date, e.g. month 13
        raise Invalid("invalid_value") from exc


def check_window(text: str, now: float) -> None:
    limit = limits()
    epoch = hour_to_epoch(text)
    if epoch < now - limit["max_event_age_hours"] * 3600:
        raise Invalid("stale_event")
    if epoch > now + limit["max_future_hours"] * 3600:
        raise Invalid("future_event")


def validate_event(name: str, t: str, props: Any, now: float) -> None:
    events = schema()["usage"]["events"]
    if name not in events:
        raise Invalid("unknown_event")
    if not isinstance(t, str) or not HOUR_RE.fullmatch(t):
        raise Invalid("invalid_value")
    check_window(t, now)
    validate_object(events[name], props)


def validate_report(report: Any, now: float) -> None:
    spec = schema()["errors"]["report"]
    validate_object(spec, report)
    if hour_to_epoch(report["first_t"]) > hour_to_epoch(report["last_t"]):
        raise Invalid("invalid_value")
    check_window(report["last_t"], now)


@dataclass(frozen=True)
class BatchResult:
    batch: str  # "ok" or a stable batch rejection code
    accepted: list[int]
    rejected: list[dict[str, Any]]


_UUID = {"kind": "pattern", "regex": schema()["types"]["uuid"]["regex"], "max_len": 36}


def validate_batch(kind: str, body: Any, now: float) -> BatchResult:
    """Validate a full request body. ``kind`` is ``usage`` or ``errors``."""
    contract = schema()
    cfg = contract["usage" if kind == "usage" else "errors"]
    id_field = cfg["id_field"]
    list_field = "events" if kind == "usage" else "reports"
    allowed = {"schema", "batch_id", id_field, "app", list_field, *cfg["envelope_extra"].keys()}

    def fail(code: str) -> BatchResult:
        return BatchResult(code, [], [])

    if not isinstance(body, dict):
        return fail("invalid_envelope")
    if any(key not in allowed for key in body):
        return fail("unknown_field")
    if any(key not in body for key in ("schema", "batch_id", id_field, "app", list_field)):
        return fail("invalid_envelope")
    if body["schema"] != contract["schema_version"] or isinstance(body["schema"], bool):
        return fail("schema_unsupported")
    for key in ("batch_id", id_field):
        if not valid_value(_UUID, body[key]):
            return fail("invalid_envelope")
    for key, spec in cfg["envelope_extra"].items():
        if key in body and not valid_value(spec, body[key]):
            return fail("invalid_envelope")
    try:
        validate_object(contract["app"], body["app"])
    except Invalid:
        return fail("invalid_app")
    items = body[list_field]
    if not isinstance(items, list) or not items:
        return fail("invalid_envelope")
    cap = limits()["usage_batch_max_events" if kind == "usage" else "error_batch_max_reports"]
    if len(items) > cap:
        return fail("too_many_events")
    accepted: list[int] = []
    rejected: list[dict[str, Any]] = []
    for index, row in enumerate(items):
        try:
            if kind == "usage":
                if not isinstance(row, dict) or set(row) != {"name", "t", "props"} or not isinstance(row["props"], dict):
                    raise Invalid("invalid_event")
                if not isinstance(row["name"], str):
                    raise Invalid("invalid_event")
                validate_event(row["name"], row["t"], row["props"], now)
            else:
                validate_report(row, now)
        except Invalid as exc:
            rejected.append({"index": index, "code": exc.code})
        else:
            accepted.append(index)
    return BatchResult("ok", accepted, rejected)
