from __future__ import annotations

import json
import sys
import threading
from dataclasses import dataclass, field
from typing import Any

from poe2value.config import PobConfig, fingerprint_hash, load_config, validate_pob_path
from poe2value.errors import EngineError, PobBootFailed, WorkerUnhealthy, raise_from_payload
from poe2value.items.effect_components import ComponentReference, MAX_EFFECTS, normalize_effect_catalog
from poe2value.metrics import RAW_METRIC_FIELDS, metric_delta, normalize_metrics
from poe2value.pob.lua_host import LuaHost
from poe2value.tooltip_perf import perf_enabled


def _configure_std_streams_utf8() -> None:
    """Ensure stdout/stderr use UTF-8 encoding on all platforms.

    On Windows, subprocess pipes default to the active code page (charmap).
    Reconfigure the text wrappers to UTF-8 so Unicode in build data, paths,
    item names, and PoB output cannot terminate the worker.
    """
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace", write_through=True)
    except Exception:
        pass
    try:
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace", write_through=True)
    except Exception:
        pass
    # For frozen/windowed builds where streams may be None or lack reconfigure,
    # fall back to binary wrappers with explicit encoding.
    if getattr(sys, "frozen", False):
        try:
            if sys.stdout is not None and hasattr(sys.stdout, "buffer"):
                import io

                sys.stdout = io.TextIOWrapper(
                    sys.stdout.buffer, encoding="utf-8", errors="replace", write_through=True
                )
        except Exception:
            pass
        try:
            if sys.stderr is not None and hasattr(sys.stderr, "buffer"):
                import io

                sys.stderr = io.TextIOWrapper(
                    sys.stderr.buffer, encoding="utf-8", errors="replace", write_through=True
                )
        except Exception:
            pass


def decorate_build_result(result: dict[str, Any]) -> dict[str, Any]:
    if "fingerprint" in result:
        result["fingerprint_hash"] = fingerprint_hash(result["fingerprint"])
    if "metrics" in result:
        result["normalized"] = normalize_metrics(result["metrics"])
    build = result.get("build") or {}
    if build.get("effect_catalog"):
        build["effect_catalog"] = normalize_effect_catalog(build["effect_catalog"])
    return result


def decorate_effect_result(result: dict[str, Any]) -> dict[str, Any]:
    reference = result.get("reference")
    if isinstance(reference, dict):
        result["reference"] = ComponentReference.from_dict(reference).to_dict()
    return result


def decorate_contextual_effect_result(result: dict[str, Any]) -> dict[str, Any]:
    """Normalise a Slice 3 weapon-set-qualified effect read.

    The nested ``baseline``/``candidate`` blocks carry their own references;
    only the top-level reference (when present) is normalised here.
    """
    result = decorate_effect_result(result)
    for key in ("baseline", "candidate"):
        block = result.get(key)
        if isinstance(block, dict) and isinstance(block.get("reference"), dict):
            try:
                block["reference"] = ComponentReference.from_dict(block["reference"]).to_dict()
            except (TypeError, ValueError):
                pass
    return result


def decorate_metrics(result: dict[str, Any]) -> dict[str, Any]:
    raw = result.get("raw", {})
    result["normalized"] = normalize_metrics(raw)
    result["fingerprint_hash"] = fingerprint_hash(result.get("fingerprint", {}))
    result["raw_fields"] = {k: raw.get(k) for k in RAW_METRIC_FIELDS if k in raw}
    return result


