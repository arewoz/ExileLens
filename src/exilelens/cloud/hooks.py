"""Tiny, dependency-free bridge from existing app code to the (optional) cloud services.

Producers import only this module. With no registered service, or with error reporting off, every call
is a cheap no-op, and no call can ever raise into the caller.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_services: Any | None = None


def register(services: Any | None) -> None:
    global _services
    _services = services


def get() -> Any | None:
    return _services


def error_recorded(code: str, exc: BaseException | None = None) -> None:
    """A registered EL-* error was recorded locally; forward its structured form if the user opted in."""
    services = _services
    if services is None:
        return
    try:
        services.errors.capture_exception(code, exc)
    except Exception:  # noqa: BLE001
        logger.debug("cloud_error_hook_failed")


def unhandled_exception(exc_type: type | None, exc: BaseException | None, tb: Any) -> None:
    services = _services
    if services is None:
        return
    try:
        services.errors.capture("EL-APP-099", exc_type, tb)
    except Exception:  # noqa: BLE001
        logger.debug("cloud_unhandled_hook_failed")


def onboarding_completed(*, outcome: str) -> None:
    services = _services
    if services is None:
        return
    try:
        services.usage.onboarding_completed(outcome=outcome, pob_autodetected=bool(getattr(services, "pob_autodetected", False)))
    except Exception:  # noqa: BLE001
        logger.debug("cloud_onboarding_hook_failed")
