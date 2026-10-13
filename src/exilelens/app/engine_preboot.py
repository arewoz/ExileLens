"""PERF-01: start the PoB worker while the UI is still being built.

Startup used to build the dashboard, overlay and tray first and only then, from the first event-loop task,
boot the PoB worker (about 4 s of subprocess start + Lua data load). The two do not depend on each other: the
worker is a separate process and the UI work is Python on the UI thread, so they now overlap.

The preboot owns nothing but the engine. The controller adopts it with ``start_engine_async(preboot=...)``,
which delivers the same ``engine_ready`` / ``engine_failed`` signals on the same thread as before, so error
reporting, readiness and the recovery UI are unchanged. A preboot that is not adopted is shut down.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from exilelens.config import PobConfig, validate_pob_path
from exilelens.engine import Engine

logger = logging.getLogger(__name__)


class EnginePreboot:
    """One background engine boot. ``wait`` hands the result to exactly one consumer."""

    def __init__(self, pob_path: str) -> None:
        self.config = PobConfig(pob_path=Path(pob_path))
        self._done = threading.Event()
        self._engine: Engine | None = None
        self._error: BaseException | None = None
        self._claimed = False
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._boot, name="exilelens-engine-preboot", daemon=True)

    def start(self) -> None:
        logger.info("engine_preboot_started pob_path=%s", self.config.pob_path)
        self._thread.start()

    def _boot(self) -> None:
        engine: Engine | None = None
        try:
            validate_pob_path(self.config)
            engine = Engine(self.config, use_subprocess=True)
            engine.start()
        except Exception as exc:  # noqa: BLE001 - replayed to the consumer exactly as a normal boot failure
            logger.exception("engine_preboot_failed")
            if engine is not None:
                try:
                    engine.shutdown()
                except Exception:  # noqa: BLE001
                    logger.exception("engine_boot_cleanup_failed")
            self._error = exc
            self._engine = None
        else:
            self._engine = engine
        finally:
            self._done.set()

    def matches(self, pob_path: str) -> bool:
        return self.config.pob_path == Path(pob_path)

    def wait(self, timeout: float | None = None) -> tuple[Engine | None, BaseException | None]:
        """Block for the boot result and take ownership of the engine. Callable once."""
        self._done.wait(timeout)
        with self._lock:
            if self._claimed:
                return None, RuntimeError("engine preboot result was already taken")
            self._claimed = True
            return self._engine, self._error

    def discard(self) -> None:
        """Shut an unadopted engine down without blocking the caller."""
        with self._lock:
            if self._claimed:
                return
            self._claimed = True

        def _reap() -> None:
            self._done.wait()
            engine = self._engine
            self._engine = None
            if engine is not None:
                try:
                    engine.shutdown()
                except Exception:  # noqa: BLE001
                    logger.exception("engine_preboot_discard_failed")

        threading.Thread(target=_reap, name="exilelens-engine-preboot-reap", daemon=True).start()


def preboot_for(pob_path: Any) -> EnginePreboot | None:
    """A started preboot for ``pob_path``, or ``None`` when no PoB folder is configured yet (first run)."""
    raw = str(pob_path or "").strip()
    if not raw:
        return None
    preboot = EnginePreboot(raw)
    preboot.start()
    return preboot