def decorate_gear_plan_evaluation(result: dict[str, Any]) -> dict[str, Any]:
    baseline_raw = result["baseline"]["metrics"]
    final_raw = result["final"]["metrics"]
    restored_raw = result["restored"]["metrics"]
    baseline_norm = normalize_metrics(baseline_raw)
    final_norm = normalize_metrics(final_raw)
    restored_norm = normalize_metrics(restored_raw)
    result["baseline"]["normalized"] = baseline_norm
    result["final"]["normalized"] = final_norm
    result["restored"]["normalized"] = restored_norm
    result["baseline"]["fingerprint_hash"] = fingerprint_hash(result["baseline"]["fingerprint"])
    result["final"]["fingerprint_hash"] = fingerprint_hash(result["final"]["fingerprint"])
    result["restored"]["fingerprint_hash"] = fingerprint_hash(result["restored"]["fingerprint"])
    result["delta"] = metric_delta(baseline_norm, final_norm)
    result["restore"] = {
        "equipment_match": result["restore"].get("equipment_match", result["restored"].get("restore_ok")),
        "fingerprint_match": result["baseline"]["fingerprint_hash"] == result["restored"]["fingerprint_hash"],
        "metrics_match": baseline_norm == restored_norm,
        "pass": bool(result["restore"].get("pass", False)),
    }
    return result


def decorate_evaluation(result: dict[str, Any]) -> dict[str, Any]:
    baseline_raw = result["baseline"]["metrics"]
    candidate_raw = result["candidate"]["metrics"]
    restored_raw = result["restored"]["metrics"]
    baseline_norm = normalize_metrics(baseline_raw)
    candidate_norm = normalize_metrics(candidate_raw)
    restored_norm = normalize_metrics(restored_raw)
    result["baseline"]["normalized"] = baseline_norm
    result["candidate"]["normalized"] = candidate_norm
    result["restored"]["normalized"] = restored_norm
    result["baseline"]["fingerprint_hash"] = fingerprint_hash(result["baseline"]["fingerprint"])
    result["candidate"]["fingerprint_hash"] = fingerprint_hash(result["candidate"]["fingerprint"])
    result["restored"]["fingerprint_hash"] = fingerprint_hash(result["restored"]["fingerprint"])
    result["delta"] = metric_delta(baseline_norm, candidate_norm)
    result["restore"] = {
        "equipment_match": result["restored"]["restore_ok"],
        "fingerprint_match": result["baseline"]["fingerprint_hash"]
        == result["restored"]["fingerprint_hash"],
        "metrics_match": baseline_norm == restored_norm,
        "pass": result["restored"]["restore_ok"]
        and result["baseline"]["fingerprint_hash"] == result["restored"]["fingerprint_hash"],
    }
    return result


def decorate_restored_block(result: dict[str, Any]) -> dict[str, Any]:
    """Normalise the restored block a finalised deferred transaction returns."""
    restored = result.get("restored")
    if restored is not None:
        restored["normalized"] = normalize_metrics(restored["metrics"])
        restored["fingerprint_hash"] = fingerprint_hash(restored["fingerprint"])
    return result


def decorate_item_slot_evaluation(result: dict[str, Any]) -> dict[str, Any]:
    """Decorate one PERF-02 batched item transaction.

    The baseline and the restore verification are shared by every slot -- there is one
    transaction -- so they are normalised once and each measured slot gets its own
    candidate normalisation and delta. A deferred transaction carries no ``restored``
    block yet; ``restore.status`` says so rather than the absence being implicit.
    """
    baseline = result["baseline"]
    baseline_norm = normalize_metrics(baseline["metrics"])
    baseline["normalized"] = baseline_norm
    baseline["fingerprint_hash"] = fingerprint_hash(baseline["fingerprint"])

    # A socket-normalization baseline override (see items/evaluation.py) makes
    # ``baseline`` reflect the stripped equipped item, on purpose -- that is what
    # candidate deltas must be measured against. But the transaction still restores
    # the TRUE, un-stripped equipped item at the end, so restore verification must
    # compare against the true pre-override fingerprint the worker returns
    # separately, never against the (deliberately different) override baseline.
    true_baseline = result.get("true_baseline") or baseline
    true_baseline_hash = fingerprint_hash(true_baseline["fingerprint"])
    true_baseline_norm = (
        normalize_metrics(true_baseline["metrics"]) if "metrics" in true_baseline else baseline_norm
    )

    restore = result.get("restore") or {}
    status = str(restore.get("status") or "")
    restored = result.get("restored")
    if restored is not None:
        restored_norm = normalize_metrics(restored["metrics"])
        restored["normalized"] = restored_norm
        restored["fingerprint_hash"] = fingerprint_hash(restored["fingerprint"])
        restore = {
            "status": status or "OK",
            "equipment_match": restored["restore_ok"],
            "fingerprint_match": true_baseline_hash == restored["fingerprint_hash"],
            "metrics_match": true_baseline_norm == restored_norm,
            "pass": restored["restore_ok"] and true_baseline_hash == restored["fingerprint_hash"],
        }
    else:
        # Deferred: the restore has not run yet, so there is nothing to pass or fail.
        # `pass` is None, never True -- a caller must not read "not failed" as "verified".
        restore = {"status": status or "DEFERRED", "pass": None}
    result["restore"] = restore

    for entry in result.get("slots") or []:
        candidate = entry.get("candidate")
        if candidate is None:
            continue
        candidate_norm = normalize_metrics(candidate["metrics"])
        candidate["normalized"] = candidate_norm
        candidate["fingerprint_hash"] = fingerprint_hash(candidate["fingerprint"])
        entry["delta"] = metric_delta(baseline_norm, candidate_norm)
    return result


