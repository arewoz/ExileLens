from __future__ import annotations

import json
import logging
import os
import queue
import subprocess
import sys
import threading
import time
from collections import deque
from typing import Any

from pathlib import Path

from poe2value._paths import is_frozen, repo_root
from poe2value.build_source import BuildSource, read_build_source
from poe2value.build_sources import (
    BuildRevision,
    BuildSource as BuildOrigin,
    BuildSourceRef,
    LocalPobBuildSource,
    PobEngineInput,
    local_input_from_snapshot,
)
from poe2value.config import PobConfig, load_config
from poe2value.tooltip_perf import perf_enabled
from poe2value.errors import RestoreFailed, WorkerUnhealthy
from poe2value.worker import WorkerSession, decorate_build_result, decorate_evaluation, decorate_metrics

logger = logging.getLogger(__name__)

#: Cold PoB boot (Lua + data load) on a slow disk can take a while; a hang must still end.
BOOT_TIMEOUT_S = 180.0
#: One Lua call. Generous: a legitimately slow evaluation must not be cut off.
DEFAULT_REQUEST_TIMEOUT_S = 120.0
SHUTDOWN_TIMEOUT_S = 5.0
STDERR_TAIL_LINES = 200
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def _timeout_from_env(default: float) -> float:
    raw = os.environ.get("POE2VALUE_WORKER_TIMEOUT_S", "").strip()
    try:
        value = float(raw) if raw else default
    except ValueError:
        return default
    return value if value > 0 else default


def _write_snapshot(source: PobEngineInput) -> str:
    """Write the exact validated bytes where the worker can read them."""
    import tempfile

    handle, name = tempfile.mkstemp(prefix="exilelens-build-", suffix=".xml")
    with os.fdopen(handle, "wb") as stream:
        stream.write(source.data)
    return name


