"""Error reports built from objects, never scrubbed from text.

A report contains: a registered ``EL-*`` code, its component, an allowlisted exception *type*, up to 12
normalised stack frames (module, function, optional line), an occurrence count and hour-granular first/last
times. It is constructed field by field from the exception object:

* the exception message is never read, so it cannot leak a path, an item or a name;
* frames use ``module.__name__`` and ``co_qualname`` — ``co_filename`` is never touched;
* modules outside ExileLens collapse to ``lib.<package>`` / ``stdlib.<module>`` (no function, no line);
* locals, environment variables and arguments are never examined.

The contract validator is the last gate: a report that does not fit is dropped, not repaired.
"""

from __future__ import annotations

import re
import sys
import threading
import time
from types import TracebackType
from typing import Any, Callable

from exilelens.cloud import contract
from exilelens.cloud.sink import NullSink, Sink, hour_string

MAX_FRAMES = 12
DAILY_DISTINCT_REPORT_LIMIT = 20
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_.]{0,79}")
_COMPONENTS = set(contract.schema()["types"]["component"]["values"])
_EL_CODE = re.compile(r"EL-([A-Z]{2,4})-[0-9]{3}")
# Exception classes whose *name* is safe and useful. Anything else is reported as "other".
_SAFE_EXCEPTION_MODULES = {
    "builtins", "json", "json.decoder", "ssl", "socket", "urllib.error", "zipfile", "subprocess",
    "concurrent.futures._base", "concurrent.futures", "asyncio", "queue",
}
_STDLIB = set(getattr(sys, "stdlib_module_names", ()))
UNEXPECTED_SESSION_END_CODE = "EL-APP-100"


def component_for(code: str) -> str:
    match = _EL_CODE.fullmatch(code or "")
    return match.group(1) if match and match.group(1) in _COMPONENTS else "APP"


def _clean_identifier(text: str) -> str | None:
    cleaned = text.replace("<locals>", "locals").replace("<lambda>", "lambda").replace("<genexpr>", "genexpr")
    cleaned = cleaned.replace("<listcomp>", "listcomp").replace("<dictcomp>", "dictcomp").replace("<setcomp>", "setcomp")
    cleaned = cleaned.replace("<module>", "module")
    return cleaned if _IDENT.fullmatch(cleaned) else None


def exception_type_name(exc_type: type | None) -> str:
    if exc_type is None:
        return "Failure"
    module = getattr(exc_type, "__module__", "") or ""
    name = _clean_identifier(getattr(exc_type, "__qualname__", "") or "")
    if name is None:
        return "other"
    if module == "builtins":
        return name
    if module == "exilelens" or module.startswith("exilelens."):
        return name
    if module in _SAFE_EXCEPTION_MODULES:
        return _clean_identifier(f"{module}.{name}") or "other"
    return "other"


def _frame_for(module: str | None, function: str | None, line: int | None) -> dict[str, Any] | None:
    module = module or ""
    top = module.split(".")[0]
    if top == "exilelens":
        clean_module = _clean_identifier(module)
        if clean_module is None:
            return None
        frame: dict[str, Any] = {"module": clean_module}
        clean_function = _clean_identifier(function or "") if function else None
        if clean_function:
            frame["function"] = clean_function
        if isinstance(line, int) and 0 < line <= 100000:
            frame["line"] = line
        return frame
    if top in _STDLIB:
        clean_module = _clean_identifier(f"stdlib.{top}")
    else:
        clean_module = _clean_identifier(f"lib.{top}") if top else None
    return {"module": clean_module} if clean_module else {"module": "other"}