def decorate_slot_cleared(result: dict[str, Any]) -> dict[str, Any]:
    baseline_raw = result["baseline"]["metrics"]
    cleared_raw = result["cleared"]["metrics"]
    restored_raw = result["restored"]["metrics"]
    baseline_norm = normalize_metrics(baseline_raw)
    cleared_norm = normalize_metrics(cleared_raw)
    restored_norm = normalize_metrics(restored_raw)
    result["baseline"]["normalized"] = baseline_norm
    result["cleared"]["normalized"] = cleared_norm
    result["restored"]["normalized"] = restored_norm
    result["baseline"]["fingerprint_hash"] = fingerprint_hash(result["baseline"]["fingerprint"])
    result["cleared"]["fingerprint_hash"] = fingerprint_hash(result["cleared"]["fingerprint"])
    result["restored"]["fingerprint_hash"] = fingerprint_hash(result["restored"]["fingerprint"])
    result["delta"] = metric_delta(baseline_norm, cleared_norm)
    restore = result.get("restore") or {}
    if "pass" not in restore:
        result["restore"] = {
            "equipment_match": restore.get("equipment_match", True),
            "fingerprint_match": result["baseline"]["fingerprint_hash"] == result["restored"]["fingerprint_hash"],
            "metrics_match": baseline_norm == restored_norm,
            "pass": bool(restore.get("pass", result["restored"].get("restore_ok"))),
        }
    return result