class SubprocessWorkerClient:
    """JSON-lines client for the PoB worker process.

    Every response is read through a background thread with a deadline, and stderr is
    drained continuously. Before this, stderr was a pipe nobody read (Lua ``print`` goes
    there) and ``readline`` had no timeout, so a full pipe or a hung Lua call froze the
    caller forever -- during startup that meant a process with no tray icon.
    A hang or crash now kills the worker and raises ``WorkerUnhealthy`` so the
    controller's recovery path runs.
    """

    def __init__(
        self,
        config: PobConfig | None = None,
        *,
        request_timeout_s: float | None = None,
        boot_timeout_s: float = BOOT_TIMEOUT_S,
    ):
        self.config = config or load_config()
        self._proc: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()
        self._request_id = 0
        self._responses: queue.Queue[str | None] = queue.Queue()
        self._stderr_tail: deque[str] = deque(maxlen=STDERR_TAIL_LINES)
        self._request_timeout_s = request_timeout_s or _timeout_from_env(DEFAULT_REQUEST_TIMEOUT_S)
        self._boot_timeout_s = boot_timeout_s

    @property
    def stderr_tail(self) -> list[str]:
        return list(self._stderr_tail)

    @property
    def pid(self) -> int | None:
        return self._proc.pid if self._proc is not None else None

    def _command(self) -> tuple[list[str], dict[str, str]]:
        env = dict(os.environ)
        # Force UTF-8 mode in the child Python process so its stdio uses UTF-8
        # regardless of the active Windows code page. This prevents
        # 'charmap' codec errors when Unicode appears in build data or paths.
        env["PYTHONUTF8"] = "1"
        if is_frozen():
            cmd = [sys.executable, "--poe2value-worker"]
        else:
            cmd = [sys.executable, "-X", "utf8", "-m", "poe2value.worker"]
            env["PYTHONPATH"] = str(repo_root() / "src")
        env["POB2_PATH"] = str(self.config.pob_path)
        return cmd, env

    def start(self) -> None:
        if self._proc and self._proc.poll() is None:
            return
        cmd, env = self._command()
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
            cwd=str(repo_root()),
            creationflags=CREATE_NO_WINDOW,
        )
        self._proc = proc
        self._responses = queue.Queue()
        threading.Thread(target=self._pump_stdout, args=(proc, self._responses), name="pob-worker-stdout", daemon=True).start()
        threading.Thread(target=self._pump_stderr, args=(proc,), name="pob-worker-stderr", daemon=True).start()
        logger.info("pob_worker_started pid=%s", proc.pid)
        # Boot the worker with a ping once the process is alive.
        self.request("ping", timeout_s=self._boot_timeout_s)

    @staticmethod
    def _pump_stdout(proc: subprocess.Popen[str], sink: queue.Queue[str | None]) -> None:
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                sink.put(line)
        except (OSError, ValueError):
            pass
        finally:
            sink.put(None)

    def _pump_stderr(self, proc: subprocess.Popen[str]) -> None:
        try:
            assert proc.stderr is not None
            for line in proc.stderr:
                text = line.rstrip()
                if text:
                    self._stderr_tail.append(text)
                    logger.debug("pob_worker_stderr %s", text[:500])
        except (OSError, ValueError):
            pass

    def request(self, method: str, params: dict[str, Any] | None = None, *, timeout_s: float | None = None) -> Any:
        proc = self._proc
        if not proc or proc.poll() is not None:
            raise self._unhealthy(f"PoB worker is not running (method {method})", method=method)
        self._request_id += 1
        payload = {"id": self._request_id, "method": method, "params": params or {}}
        line = json.dumps(payload, separators=(",", ":"))
        with self._lock:
            assert proc.stdin is not None
            try:
                proc.stdin.write(line + "\n")
                proc.stdin.flush()
            except (OSError, ValueError) as exc:
                self._kill()
                raise self._unhealthy(f"PoB worker stopped accepting requests: {exc}", method=method) from exc
            response = self._read_response(method, timeout_s or self._request_timeout_s)
        if not response.get("ok"):
            from poe2value.errors import raise_from_payload

            raise_from_payload(response.get("error") or {})
        return response.get("result")

    def _read_response(self, method: str, timeout_s: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_s
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._kill()
                raise self._unhealthy(
                    f"PoB worker did not answer '{method}' within {int(timeout_s)} s and was restarted",
                    method=method,
                )
            try:
                response_line = self._responses.get(timeout=remaining)
            except queue.Empty:
                continue
            if response_line is None:
                self._kill()
                raise self._unhealthy(f"PoB worker process ended unexpectedly during '{method}'", method=method)
            response_line = response_line.strip()
            if not response_line or not response_line.startswith("{"):
                continue
            return json.loads(response_line)

    def _unhealthy(self, message: str, *, method: str) -> WorkerUnhealthy:
        tail = self.stderr_tail[-20:]
        logger.error("pob_worker_unhealthy method=%s message=%s stderr_tail=%s", method, message, tail)
        return WorkerUnhealthy(message, {"method": method, "stderr_tail": tail})

    def _kill(self) -> None:
        proc = self._proc
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.kill()
            proc.wait(timeout=SHUTDOWN_TIMEOUT_S)
        except (OSError, subprocess.TimeoutExpired):
            logger.exception("pob_worker_kill_failed pid=%s", proc.pid)

    def shutdown(self) -> None:
        proc = self._proc
        if not proc:
            return
        try:
            if proc.poll() is None:
                self.request("shutdown", timeout_s=SHUTDOWN_TIMEOUT_S)
        except Exception:  # noqa: BLE001 - shutdown continues to the hard stop below
            logger.warning("pob_worker_graceful_shutdown_failed pid=%s", proc.pid, exc_info=True)
        finally:
            try:
                if proc.stdin:
                    proc.stdin.close()
            except OSError:
                pass
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=SHUTDOWN_TIMEOUT_S)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=SHUTDOWN_TIMEOUT_S)
            logger.info("pob_worker_stopped pid=%s code=%s", proc.pid, proc.returncode)
            self._proc = None