def frames_from_traceback(tb: TracebackType | None) -> list[dict[str, Any]]:
    """Innermost-first normalised frames; never reads file names."""
    collected: list[tuple[str | None, str | None, int | None]] = []
    node = tb
    while node is not None:
        code = node.tb_frame.f_code
        module = node.tb_frame.f_globals.get("__name__")
        function = getattr(code, "co_qualname", None) or code.co_name
        collected.append((module if isinstance(module, str) else None, function, node.tb_lineno))
        node = node.tb_next
    frames: list[dict[str, Any]] = []
    for module, function, line in reversed(collected):
        frame = _frame_for(module, function, line)
        if frame is None:
            continue
        if frames and frames[-1] == frame and "function" not in frame:
            continue  # collapse runs of identical library frames
        frames.append(frame)
        if len(frames) >= MAX_FRAMES:
            break
    return frames


def build_report(
    code: str,
    exc_type: type | None,
    tb: TracebackType | None,
    *,
    now: float,
    pob_version: str | None = None,
    count: int = 1,
) -> dict[str, Any]:
    hour = hour_string(now)
    report: dict[str, Any] = {
        "error_code": code if _EL_CODE.fullmatch(code or "") else "EL-APP-099",
        "component": component_for(code),
        "exception_type": exception_type_name(exc_type),
        "frames": frames_from_traceback(tb),
        "count": count,
        "first_t": hour,
        "last_t": hour,
    }
    if pob_version and contract.valid_value({"ref": "version"}, pob_version):
        report["pob_version"] = pob_version
    return report


def _key(report: dict[str, Any]) -> tuple[Any, ...]:
    frames = tuple((f.get("module"), f.get("function")) for f in report["frames"][:5])
    return report["error_code"], report["exception_type"], frames


class ErrorReporter:
    """Aggregates identical reports locally and hands each distinct one to the sink once per window."""

    def __init__(self, sink: Sink | NullSink | None = None, clock: Callable[[], float] = time.time) -> None:
        self.sink: Sink | NullSink = sink or NullSink()
        self._clock = clock
        self._lock = threading.Lock()
        self._open: dict[tuple[Any, ...], dict[str, Any]] = {}
        self._day = ""
        self._distinct_today = 0
        self.pob_version: str | None = None

    @property
    def active(self) -> bool:
        return bool(self.sink.active)

    def capture(self, code: str, exc_type: type | None = None, tb: TracebackType | None = None) -> bool:
        """Record one error occurrence. Safe to call from any thread; never raises."""
        if not self.sink.active:
            return False
        try:
            now = self._clock()
            report = build_report(code, exc_type, tb, now=now, pob_version=self.pob_version)
            key = _key(report)
            day = time.strftime("%Y-%m-%d", time.gmtime(now))
            with self._lock:
                if day != self._day:
                    self._day, self._distinct_today = day, 0
                existing = self._open.get(key)
                if existing is not None:
                    existing["count"] = min(existing["count"] + 1, 1000)
                    existing["last_t"] = report["last_t"]
                    return True
                if self._distinct_today >= DAILY_DISTINCT_REPORT_LIMIT:
                    return False
                self._distinct_today += 1
                self._open[key] = report
            return True
        except Exception:  # noqa: BLE001 - error reporting must never raise into the app
            return False

    def capture_exception(self, code: str, exc: BaseException | None) -> bool:
        if exc is None:
            return self.capture(code, None, None)
        return self.capture(code, type(exc), exc.__traceback__)

    def unexpected_session_end(self) -> bool:
        """The previous session ended without a clean shutdown (power loss, kill, native crash, ...)."""
        if not self.sink.active:
            return False
        report = build_report(UNEXPECTED_SESSION_END_CODE, None, None, now=self._clock())
        report["exception_type"] = "UnexpectedSessionEnd"
        report["frames"] = []
        return self.sink.add(report)

    def roll_up(self) -> int:
        """Move aggregated reports into the sink queue (called by the flusher before each upload)."""
        with self._lock:
            reports = list(self._open.values())
            self._open.clear()
        added = 0
        for report in reports:
            if self.sink.add(report):
                added += 1
        return added

    def discard_open(self) -> None:
        with self._lock:
            self._open.clear()