@dataclass
class WorkerSession:
    config: PobConfig
    host: LuaHost = field(init=False)
    request_id: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    healthy: bool = True

    def __post_init__(self) -> None:
        self.host = LuaHost(self.config)

    def _next_id(self) -> int:
        self.request_id += 1
        return self.request_id

    def request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        if not self.healthy:
            raise WorkerUnhealthy("worker session is unhealthy; reload build before continuing")
        payload = {"id": self._next_id(), "method": method, "params": params or {}}
        with self._lock:
            raw = self.host.dispatch_json(json.dumps(payload, separators=(",", ":")))
        response = json.loads(raw)
        if not response.get("ok"):
            error = response.get("error") or {}
            code = error.get("code")
            if code == "RESTORE_FAILED":
                self.healthy = False
            raise_from_payload(error)
        return response.get("result")

    def ping(self) -> dict[str, Any]:
        return self.request("ping")

    def engine_info(self) -> dict[str, Any]:
        return self.request("engine_info")

    def load_build(
        self,
        path: str,
        context: str = "MAP",
        *,
        xml_path: str | None = None,
        revision: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"path": str(path), "context": context}
        if xml_path is not None:
            params["xml_path"] = str(xml_path)
        if revision is not None:
            params["revision"] = revision
        # A real reload is the recovery path after a failed restore: it must be allowed
        # while the session is marked unhealthy (the Lua worker re-parses the build).
        self.healthy = True
        result = self.request("load_build", params)
        return self._decorate_build_result(result)

    def unload_build(self) -> dict[str, Any]:
        return self.request("unload_build")

    def get_build_info(self) -> dict[str, Any]:
        result = self.request("get_build_info")
        return self._decorate_build_result(result)

    def get_equipment(self) -> dict[str, Any]:
        return self.request("get_equipment")

    def list_calculable_effects(
        self,
        *,
        indices: list[int] | None = None,
        max_effects: int = MAX_EFFECTS,
        force_cache_miss: bool = False,
        malformed_cache: bool = False,
        weapon_set: int | None = None,
    ) -> dict[str, Any]:
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
        return normalize_effect_catalog(self.request("list_calculable_effects", params))

    def read_effect_metrics(
        self,
        reference: dict[str, Any],
        *,
        force_cache_miss: bool = False,
        malformed_cache: bool = False,
        malformed_fallback: bool = False,
        weapon_set: int | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"reference": dict(reference)}
        if force_cache_miss:
            params["force_cache_miss"] = True
        if malformed_cache:
            params["malformed_cache"] = True
        if malformed_fallback:
            params["malformed_fallback"] = True
        if weapon_set is not None:
            if int(weapon_set) not in (1, 2):
                raise ValueError("weapon_set must be 1 or 2")
            params["weapon_set"] = int(weapon_set)
        return decorate_contextual_effect_result(self.request("read_effect_metrics", params))

    def get_weapon_set_context(self) -> dict[str, Any]:
        return self.request("get_weapon_set_context", {})

    def evaluate_effect_candidate(
        self,
        reference: dict[str, Any],
        *,
        weapon_set: int,
        physical_slot: str,
        item_raw: str,
        test_fault: str | None = None,
    ) -> dict[str, Any]:
        """Slice 3 internal: measure one component with a candidate in one exact physical weapon slot."""
        from poe2value.items.effect_components import ComponentReference

        raw_reference = ComponentReference.from_dict(dict(reference)).to_dict()
        if int(weapon_set) not in (1, 2):
            raise ValueError("weapon_set must be 1 or 2")
        params: dict[str, Any] = {
            "reference": raw_reference,
            "weapon_set": int(weapon_set),
            "physical_slot": str(physical_slot),
            "item_raw": str(item_raw),
        }
        if test_fault:
            params["test_fault"] = test_fault
        return decorate_contextual_effect_result(self.request("evaluate_effect_candidate", params))

    def apply_live_equipment(self, equipment: list[dict[str, Any]]) -> dict[str, Any]:
        result = self.request("apply_live_equipment", {"equipment": equipment})
        return self._decorate_build_result(result)

    def get_metrics(self, context: str | None = None) -> dict[str, Any]:
        params = {"context": context} if context else {}
        result = self.request("get_metrics", params)
        return self._decorate_metrics(result)

    def evaluate_candidate(
        self,
        slot: str,
        item_raw: str,
        *,
        context: str | None = None,
        tolerance: float = 0.5,
        component_keys: list[str] | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"slot": slot, "item_raw": item_raw, "tolerance": tolerance}
        if context:
            params["context"] = context
        if component_keys:
            params["component_keys"] = component_keys
        if perf_enabled():
            # Diagnostic only: makes the Lua side return its per-stage breakdown.
            params["perf"] = True
        result = self.request("evaluate_candidate", params)
        return self._decorate_evaluation(result)

    def evaluate_slot_cleared(
        self,
        slot: str,
        *,
        context: str | None = None,
        tolerance: float = 0.5,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"slot": slot, "tolerance": tolerance}
        if context:
            params["context"] = context
        result = self.request("evaluate_slot_cleared", params)
        return decorate_slot_cleared(result)

    def evaluate_gear_plan(
        self,
        replacements: list[dict[str, Any]],
        *,
        context: str | None = None,
        tolerance: float = 0.5,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"replacements": replacements, "tolerance": tolerance}
        if context:
            params["context"] = context
        result = self.request("evaluate_gear_plan", params)
        return decorate_gear_plan_evaluation(result)

    def evaluate_item_slots(
        self,
        slots: list[str],
        item_raw: str,
        *,
        context: str | None = None,
        tolerance: float = 0.5,
        component_keys: list[str] | None = None,
        defer_restore: bool = False,
        test_fault: str | None = None,
        baseline_overrides: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"slots": list(slots), "item_raw": item_raw, "tolerance": tolerance}
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
        return decorate_item_slot_evaluation(self.request("evaluate_item_slots", params))

    def finalize_transaction(self) -> dict[str, Any]:
        return self.request("finalize_transaction")

    def parse_item(self, item_raw: str) -> dict[str, Any]:
        return self.request("parse_item", {"item_raw": item_raw})

    def resolve_compatible_slots(self, item_raw: str) -> dict[str, Any]:
        return self.request("resolve_compatible_slots", {"item_raw": item_raw})

    def shutdown(self) -> None:
        try:
            self.request("shutdown")
        finally:
            self.host.close()

    def _decorate_build_result(self, result: dict[str, Any]) -> dict[str, Any]:
        return decorate_build_result(result)

    def _decorate_metrics(self, result: dict[str, Any]) -> dict[str, Any]:
        return decorate_metrics(result)

    def _decorate_evaluation(self, result: dict[str, Any]) -> dict[str, Any]:
        return decorate_evaluation(result)


