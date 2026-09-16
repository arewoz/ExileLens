"""Runtime logging configuration.

Before MARKET-01B9 the application never called ``logging.basicConfig`` and the
frozen build is windowed (``console=False``), so every ``logger.info`` diagnostic —
including the whole ``price_check_capture`` phase trail — was discarded. Owner-side
failures were therefore impossible to triage. This module gives the app a rotating
log file under the existing app data directory.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
from pathlib import Path

LOG_DIR_NAME = "logs"
LOG_FILE_NAME = "poe2value.log"
_MAX_BYTES = 4 * 1024 * 1024
_BACKUP_COUNT = 3

_configured = False
_configured_path: Path | None = None


def redact_log_text(text: str) -> str:
    """Redact credential-shaped values before they reach a persisted log.

    This is a last line of defence, not permission for call sites to log request
    bodies, clipboard text, or other private payloads.
    """
    import re

    value = str(text)
    field = (
        r"(?:authorization|cookie|set-cookie|poesessid|password|passwd|api[_-]?key|"
        r"client[_-]?secret|secret|(?:access|refresh|id)?_?token|session(?:[_-]?id)?)"
    )
    # Covers ordinary key/value output, JSON, and Python dict reprs without
    # consuming following useful fields on the same line.
    value = re.sub(
        rf"(?i)(\b{field}\b\s*[:=]\s*)(?:Bearer\s+|Basic\s+)?(?:\"[^\"]*\"|'[^']*'|[^\s,;}}]+)",
        r"\1[REDACTED]",
        value,
    )
    value = re.sub(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+", r"\1 [REDACTED]", value)
    return value


class _RedactingFormatter(logging.Formatter):
    """Formatter-level defence, including exception text."""

    def format(self, record: logging.LogRecord) -> str:
        return redact_log_text(super().format(record))


class _RedactingFilter(logging.Filter):
    """Redact the message before other handlers or formatters consume it."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - logging must never fail the caller
            return True
        record.msg = redact_log_text(message)
        record.args = ()
        return True


def log_dir() -> Path:
    from poe2value.app.settings import app_data_dir

    path = app_data_dir() / LOG_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_path() -> Path:
    return log_dir() / LOG_FILE_NAME


def resolve_level() -> int:
    raw = os.environ.get("POE2VALUE_LOG_LEVEL", "").strip().upper()
    if raw:
        return logging.getLevelNamesMapping().get(raw, logging.INFO)
    return logging.INFO


def configure_logging(*, force: bool = False) -> Path | None:
    """Attach a rotating file handler to the root logger. Idempotent."""
    global _configured, _configured_path
    if _configured and not force:
        return _configured_path

    root = logging.getLogger()
    level = resolve_level()
    root.setLevel(level)

    try:
        target = log_path()
    except (OSError, RuntimeError, ValueError):
        # Logging is support infrastructure: unavailable local storage must never
        # prevent the application from starting.
        return None

    for handler in list(root.handlers):
        if getattr(handler, "_poe2value_file_handler", False):
            root.removeHandler(handler)
            handler.close()

    try:
        handler = logging.handlers.RotatingFileHandler(
            target,
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
            delay=True,
        )
    except (OSError, RuntimeError, ValueError):
        return None

    handler.setLevel(level)
    handler.addFilter(_RedactingFilter())
    handler.setFormatter(
        _RedactingFormatter("%(asctime)s %(levelname)s %(name)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
    )
    handler._poe2value_file_handler = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    _configured = True
    _configured_path = target
    return target


_CRASH_LOG_NAME = "crash.log"
_CRASH_LOG_MAX_BYTES = 1024 * 1024
_crash_file = None


def install_crash_handlers() -> None:
    """Route every unhandled exception into the log file.

    The frozen build is windowed, so ``sys.stderr`` is gone and an exception raised in a
    Qt slot or a background thread used to disappear while the process kept running.
    Native crashes go to ``crash.log`` through faulthandler.
    """
    global _crash_file
    import faulthandler
    import sys
    import threading

    crash_logger = logging.getLogger("poe2value.crash")

    def _excepthook(exc_type, exc, tb) -> None:  # noqa: ANN001
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        crash_logger.critical("unhandled_exception", exc_info=(exc_type, exc, tb))

    def _thread_excepthook(args) -> None:  # noqa: ANN001
        if args.exc_type is SystemExit:
            return
        crash_logger.critical(
            "unhandled_thread_exception thread=%s",
            getattr(args.thread, "name", "?"),
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook
    if _crash_file is not None:
        return
    try:
        target = log_dir() / _CRASH_LOG_NAME
        if target.exists() and target.stat().st_size > _CRASH_LOG_MAX_BYTES:
            target.unlink()
        _crash_file = open(target, "a", encoding="utf-8")  # noqa: SIM115 - must outlive this call
        faulthandler.enable(file=_crash_file, all_threads=True)
    except (OSError, RuntimeError, ValueError):
        crash_logger.exception("faulthandler could not be enabled")


def log_price_check_startup_mode(settings) -> dict[str, object]:
    """Emit the startup mode banner required by MARKET-01B9 section 13."""
    from poe2value.price_check.diagnostic_mode import resolve_price_check_diagnostic_mode
    from poe2value.price_check.market_policy import is_live_market_enabled, resolve_strict_live

    mode = resolve_price_check_diagnostic_mode(getattr(settings, "price_check_diagnostic_mode", ""))
    saved_league = str(getattr(settings, "market_league", "") or "") or None
    payload = {
        "price_check_mode": "NORMAL" if mode.value == "" else mode.value.upper(),
        "live_provider_enabled": is_live_market_enabled(getattr(settings, "live_market_mode", None)),
        "strict_live": resolve_strict_live(getattr(settings, "strict_live", None)),
        "price_check_enabled": bool(getattr(settings, "price_check_enabled", False)),
        "overlay_enabled": bool(getattr(settings, "overlay_enabled", False)),
        "price_check_hotkey": getattr(settings, "price_check_hotkey", ""),
        "league_mode": str(getattr(settings, "market_league_mode", "AUTO") or "AUTO").upper(),
        "saved_league": saved_league,
        "cached_leagues": len(getattr(settings, "market_league_cache", None) or []),
    }
    logging.getLogger("poe2value.app.main").info("price_check_startup %s", payload)
    return payload
