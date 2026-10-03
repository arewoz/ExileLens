"""The "See what is collected" model, derived from the canonical contract.

Nothing here is hand-maintained prose about fields: events, allowed values, limits, retention and the
"never collected" list all come from ``events.v1.json`` (the same file the Worker validates against), so
the screen cannot drift from what is actually accepted. The example payload is either the real next
batch from the local queue (ID masked) or a synthetic one that is itself validated by the tests.
"""

from __future__ import annotations

import json
from typing import Any

from exilelens.cloud import contract


def _describe_spec(spec: dict[str, Any]) -> str:
    spec = contract._resolve(spec)
    kind = spec["kind"]
    if kind == "enum":
        return " | ".join(spec["values"])
    if kind == "bool":
        return "yes / no"
    if kind == "int":
        return f"whole number {spec['min']}–{spec['max']}"
    if kind == "pattern":
        return {"version": "version number", "el_code": "registered error code", "identifier": "code identifier"}.get(
            _pattern_name(spec), "restricted text format"
        )
    if kind == "list":
        inner = ", ".join(spec["item"]["props"])
        return f"up to {spec['max_items']} entries of: {inner}"
    return kind


def _pattern_name(spec: dict[str, Any]) -> str:
    for name, candidate in contract.schema()["types"].items():
        if candidate == spec:
            return name
    return ""


def _fields(obj: dict[str, Any]) -> list[dict[str, str]]:
    return [{"name": name, "allowed": _describe_spec(spec)} for name, spec in obj["props"].items()]


def usage_events() -> list[dict[str, Any]]:
    events = contract.schema()["usage"]["events"]
    return [{"name": name, "description": cfg["description"], "fields": _fields(cfg)} for name, cfg in events.items()]


def error_report_model() -> dict[str, Any]:
    report = contract.schema()["errors"]["report"]
    return {"name": "error_report", "description": report["description"], "fields": _fields(report)}


def example_batch(kind: str, now_hour: str = "2026-01-01T12:00Z") -> dict[str, Any]:
    """A synthetic, contract-valid example (used when nothing is queued yet)."""
    app = {"version": "0.7.0", "channel": "stable", "packaged": True, "os": "win11"}
    if kind == "usage":
        return {
            "schema": 1,
            "batch_id": "(assigned when sent)",
            "analytics_id": "(random ID, created when first sent)",
            "app": app,
            "events": [
                {"name": "app_started", "t": now_hour, "props": {"launch": "normal", "previous_session": "clean", "pob_configured": True}},
                {
                    "name": "item_checks_summary",
                    "t": now_hour,
                    "props": {
                        "buckets": [
                            {"verdict": "sidegrade", "confidence": "high", "quality": "full", "latency": "lt_500ms", "outcome": "ok", "n": 7}
                        ]
                    },
                },
            ],
        }
    return {
        "schema": 1,
        "batch_id": "(assigned when sent)",
        "diagnostic_id": "(random ID, created when first sent)",
        "app": app,
        "reports": [
            {
                "error_code": "EL-WRK-002",
                "component": "WRK",
                "exception_type": "TimeoutError",
                "frames": [{"module": "exilelens.app.engine", "function": "PobWorker.call", "line": 412}, {"module": "stdlib.threading"}],
                "count": 1,
                "first_t": now_hour,
                "last_t": now_hour,
            }
        ],
    }


def describe(cloud: Any | None = None) -> dict[str, Any]:
    """Everything the transparency dialog shows."""
    contract_data = contract.schema()
    status = cloud.status() if cloud is not None else {}
    categories = []
    for key, sink_key in (("usage", "usage"), ("errors", "errors")):
        info = contract_data["categories"][key]
        sink = cloud.usage.sink if (cloud is not None and key == "usage") else (cloud.errors.sink if cloud is not None else None)
        preview = sink.next_batch_preview() if sink is not None else None
        categories.append(
            {
                "key": key,
                "title": info["title"],
                "summary": info["summary"],
                "identifier": contract_data["identifiers"]["analytics_id" if key == "usage" else "diagnostic_id"],
                "events": usage_events() if key == "usage" else [error_report_model()],
                "queued": int(status.get(sink_key, {}).get("queued", 0)) if status else 0,
                "example_is_real": preview is not None,
                "example": json.dumps(preview or example_batch(key), indent=2),
            }
        )
    retention = contract_data["retention"]
    return {
        "categories": categories,
        "never_collected": list(contract_data["never_collected"]),
        "retention": (
            f"Raw usage events are deleted after {retention['raw_events_days']} days; summaries are kept "
            f"{retention['aggregates_months']} months. Error groups are kept {retention['error_groups_months']} months."
        ),
        "consent_version": contract_data["consent_version"],
        "endpoint_configured": bool(status.get("endpoint_configured")) if status else False,
    }