def run_worker_stdio(config: PobConfig | None = None) -> int:
    cfg = config or load_config()
    session: WorkerSession | None = None
    try:
        validate_pob_path(cfg)
        session = WorkerSession(cfg)
        session.host.boot()
    except Exception as exc:  # noqa: BLE001 - return a structured startup error to the parent
        error = exc if isinstance(exc, EngineError) else PobBootFailed(str(exc))
        message = getattr(exc, "message", None) or str(exc) or type(exc).__name__
        try:
            sys.stderr.write(f"ExileLens PoB worker could not start: {message}\n")
            sys.stderr.flush()
        except Exception:  # noqa: BLE001 - stderr may be closed in frozen windowed mode
            pass
        try:
            line = sys.stdin.readline().strip()
        except (OSError, ValueError):
            line = ""
        if line:
            try:
                req_id = json.loads(line).get("id")
            except json.JSONDecodeError:
                req_id = None
            sys.stdout.write(json.dumps({"id": req_id, "ok": False, "error": error.to_dict()}) + "\n")
            sys.stdout.flush()
        if session is not None:
            session.host.close()
        return 2
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            response = session.host.dispatch_json(line)
        except Exception as exc:  # pragma: no cover - protocol safety net
            req_id = None
            try:
                req_id = json.loads(line).get("id")
            except json.JSONDecodeError:
                pass
            response = json.dumps(
                {
                    "id": req_id,
                    "ok": False,
                    "error": {"code": "CALC_FAILED", "message": str(exc)},
                }
            )
        sys.stdout.write(response + "\n")
        sys.stdout.flush()
        try:
            parsed = json.loads(response)
            if parsed.get("ok") and parsed.get("result", {}).get("shutting_down"):
                break
        except json.JSONDecodeError:
            pass
    session.host.close()
    return 0


def run_worker_entrypoint(config: PobConfig | None = None) -> int:
    """Windowed/frozen-safe worker boundary: never let startup exceptions escape."""
    _configure_std_streams_utf8()
    try:
        return run_worker_stdio(config)
    except Exception as exc:  # noqa: BLE001 - this is the child process crash boundary
        message = getattr(exc, "message", None) or str(exc) or type(exc).__name__
        try:
            sys.stderr.write(f"ExileLens PoB worker could not start: {message}\n")
            sys.stderr.flush()
        except Exception:  # noqa: BLE001 - even a closed stderr must not trigger a frozen traceback dialog
            pass
        return 2


if __name__ == "__main__":
    raise SystemExit(run_worker_entrypoint())