class Engine:
    def __init__(self, config: PobConfig | None = None, *, use_subprocess: bool = False):
        self.config = config or load_config()
        self.use_subprocess = use_subprocess
        self._session: WorkerSession | SubprocessWorkerClient | None = None
        self._ready_path: str | None = None
        self._ready_source_key: str | None = None
        self._ready_context: str | None = None
        self._loaded_source: BuildSource | None = None
        self._loaded_source_ref: BuildSourceRef | None = None
        self._loaded_revision: BuildRevision | None = None
        self._source_generation = 0
        self._last_load_reloaded = False
        # Keep the public diagnostic used by the BUILD-REFRESH checks while the
        # newer source/revision model owns freshness decisions.
        self.reload_count = 0

    @property
    def loaded_source(self) -> BuildSource | None:
        """The exact build bytes the worker currently holds (None before any load)."""
        return self._loaded_source

    @property
    def loaded_source_ref(self) -> BuildSourceRef | None:
        return self._loaded_source_ref

    @property
    def loaded_revision(self) -> BuildRevision | None:
        return self._loaded_revision

    @property
    def source_generation(self) -> int:
        return self._source_generation

    @property
    def last_load_reloaded(self) -> bool:
        """True when the last load/ensure call actually re-parsed the XML."""
        return self._last_load_reloaded

    def worker_diagnostics(self) -> dict[str, Any]:
        session = self._session
        return {
            "pid": session.pid if isinstance(session, SubprocessWorkerClient) else None,
            "stderr_tail": session.stderr_tail[-20:] if isinstance(session, SubprocessWorkerClient) else [],
        }

    def start(self) -> None:
        if self._session:
            return
        if self.use_subprocess:
            client = SubprocessWorkerClient(self.config)
            try:
                client.start()
            except Exception:
                client.shutdown()
                raise
            self._session = client
        else:
            session = WorkerSession(self.config)
            session.host.boot()
            self._session = session

    def shutdown(self) -> None:
        if not self._session:
            return
        self._session.shutdown()
        self._session = None
        self._ready_path = None
        self._ready_source_key = None
        self._ready_context = None
        self._loaded_source = None
        self._loaded_source_ref = None
        self._loaded_revision = None

    def _call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        if not self._session:
            self.start()
        assert self._session is not None
        return self._session.request(method, params)

    def ping(self) -> dict[str, Any]:
        return self._call("ping")

    def engine_info(self) -> dict[str, Any]:
        return self._call("engine_info")

    def load_build(
        self,
        path: str | Path,
        context: str = "MAP",
        *,
        source: BuildSource | None = None,
    ) -> dict[str, Any]:
        """Load exactly ``source`` (read from ``path`` when not given) into the worker.

        The worker re-parses unless it already holds this exact revision. Validation
        failures raise before the worker is touched.
        """
        resolved = str(Path(path).resolve())
        if source is None or source.path != resolved:
            source = read_build_source(resolved)
        return self.load_prepared_input(local_input_from_snapshot(source), context=context)

    def load_source(self, source: BuildOrigin, context: str = "MAP") -> dict[str, Any]:
        """Establish PoB state from a logical source without treating its ID as a path."""
        return self.load_prepared_input(source.prepare_engine_input(), context=context)

    def load_prepared_input(self, engine_input: PobEngineInput, context: str = "MAP") -> dict[str, Any]:
        """Load already prepared bytes; no second XML read or validation pass."""
        previous_identity = (self._ready_source_key, self._loaded_revision.token if self._loaded_revision else None)
        snapshot = _write_snapshot(engine_input)
        # After a failed restore the worker's in-memory build is corrupt even though the
        # file revision is unchanged: omit the revision so the worker must re-parse.
        revision = None if getattr(self, "_needs_reparse", False) else engine_input.revision.token
        try:
            session = self._session
            if isinstance(session, WorkerSession):
                result = session.load_build(engine_input.locator, context=context, xml_path=snapshot, revision=revision)
            else:
                params = {"path": engine_input.locator, "context": context, "xml_path": snapshot}
                if revision is not None:
                    params["revision"] = revision
                result = self._call("load_build", params)
                result = decorate_build_result(result)
            self._needs_reparse = False
        except Exception:
            # The worker unloads on a failed parse; nothing may claim a build is ready.
            self._ready_path = None
            self._ready_source_key = None
            self._loaded_source = None
            self._loaded_source_ref = None
            self._loaded_revision = None
            raise
        finally:
            try:
                os.unlink(snapshot)
            except OSError:
                logger.debug("build snapshot cleanup failed path=%s", snapshot)
        self._ready_path = engine_input.local_snapshot.path if engine_input.local_snapshot else None
        self._ready_source_key = engine_input.source_ref.key
        self._ready_context = context
        self._loaded_source = engine_input.local_snapshot
        self._loaded_source_ref = engine_input.source_ref
        self._loaded_revision = engine_input.revision
        if previous_identity != (engine_input.source_ref.key, engine_input.revision.token):
            for cache_name in ("_native_component_report_cache", "_actor_ailment_offense_coverage_cache"):
                if hasattr(self, cache_name):
                    getattr(self, cache_name).clear()
        self._last_load_reloaded = bool(result.get("reloaded", True)) if isinstance(result, dict) else True
        if self._last_load_reloaded:
            self._source_generation += 1
            self.reload_count += 1
        logger.info(
            "engine_build_loaded source=%s revision=%s bytes=%s reloaded=%s",
            engine_input.source_ref.key,
            engine_input.revision.token,
            len(engine_input.data),
            self._last_load_reloaded,
        )
        return result

    def ensure_build_ready(self, path: str | Path, context: str = "MAP") -> dict[str, Any]:
        """Keep PoB hot, but never stale: reload when path, context or file revision changed.

        The revision check is one ``stat`` (~ms); a real reload only happens after the
        file was saved.
        """
        return self.ensure_source_ready(LocalPobBuildSource(path), context=context)

    def ensure_source_ready(self, source: BuildOrigin, context: str = "MAP") -> dict[str, Any]:
        """Reuse loaded PoB state when the source's own revision has not moved."""
        loaded = self._loaded_revision
        if (
            self._ready_source_key == source.ref.key
            and self._ready_context == context
            and self._session is not None
            and loaded is not None
        ):
            current = source.current_revision()
            if current is None or loaded.freshness_token == current.freshness_token:
                # Unchanged, or source temporarily unavailable: keep last good state.
                self._last_load_reloaded = False
                return self.get_build_info()
        return self.load_source(source, context=context)

    def get_build_info(self) -> dict[str, Any]:
        session = self._session
        if isinstance(session, WorkerSession):
            return session.get_build_info()
        result = self._call("get_build_info")
        return decorate_build_result(result)

    def list_calculable_effects(
        self,
        *,
        indices: list[int] | None = None,
        max_effects: int = 8,
        force_cache_miss: bool = False,
        malformed_cache: bool = False,
        weapon_set: int | None = None,
    ) -> dict[str, Any]:
        """Return a bounded effect catalog; normal reads are GlobalCache-backed.

        ``weapon_set`` (1/2) is explicit-diagnostic only: it enumerates under
        a transient bridge-owned context switch. Ordinary callers omit it
        and pay zero extra frames.
        """
        from poe2value.items.effect_components import normalize_effect_catalog

        session = self._session
        if isinstance(session, WorkerSession):
            return session.list_calculable_effects(
                indices=indices,
                max_effects=max_effects,
                force_cache_miss=force_cache_miss,
                malformed_cache=malformed_cache,
                weapon_set=weapon_set,
            )
        params: dict[str, Any] = {"max_effects": max_effects}
        if indices is not None:
            params["indices"] = list(indices)
        if force_cache_miss:
            params["force_cache_miss"] = True
        if malformed_cache:
            params["malformed_cache"] = True
        if weapon_set is not None:
            if int(weapon_set) not in (1, 2):
                raise ValueError("weapon_set must be 1 or 2")
            params["weapon_set"] = int(weapon_set)
        return normalize_effect_catalog(self._call("list_calculable_effects", params))

    def read_effect_metrics(
        self,
        reference: dict[str, Any] | Any,
        *,
        force_cache_miss: bool = False,
        malformed_cache: bool = False,
        malformed_fallback: bool = False,
        weapon_set: int | None = None,
    ) -> dict[str, Any]:
        """Read one exact semantic effect, transactionally recalculating on cache miss.

        ``weapon_set`` (1/2) is Slice 3 internal: it routes through the
        bridge-owned context transaction. Ordinary callers omit it and pay
        zero extra frames.
        """
        from poe2value.items.effect_components import ComponentReference
        from poe2value.worker import decorate_contextual_effect_result

        raw_reference = (
            reference.to_dict()
            if isinstance(reference, ComponentReference)
            else ComponentReference.from_dict(dict(reference)).to_dict()
        )
        if weapon_set is not None and int(weapon_set) not in (1, 2):
            raise ValueError("weapon_set must be 1 or 2")
        session = self._session
        if isinstance(session, WorkerSession):
            return self._guard_restore(lambda: session.read_effect_metrics(
                raw_reference,
                force_cache_miss=force_cache_miss,
                malformed_cache=malformed_cache,
                malformed_fallback=malformed_fallback,
                weapon_set=weapon_set,
            ))
        params: dict[str, Any] = {"reference": raw_reference}
        if force_cache_miss:
            params["force_cache_miss"] = True
        if malformed_cache:
            params["malformed_cache"] = True
        if malformed_fallback:
            params["malformed_fallback"] = True
        if weapon_set is not None:
            params["weapon_set"] = int(weapon_set)
        return self._guard_restore(lambda: decorate_contextual_effect_result(self._call("read_effect_metrics", params)))

    def get_weapon_set_context(self) -> dict[str, Any]:
        """Slice 3 internal diagnostic: current weapon-set context + physical weapon raws."""
        return self._call("get_weapon_set_context", {})

    def evaluate_effect_candidate(
        self,
        reference: dict[str, Any] | Any,
        *,
        weapon_set: int,
        physical_slot: str,
        item_raw: str,
        test_fault: str | None = None,
    ) -> dict[str, Any]:
        """Slice 3 internal: one component, one context, one exact physical slot.

        Component evidence only; never a public Item Check verdict.
        """
        from poe2value.items.effect_components import ComponentReference
        from poe2value.worker import decorate_contextual_effect_result

        raw_reference = (
            reference.to_dict()
            if isinstance(reference, ComponentReference)
            else ComponentReference.from_dict(dict(reference)).to_dict()
        )
        if int(weapon_set) not in (1, 2):
            raise ValueError("weapon_set must be 1 or 2")
        session = self._session
        if isinstance(session, WorkerSession):
            return self._guard_restore(lambda: session.evaluate_effect_candidate(
                raw_reference, weapon_set=int(weapon_set),
                physical_slot=str(physical_slot), item_raw=str(item_raw),
                test_fault=test_fault,
            ))
        params: dict[str, Any] = {
            "reference": raw_reference,
            "weapon_set": int(weapon_set),
            "physical_slot": str(physical_slot),
            "item_raw": str(item_raw),
        }
        if test_fault:
            params["test_fault"] = test_fault
        return self._guard_restore(lambda: decorate_contextual_effect_result(self._call("evaluate_effect_candidate", params)))

    def invalidate_build(self) -> None:
        """Forget the loaded build so the next ``ensure_build_ready`` does a real reload.

        Used after a failed restore: the worker's build no longer equals the baseline,
        and no later comparison may run from it.
        """
        self._ready_path = None
        self._ready_source_key = None
        self._ready_context = None
        self._loaded_source = None
        self._loaded_source_ref = None
        self._loaded_revision = None
        self._needs_reparse = True

    def _guard_restore(self, call):
        try:
            return call()
        except RestoreFailed:
            self.invalidate_build()
            raise

    def evaluate_candidate(
        self,
        slot: str,
        item_raw: str,
        *,
        context: str | None = None,
        test_fault: str | None = None,
        component_keys: list[str] | None = None,
    ) -> dict[str, Any]:
        """``test_fault`` is a test-only hook (e.g. ``"corrupt_restore"``) for recovery tests."""
        session = self._session
        if isinstance(session, WorkerSession) and not test_fault:
            return self._guard_restore(lambda: session.evaluate_candidate(
                slot, item_raw, context=context, component_keys=component_keys,
            ))
        params: dict[str, Any] = {"slot": slot, "item_raw": item_raw}
        if context:
            params["context"] = context
        if test_fault:
            params["test_fault"] = test_fault
        if component_keys:
            params["component_keys"] = component_keys
        if perf_enabled():
            params["perf"] = True
        result = self._guard_restore(lambda: self._call("evaluate_candidate", params))
        return decorate_evaluation(result)

    def evaluate_item_slots(
        self,
        slots: list[str],
        item_raw: str,
        *,
        context: str | None = None,
        component_keys: list[str] | None = None,
        defer_restore: bool = False,
        test_fault: str | None = None,
        baseline_overrides: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """PERF-02: measure every compatible slot for one item in a single transaction.

        ``defer_restore`` parks the restore + verification inside the worker instead of
        running it before returning. It is only safe for a caller that guarantees the
        restore is finalised before the next evaluation starts -- see
        :meth:`finalize_transaction`. The worker enforces the same thing independently:
        any later request drains the pending restore before touching the build.

        ``baseline_overrides`` (slot -> raw item text) lets the "ignore socketed
        modifiers" Item Check setting substitute a normalized version of the
        currently equipped item for baseline measurement only -- see
        items/evaluation.py and runtime/lua/bridge.lua's ``tx_begin``. The build is
        still fully restored to its true, un-overridden equipped items afterward.
        """
        from poe2value.worker import decorate_item_slot_evaluation

        session = self._session
        if isinstance(session, WorkerSession) and not test_fault:
            return self._guard_restore(lambda: session.evaluate_item_slots(
                slots, item_raw, context=context, component_keys=component_keys,
                defer_restore=defer_restore, baseline_overrides=baseline_overrides,
            ))
        params: dict[str, Any] = {"slots": list(slots), "item_raw": item_raw}
        if context:
            params["context"] = context
        if component_keys:
            params["component_keys"] = component_keys
        if defer_restore:
            params["defer_restore"] = True
        if test_fault:
            params["test_fault"] = test_fault
        if baseline_overrides:
            params["baseline_overrides"] = dict(baseline_overrides)
        if perf_enabled():
            params["perf"] = True
        result = self._guard_restore(lambda: self._call("evaluate_item_slots", params))
        return decorate_item_slot_evaluation(result)

    def finalize_transaction(self) -> dict[str, Any]:
        """Complete a deferred restore. Idempotent: returns status IDLE when there is none.

        A failure here means the build state is no longer trustworthy going forward. It
        raises RestoreFailed, which invalidates the loaded build so the next evaluation
        starts from a real reload. Callers using deferred Item Check evaluation must
        finalize before delivering success, so a restore failure suppresses that result.
        """
        from poe2value.worker import decorate_restored_block

        session = self._session
        if session is None:
            return {"status": "IDLE"}
        if isinstance(session, WorkerSession):
            return self._guard_restore(lambda: decorate_restored_block(session.finalize_transaction()))
        return self._guard_restore(lambda: decorate_restored_block(self._call("finalize_transaction", {})))

    def evaluate_slot_cleared(self, slot: str, *, context: str | None = None) -> dict[str, Any]:
        from poe2value.worker import decorate_slot_cleared

        session = self._session
        if isinstance(session, WorkerSession):
            return self._guard_restore(lambda: session.evaluate_slot_cleared(slot, context=context))
        params: dict[str, Any] = {"slot": slot}
        if context:
            params["context"] = context
        result = self._guard_restore(lambda: self._call("evaluate_slot_cleared", params))
        return decorate_slot_cleared(result)

    def evaluate_gear_plan(
        self,
        replacements: list[dict[str, Any]],
        *,
        context: str | None = None,
        tolerance: float = 0.5,
    ) -> dict[str, Any]:
        from poe2value.worker import decorate_gear_plan_evaluation

        session = self._session
        if isinstance(session, WorkerSession):
            return self._guard_restore(
                lambda: session.evaluate_gear_plan(replacements, context=context, tolerance=tolerance)
            )
        params: dict[str, Any] = {"replacements": replacements, "tolerance": tolerance}
        if context:
            params["context"] = context
        result = self._guard_restore(lambda: self._call("evaluate_gear_plan", params))
        return decorate_gear_plan_evaluation(result)

    def get_tree_snapshot(self) -> dict[str, Any]:
        return self._call("get_tree_snapshot")

    def evaluate_tree_path(
        self,
        node_ids: list[int],
        *,
        target_id: int | None = None,
        context: str | None = None,
    ) -> dict[str, Any]:
        from poe2value.tree.mutations import decorate_tree_evaluation

        params: dict[str, Any] = {"node_ids": [int(n) for n in node_ids]}
        if target_id is not None:
            params["target_id"] = int(target_id)
        if context:
            params["context"] = context
        session = self._session
        if isinstance(session, WorkerSession):
            result = session.request("evaluate_tree_path", params)
            return decorate_tree_evaluation(result)
        result = self._call("evaluate_tree_path", params)
        return decorate_tree_evaluation(result)

    def parse_item(self, item_raw: str) -> dict[str, Any]:
        return self._call("parse_item", {"item_raw": item_raw})

    def resolve_compatible_slots(self, item_raw: str) -> dict[str, Any]:
        return self._call("resolve_compatible_slots", {"item_raw": item_raw})

    def get_metrics(self, context: str | None = None) -> dict[str, Any]:
        session = self._session
        if isinstance(session, WorkerSession):
            return session.get_metrics(context=context)
        result = self._call("get_metrics", {"context": context} if context else {})
        return decorate_metrics(result)

    def get_equipment(self) -> dict[str, Any]:
        return self._call("get_equipment")

    def apply_live_equipment(self, equipment: list[dict[str, Any]]) -> dict[str, Any]:
        result = self._call("apply_live_equipment", {"equipment": equipment})
        return decorate_build_result(result)

    def list_loadouts(self) -> dict[str, Any]:
        return self._call("list_loadouts")

    def list_item_sets(self) -> dict[str, Any]:
        from poe2value.baseline import normalize_item_sets_payload

        return normalize_item_sets_payload(self._call("list_item_sets"))

    def set_active_loadout(self, name: str) -> dict[str, Any]:
        result = self._call("set_active_loadout", {"name": name})
        return decorate_build_result(result)

    def set_active_item_set(self, item_set_id: str | int) -> dict[str, Any]:
        from poe2value.baseline import item_set_wire_value

        result = self._call("set_active_item_set", {"item_set_id": item_set_wire_value(item_set_id)})
        return decorate_build_result(result)

    def list_tree_sets(self) -> dict[str, Any]:
        return self._call("list_tree_sets")

    def set_active_tree_set(self, tree_set_id: str | int) -> dict[str, Any]:
        result = self._call("set_active_tree_set", {"tree_set_id": str(tree_set_id)})
        return decorate_build_result(result)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.shutdown()
        return False
