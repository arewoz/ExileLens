from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QPoint, QThread, QTimer, Signal

from poe2value.app.build_revision import BuildFileRevision, read_build_revision
from poe2value.app.build_cache import (
    ActiveBuildStatus,
    BuildCache,
    BuildCacheEntry,
    BuildCacheKey,
    revision_dict,
    status_from_entry,
)
from poe2value.app.item_check_lifecycle import (
    ITEM_CHECK_USER_TIMEOUT_MS,
    ITEM_CHECK_WATCHDOG_MS,
    ItemCheckLifecycleRegistry,
    ItemCheckPhase,
)
from poe2value.app.heartbeat import HeartbeatState, StallKind
from poe2value.app.runtime_trace import trace
from poe2value.app.scheduler import BoundedEvaluationScheduler
from poe2value.app.settings import AppSettings, BaselineMode, save_settings
from poe2value._version import __version__, git_commit
from poe2value.branding import APP_NAME
from poe2value.build_source import BuildSource, read_build_source
from poe2value.build_sources import LocalPobBuildSource
from poe2value.config import PobConfig, validate_pob_path
from poe2value.engine import Engine
from poe2value.errors import EngineError, NotPoe2Item, UnsupportedGameLanguage, WorkerUnhealthy
from poe2value.items.cache import ItemPipelineCache
from poe2value.items.evaluation import classify_localization_failure, evaluate_item
from poe2value.items.language_detect import UNSUPPORTED_LANGUAGE_TITLE
from poe2value.items.history import baseline_identity
from poe2value.items.compare import STALE_BUILD_CHANGED, PinCompareState, build_compare_summary
from poe2value.items.item_check_settings import ItemCheckProSettings
from poe2value.items.loot_review import LootReviewSession
from poe2value.items.persistent_history import PersistentItemHistory
from poe2value.items.potential import UpgradePotentialAnalyzer
from poe2value.items.primary_metric import resolve_primary_metric
from poe2value.items.build_intel.decomposition import run_bounded_decomposition
from poe2value.items.build_intel.engine import attach_decomposition
from poe2value.items.build_intel.item_semantics import parse_item_semantics
from poe2value.items.build_intel.relevance import rank_groups_for_decomposition
from poe2value.items.build_intel.models import BuildMod
from poe2value.items.price import ManualPrice, ManualPriceError, parse_manual_price
from poe2value.items.evaluation_identity import EvaluationContextIdentity, EvaluationIdentity, identity_from_state
from poe2value.items.raw_input import ItemInputSource, RawItemInput
from poe2value.items.recognition import recognize_input
from poe2value.items.result_cache import EvaluationResultCache, evaluation_cache_key
from poe2value.items.upgrade_path import attach_upgrade_path_presentation
from poe2value.items.value_layer import rescore_evaluation
from poe2value.app.build_state import BaselineState, BuildInfo, BuildState
from poe2value.app.item_dismiss import ItemDismissController
from poe2value.app.external_clipboard_capture import (
    ExternalClipboardCandidate,
    ExternalClipboardDecision,
    ExternalClipboardRouter,
)
from poe2value.app.price_check_capture import PriceCheckCaptureCoordinator
from poe2value.app.price_check_session import PriceCheckSession
from poe2value.price_check.panel_edits import apply_panel_edits
from poe2value.app.price_check_hotkey import PriceCheckHotkeyController
from poe2value.app.refine_price_hotkey import RefinePriceHotkeyController
from poe2value.app.settings import DEFAULT_PRICE_CHECK_HOTKEY
from poe2value.app.modules.registry import FeatureModule, is_enabled
from poe2value.app.progress import OperationProgressHub, OperationStatus
from poe2value.platform.windows.clipboard_identity import is_duplicate_clipboard_event
from poe2value.platform.windows.cursor import get_cursor_pos_physical
from poe2value.analysis.cache import ProbeCache
from poe2value.analysis.pipeline import AnalysisYielded, analyze_build, analyze_slot, rescore_analysis
from poe2value.market.engine import run_market_search
from poe2value.market.eval_cache import MarketEvalCache
from poe2value.market.models import MarketSearchRequest as DomainMarketSearchRequest
from poe2value.market.models import SearchDepth
from poe2value.gear.engine import run_gear_optimization
from poe2value.gear.cache import GearPlanEvalCache
from poe2value.gear.models import GearOptimizationRequest as DomainGearOptimizationRequest, GearSearchPreset, PlanConstraint
from poe2value.gear.registry import CandidatePoolRegistry
from poe2value.market_assist.evaluator import evaluate_capture_observation
from poe2value.market_assist.finalization import finalize_session_to_pool, pool_to_handoff_payload
from poe2value.market_assist.guidance import AdaptiveMarketGuidance
from poe2value.market_assist.ideal_target import IdealTargetAnalyzer
from poe2value.market_assist.session_store import MarketCaptureSessionStore
from poe2value.market_assist.settings import MarketAssistantRuntimeSettings
from poe2value.market.models import ListingPrice
from poe2value.platform.windows.foreground_info import evaluate_poe_foreground_match
from poe2value.price_check.capture_diagnostics import CapturePhase, log_capture_phase
from poe2value.price_check.cache import PriceCheckCache
from poe2value.price_check.diagnostic_mode import (
    is_market_only_mode,
    load_market_fixture_text,
)
from poe2value.price_check.factory import build_default_price_check_providers, build_market_only_price_check_providers
from poe2value.price_check.league_catalog import LeagueCatalog
from poe2value.price_check.league_resolver import (
    MODE_PINNED,
    LeagueResolution,
    describe_resolution,
    resolve_market_league,
)
from poe2value.price_check.models import CompiledPriceCheckRequest, LeagueContext, PriceCheckRequest as DomainPriceCheckRequest
from poe2value.price_check.presentation import (
    build_capture_test_presentation,
    build_market_only_presentation,
    build_price_check_acquisition_failure,
    build_price_check_league_required,
    build_price_check_queued,
)
from poe2value.price_check.service import PriceCheckService
from poe2value.baseline import ResolvedBaseline, canonical_item_set_id, resolve_item_set
from poe2value.tree.calibration_session import CalibrationSession
from poe2value.tree.tracked_loader import TrackedTreeLoader
from poe2value.tree.tracked_source import TrackedTreeSource

logger = logging.getLogger(__name__)
from poe2value.tree.view_model import TreeCoachViewModel


@dataclass
class EvaluationRequest:
    request_id: int
    raw_text: str
    content_hash: str
    clipboard_received_ms: float
    copy_timestamp: float
    cursor_position: QPoint | None = None
    copy_anchor_screen_px: tuple[int, int] | None = None
    baseline_generation: int = 0
    presentation_generation: int = 0
    clipboard_sequence: int | None = None
    kind: str = "gameplay"
    context_identity: str = ""
    candidate_fingerprint: str = ""


@dataclass
class BaselineReloadRequest:
    request_id: int
    path: str
    context: str = "MAP"
    loadout: str = ""
    item_set: str = ""
    baseline_generation: int = 0
    kind: str = "baseline"
    apply: str = "load_xml"


@dataclass
class MarketSearchRequest:
    request_id: int
    slot: str
    profile: str = "BALANCED"
    budget_amount: float | None = None
    budget_currency: str | None = None
    depth: str = "BALANCED"
    source: str = "fixture"
    fixture_corpus: str | None = None
    import_path: str | None = None
    search_intent: dict[str, Any] | None = None
    baseline_generation: int = 0
    kind: str = "market"
    priority: int = 0


@dataclass
class GearOptimizationRequest:
    request_id: int
    budget_amount: float
    budget_currency: str
    profile: str = "BALANCED"
    search_preset: str = "BALANCED"
    enabled_slots: tuple[str, ...] = ()
    max_purchases: int | None = None
    min_dps_floor: float | None = None
    min_max_hit_floor: float | None = None
    baseline_generation: int = 0
    kind: str = "gear"
    priority: int = 0


@dataclass
class MarketCaptureEvalRequest:
    request_id: int
    observation_id: str
    item_raw: str
    product_slot: str
    pob_slot: str
    price_amount: float | None = None
    price_currency: str | None = None
    baseline_generation: int = 0
    kind: str = "market_capture"
    priority: int = 0


@dataclass
class UpgradePathRequest:
    request_id: int
    parent_request_id: int
    content_hash: str
    item_raw: str
    slot: str
    result_snapshot: dict[str, Any]
    baseline_generation: int = 0
    presentation_generation: int = 0
    profile: str = "BALANCED"
    style: str = "BALANCED"
    deep: bool = False
    kind: str = "upgrade_path"
    priority: int = 22


@dataclass
class BuildDecompRequest:
    request_id: int
    parent_request_id: int
    content_hash: str
    item_raw: str
    slot: str
    result_snapshot: dict[str, Any]
    baseline_generation: int = 0
    presentation_generation: int = 0
    profile: str = "BALANCED"
    kind: str = "build_decomp"
    priority: int = 20


@dataclass
class AnalysisRequest:
    request_id: int
    baseline_generation: int = 0
    profile: str = "BALANCED"
    slot: str | None = None
    kind: str = "analysis"
    task: str = "build"
    max_points: int = 3
    scope: str = "frontier"
    node_ids: list[int] | None = None
    priority: int = 0


@dataclass
class EvaluationTiming:
    request_id: int
    clipboard_received_ms: float = 0.0
    evaluation_started_ms: float = 0.0
    evaluation_finished_ms: float = 0.0
    ui_updated_ms: float = 0.0
    pipeline_timings: dict[str, Any] = field(default_factory=dict)


class _EvaluationWorker(QObject):
    evaluate = Signal(object)
    analyze = Signal(object)
    market_search = Signal(object)
    gear_optimization = Signal(object)
    market_capture_eval = Signal(object)
    reload_baseline = Signal(object)
    upgrade_path = Signal(object)
    build_decomp = Signal(object)
    finished_eval = Signal(int, object, object)  # request_id, (result, timing)|None, error|None
    finished_analysis = Signal(int, object, object)
    finished_market = Signal(int, object, object)
    finished_gear = Signal(int, object, object)
    finished_market_capture = Signal(int, object, object)
    finished_baseline = Signal(int, object, object)
    finished_upgrade_path = Signal(int, object, object)
    finished_build_decomp = Signal(int, object, object)
    analysis_progress = Signal(object)
    market_progress = Signal(object)
    gear_progress = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._engine: Engine | None = None
        self._build_path = ""
        self._context = "MAP"
        self._baseline_mode = BaselineMode.POB_BUILD_GEAR
        self._value_profile = "BALANCED"
        self._cache = ItemPipelineCache()
        self._probe_cache = ProbeCache()
        self._market_cache = MarketEvalCache()
        self._gear_cache = GearPlanEvalCache()
        self._gear_registry = CandidatePoolRegistry()
        self._gear_baseline_fingerprint = ""
        self._tree_cache = None
        self._yield_analysis = False
        self._loadout = ""
        self._item_set = ""
        self._pob_path = ""
        self._item_check_pro: dict[str, Any] = {}
        self._upgrade_path_cache: dict[str, dict[str, Any]] = {}
        self._offense_coverage_cache: dict[str, dict[str, Any]] = {}
        self._offense_coverage: dict[str, Any] | None = None
        self._potential_analyzer: UpgradePotentialAnalyzer | None = None
        self.evaluate.connect(self.run_evaluation)
        self.analyze.connect(self.run_analysis)
        self.market_search.connect(self.run_market_search)
        self.gear_optimization.connect(self.run_gear_optimization)
        self.market_capture_eval.connect(self.run_market_capture_eval)
        self.reload_baseline.connect(self.run_baseline_reload)
        self.upgrade_path.connect(self.run_upgrade_path)
        self.build_decomp.connect(self.run_build_decomp)

    def request_yield(self) -> None:
        self._yield_analysis = True

    def configure(
        self,
        engine: Engine,
        build_path: str,
        context: str,
        *,
        baseline_mode: BaselineMode = BaselineMode.POB_BUILD_GEAR,
        value_profile: str = "BALANCED",
        loadout: str = "",
        item_set: str = "",
        pob_path: str = "",
        gear_registry: CandidatePoolRegistry | None = None,
        gear_baseline_fingerprint: str = "",
        item_check_pro: dict[str, Any] | None = None,
        upgrade_path_cache: dict[str, dict[str, Any]] | None = None,
        offense_coverage: dict[str, Any] | None = None,
        offense_coverage_cache: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self._engine = engine
        self._build_path = build_path
        self._context = context
        self._baseline_mode = baseline_mode
        self._value_profile = value_profile
        self._loadout = loadout
        self._item_set = item_set
        self._pob_path = pob_path
        self._gear_registry = gear_registry or CandidatePoolRegistry()
        self._gear_baseline_fingerprint = gear_baseline_fingerprint
        self._item_check_pro = dict(item_check_pro or {})
        self._upgrade_path_cache = upgrade_path_cache if upgrade_path_cache is not None else {}
        self._offense_coverage = dict(offense_coverage) if offense_coverage else None
        self._offense_coverage_cache = offense_coverage_cache if offense_coverage_cache is not None else {}
        self._potential_analyzer = None

    def invalidate_baseline_caches(self) -> None:
        self._cache.invalidate()
        self._probe_cache.invalidate()
        self._market_cache.invalidate()
        if self._tree_cache is not None:
            self._tree_cache.invalidate()

    def run_baseline_reload(self, request: BaselineReloadRequest) -> None:
        import time as _time

        started = _time.perf_counter()
        try:
            assert self._engine is not None
            self.invalidate_baseline_caches()
            from poe2value.tree.cache import TreeEvalCache
            from poe2value.tree.mutations import load_tree_snapshot

            if self._tree_cache is None:
                self._tree_cache = TreeEvalCache()
            path = request.path
            context = request.context
            if request.apply == "load_xml":
                result = self._engine.load_build(path, context=context)
            else:
                result = self._engine.ensure_build_ready(path, context=context)
            build = result.get("build") if isinstance(result.get("build"), dict) else {}
            name = (build or {}).get("name") or Path(path).stem
            loadout_info = self._engine.list_loadouts()
            item_set_info = self._engine.list_item_sets()
            loadouts = list(loadout_info.get("loadouts") or [])
            item_sets = list(item_set_info.get("item_sets") or [])
            active_loadout = str(loadout_info.get("active") or "")
            wanted_loadout = (request.loadout or "").strip()
            if wanted_loadout and wanted_loadout in {entry.get("name") for entry in loadouts}:
                self._engine.set_active_loadout(wanted_loadout)
                active_loadout = wanted_loadout
                item_set_info = self._engine.list_item_sets()
                item_sets = list(item_set_info.get("item_sets") or [])
            wanted_item = (request.item_set or "").strip()
            if wanted_item:
                resolved_wanted = resolve_item_set(item_sets, wanted_item)
                if resolved_wanted.valid:
                    self._engine.set_active_item_set(resolved_wanted.id)
                    item_set_info = self._engine.list_item_sets()
                    item_sets = list(item_set_info.get("item_sets") or [])
            resolved = resolve_item_set(item_sets, item_set_info.get("active_id"))
            metrics = self._engine.get_metrics(context=context)
            fingerprint = str(metrics.get("fingerprint_hash") or "")
            equipment = {}
            try:
                equipment = self._engine.get_equipment() or {}
            except Exception:
                equipment = {}
            from poe2value.config import fingerprint_hash
            from poe2value.tree.fingerprint import tree_fingerprint_from_components

            equipment_fp = fingerprint_hash(equipment if isinstance(equipment, dict) else {"equipment": equipment})
            tree_fp = tree_fingerprint_from_components(metrics.get("fingerprint") or {})
            snapshot = load_tree_snapshot(
                self._engine,
                build_path=path,
                context=context,
                profile=self._value_profile,
                generation=request.baseline_generation,
                loadout=active_loadout,
                item_set=resolved.id,
            )
            tree_set = snapshot.tree_set if isinstance(snapshot.tree_set, dict) else {}
            self._build_path = path
            self._context = context
            self._loadout = active_loadout
            self._item_set = resolved.id
            elapsed = (_time.perf_counter() - started) * 1000
            payload = {
                "ok": True,
                "build_path": path,
                "build_name": name,
                "context": context,
                "loadouts": loadouts,
                "item_sets": item_sets,
                "active_loadout": active_loadout,
                "item_set_id": resolved.id,
                "item_set_name": resolved.name,
                "item_set_valid": resolved.valid,
                "tree_set": tree_set,
                "fingerprint": fingerprint,
                "fingerprint_components": dict(metrics.get("fingerprint") or {}),
                "source_revision": getattr(getattr(self._engine, "loaded_revision", None), "token", ""),
                "tree_fingerprint": snapshot.baseline.tree_fingerprint or tree_fp,
                "equipment_fingerprint": equipment_fp,
                "metrics": metrics.get("raw") or metrics.get("normalized") or metrics,
                "graph": snapshot.to_graph_export(),
                "baseline": snapshot.baseline.to_dict(),
                "reload_ms": round(elapsed, 2),
                "request_meta": {
                    "request_id": request.request_id,
                    "baseline_generation": request.baseline_generation,
                    "kind": "baseline",
                },
            }
            self.finished_baseline.emit(request.request_id, payload, None)
        except Exception as exc:
            self.finished_baseline.emit(request.request_id, None, exc)

    def run_evaluation(self, request: EvaluationRequest) -> None:
        started = time.perf_counter() * 1000
        try:
            assert self._engine is not None
            result = evaluate_item(
                request.raw_text,
                self._engine,
                build_path=self._build_path,
                context=self._context,
                source=ItemInputSource.CLIPBOARD,
                cache=self._cache,
                debug=False,
                value_profile=self._value_profile,
                loadout=self._loadout,
                item_set=self._item_set,
                item_check_pro=self._item_check_pro,
                offense_coverage=self._offense_coverage,
                # PERF-02: this is the delivery path the restore is moved off. Safe here
                # and only here, because _finalize_deferred_restore below runs before
                # this slot returns, and this thread processes one request at a time --
                # so the next evaluation cannot start on an unverified state. The worker
                # enforces the same invariant independently.
                defer_restore=True,
            )
            finished = time.perf_counter() * 1000
            timing = EvaluationTiming(
                request_id=request.request_id,
                clipboard_received_ms=request.clipboard_received_ms,
                evaluation_started_ms=started,
                evaluation_finished_ms=finished,
                pipeline_timings=result.get("timings", {}),
            )
            result["request_meta"] = {
                "request_id": request.request_id,
                "content_hash": request.content_hash,
                "copy_timestamp": request.copy_timestamp,
                "cursor_position": (
                    {"x": request.cursor_position.x(), "y": request.cursor_position.y()}
                    if request.cursor_position is not None
                    else None
                ),
                "copy_anchor_screen_px": (
                    {"x": request.copy_anchor_screen_px[0], "y": request.copy_anchor_screen_px[1]}
                    if request.copy_anchor_screen_px is not None
                    else None
                ),
                "baseline_generation": request.baseline_generation,
                "baseline_mode": self._baseline_mode.value,
                "presentation_generation": request.presentation_generation,
                "context": self._context,
                "value_profile": self._value_profile,
                "clipboard_sequence": request.clipboard_sequence,
                "cache_hit": False,
                "evaluation_context_identity": request.context_identity,
                "candidate_fingerprint": request.candidate_fingerprint,
                "worker_source_revision": str(result.get("source_revision") or ""),
                "worker_source_generation": int(result.get("source_generation") or 0),
                # Which exact build bytes produced this result (More Info / diagnostics).
                "build_sha": source.short_sha if isinstance(source := getattr(self._engine, "loaded_source", None), BuildSource) else "",
            }
            self.finished_eval.emit(request.request_id, (result, timing), None)
        except NotPoe2Item as exc:
            self.finished_eval.emit(request.request_id, None, exc)
        except Exception as exc:
            self.finished_eval.emit(request.request_id, None, exc)
        finally:
            # The user already has the answer; restoring the build prepares the NEXT one.
            # Runs in `finally` so a failed evaluation still cannot leave a candidate
            # item equipped.
            self._finalize_deferred_restore()

    def _finalize_deferred_restore(self) -> None:
        """Complete the restore + verification parked by a deferred evaluation.

        Runs after the result has been emitted, still on this thread and still inside the
        slot that handled the request, so the next queued evaluation cannot begin until it
        returns. A failure means the build is no longer trustworthy going forward -- never
        that the delivered result was wrong, which was measured from a baseline an earlier
        transaction verified. Engine.finalize_transaction invalidates the loaded build on
        failure, so the next Item Check reloads known-good bytes before measuring.
        """
        engine = self._engine
        if engine is None or not hasattr(engine, "finalize_transaction"):
            return
        try:
            engine.finalize_transaction()
        except Exception:
            logger.exception("deferred PoB restore failed; the build will be reloaded before the next item")

    def run_analysis(self, request: AnalysisRequest) -> None:
        self._yield_analysis = False
        try:
            assert self._engine is not None

            def should_yield() -> bool:
                return self._yield_analysis

            def on_progress(payload: dict[str, Any]) -> None:
                self.analysis_progress.emit(payload)

            kwargs = {
                "build_path": self._build_path,
                "context": self._context,
                "profile": request.profile or self._value_profile,
                "generation": request.baseline_generation,
                "loadout": self._loadout,
                "item_set": self._item_set,
                "pob_path": self._pob_path,
                "cache": self._probe_cache,
                "should_yield": should_yield,
                "on_progress": on_progress,
            }
            if getattr(request, "task", "build") in {"tree", "tree_snapshot"}:
                from poe2value.tree.cache import TreeEvalCache
                from poe2value.tree.pipeline import analyze_tree

                if self._tree_cache is None:
                    self._tree_cache = TreeEvalCache()
                result = analyze_tree(
                    self._engine,
                    build_path=self._build_path,
                    context=self._context,
                    profile=request.profile or self._value_profile,
                    generation=request.baseline_generation,
                    loadout=self._loadout,
                    item_set=self._item_set,
                    max_points=getattr(request, "max_points", 3),
                    scope="snapshot" if request.task == "tree_snapshot" else getattr(request, "scope", "frontier"),
                    visible_node_ids=getattr(request, "node_ids", None),
                    cache=self._tree_cache,
                    should_yield=should_yield,
                    on_progress=on_progress,
                )
            elif request.slot:
                result = analyze_slot(self._engine, slot=request.slot, **kwargs)
            else:
                result = analyze_build(self._engine, **kwargs)
            result["request_meta"] = {
                "request_id": request.request_id,
                "baseline_generation": request.baseline_generation,
                "kind": "analysis",
            }
            self.finished_analysis.emit(request.request_id, result, None)
        except AnalysisYielded:
            self.finished_analysis.emit(
                request.request_id,
                {
                    "status": "yielded",
                    "request_meta": {
                        "request_id": request.request_id,
                        "baseline_generation": request.baseline_generation,
                    },
                },
                None,
            )
        except Exception as exc:
            self.finished_analysis.emit(request.request_id, None, exc)

    def run_market_search(self, request: MarketSearchRequest) -> None:
        self._yield_analysis = False
        try:
            assert self._engine is not None

            def should_yield() -> bool:
                return self._yield_analysis

            def on_progress(payload: dict[str, Any]) -> None:
                self.market_progress.emit(payload)

            revision = read_build_revision(self._build_path)
            domain = DomainMarketSearchRequest(
                slot=request.slot,
                profile=request.profile or self._value_profile,
                budget_amount=request.budget_amount,
                budget_currency=request.budget_currency,
                depth=SearchDepth(str(request.depth).upper()),
                source=request.source,
                fixture_corpus=request.fixture_corpus,
                import_path=request.import_path,
                search_intent=request.search_intent,
                baseline_generation=request.baseline_generation,
                build_revision=(
                    {
                        "path": revision.path,
                        "mtime_ns": revision.mtime_ns,
                        "size": revision.size,
                    }
                    if revision
                    else None
                ),
            )
            result = run_market_search(
                self._engine,
                domain,
                build_path=self._build_path,
                context=self._context,
                loadout=self._loadout,
                item_set=self._item_set,
                generation=request.baseline_generation,
                pob_path=self._pob_path,
                cache=self._market_cache,
                should_yield=should_yield,
                on_progress=on_progress,
            )
            payload = result.to_dict()
            payload["request_meta"] = {
                "request_id": request.request_id,
                "baseline_generation": request.baseline_generation,
                "kind": "market",
            }
            self.finished_market.emit(request.request_id, payload, None)
        except AnalysisYielded:
            self.finished_market.emit(
                request.request_id,
                {
                    "status": "yielded",
                    "request_meta": {
                        "request_id": request.request_id,
                        "baseline_generation": request.baseline_generation,
                    },
                },
                None,
            )
        except Exception as exc:
            self.finished_market.emit(request.request_id, None, exc)

    def run_gear_optimization(self, request: GearOptimizationRequest) -> None:
        self._yield_analysis = False
        try:
            assert self._engine is not None

            def should_yield() -> bool:
                return self._yield_analysis

            def on_progress(payload: dict[str, Any]) -> None:
                self.gear_progress.emit(payload)

            revision = read_build_revision(self._build_path)
            pools = self._gear_registry.ready_pools(
                baseline_fingerprint=self._gear_baseline_fingerprint,
                baseline_generation=request.baseline_generation,
                profile=request.profile or self._value_profile,
                enabled_slots=request.enabled_slots,
            )
            domain = DomainGearOptimizationRequest(
                baseline_fingerprint=self._gear_baseline_fingerprint,
                baseline_generation=request.baseline_generation,
                pools=pools,
                budget_amount=float(request.budget_amount),
                budget_currency=request.budget_currency,
                profile=request.profile or self._value_profile,
                context=self._context,
                constraints=(
                    PlanConstraint.MAIN_SKILL_MUST_REMAIN_VALID,
                    PlanConstraint.KEEP_ELEMENTAL_RES_CAPS,
                    PlanConstraint.EHP_NOT_BELOW_CURRENT,
                    PlanConstraint.RESOURCE_STATE_NOT_WORSE,
                    PlanConstraint.MAX_PURCHASES,
                ),
                search_preset=GearSearchPreset(str(request.search_preset).upper()),
                enabled_slots=request.enabled_slots,
                max_purchases=request.max_purchases,
                min_dps_floor=request.min_dps_floor,
                min_max_hit_floor=request.min_max_hit_floor,
                build_revision=(
                    {
                        "path": revision.path,
                        "mtime_ns": revision.mtime_ns,
                        "size": revision.size,
                    }
                    if revision
                    else None
                ),
            )
            result = run_gear_optimization(
                self._engine,
                domain,
                build_path=self._build_path,
                context=self._context,
                loadout=self._loadout,
                item_set=self._item_set,
                registry=self._gear_registry,
                cache=self._gear_cache,
                should_yield=should_yield,
                on_progress=on_progress,
            )
            payload = result.to_dict()
            payload["request_meta"] = {
                "request_id": request.request_id,
                "baseline_generation": request.baseline_generation,
                "kind": "gear",
            }
            self.finished_gear.emit(request.request_id, payload, None)
        except Exception as exc:
            self.finished_gear.emit(request.request_id, None, exc)

    def run_market_capture_eval(self, request: MarketCaptureEvalRequest) -> None:
        try:
            assert self._engine is not None
            price = None
            if request.price_amount is not None and request.price_currency:
                price = ListingPrice(amount=float(request.price_amount), currency=str(request.price_currency))
            fingerprint = self._gear_baseline_fingerprint or str(self._engine.get_metrics().get("fingerprint_hash") or "")
            evaluation = evaluate_capture_observation(
                self._engine,
                item_raw=request.item_raw,
                product_slot=request.product_slot,
                pob_slot=request.pob_slot,
                build_path=self._build_path,
                context=self._context,
                profile=self._value_profile,
                price=price,
                fingerprint=fingerprint,
                cache=self._market_cache,
                budget_currency=request.price_currency,
            )
            payload = {
                "observation_id": request.observation_id,
                "evaluation": evaluation,
                "request_meta": {
                    "request_id": request.request_id,
                    "baseline_generation": request.baseline_generation,
                    "kind": "market_capture",
                },
            }
            self.finished_market_capture.emit(request.request_id, payload, None)
        except Exception as exc:
            self.finished_market_capture.emit(request.request_id, None, exc)

    def run_upgrade_path(self, request: UpgradePathRequest) -> None:
        try:
            assert self._engine is not None
            if self._potential_analyzer is None:
                self._potential_analyzer = UpgradePotentialAnalyzer(self._engine, cache=self._upgrade_path_cache)
            analyzer = self._potential_analyzer
            result = dict(request.result_snapshot)
            payload = analyzer.analyze(
                slot=request.slot,
                item_raw=request.item_raw,
                result=result,
                profile=request.profile or self._value_profile,
                style=request.style,
                deep=request.deep,
            ).to_dict()
            self.finished_upgrade_path.emit(
                request.request_id,
                {
                    "parent_request_id": request.parent_request_id,
                    "content_hash": request.content_hash,
                    "upgrade_potential": payload,
                    "presentation_generation": request.presentation_generation,
                    "baseline_generation": request.baseline_generation,
                    "request_meta": {
                        "request_id": request.request_id,
                        "parent_request_id": request.parent_request_id,
                        "kind": "upgrade_path",
                    },
                },
                None,
            )
        except Exception as exc:
            self.finished_upgrade_path.emit(request.request_id, None, exc)

    def run_build_decomp(self, request: BuildDecompRequest) -> None:
        try:
            assert self._engine is not None
            snapshot = dict(request.result_snapshot)
            intel = (snapshot.get("recommendation") or {}).get("build_comparison") or snapshot.get("build_comparison") or {}
            semantic_payload = intel.get("semantic") or {}
            metadata = snapshot.get("metadata") or {}
            if hasattr(metadata, "__dict__") and not isinstance(metadata, dict):
                metadata = dict(metadata.__dict__)
            semantic = parse_item_semantics(
                request.item_raw,
                metadata=metadata,
                product_slot=str((snapshot.get("recommendation") or {}).get("product_slot") or ""),
            )
            mods: list[BuildMod] = []
            for item in intel.get("mods") or []:
                if isinstance(item, BuildMod):
                    mods.append(item)
                    continue
                if isinstance(item, dict):
                    allowed = {key: item[key] for key in item if key in BuildMod.__dataclass_fields__}
                    mods.append(BuildMod(**allowed))
            groups = rank_groups_for_decomposition(mods)
            if not groups:
                groups = list((semantic_payload.get("groups") or semantic.groups or {}).keys())[:5]
            primary = snapshot.get("primary_metric") or {}
            recommendation = snapshot.get("recommendation") or {}
            payload = run_bounded_decomposition(
                self._engine,
                slot=request.slot,
                item_raw=request.item_raw,
                semantic=semantic,
                groups=groups,
                whole_comparison=recommendation,
                context=self._context,
                profile=request.profile or self._value_profile,
                primary_field=primary.get("pob_field") or "CombinedDPS",
                primary_confidence=primary.get("confidence") or "high",
                offense_coverage=snapshot.get("offense_coverage"),
                cache=self._upgrade_path_cache,
            )
            self.finished_build_decomp.emit(
                request.request_id,
                {
                    "parent_request_id": request.parent_request_id,
                    "content_hash": request.content_hash,
                    "decomposition": payload,
                    "presentation_generation": request.presentation_generation,
                    "baseline_generation": request.baseline_generation,
                    "request_meta": {
                        "request_id": request.request_id,
                        "parent_request_id": request.parent_request_id,
                        "kind": "build_decomp",
                    },
                },
                None,
            )
        except Exception as exc:
            self.finished_build_decomp.emit(request.request_id, None, exc)



class EvaluationController(QObject):
    build_changed = Signal(object)
    loadouts_changed = Signal(object)
    evaluation_started = Signal(int)
    evaluation_finished = Signal(int, object)
    evaluation_error = Signal(int, str)
    # LANG-01: errors that need their own headline instead of "Could not analyze".
    evaluation_titled_error = Signal(int, str, str)
    evaluation_warming = Signal(int)
    evaluation_timeout = Signal(int)
    analyzing = Signal(int)
    state_message = Signal(str)
    heartbeat_updated = Signal(object)
    presentation_invalidated = Signal()
    last_result_rescored = Signal(object)
    analysis_started = Signal(int)
    analysis_progress = Signal(object)
    analysis_finished = Signal(object)
    analysis_error = Signal(str)
    analysis_stale = Signal()
    market_started = Signal(int)
    market_progress = Signal(object)
    market_finished = Signal(object)
    market_error = Signal(str)
    market_stale = Signal()
    gear_started = Signal(int)
    gear_progress = Signal(object)
    gear_finished = Signal(object)
    gear_error = Signal(str)
    gear_stale = Signal()
    market_capture_updated = Signal(object)
    market_capture_session_changed = Signal(object)
    market_capture_new_best = Signal()
    baseline_state_changed = Signal(object)
    active_build_status_changed = Signal(object)
    value_profile_changed = Signal(str)
    upgrade_path_updated = Signal(int, object)
    tree_overlay_invalidated = Signal()
    tree_overlay_show_requested = Signal(bool)
    tree_overlay_calibrate_requested = Signal()
    tree_overlay_mode_requested = Signal(str)
    tree_overlay_realign_requested = Signal()
    tree_overlay_scale_requested = Signal()
    tree_overlay_test_pattern_requested = Signal()
    tree_overlay_debug_requested = Signal(bool)
    tree_overlay_capture_requested = Signal(str)
    tree_overlay_fine_tune_requested = Signal()
    tree_overlay_looks_good_requested = Signal()
    tree_overlay_reset_calibration_requested = Signal()
    tree_overlay_anchors_only_requested = Signal(bool)
    tracked_tree_changed = Signal(object)
    tracked_tree_sets_changed = Signal(object)
    tracked_tree_error = Signal(str)
    pin_compare_changed = Signal()
    price_check_started = Signal(int)
    #: Emitted the moment a Shift+C capture is parsed, before any market work. The
    #: panel opens on this, so the user sees the item acknowledged rather than
    #: waiting on a search that may be queued behind the rate scheduler.
    price_check_captured = Signal(int, dict)
    price_check_finished = Signal(int, object)
    refine_last_price_requested = Signal()
    # MARKET-01B10: request_id, list[str] leagues, str failure_code, str stale_league
    league_selection_required = Signal(int, object, str, str)
    market_league_changed = Signal(str, str)
    #: PoB worker booted in the background and is ready for load_build.
    engine_ready = Signal()
    #: PoB worker could not start; the payload is a user-facing reason.
    engine_failed = Signal(str)
    #: Internal: boot thread -> GUI thread hand-off (engine or None, exception or None).
    _engine_boot_result = Signal(object, object)

    def __init__(
        self,
        settings: AppSettings,
        parent: QObject | None = None,
        build_cache: BuildCache | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.build_info = BuildInfo(context=settings.context)
        self.baseline_state = BaselineState(state=BuildState.NO_BUILD, context=settings.context)
        self._build_cache = build_cache or BuildCache()
        self._active_build_status = status_from_entry(self._build_cache.load_active())
        self.tree_view_model = TreeCoachViewModel(profile=settings.value_profile)
        self.calibration_session = CalibrationSession()
        self.calibration_session.load_saved(settings.tree_overlay_calibration)
        self.tree_overlay_diagnostics: dict[str, Any] = {}
        self._engine: Engine | None = None
        self._started_monotonic = time.monotonic()
        self._engine_booting = False
        self._engine_error = ""
        self._last_build_error = ""
        #: Bytes of the last build that loaded successfully; restored if a reload breaks.
        self._last_good_source: BuildSource | None = None
        self._build_loaded_at: float | None = None
        self._reload_warning = ""
        self._shutting_down = False
        self._engine_boot_result.connect(self._on_engine_boot_result)
        self._request_id = 0
        self._latest_request_id = 0
        self._pending_request_id: int | None = None
        self._last_clipboard_sequence: int | None = None
        self._last_clipboard_hash: str = ""
        self._result_cache = EvaluationResultCache()
        self._worker = _EvaluationWorker()
        self._thread = QThread()
        self._worker.moveToThread(self._thread)
        self._worker.finished_eval.connect(self._on_worker_finished)
        self._worker.finished_analysis.connect(self._on_analysis_finished)
        self._worker.finished_market.connect(self._on_market_finished)
        self._worker.finished_gear.connect(self._on_gear_finished)
        self._worker.finished_market_capture.connect(self._on_market_capture_finished)
        self._worker.finished_baseline.connect(self._on_baseline_finished)
        self._worker.finished_upgrade_path.connect(self._on_upgrade_path_finished)
        self._worker.finished_build_decomp.connect(self._on_build_decomp_finished)
        self._worker.analysis_progress.connect(self._on_analysis_progress)
        self._worker.market_progress.connect(self._on_market_progress)
        self._worker.gear_progress.connect(self._on_gear_progress)
        self._thread.start()
        self._recovery_attempted = False
        self._last_result: dict[str, Any] | None = None
        self._last_timing: EvaluationTiming | None = None
        self._analyzing_timers: dict[int, QTimer] = {}
        self._item_check_watchdogs: dict[int, QTimer] = {}
        self._item_check_user_timeouts: dict[int, QTimer] = {}
        self._item_check_lifecycle = ItemCheckLifecycleRegistry()
        self._pob_warm = False
        self._retry_request: EvaluationRequest | None = None
        self._baseline_generation = 0
        self._worker_generation = 0
        self._evaluation_fingerprint_components: dict[str, Any] = {}
        self._equipment_fingerprint = ""
        self._presentation_generation = 0
        self._tree_analysis_generation = 0
        self._overlay_calibration_generation = 0
        self._accept_tree = True
        self._clipboard_listening = True
        self._last_clipboard: dict[str, Any] = {}
        self._last_item_request: dict[str, Any] = {}
        self._loadouts: list[dict[str, Any]] = []
        self._item_sets: list[dict[str, Any]] = []
        self._active_loadout = ""
        self._active_item_set_id = ""
        self._active_item_set_name = ""
        self._active_tree_set_id = ""
        self._active_tree_set_name = ""
        self._tracked_loader: TrackedTreeLoader | None = None
        self.tracked_tree_source: TrackedTreeSource | None = None
        self.tracked_tree_sets: list[dict[str, Any]] = []
        self._tracked_tree_generation = 0
        self._tracked_tree_loading = False
        self._tracked_tree_error = ""
        self._heartbeat_state = HeartbeatState()
        self._scheduler = BoundedEvaluationScheduler(self._dispatch_to_worker)
        self._heartbeat_timer = QTimer(self)
        self._heartbeat_timer.timeout.connect(self._on_heartbeat)
        self._heartbeat_timer.start(1000)
        pro = ItemCheckProSettings.from_dict(self.settings.item_check_pro)
        self._history = PersistentItemHistory(limit=pro.clamp_history_size())
        self._pin_compare = PinCompareState()
        self._pinned_windows: dict[str, Any] = {}
        self._loot_review = LootReviewSession()
        self._potential_analyzer: UpgradePotentialAnalyzer | None = None
        self._upgrade_path_cache: dict[str, dict[str, Any]] = {}
        self._offense_coverage_cache: dict[str, dict[str, Any]] = {}
        self._offense_coverage: dict[str, Any] | None = None
        self._upgrade_path_jobs: dict[int, UpgradePathRequest] = {}
        self._active_upgrade_parent_id: int | None = None
        self._prices: dict[tuple[str, str], ManualPrice] = {}
        self._last_analysis: dict[str, Any] | None = None
        self._last_market_result: dict[str, Any] | None = None
        self._last_gear_result: dict[str, Any] | None = None
        self.pool_registry = CandidatePoolRegistry()
        self._market_capture_store = MarketCaptureSessionStore()
        self._market_capture_guidance = AdaptiveMarketGuidance()
        self._market_capture_ideal = IdealTargetAnalyzer()
        self._market_capture_cancelled = False
        self._market_capture_new_best_id: str | None = None
        self._market_cancelled = False
        self._gear_cancelled = False
        self._analysis_resume: AnalysisRequest | None = None
        self._analysis_generation = -1
        self._analysis_cancelled = False
        self._baseline_wait_loop = None
        self._build_file_revision: BuildFileRevision | None = None
        self._deferred_evaluation: EvaluationRequest | None = None
        self._auto_reload_status = "UNCHANGED"
        self._reload_status_message = ""
        self._last_copy_anchor_physical: tuple[int, int] | None = None
        self._overlay_placement_diag: dict[str, Any] = {}
        self._request_anchors: dict[int, tuple[int, int]] = {}
        self.progress_hub = OperationProgressHub(self)
        self._progress_by_kind: dict[str, str] = {}
        self.item_dismiss = ItemDismissController(self)
        self.price_check_hotkey = PriceCheckHotkeyController(
            self,
            hotkey=str(getattr(settings, "price_check_hotkey", DEFAULT_PRICE_CHECK_HOTKEY) or DEFAULT_PRICE_CHECK_HOTKEY),
            release_wait_ms=int(getattr(settings, "price_check_release_wait_ms", 500) or 500),
        )
        self.refine_price_hotkey = RefinePriceHotkeyController(
            self,
            hotkey=str(getattr(settings, "price_check_refine_hotkey", "ctrl+shift+r") or "ctrl+shift+r"),
            price_check_hotkey=str(getattr(settings, "price_check_hotkey", DEFAULT_PRICE_CHECK_HOTKEY) or DEFAULT_PRICE_CHECK_HOTKEY),
        )
        self._last_price_check_item_raw = ""
        self._last_price_check_result = None
        self._last_price_check_presentation: dict[str, Any] = {}
        timeout_ms = int(getattr(settings, "price_check_capture_timeout_ms", 600) or 600)
        self.price_check_capture = PriceCheckCaptureCoordinator(self, timeout_ms=timeout_ms)
        self.price_check_capture.capture_started.connect(self._on_price_check_capture_started)
        self.price_check_capture.capture_ready.connect(self._on_price_check_capture_ready)
        self.price_check_capture.capture_failed.connect(self._on_price_check_capture_failed)
        self._external_clipboard_router = ExternalClipboardRouter()
        self._external_clipboard_counts: dict[str, int] = {}
        self._last_external_clipboard_decision = "(none)"
        self._price_check_cache = PriceCheckCache()
        self._price_check_service = PriceCheckService(
            providers=build_default_price_check_providers(
                observations_fn=self._price_check_observations,
                league=settings.market_league,
                cache=self._price_check_cache,
                live_market_mode=settings.live_market_mode,
                diagnostic_mode=settings.price_check_diagnostic_mode,
            ),
            cache=self._price_check_cache,
            live_market_mode=settings.live_market_mode,
            settings_strict_live=settings.strict_live,
            diagnostic_mode=settings.price_check_diagnostic_mode,
        )
        self._market_only_service = PriceCheckService(
            providers=build_market_only_price_check_providers(
                league=settings.market_league,
                cache=PriceCheckCache(live_ttl_seconds=0.0),
            ),
            cache=PriceCheckCache(live_ttl_seconds=0.0),
            strict_live=True,
            diagnostic_mode="market_only",
        )
        self._price_check_inflight = False
        self._active_price_check_id: int | None = None
        self._latest_price_check_id = 0
        self._price_check_session = PriceCheckSession()
        self._league_catalog: LeagueCatalog | None = None
        self._pending_league_request: tuple[str, int, tuple[int, int] | None] | None = None
        self._queued_refreshes: dict[str, tuple[str, int, tuple[int, int] | None, Any, Any]] = {}
        self._queued_timers: dict[str, QTimer] = {}

    def _require_module(self, module: FeatureModule, *, message: str) -> bool:
        if is_enabled(module):
            return True
        self.state_message.emit(message)
        return False

    def _track_progress(self, kind: str, *, module: str, title: str, request_id: int) -> str:
        op = self.progress_hub.begin(module=module, title=title, operation_id=f"{kind}-{request_id}", cancellable=True)
        self._progress_by_kind[kind] = op.operation_id
        return op.operation_id

    def _emit_progress(self, kind: str, payload: dict[str, Any], *, module: str, title: str) -> None:
        op_id = self._progress_by_kind.get(kind)
        if not op_id:
            return
        self.progress_hub.update_from_payload(op_id, payload, module=module, title=title)

    def _finish_progress(self, kind: str, *, status: OperationStatus = OperationStatus.COMPLETE, detail: str = "") -> None:
        op_id = self._progress_by_kind.pop(kind, None)
        if op_id:
            self.progress_hub.finish(op_id, status=status, detail=detail)

    def cancel_module_work(self, module: FeatureModule) -> None:
        if module is FeatureModule.BUILD_ANALYSIS:
            self._scheduler.discard_queued_analysis()
            self._analysis_resume = None
            self._analysis_cancelled = True
            self._worker.request_yield()
            self._finish_progress("analysis", status=OperationStatus.CANCELLED)
        if module is FeatureModule.TREE_TOOLS:
            self.cancel_tree_analysis()
            self._finish_progress("tree", status=OperationStatus.CANCELLED)
        if module is FeatureModule.MARKET:
            self.cancel_market_search()
            self._finish_progress("market", status=OperationStatus.CANCELLED)
        if module is FeatureModule.MARKET_ASSISTANT:
            self.stop_market_capture_session(finalize=False)
            self._finish_progress("market_capture", status=OperationStatus.CANCELLED)
        if module is FeatureModule.GEAR_OPTIMIZER:
            self.cancel_gear_optimization()
            self._finish_progress("gear", status=OperationStatus.CANCELLED)
        if module is FeatureModule.LIVE_TREE_OVERLAY:
            self.settings.tree_overlay_enabled = False
            self.tree_overlay_show_requested.emit(False)

    def _configure_worker(self) -> None:
        if not self._engine or not self.build_info.path:
            return
        self._worker.configure(
            self._engine,
            self.build_info.path,
            self.build_info.context,
            baseline_mode=BaselineMode(self.settings.baseline_mode),
            value_profile=self.settings.value_profile,
            loadout=self._active_loadout,
            item_set=self._active_item_set_id,
            pob_path=self.settings.pob_path,
            gear_registry=self.pool_registry,
            gear_baseline_fingerprint=self.baseline_state.fingerprint or self._equipment_fingerprint,
            item_check_pro=self.settings.item_check_pro,
            upgrade_path_cache=self._upgrade_path_cache,
            offense_coverage=self._offense_coverage,
            offense_coverage_cache=self._offense_coverage_cache,
        )

    def item_check_settings(self) -> ItemCheckProSettings:
        return ItemCheckProSettings.from_dict(self.settings.item_check_pro)

    def update_item_check_settings(self, **kwargs: Any) -> ItemCheckProSettings:
        current = self.item_check_settings().to_dict()
        current.update({key: value for key, value in kwargs.items() if value is not None})
        self.settings.item_check_pro = current
        pro = ItemCheckProSettings.from_dict(current)
        self._history.limit = pro.clamp_history_size()
        self._configure_worker()
        return pro

    def _baseline_identity(self) -> str:
        fingerprint = self.baseline_state.fingerprint
        if not fingerprint and self._last_result:
            rec = self._last_result.get("recommendation") or {}
            fingerprint = str(((rec.get("baseline") or {}).get("fingerprint_hash")) or "")
        return baseline_identity(
            fingerprint=fingerprint,
            source_identity=self.build_info.source_ref.key if self.build_info.source_ref else self.build_info.path,
            loadout=self._active_loadout,
            item_set=self._active_item_set_id,
            context=self.build_info.context,
            generation=self._baseline_generation,
        )

    @property
    def engine(self) -> Engine | None:
        return self._engine

    @staticmethod
    def _pob_head_hint() -> str:
        from poe2value import SUPPORTED_POB_HEAD

        return SUPPORTED_POB_HEAD[:12]

    @property
    def last_result(self) -> dict[str, Any] | None:
        return self._last_result

    @property
    def last_timing(self) -> EvaluationTiming | None:
        return self._last_timing

    @property
    def baseline_generation(self) -> int:
        return self._baseline_generation

    @property
    def heartbeat_state(self) -> HeartbeatState:
        return self._heartbeat_state

    @property
    def scheduler_metrics(self):
        return self._scheduler.metrics

    @property
    def presentation_generation(self) -> int:
        return self._presentation_generation

    @property
    def latest_request_id(self) -> int:
        return self._latest_request_id

    @property
    def has_inflight_request(self) -> bool:
        return self._pending_request_id is not None or self._scheduler.active is not None

    @property
    def has_inflight_gameplay_request(self) -> bool:
        active = self._scheduler.active
        pending = self._scheduler.pending
        if getattr(active, "kind", None) == "gameplay":
            return True
        if getattr(pending, "kind", None) == "gameplay":
            return True
        return False

    @property
    def item_presentation_generation(self) -> int:
        return self._presentation_generation

    @property
    def tree_analysis_generation(self) -> int:
        return self._tree_analysis_generation

    @property
    def overlay_calibration_generation(self) -> int:
        return self._overlay_calibration_generation

    @property
    def tracked_tree_generation(self) -> int:
        return self._tracked_tree_generation

    def tracked_snapshot(self):
        if self.tracked_tree_source is not None:
            return self.tracked_tree_source.passive_tree_snapshot
        return self.tree_view_model.snapshot

    def _ensure_tracked_loader(self) -> TrackedTreeLoader:
        if self._tracked_loader is None:
            config = PobConfig(pob_path=Path(self.settings.pob_path))
            self._tracked_loader = TrackedTreeLoader(config)
        return self._tracked_loader

    def _on_analysis_progress(self, payload: object) -> None:
        if isinstance(payload, dict):
            kind = str(payload.get("kind") or "analysis")
            title = "Tree Analysis" if kind.startswith("tree") else "Analyze Build"
            progress_kind = "tree" if kind.startswith("tree") else "analysis"
            self._emit_progress(progress_kind, payload, module=progress_kind.upper(), title=title)
        self.analysis_progress.emit(payload)

    def _on_market_progress(self, payload: object) -> None:
        if isinstance(payload, dict):
            self._emit_progress("market", payload, module="MARKET", title="Market Search")
        self.market_progress.emit(payload)

    def _on_gear_progress(self, payload: object) -> None:
        if isinstance(payload, dict):
            self._emit_progress("gear", payload, module="GEAR_OPTIMIZER", title="Gear Optimization")
        self.gear_progress.emit(payload)

    def reload_tracked_tree(
        self,
        *,
        build_path: str | None = None,
        tree_set_id: str | None = None,
        refresh_sets_only: bool = False,
    ) -> None:
        if not is_enabled(FeatureModule.TREE_TOOLS):
            return
        path = (build_path or self.settings.tracked_build_path or self.build_info.path or "").strip()
        if not path:
            self._tracked_tree_error = "Select a tracked build first."
            self.tracked_tree_error.emit(self._tracked_tree_error)
            return
        self._tracked_tree_loading = True
        self._tracked_tree_error = ""
        try:
            loader = self._ensure_tracked_loader()
            context = self.build_info.context or self.settings.context
            sets = loader.list_tree_sets(path, context=context)
            self.tracked_tree_sets = sets
            self.tracked_tree_sets_changed.emit({"tree_sets": sets, "build_path": path})
            if refresh_sets_only:
                self._tracked_tree_loading = False
                return
            wanted = (tree_set_id or self.settings.tracked_tree_set_id or "").strip()
            if not wanted:
                for entry in sets:
                    if entry.get("active"):
                        wanted = str(entry.get("id") or entry.get("index") or "")
                        break
                if not wanted and sets:
                    wanted = str(sets[0].get("id") or sets[0].get("index") or "1")
            self._tracked_tree_generation += 1
            source = loader.load_tracked_source(
                build_path=path,
                tree_set_id=wanted,
                context=context,
                generation=self._tracked_tree_generation,
            )
            self.tracked_tree_source = source
            self.settings.tracked_build_path = path
            self.settings.tracked_tree_set_id = source.tree_set_id
            from poe2value.app.settings import save_settings

            save_settings(self.settings)
            self.tree_view_model.set_tracking_snapshot(source.passive_tree_snapshot)
            self.calibration_session.mark_layout(source.passive_tree_snapshot)
            self.tracked_tree_changed.emit(source.to_dict())
            self.tree_overlay_invalidated.emit()
        except Exception as exc:
            self._tracked_tree_error = str(exc)
            self.tracked_tree_error.emit(self._tracked_tree_error)
        finally:
            self._tracked_tree_loading = False

    def set_tracked_tree_set(self, tree_set_id: str) -> None:
        self.settings.tracked_tree_set_id = str(tree_set_id or "")
        from poe2value.app.settings import save_settings

        save_settings(self.settings)
        self.reload_tracked_tree(tree_set_id=str(tree_set_id))

    def step_tracked_tree_set(self, delta: int) -> None:
        sets = self.tracked_tree_sets
        if not sets:
            return
        current = str(self.settings.tracked_tree_set_id or "")
        ids = [str(entry.get("id") or entry.get("index") or "") for entry in sets]
        if current not in ids:
            idx = 0
        else:
            idx = ids.index(current)
        idx = (idx + int(delta)) % len(ids)
        self.set_tracked_tree_set(ids[idx])

    def bump_calibration_generation(self) -> None:
        self._overlay_calibration_generation += 1

    def set_tree_overlay_mode(self, mode: str) -> None:
        self.settings.tree_overlay_mode = str(mode)
        self.tree_overlay_mode_requested.emit(str(mode))
        self.tree_overlay_invalidated.emit()

    @property
    def loadouts(self) -> list[dict[str, Any]]:
        return self._loadouts

    @property
    def item_sets(self) -> list[dict[str, Any]]:
        return self._item_sets

    @property
    def active_loadout(self) -> str:
        return self._active_loadout

    @property
    def active_item_set_id(self) -> str:
        return self._active_item_set_id

    @property
    def active_item_set_name(self) -> str:
        return self._active_item_set_name

    def resolved_baseline(self) -> ResolvedBaseline:
        resolved = resolve_item_set(self._item_sets, self._active_item_set_id)
        loadout = self._active_loadout
        fingerprint = self.baseline_state.fingerprint
        return ResolvedBaseline(
            build_path=self.build_info.path,
            build_name=self.build_info.name or self.baseline_state.build_name,
            loadout_id=loadout,
            loadout_name=self.baseline_state.loadout_name or loadout,
            item_set_id=resolved.id,
            item_set_name=resolved.name or self._active_item_set_name,
            tree_set_id=self._active_tree_set_id,
            tree_set_name=self._active_tree_set_name,
            context=self.build_info.context or self.settings.context,
            fingerprint=fingerprint,
            item_set_valid=resolved.valid,
        )

    def invalidate_presentation(self) -> None:
        self._presentation_generation += 1
        self.presentation_invalidated.emit()

    def _publish_baseline_state(self) -> None:
        self.baseline_state_changed.emit(self.baseline_state)
        self.build_changed.emit(self.build_info)

    def active_build_status(self) -> ActiveBuildStatus:
        return self._active_build_status

    def _publish_active_build_status(self) -> None:
        self.active_build_status_changed.emit(self._active_build_status)

    def _cache_key_for_path(self, path: str) -> BuildCacheKey:
        return BuildCacheKey.for_source(LocalPobBuildSource(path).ref)

    def _persist_ready_build_cache(self, path: str) -> None:
        key = self._cache_key_for_path(path)
        previous = self._build_cache.get(key)
        entry = previous or BuildCacheEntry(key=str(key), build_path=path)
        entry.build_path = str(Path(path).resolve())
        entry.source_kind = LocalPobBuildSource(path).ref.kind.value
        entry.source_identity = LocalPobBuildSource(path).ref.identity
        loaded_revision = getattr(self._engine, "loaded_revision", None)
        entry.source_revision = loaded_revision.token if loaded_revision is not None else ""
        entry.display_name = self.baseline_state.build_name
        entry.context = self.baseline_state.context
        entry.loadout = self.baseline_state.loadout_id
        entry.item_set_id = str(self.baseline_state.item_set_id or "")
        entry.item_set_name = self.baseline_state.item_set_name
        entry.tree_set_name = self.baseline_state.tree_set_name
        entry.fingerprint = self.baseline_state.fingerprint
        entry.tree_fingerprint = self.baseline_state.tree_fingerprint
        entry.equipment_fingerprint = self.baseline_state.equipment_fingerprint
        entry.metrics = dict(self.baseline_state.metrics)
        # The revision that was loaded, next to the fingerprints it produced.
        entry.build_revision = revision_dict(self._build_file_revision or read_build_revision(path))
        entry.pob_head = self._pob_head_hint()
        entry.loaded_at = time.time()
        entry.last_refresh_attempt_at = entry.loaded_at
        entry.last_refresh_error = None
        self._build_cache.upsert(entry)
        self._active_build_status = status_from_entry(entry, engine_state=BuildState.READY.value)
        self._publish_active_build_status()

    def _begin_reload_transaction(self, path: str, context: str, *, reloading: bool) -> None:
        self._accept_tree = False
        dropped = self._scheduler.discard_queued_analysis()
        self._analysis_resume = None
        self._analysis_cancelled = True
        self._worker.request_yield()
        self._baseline_generation += 1
        self._tree_analysis_generation += 1
        self._history.mark_historical()
        self._pin_compare.mark_stale()
        self._refresh_pinned_overlay_stale(STALE_BUILD_CHANGED)
        self._loot_review.stop()
        self._last_analysis = None
        self._last_result = None
        self.tree_view_model.reset_for_baseline()
        self.analysis_stale.emit()
        self.tree_overlay_invalidated.emit()
        self.invalidate_presentation()
        self._equipment_fingerprint = ""
        self._last_clipboard_sequence = None
        self._last_clipboard_hash = ""
        self._result_cache.invalidate()
        self._worker.invalidate_baseline_caches()
        self._offense_coverage = None
        self._offense_coverage_cache.clear()
        self._upgrade_path_cache.clear()
        trace("baseline_reload_begin", generation=self._baseline_generation, dropped=dropped, path=path)
        state = BuildState.RELOADING if reloading else BuildState.LOADING
        self.build_info = BuildInfo(path=path, source_ref=LocalPobBuildSource(path).ref, context=context, state=state, name=Path(path).stem)
        self.baseline_state = BaselineState(
            state=state,
            build_path=path,
            source_ref=LocalPobBuildSource(path).ref,
            build_name=Path(path).stem,
            context=context,
            generation=self._baseline_generation,
        )
        self._publish_baseline_state()
        self._active_build_status = replace(
            self._active_build_status,
            freshness="REFRESHING",
            engine_state=state.value,
        )
        self._publish_active_build_status()

    def _wait_for_pob_idle(self, timeout_ms: int = 180_000) -> None:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            return
        deadline = time.perf_counter() + (timeout_ms / 1000.0)
        while self._scheduler.active is not None and time.perf_counter() < deadline:
            kind = str(getattr(self._scheduler.active, "kind", ""))
            if kind not in {"gameplay", "baseline"}:
                self._worker.request_yield()
            app.processEvents()
            time.sleep(0.01)

    def _fail_baseline(self, message: str) -> None:
        self._last_build_error = message
        logger.warning("build_load_failed path=%s reason=%s", self.build_info.path, message)
        self._accept_tree = False
        self.build_info = BuildInfo(
            path=self.build_info.path,
            name=self.build_info.name,
            context=self.build_info.context,
            state=BuildState.FAILED,
            error_message=message,
        )
        self.baseline_state = BaselineState(
            state=BuildState.FAILED,
            build_path=self.build_info.path,
            build_name=self.build_info.name,
            context=self.build_info.context,
            generation=self._baseline_generation,
            error=message,
        )
        self._publish_baseline_state()
        key = self._cache_key_for_path(self.build_info.path) if self.build_info.path else None
        if key is not None:
            self._build_cache.record_refresh_error(key, "POB_LOAD_FAILED", message)
        self._active_build_status = status_from_entry(
            self._build_cache.load_active(), engine_state=BuildState.FAILED.value
        )
        self._publish_active_build_status()
        if self._baseline_wait_loop is not None:
            self._baseline_wait_loop.quit()
        if self._deferred_evaluation is not None:
            deferred = self._deferred_evaluation
            self._deferred_evaluation = None
            self._auto_reload_status = "FAILED"
            self._stop_item_check_watchdog(deferred.request_id)
            self._item_check_lifecycle.mark_error(deferred.request_id, message, stage="baseline")
            self.evaluation_error.emit(deferred.request_id, message)

    def _bump_baseline_generation(self) -> None:
        self._baseline_generation += 1
        self._tree_analysis_generation += 1
        self._equipment_fingerprint = ""
        self._last_clipboard_sequence = None
        self._last_clipboard_hash = ""
        self._history.mark_historical()
        self._pin_compare.mark_stale()
        self._loot_review.stop()
        self._result_cache.invalidate()
        self._worker.invalidate_baseline_caches()
        self._offense_coverage = None
        self._offense_coverage_cache.clear()
        self._upgrade_path_cache.clear()
        if self._last_analysis is not None:
            self._last_analysis = None
            self.analysis_stale.emit()
        self._analysis_resume = None
        self.tree_view_model.reset_for_baseline()
        self.tree_overlay_invalidated.emit()

    def start_engine(self) -> None:
        config = PobConfig(pob_path=Path(self.settings.pob_path))
        # Subprocess worker avoids Lua/Qt DLL conflicts on Windows when QApplication is active.
        self._engine = Engine(config, use_subprocess=True)
        self._engine.start()
        self._worker_generation += 1

    def shutdown_engine(self) -> None:
        if self._engine:
            self._engine.shutdown()
            self._engine = None

    @property
    def engine_error(self) -> str:
        return self._engine_error

    @property
    def last_build_error(self) -> str:
        return self._last_build_error

    @property
    def reload_warning(self) -> str:
        """Non-empty while a reload failed and the previous build is still in use."""
        return self._reload_warning

    @property
    def build_loaded_at(self) -> float | None:
        return self._build_loaded_at

    @property
    def last_good_source(self) -> BuildSource | None:
        return self._last_good_source

    def restart_engine(self) -> bool:
        """Apply a changed PoB folder without restarting ExileLens.

        The build is reloaded by the ``engine_ready`` handler once the new worker is up.
        """
        logger.info("engine_restart_requested pob_path=%s", self.settings.pob_path)
        self._wait_for_pob_idle()
        if self._tracked_loader is not None:
            self._tracked_loader.shutdown()
            self._tracked_loader = None
        try:
            self.shutdown_engine()
        except Exception:  # noqa: BLE001 - a dead worker must not block the restart
            logger.exception("engine_restart_shutdown_failed")
            self._engine = None
        if self.build_info.path:
            self.build_info = BuildInfo(
                path=self.build_info.path,
                name=self.build_info.name,
                context=self.build_info.context,
                state=BuildState.LOADING,
            )
            self.build_changed.emit(self.build_info)
        return self.start_engine_async()

    @property
    def engine_booting(self) -> bool:
        return self._engine_booting

    def engine_status(self) -> str:
        if self._engine is not None:
            return "ready"
        if self._engine_booting:
            return "starting"
        if self._engine_error:
            return f"failed: {self._engine_error}"
        return "stopped"

    def start_engine_async(self) -> bool:
        """Boot the PoB worker off the GUI thread.

        Startup used to block here before the tray existed, so a slow or hung worker
        left a process with no window, no tray and the single-instance lock held.
        Emits ``engine_ready`` or ``engine_failed`` on the GUI thread.
        """
        if self._engine is not None:
            self.engine_ready.emit()
            return True
        if self._engine_booting:
            return True
        self._engine_booting = True
        self._engine_error = ""
        config = PobConfig(pob_path=Path(self.settings.pob_path))
        logger.info("engine_boot_started pob_path=%s", config.pob_path)

        def _boot() -> None:
            engine: Engine | None = None
            try:
                validate_pob_path(config)
                engine = Engine(config, use_subprocess=True)
                engine.start()
            except Exception as exc:  # noqa: BLE001 - reported to the GUI thread below
                logger.exception("engine_boot_failed")
                if engine is not None:
                    try:
                        engine.shutdown()
                    except Exception:  # noqa: BLE001
                        logger.exception("engine_boot_cleanup_failed")
                self._engine_boot_result.emit(None, exc)
                return
            self._engine_boot_result.emit(engine, None)

        threading.Thread(target=_boot, name="exilelens-engine-boot", daemon=True).start()
        return True

    def _on_engine_boot_result(self, engine: object, error: object) -> None:
        self._engine_booting = False
        if error is not None or engine is None:
            detail = getattr(error, "message", None) or str(error or "unknown error")
            self._engine_error = f"Path of Building could not start: {detail}"
            logger.error("engine_failed reason=%s", detail)
            self.engine_failed.emit(self._engine_error)
            return
        if self._shutting_down:
            engine.shutdown()  # type: ignore[union-attr]
            return
        self._engine = engine  # type: ignore[assignment]
        self._worker_generation += 1
        logger.info("engine_ready")
        self.engine_ready.emit()

    def _refresh_loadout_catalog(self) -> None:
        if not self._engine:
            return
        try:
            loadout_info = self._engine.list_loadouts()
            item_set_info = self._engine.list_item_sets()
            self._loadouts = list(loadout_info.get("loadouts") or [])
            self._item_sets = list(item_set_info.get("item_sets") or [])
            self._active_loadout = str(loadout_info.get("active") or "")
            resolved = resolve_item_set(self._item_sets, item_set_info.get("active_id"))
            self._active_item_set_id = resolved.id
            self._active_item_set_name = resolved.name
            self.loadouts_changed.emit(
                {
                    "loadouts": self._loadouts,
                    "item_sets": self._item_sets,
                    "active_loadout": self._active_loadout,
                    "active_item_set_id": self._active_item_set_id,
                }
            )
        except Exception:
            self._loadouts = []
            self._item_sets = []

    def _apply_loadout_selection(self) -> None:
        if not self._engine:
            return
        selected = self.settings.selected_loadout.strip()
        if selected:
            names = {entry.get("name") for entry in self._loadouts}
            if selected in names:
                self._engine.set_active_loadout(selected)
                self._active_loadout = selected
        if not self.settings.item_set_follow_loadout:
            item_set_id = self.settings.selected_item_set_id.strip()
            if item_set_id:
                known = {canonical_item_set_id(entry.get("id")) for entry in self._item_sets}
                canonical = canonical_item_set_id(item_set_id)
                if canonical in known:
                    self._engine.set_active_item_set(canonical)
                    resolved = resolve_item_set(self._item_sets, canonical)
                    self._active_item_set_id = resolved.id
                    self._active_item_set_name = resolved.name

    def _slot_item_name(self, equipment: dict[str, Any], slot: str) -> str:
        rows = []
        if isinstance(equipment, dict):
            rows = equipment.get("equipment") or equipment.get("slots") or []
            if isinstance(equipment.get(slot), dict):
                rows = [equipment[slot], *list(rows or [])]
        elif isinstance(equipment, list):
            rows = equipment
        for row in rows or []:
            if isinstance(row, dict) and str(row.get("slot") or "") == slot:
                return str(row.get("name") or row.get("typeLine") or row.get("base_name") or "")
        return ""

    def _capture_ready_baseline(self, path: str, context: str, *, started: float) -> None:
        assert self._engine is not None
        self._refresh_loadout_catalog()
        self._apply_loadout_selection()
        metrics = self._engine.get_metrics(context=context)
        self._evaluation_fingerprint_components = dict(metrics.get("fingerprint") or {})
        fingerprint = str(metrics.get("fingerprint_hash") or "")
        equipment: dict[str, Any] = {}
        try:
            equipment = self._engine.get_equipment() or {}
        except Exception:
            equipment = {}
        from poe2value.config import fingerprint_hash
        from poe2value.tree.fingerprint import tree_fingerprint_from_components
        from poe2value.tree.mutations import load_tree_snapshot

        equipment_fp = fingerprint_hash(equipment if isinstance(equipment, dict) else {"equipment": equipment})
        tree_fp = tree_fingerprint_from_components(metrics.get("fingerprint") or {})
        snapshot = load_tree_snapshot(
            self._engine,
            build_path=path,
            context=context,
            profile=self.settings.value_profile,
            generation=self._baseline_generation,
            loadout=self._active_loadout,
            item_set=self._active_item_set_id,
        )
        tree_set = snapshot.tree_set if isinstance(snapshot.tree_set, dict) else {}
        index = tree_set.get("index")
        self._active_tree_set_id = "" if index is None else str(index)
        self._active_tree_set_name = str(tree_set.get("title") or tree_set.get("name") or "")
        self._equipment_fingerprint = fingerprint or equipment_fp
        name = self.build_info.name or Path(path).stem
        info = self._engine.get_build_info() if hasattr(self._engine, "get_build_info") else {}
        if isinstance(info, dict) and info.get("name"):
            name = str(info.get("name"))
        elapsed = (time.perf_counter() - started) * 1000
        equipped_summary = {
            "Helmet": self._slot_item_name(equipment, "Helmet"),
            "Ring 1": self._slot_item_name(equipment, "Ring 1"),
            "raw": equipment,
        }
        source_ref = getattr(self._engine, "loaded_source_ref", None) or LocalPobBuildSource(path).ref
        loaded_revision = getattr(self._engine, "loaded_revision", None)
        self.build_info = BuildInfo(path=path, source_ref=source_ref, name=name, context=context, state=BuildState.READY)
        self.baseline_state = BaselineState(
            state=BuildState.READY,
            build_path=path,
            source_ref=source_ref,
            source_revision=loaded_revision.token if loaded_revision is not None else "",
            build_name=name,
            loadout_id=self._active_loadout,
            loadout_name=self._active_loadout,
            item_set_id=self._active_item_set_id,
            item_set_name=self._active_item_set_name,
            tree_set_id=self._active_tree_set_id,
            tree_set_name=self._active_tree_set_name,
            context=context,
            generation=self._baseline_generation,
            fingerprint=fingerprint,
            tree_fingerprint=snapshot.baseline.tree_fingerprint or tree_fp,
            equipment_fingerprint=equipment_fp,
            metrics=metrics.get("raw") or metrics.get("normalized") or metrics,
            equipped_items=equipped_summary,
            reload_ms=round(elapsed, 2),
        )
        self.tree_view_model.ingest_graph_payload(snapshot.to_graph_export())
        self._accept_tree = True
        self._configure_worker()
        self._recovery_attempted = False
        self._publish_baseline_state()
        logger.info(
            "build_loaded path=%s name=%s generation=%s equipment_fp=%s reload_ms=%.0f",
            path,
            self.build_info.name,
            self._baseline_generation,
            str(equipment_fp or "")[:12],
            elapsed,
        )
        self._record_build_revision(path)
        self._persist_ready_build_cache(path)
        self._persist_build_settings(path, context)
        if self._baseline_wait_loop is not None:
            self._baseline_wait_loop.quit()
        self._resume_deferred_evaluation()

    def _record_build_revision(self, path: str) -> None:
        source = getattr(self._engine, "loaded_source", None) if self._engine is not None else None
        if isinstance(source, BuildSource) and source.path == str(Path(path).resolve()):
            # Record the revision that was parsed, not a later stat: a PoB save landing
            # during the load must still be seen as a change on the next Item Check.
            if self._last_good_source is None or self._last_good_source.sha256 != source.sha256:
                self._build_loaded_at = time.time()
            self._last_good_source = source
            self._build_file_revision = BuildFileRevision(path=source.path, mtime_ns=source.mtime_ns, size=source.size)
            return
        revision = read_build_revision(path)
        if revision is not None:
            self._build_file_revision = revision

    def _disk_revision_changed(self, path: str) -> bool:
        current = read_build_revision(path)
        if current is None:
            return False
        if self._build_file_revision is None:
            if self.build_info.is_ready:
                self._build_file_revision = current
            return False
        return current.changed_from(self._build_file_revision)

    def _resume_deferred_evaluation(self) -> None:
        request = self._deferred_evaluation
        if request is None or not self.build_info.is_ready:
            return
        self._deferred_evaluation = None
        # Built before the reload; it now belongs to the new baseline. Keeping the old
        # generation made every held-back check fail "Build changed during evaluation".
        request = replace(
            request,
            baseline_generation=self._baseline_generation,
            presentation_generation=self._presentation_generation,
            context_identity=self._current_evaluation_identity().token,
        )
        self._submit_evaluation_request(request)

    def reload_evaluation_build(self) -> None:
        """Manual reload of the selected evaluation build from disk."""
        self._auto_reload_status = "MANUAL"
        self.reload_build()

    def change_build(self, path: str) -> None:
        previous = self.build_info.path
        self.load_build(path, context=self.settings.context)
        if not self.build_info.is_ready and previous and previous != str(Path(path).resolve()):
            self.load_build(previous, context=self.build_info.context)

    def load_build(self, path: str, *, context: str | None = None) -> None:
        context = context or self.settings.context
        resolved = str(Path(path).resolve())
        if self._engine is None:
            self._fail_baseline("PoB engine is not started")
            return
        reloading = self.build_info.state == BuildState.READY
        same_build = reloading and self.build_info.path == resolved and self._last_good_source is not None
        started = time.perf_counter()
        # Read and validate before touching anything: a broken or half-saved file must
        # not tear down a build that works.
        try:
            source = read_build_source(resolved)
        except EngineError as exc:
            if same_build:
                self._keep_last_good_build(exc.message)
                return
            self._begin_reload_transaction(resolved, context, reloading=reloading)
            self._fail_baseline(exc.message)
            return
        logger.info(
            "build_reload_begin path=%s sha=%s size=%s mtime_ns=%s reloading=%s",
            resolved,
            source.short_sha,
            source.size,
            source.mtime_ns,
            reloading,
        )
        self._begin_reload_transaction(resolved, context, reloading=reloading)
        self._wait_for_pob_idle()
        try:
            result = self._engine.load_build(resolved, context=context, source=source)
            build = result.get("build") if isinstance(result.get("build"), dict) else {}
            name = (build or {}).get("name") or Path(resolved).stem
            self.build_info = BuildInfo(path=resolved, name=name, context=context, state=BuildState.LOADING if not reloading else BuildState.RELOADING)
            self._reload_warning = ""
            self._capture_ready_baseline(resolved, context, started=started)
        except Exception as exc:
            message = exc.message if isinstance(exc, EngineError) else str(exc)
            if same_build and self._restore_last_good_build(resolved, context, message, started=started):
                return
            self._fail_baseline(message)

    def _keep_last_good_build(self, reason: str) -> None:
        """A reload failed; keep evaluating against the last build that loaded, and say so."""
        loaded_at = (
            time.strftime("%H:%M:%S", time.localtime(self._build_loaded_at)) if self._build_loaded_at else "startup"
        )
        message = f"Build reload failed — still using the build loaded at {loaded_at}. {reason}"
        self._reload_warning = message
        self._reload_status_message = message
        self._auto_reload_status = "FAILED_KEPT_PREVIOUS"
        source = self._last_good_source
        logger.warning(
            "build_reload_failed kept_previous path=%s loaded_sha=%s reason=%s",
            self.build_info.path,
            source.short_sha if source else "",
            reason,
        )
        self.state_message.emit(message)
        self._resume_deferred_evaluation()

    def _restore_last_good_build(self, path: str, context: str, reason: str, *, started: float) -> bool:
        """PoB rejected the new file after validation; reload the previous bytes."""
        source = self._last_good_source
        if source is None or self._engine is None:
            return False
        try:
            self._engine.load_build(path, context=context, source=source)
            self.build_info = BuildInfo(path=path, name=self.build_info.name, context=context, state=BuildState.RELOADING)
            self._capture_ready_baseline(path, context, started=started)
        except Exception:  # noqa: BLE001 - fall through to a visible failure
            logger.exception("build_restore_failed path=%s sha=%s", path, source.short_sha)
            return False
        self._keep_last_good_build(reason)
        return True

    def reload_build(self) -> None:
        if self.build_info.path:
            self.load_build(self.build_info.path, context=self.build_info.context)

    def set_context(self, context: str) -> None:
        self.settings.context = context
        if self.build_info.path:
            self.load_build(self.build_info.path, context=context)

    def set_active_loadout(self, name: str) -> None:
        if not self._engine or not self.build_info.is_ready:
            return
        started = time.perf_counter()
        self.settings.selected_loadout = name
        self._begin_reload_transaction(self.build_info.path, self.build_info.context, reloading=True)
        self._wait_for_pob_idle()
        try:
            self._engine.set_active_loadout(name)
            self._active_loadout = name
            if self.settings.item_set_follow_loadout:
                item_sets = self._engine.list_item_sets()
                resolved = resolve_item_set(item_sets, item_sets.get("active_id"))
                self._active_item_set_id = resolved.id
                self._active_item_set_name = resolved.name
                self.settings.selected_item_set_id = self._active_item_set_id
            self._capture_ready_baseline(self.build_info.path, self.build_info.context, started=started)
        except Exception as exc:
            self._fail_baseline(str(exc))

    def set_active_item_set(self, item_set_id: str, *, follow_loadout: bool | None = None) -> None:
        if not self._engine or not self.build_info.is_ready:
            return
        if follow_loadout is not None:
            self.settings.item_set_follow_loadout = follow_loadout
        if self.settings.item_set_follow_loadout:
            self.settings.selected_item_set_id = ""
            return
        started = time.perf_counter()
        self.settings.selected_item_set_id = canonical_item_set_id(item_set_id)
        self._begin_reload_transaction(self.build_info.path, self.build_info.context, reloading=True)
        self._wait_for_pob_idle()
        try:
            self._engine.set_active_item_set(self.settings.selected_item_set_id)
            resolved = resolve_item_set(self._item_sets, self.settings.selected_item_set_id)
            self._active_item_set_id = resolved.id
            self._active_item_set_name = resolved.name
            self._capture_ready_baseline(self.build_info.path, self.build_info.context, started=started)
        except Exception as exc:
            self._fail_baseline(str(exc))

    def _evaluation_cache_key(self, content_hash: str) -> str:
        identity = self.resolved_baseline()
        fingerprint = self._equipment_fingerprint or identity.fingerprint
        return evaluation_cache_key(
            content_hash=content_hash,
            fingerprint=fingerprint,
            source_identity=self.build_info.source_ref.key if self.build_info.source_ref else self.build_info.path,
            loadout=self._active_loadout,
            item_set=self._active_item_set_id,
            context=self.build_info.context or self.settings.context,
            generation=self._baseline_generation,
            context_identity=self._current_evaluation_identity().token,
            candidate_fingerprint=content_hash,
        )

    def _store_evaluation_cache(self, content_hash: str, result: dict[str, Any]) -> None:
        rec = result.get("recommendation") or {}
        fingerprint = str(((rec.get("baseline") or {}).get("fingerprint_hash")) or self._equipment_fingerprint)
        if fingerprint:
            self._equipment_fingerprint = fingerprint
        key = evaluation_cache_key(
            content_hash=content_hash,
            fingerprint=fingerprint,
            source_identity=self.build_info.source_ref.key if self.build_info.source_ref else self.build_info.path,
            loadout=self._active_loadout,
            item_set=self._active_item_set_id,
            context=self.build_info.context or self.settings.context,
            generation=self._baseline_generation,
            context_identity=self._current_evaluation_identity().token,
            candidate_fingerprint=content_hash,
        )
        self._result_cache.put(key, result)

    def _current_evaluation_identity(self) -> EvaluationContextIdentity:
        state = self.baseline_state
        source_ref = state.source_ref or self.build_info.source_ref
        loaded_revision = getattr(self._engine, "loaded_revision", None) if self._engine else None
        return identity_from_state(
            source_identity=source_ref.key if source_ref else (state.build_path or self.build_info.path),
            source_revision=state.source_revision or getattr(loaded_revision, "token", ""),
            build_generation=self._baseline_generation,
            baseline_fingerprint=state.fingerprint or self._equipment_fingerprint,
            equipment_fingerprint=state.equipment_fingerprint or self._equipment_fingerprint,
            tree_fingerprint=state.tree_fingerprint,
            fingerprint_components=self._evaluation_fingerprint_components,
            loadout=self._active_loadout,
            item_set=self._active_item_set_id,
            calculation_context=self.build_info.context or self.settings.context,
            worker_generation=self._worker_generation,
        )

    def submit_clipboard_text(
        self,
        text: str,
        *,
        cursor_position: QPoint | None = None,
        copy_anchor_screen_px: tuple[int, int] | None = None,
        copy_timestamp: float | None = None,
        content_hash: str | None = None,
        clipboard_sequence: int | None = None,
    ) -> int | None:
        if not self._require_module(FeatureModule.ITEM_CHECK, message="Item Check module is disabled."):
            return None
        self._heartbeat_state.note_clipboard()
        if self.build_info.state in {BuildState.NO_BUILD, BuildState.FAILED}:
            self._request_id += 1
            request_id = self._request_id
            self._latest_request_id = request_id
            message = "No build loaded — choose a PoB build file on the Build page."
            self.state_message.emit(message)
            self._begin_eval_feedback(request_id)
            self._emit_item_check_error(request_id, message)
            return request_id

        # Upstream clipboard hashes identify capture events. Evaluation reuse must use
        # the semantic item fingerprint derived from the text itself.
        raw = RawItemInput.from_text(text, source=ItemInputSource.CLIPBOARD)
        recognition = recognize_input(raw)
        if not recognition.recognized:
            self._scheduler.metrics.dropped_non_item += 1
            self._request_id += 1
            request_id = self._request_id
            self._latest_request_id = request_id
            reason = recognition.reason or "unsupported clipboard text"
            logger.info(
                "item_check_submit dropped reason=%s seq=%s",
                reason,
                clipboard_sequence,
            )
            self._item_check_lifecycle.begin(request_id, content_hash=raw.content_hash)
            self._begin_eval_feedback(request_id)
            # LANG-01: recognition is the first boundary a localized client hits
            # (most languages have no "Rarity:" header at all). Same classifier as
            # the post-parse boundary — English text keeps the original message.
            classified = classify_localization_failure(text, NotPoe2Item(reason))
            if isinstance(classified, UnsupportedGameLanguage):
                self._emit_item_check_error(
                    request_id,
                    classified.message,
                    title=UNSUPPORTED_LANGUAGE_TITLE,
                    stage="unsupported_item_language",
                    detected_language=classified.language_code,
                    confidence=classified.confidence,
                )
                return request_id
            self._emit_item_check_error(request_id, f"Unsupported item — {reason}")
            return request_id

        if is_duplicate_clipboard_event(self._last_clipboard_sequence, clipboard_sequence):
            return None
        if clipboard_sequence is not None:
            self._last_clipboard_sequence = clipboard_sequence
        self._last_clipboard_hash = raw.content_hash

        anchor = copy_anchor_screen_px or get_cursor_pos_physical()
        if anchor is not None and not (anchor[0] == 0 and anchor[1] == 0):
            self._last_copy_anchor_physical = anchor

        self._request_id += 1
        request_id = self._request_id
        self._latest_request_id = request_id
        item_class = ""
        for line in text.replace("\r\n", "\n").split("\n"):
            if line.startswith("Item Class:"):
                item_class = line.split(":", 1)[1].strip()
                break
        self._item_check_lifecycle.begin(request_id, content_hash=raw.content_hash, item_class=item_class)
        self._item_check_lifecycle.advance(request_id, ItemCheckPhase.RECOGNIZED, item_class=item_class)
        self._cancel_upgrade_path_work()
        self._presentation_generation += 1
        presentation_generation = self._presentation_generation
        received_ms = time.perf_counter() * 1000
        logical_cursor = cursor_position
        if logical_cursor is None and anchor is not None:
            from poe2value.platform.windows.poe_window import physical_to_logical

            lx, ly = physical_to_logical(float(anchor[0]), float(anchor[1]))
            logical_cursor = QPoint(int(round(lx)), int(round(ly)))
        request = EvaluationRequest(
            request_id=request_id,
            raw_text=text,
            content_hash=raw.content_hash,
            clipboard_received_ms=received_ms,
            copy_timestamp=copy_timestamp if copy_timestamp is not None else time.time(),
            cursor_position=logical_cursor,
            copy_anchor_screen_px=anchor,
            baseline_generation=self._baseline_generation,
            presentation_generation=presentation_generation,
            clipboard_sequence=clipboard_sequence,
            context_identity=self._current_evaluation_identity().token,
            candidate_fingerprint=raw.content_hash,
        )
        self._retry_request = request
        if anchor is not None:
            self._request_anchors[request_id] = anchor

        build_path = self.build_info.path
        if build_path and self._disk_revision_changed(build_path):
            self._auto_reload_status = "RELOADED"
            self._reload_status_message = "PoB build changed on disk — reloading..."
            self.state_message.emit(self._reload_status_message)
            self._deferred_evaluation = request
            self._begin_eval_feedback(request_id)
            logger.info(
                "item_check_submit deferred request_id=%s reason=disk_revision build_state=%s",
                request_id,
                self.build_info.state.value,
            )
            if self.build_info.state not in {BuildState.RELOADING, BuildState.LOADING}:
                self.load_build(build_path, context=self.build_info.context)
            return request_id

        if self.build_info.state in {BuildState.RELOADING, BuildState.LOADING}:
            self._deferred_evaluation = request
            self._begin_eval_feedback(request_id)
            logger.info(
                "item_check_submit deferred request_id=%s reason=build_loading build_state=%s",
                request_id,
                self.build_info.state.value,
            )
            return request_id

        self._auto_reload_status = "UNCHANGED"
        logger.info(
            "item_check_submit accepted request_id=%s build_state=%s seq=%s",
            request_id,
            self.build_info.state.value,
            clipboard_sequence,
        )
        return self._submit_evaluation_request(request)

    def copy_anchor_for_request(self, request_id: int) -> tuple[int, int] | None:
        return self._request_anchors.get(request_id)

    def record_overlay_placement(self, placement: dict[str, Any]) -> None:
        self._overlay_placement_diag = dict(placement)

    def _ensure_offense_coverage(self) -> None:
        if not self._engine or not self.build_info.is_ready:
            return
        # PERF-01: this early return used to sit below the engine calls, so every
        # accepted Item Check -- including every result-cache hit -- paid a
        # get_build_info round trip on the UI thread and threw the answer away.
        # Worse than its ~1-2 ms: SubprocessWorkerClient.request holds the worker
        # lock, so a UI-thread call here blocks behind an in-flight evaluation.
        # Nothing between here and the original early return had a side effect.
        if self._offense_coverage is not None:
            return
        fingerprint = self.baseline_state.fingerprint or self._equipment_fingerprint
        if not fingerprint:
            return
        context = self.build_info.context or self.settings.context
        build_info: dict[str, Any] = {}
        try:
            raw_info = self._engine.get_build_info() if hasattr(self._engine, "get_build_info") else {}
            if isinstance(raw_info, dict):
                build_info = raw_info
        except Exception:
            build_info = {}
        baseline_metrics = dict(self.baseline_state.metrics or {})
        if not baseline_metrics:
            try:
                payload = self._engine.get_metrics(context=context)
                baseline_metrics = dict(payload.get("raw") or payload.get("normalized") or payload)
            except Exception:
                baseline_metrics = {}
        primary = resolve_primary_metric(build_info, baseline_metrics)
        from poe2value.items.offense_coverage import (
            DamageOwner,
            DamageQuantity,
            OffenseCoverageAuditor,
            infer_offense_coverage,
        )

        if primary.damage_owner == DamageOwner.MINION or primary.semantic_quantity == DamageQuantity.AILMENT_DPS:
            auditor = OffenseCoverageAuditor(self._engine, cache=self._offense_coverage_cache)
            cached = auditor.get_cached(
                fingerprint=fingerprint,
                context=context,
                primary_field=primary.pob_field,
            )
            if cached is not None:
                self._offense_coverage = cached.to_dict()
            else:
                coverage = auditor.ensure(
                    build_info=build_info,
                    baseline_metrics=baseline_metrics,
                    fingerprint=fingerprint,
                    context=context,
                    generation=self._baseline_generation,
                )
                self._offense_coverage = coverage.to_dict()
        else:
            coverage_payload = infer_offense_coverage(primary, baseline_metrics).to_dict()
            coverage_payload["audit_skipped"] = True
            self._offense_coverage = coverage_payload
        self._configure_worker()

    def _submit_evaluation_request(self, request: EvaluationRequest) -> int | None:
        request_id = request.request_id
        try:
            self._ensure_offense_coverage()
        except Exception as exc:  # noqa: BLE001 - every accepted request needs a terminal state
            logger.exception("item_check_offense_coverage_failed request_id=%s", request_id)
            self._emit_item_check_error(request_id, f"Could not prepare item analysis: {exc}")
            return request_id
        raw_hash = request.content_hash
        cursor_position = request.cursor_position
        presentation_generation = request.presentation_generation
        clipboard_sequence = request.clipboard_sequence
        received_ms = request.clipboard_received_ms

        cached = self._result_cache.get(self._evaluation_cache_key(raw_hash))
        if cached is not None:
            cached_fp = str((((cached.get("recommendation") or {}).get("baseline") or {}).get("fingerprint_hash")) or "")
            current_fp = self.resolved_baseline().fingerprint
            if cached_fp and current_fp and cached_fp != current_fp:
                cached = None
        if cached is not None:
            result = rescore_evaluation(
                cached,
                profile=self.settings.value_profile,
                price=self._prices.get((raw_hash, self._baseline_identity())),
                build_name=self.build_info.name,
                loadout_name=self._active_loadout,
                item_set_name=self._active_item_set_name or self._active_item_set_id,
                context=self.build_info.context or self.settings.context,
                item_check_pro=self.settings.item_check_pro,
            )
            anchor = request.copy_anchor_screen_px
            result["request_meta"] = {
                "request_id": request_id,
                "content_hash": raw_hash,
                "copy_timestamp": request.copy_timestamp,
                "cursor_position": (
                    {"x": cursor_position.x(), "y": cursor_position.y()} if cursor_position is not None else None
                ),
                "copy_anchor_screen_px": {"x": anchor[0], "y": anchor[1]} if anchor is not None else None,
                "baseline_generation": self._baseline_generation,
                "baseline_mode": self.settings.baseline_mode,
                "presentation_generation": presentation_generation,
                "context": self.build_info.context or self.settings.context,
                "value_profile": self.settings.value_profile,
                "clipboard_sequence": clipboard_sequence,
                "cache_hit": True,
                "evaluation_context_identity": request.context_identity,
                "candidate_fingerprint": request.candidate_fingerprint,
            }
            timing = EvaluationTiming(
                request_id=request_id,
                clipboard_received_ms=received_ms,
                evaluation_started_ms=received_ms,
                evaluation_finished_ms=time.perf_counter() * 1000,
            )
            self._begin_eval_feedback(request_id)
            self._item_check_lifecycle.advance(request_id, ItemCheckPhase.EVAL_FINISHED)
            self._deliver_evaluation_result(request_id, result, timing, from_cache=True)
            return request_id

        self._pending_request_id = request_id
        self._heartbeat_state.note_pending(request_id)
        self._begin_eval_feedback(request_id)

        self._scheduler.submit(request)
        active_kind = str(getattr(self._scheduler.active, "kind", "gameplay"))
        if active_kind not in {"gameplay", "baseline"}:
            self._worker.request_yield()
        return request_id

    def _dispatch_to_worker(self, request: EvaluationRequest | AnalysisRequest | BaselineReloadRequest | MarketSearchRequest | GearOptimizationRequest | MarketCaptureEvalRequest | UpgradePathRequest) -> None:
        self._pending_request_id = request.request_id
        kind = str(getattr(request, "kind", "gameplay"))
        if kind == "baseline":
            self._worker.reload_baseline.emit(request)
            return
        if kind == "market_capture":
            self._worker.market_capture_eval.emit(request)
            return
        if kind == "upgrade_path":
            self._worker.upgrade_path.emit(request)
            return
        if kind == "build_decomp":
            self._worker.build_decomp.emit(request)
            return
        if kind == "market":
            self._worker.market_search.emit(request)
            return
        if kind == "gear":
            self._worker.gear_optimization.emit(request)
            return
        if kind != "gameplay":
            self._worker.analyze.emit(request)
            return
        self._heartbeat_state.note_eval_started(request.request_id)
        self._worker.evaluate.emit(request)

    def _tree_request_kind(self, *, task: str, scope: str, node_ids: list[int] | None) -> str:
        if node_ids and scope not in {"visible", "frontier"}:
            return "tree_node"
        if scope == "visible":
            return "tree_visible"
        if scope in {"radius3", "radius5"}:
            return "tree_nearby"
        if task == "tree_snapshot":
            return "tree_visible"
        return "tree_frontier"

    def submit_analyze_build(self, *, slot: str | None = None) -> int | None:
        if not self._require_module(FeatureModule.BUILD_ANALYSIS, message="Build Analysis is disabled in current module preset."):
            return None
        if not self.build_info.is_ready:
            self.state_message.emit("No build loaded — select a build from the tray menu.")
            return None
        self._request_id += 1
        request_id = self._request_id
        request = AnalysisRequest(
            request_id=request_id,
            baseline_generation=self._baseline_generation,
            profile=self.settings.value_profile,
            slot=slot,
        )
        self._analysis_resume = request
        self.analysis_started.emit(request_id)
        self._track_progress("analysis", module="BUILD_ANALYSIS", title="Analyze Build", request_id=request_id)
        self._scheduler.submit(request)
        return request_id

    def submit_tree_analysis(
        self,
        *,
        max_points: int = 3,
        scope: str = "frontier",
        node_ids: list[int] | None = None,
        task: str = "tree",
    ) -> int | None:
        if not self._require_module(FeatureModule.TREE_TOOLS, message="Tree Tools are disabled in current module preset."):
            return None
        if not self.build_info.is_ready:
            self.state_message.emit("No build loaded — select a build from the tray menu.")
            return None
        self._request_id += 1
        request_id = self._request_id
        self._analysis_cancelled = False
        kind = self._tree_request_kind(task=task, scope=scope, node_ids=node_ids)
        request = AnalysisRequest(
            request_id=request_id,
            baseline_generation=self._baseline_generation,
            profile=self.settings.value_profile,
            kind=kind,
            task=task,
            max_points=max_points,
            scope=scope,
            node_ids=node_ids,
        )
        if task != "tree_snapshot":
            if node_ids:
                self.tree_view_model.mark_pending(node_ids)
            elif self.tree_view_model._frontier_valid:
                self.tree_view_model.mark_pending(self.tree_view_model._frontier_valid)
        self._analysis_resume = request
        self.analysis_started.emit(request_id)
        title = "Tree Snapshot" if task == "tree_snapshot" else "Tree Analysis"
        self._track_progress("tree", module="TREE_TOOLS", title=title, request_id=request_id)
        self._scheduler.submit(request)
        return request_id

    def submit_tree_snapshot(self) -> int | None:
        return self.submit_tree_analysis(scope="snapshot", task="tree_snapshot")

    def cancel_tree_analysis(self) -> None:
        self._analysis_cancelled = True
        self._analysis_resume = None
        self._worker.request_yield()

    def _on_analysis_finished(self, request_id: int, payload: object, error: Exception | None) -> None:
        active = self._scheduler.active
        if active is not None and getattr(active, "request_id", None) == request_id:
            self._scheduler.complete(active)
        else:
            self._scheduler.complete_by_id(request_id)

        if error is not None:
            self.analysis_error.emit(str(error))
            self._finish_progress("analysis", status=OperationStatus.FAILED, detail=str(error))
            self._finish_progress("tree", status=OperationStatus.FAILED, detail=str(error))
            return
        if not isinstance(payload, dict):
            return
        if payload.get("status") == "yielded":
            if self._analysis_cancelled:
                self._analysis_cancelled = False
                self._analysis_resume = None
                self.analysis_error.emit("Tree analysis cancelled")
                self._finish_progress("tree", status=OperationStatus.CANCELLED)
                self._finish_progress("analysis", status=OperationStatus.CANCELLED)
            return
        meta = payload.get("request_meta") or {}
        if meta.get("baseline_generation", self._baseline_generation) != self._baseline_generation:
            self.analysis_stale.emit()
            return
        tree_set = payload.get("tree_set") or {}
        if isinstance(tree_set, dict) and tree_set:
            index = tree_set.get("index")
            self._active_tree_set_id = "" if index is None else str(index)
            self._active_tree_set_name = str(tree_set.get("title") or tree_set.get("name") or "")
        baseline = payload.get("baseline") or {}
        if not self._active_tree_set_name and baseline.get("tree_set"):
            self._active_tree_set_name = str(baseline.get("tree_set"))
        self._last_analysis = payload
        self._analysis_generation = self._baseline_generation
        self._analysis_resume = None
        if payload.get("kind") in {"tree", "tree_snapshot"} or payload.get("nodes") or payload.get("graph"):
            graph = dict(payload.get("graph") or payload)
            if payload.get("baseline") and not graph.get("baseline"):
                graph["baseline"] = payload["baseline"]
            self.tree_view_model.ingest_graph_payload(graph)
            if payload.get("kind") == "tree":
                self.tree_view_model.ingest_analysis(payload, scope=payload.get("scope"))
            self._tree_analysis_generation = self.tree_view_model.tree_analysis_generation
        kind = str(payload.get("kind") or meta.get("kind") or "")
        if kind.startswith("tree") or payload.get("nodes"):
            self._finish_progress("tree", status=OperationStatus.COMPLETE)
        else:
            self._finish_progress("analysis", status=OperationStatus.COMPLETE)
        self.analysis_finished.emit(payload)

    def _on_baseline_finished(self, request_id: int, payload: object, error: Exception | None) -> None:
        active = self._scheduler.active
        if active is not None and getattr(active, "request_id", None) == request_id:
            self._scheduler.complete(active)
        else:
            self._scheduler.complete_by_id(request_id)
        if error is not None:
            self._fail_baseline(str(error))
            return
        if not isinstance(payload, dict):
            self._fail_baseline("baseline reload returned no payload")
            return
        meta = payload.get("request_meta") or {}
        if meta.get("baseline_generation", self._baseline_generation) != self._baseline_generation:
            return
        self._loadouts = list(payload.get("loadouts") or [])
        self._item_sets = list(payload.get("item_sets") or [])
        self._active_loadout = str(payload.get("active_loadout") or "")
        self._active_item_set_id = payload.get("item_set_id")
        self._active_item_set_name = str(payload.get("item_set_name") or "")
        tree_set = payload.get("tree_set") or {}
        if isinstance(tree_set, dict):
            index = tree_set.get("index")
            self._active_tree_set_id = "" if index is None else str(index)
            self._active_tree_set_name = str(tree_set.get("title") or tree_set.get("name") or "")
        path = str(payload.get("build_path") or self.build_info.path)
        context = str(payload.get("context") or self.build_info.context)
        name = str(payload.get("build_name") or Path(path).stem)
        fingerprint = str(payload.get("fingerprint") or "")
        self._equipment_fingerprint = fingerprint
        self._evaluation_fingerprint_components = dict(payload.get("fingerprint_components") or {})
        self.build_info = BuildInfo(path=path, source_ref=LocalPobBuildSource(path).ref, name=name, context=context, state=BuildState.READY)
        self.baseline_state = BaselineState(
            state=BuildState.READY,
            build_path=path,
            source_ref=LocalPobBuildSource(path).ref,
            source_revision=str(payload.get("source_revision") or ""),
            build_name=name,
            loadout_id=self._active_loadout,
            loadout_name=self._active_loadout,
            item_set_id=self._active_item_set_id,
            item_set_name=self._active_item_set_name,
            tree_set_id=self._active_tree_set_id,
            tree_set_name=self._active_tree_set_name,
            context=context,
            generation=self._baseline_generation,
            fingerprint=fingerprint,
            tree_fingerprint=str(payload.get("tree_fingerprint") or ""),
            equipment_fingerprint=str(payload.get("equipment_fingerprint") or ""),
            metrics=payload.get("metrics") or {},
            reload_ms=float(payload.get("reload_ms") or 0.0),
        )
        if payload.get("graph"):
            self.tree_view_model.ingest_graph_payload(payload["graph"])
        self._accept_tree = True
        self._configure_worker()
        self._recovery_attempted = False
        self._publish_baseline_state()
        logger.info(
            "build_loaded path=%s name=%s generation=%s equipment_fp=%s reload_ms=%.0f source=baseline_reload",
            path,
            self.build_info.name,
            self._baseline_generation,
            str(payload.get("equipment_fingerprint") or "")[:12],
            float(payload.get("reload_ms") or 0.0),
        )
        self._record_build_revision(path)
        self._persist_ready_build_cache(path)
        self._persist_build_settings(path, context)
        if self._baseline_wait_loop is not None:
            self._baseline_wait_loop.quit()
        self._auto_reload_status = "RELOADED"
        self._resume_deferred_evaluation()

    def last_analysis(self) -> dict[str, Any] | None:
        return self._last_analysis

    @property
    def last_market_result(self) -> dict[str, Any] | None:
        return self._last_market_result

    def search_intent_for_slot(self, slot: str) -> dict[str, Any] | None:
        analysis = self._last_analysis
        if not analysis:
            return None
        for row in analysis.get("slots") or []:
            if row.get("product_slot") == slot or row.get("pob_slot") == slot:
                return row.get("search_intent")
        return None

    def _price_check_observations(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        session = self._market_capture_store.active_session
        if session is None:
            return rows
        for obs in session.observations:
            price = obs.price
            rows.append(
                {
                    "observation_id": obs.observation_id,
                    "item_raw": obs.item_raw,
                    "content_hash": obs.content_hash,
                    "price_amount": price.amount if price else None,
                    "price_currency": price.currency if price else None,
                    "league": self.settings.market_league or None,
                }
            )
        return rows

    def _character_league_for_price_check(self) -> str | None:
        live_sync = getattr(self, "_live_gear_sync", None)
        if live_sync is None:
            return None
        snapshot = getattr(getattr(live_sync, "state", None), "snapshot", None)
        if snapshot is None:
            return None
        league = getattr(snapshot, "league", None)
        return str(league).strip() if league else None

    @property
    def league_catalog(self) -> LeagueCatalog:
        if self._league_catalog is None:
            self._league_catalog = LeagueCatalog.from_settings(self.settings)
        return self._league_catalog

    def refresh_league_catalog(self, *, force: bool = False):
        """Refresh the cached league list and persist it. Safe to call on a 429."""
        catalog = self.league_catalog
        result = catalog.refresh(force=force)
        if not result.from_cache:
            catalog.write_to_settings(self.settings)
            save_settings(self.settings)
        return result

    def _build_league_for_price_check(self) -> str | None:
        """League declared by the loaded build, when the build actually carries one.

        MARKET-01B10 audit: a PoB2 build file records no league, so `BuildInfo` has no
        such field today and this returns None. It is read defensively so that if a
        build or baseline ever does carry one it is used before prompting. The league is
        never inferred from a character name or any other unsafe heuristic.
        """
        for holder in (getattr(self, "build_info", None), getattr(self, "_baseline", None)):
            league = getattr(holder, "league", None)
            cleaned = str(league or "").strip()
            if cleaned:
                return cleaned
        return None

    def resolve_price_check_league(self, *, allow_network: bool = True) -> LeagueResolution:
        resolution = resolve_market_league(
            settings_league=self.settings.market_league,
            settings_mode=self.settings.market_league_mode,
            character_league=self._character_league_for_price_check(),
            build_league=self._build_league_for_price_check(),
            catalog=self.league_catalog,
            allow_network=allow_network,
        )
        logger.info(
            "price_check_league %s",
            describe_resolution(
                resolution,
                mode=self.settings.market_league_mode,
                saved=self.settings.market_league,
            ),
        )
        if resolution.resolved and resolution.source != MODE_PINNED.lower():
            # Remember what automatic resolution produced so a later rate limit cannot
            # strand the user (MARKET-01B10 section 5).
            self._remember_resolved_league(resolution.context.league or "")
        return resolution

    def _remember_resolved_league(self, league: str) -> None:
        cleaned = str(league or "").strip()
        if not cleaned or cleaned == self.settings.market_league:
            return
        self.settings.market_league = cleaned
        self.league_catalog.write_to_settings(self.settings)
        save_settings(self.settings)

    def apply_league_selection(self, league: str, *, pinned: bool = True) -> bool:
        """Persist a user league choice and resume any price check waiting on it."""
        cleaned = str(league or "").strip()
        if not cleaned:
            return False
        canonical = self.league_catalog.canonicalize(cleaned) or cleaned
        self.settings.market_league = canonical
        self.settings.market_league_mode = MODE_PINNED if pinned else "AUTO"
        self.league_catalog.write_to_settings(self.settings)
        save_settings(self.settings)
        logger.info(
            "price_check_league user selection league=%s mode=%s",
            canonical,
            self.settings.market_league_mode,
        )
        self.market_league_changed.emit(canonical, self.settings.market_league_mode)
        return self._resume_pending_price_check()

    def _resume_pending_price_check(self) -> bool:
        pending = self._pending_league_request
        self._pending_league_request = None
        if not pending:
            return False
        text, request_id, anchor = pending
        logger.info("price_check_league resuming pending request request_id=%s", request_id)
        self._request_id += 1
        resumed_id = self._request_id
        self.begin_price_check_request(request_id=resumed_id, anchor_screen_px=anchor)
        self.submit_price_check(text, copy_anchor_screen_px=anchor, request_id=resumed_id)
        return True

    def _check_price_within_budget(self, domain_request):
        """Decide *before* the network layer whether a fresh search may be sent.

        MARKET-01B11 section 11: when server policy does not currently allow another
        search, try the reusable live data first and only then queue. The live provider
        is not invoked at all, so no request can be dispatched against policy.

        MARKET-02F2A: a fetch-stage continuation may proceed when search is already
        done — only the fetch endpoint gate applies.
        """
        from poe2value.price_check.network_withhold import STAGE_FETCH
        from poe2value.price_check.rate_policy import FETCH, SEARCH, shared_policy_registry

        continuation = getattr(domain_request, "pipeline_continuation", None)
        if continuation is not None and getattr(continuation, "stage", "") == STAGE_FETCH:
            wait = shared_policy_registry().seconds_until_safe(FETCH)
            if wait <= 0:
                return self._price_check_service.check(domain_request)
            cached = self._price_from_session_cache(domain_request)
            if cached is not None:
                return cached
            return self._paced_result(domain_request, wait, stage=STAGE_FETCH)

        wait = shared_policy_registry().seconds_until_safe(SEARCH)
        if wait <= 0:
            return self._price_check_service.check(domain_request)

        cached = self._price_from_session_cache(domain_request)
        if cached is not None:
            logger.info(
                "price_check_budget search paced %.1fs — served from cached live market",
                wait,
            )
            return cached

        logger.info("price_check_budget search paced %.1fs — no reusable cache", wait)
        return self._paced_result(domain_request, wait)

    def _price_from_session_cache(self, domain_request):
        """Ask only the no-network provider for an answer."""
        if isinstance(domain_request, CompiledPriceCheckRequest):
            return self._price_check_service.cached_compiled(domain_request)
        for provider in getattr(self._price_check_service, "_providers", []) or []:
            if getattr(provider, "provider_id", "") != "market_session":
                continue
            try:
                result = provider.lookup(domain_request)
            except Exception:  # noqa: BLE001 - cache must never break a price check
                logger.exception("market session lookup failed")
                return None
            if result is not None and result.estimate.has_currency_estimate:
                return result
        return None

    def _paced_result(self, domain_request, wait: float, *, stage: str = "search"):
        """A result that says 'not yet', carrying the exact wait. No request was sent."""
        from poe2value.price_check.models import (
            LiveSearchState,
            PriceCheckDiagnostics,
            PriceCheckResult,
            PriceConfidence,
            PriceEstimate,
            PriceSourceKind,
        )
        from poe2value.price_check.network_withhold import (
            STAGE_FETCH,
            build_fetch_withhold,
            build_search_withhold,
        )

        if stage == STAGE_FETCH and domain_request.pipeline_continuation is not None:
            fetch = domain_request.pipeline_continuation.fetch
            withhold = build_fetch_withhold(
                wait_seconds=wait,
                request_id=domain_request.request_id,
                fetch=fetch,
                proactive=True,
            ) if fetch is not None else None
        else:
            withhold = build_search_withhold(
                wait_seconds=wait,
                request_id=domain_request.request_id,
                proactive=True,
            )

        message = (
            f"Comparables queued — ~{max(1, int(wait))}s"
            if stage == STAGE_FETCH
            else "Waiting for the market to allow another search."
        )
        return PriceCheckResult(
            request=domain_request,
            estimate=PriceEstimate(
                source_kind=PriceSourceKind.UNKNOWN,
                confidence=PriceConfidence.NONE,
                summary=message,
            ),
            provider_id="rate_policy",
            live_search_state=LiveSearchState.LIVE_SEARCH_RATE_LIMITED,
            message=message,
            network_withhold=withhold,
            diagnostics=PriceCheckDiagnostics(
                league=domain_request.league.league,
                provider_id="rate_policy",
                live_state=LiveSearchState.LIVE_SEARCH_RATE_LIMITED,
                rate_limit_retry_after=wait,
                search_requests=0,
                fetch_requests=0,
                total_http_requests=0,
            ),
        )

    def _maybe_queue_live_refresh(
        self,
        result,
        request_id: int,
        *,
        text: str,
        anchor: tuple[int, int] | None,
        league: str | None,
        hypothesis=None,
    ) -> int | None:
        """Turn ordinary server pacing into a short automatic wait.

        Only for waits the app can sit through. A genuine long penalty still surfaces
        as LIVE MARKET TEMPORARILY LIMITED so the user is not left staring at a spinner.
        """
        from poe2value.price_check.models import LiveSearchState
        from poe2value.price_check.network_withhold import STAGE_FETCH
        from poe2value.price_check.rate_policy import FETCH, SEARCH, shared_policy_registry

        if result.estimate.has_currency_estimate:
            return None
        if isinstance(getattr(result, "request", None), CompiledPriceCheckRequest):
            hypothesis = result.request
        withhold = getattr(result, "network_withhold", None)
        if withhold is not None and withhold.wait_seconds > 0:
            if withhold.wait_seconds > self.MAX_QUEUED_REFRESH_SECONDS:
                return None
            queued_hypothesis = getattr(result, "pending_hypothesis", None) or hypothesis
            queued_reason = withhold.reason or (
                "discovery" if getattr(result, "pending_hypothesis", None) is not None else ""
            )
            continuation = withhold.continuation
            stage = withhold.continuation_stage or STAGE_FETCH
            return self._queue_live_refresh(
                request_id,
                text=text,
                anchor=anchor,
                wait_seconds=withhold.wait_seconds,
                neighbourhood=self._neighbourhood_for(text, league, hypothesis=queued_hypothesis),
                hypothesis=queued_hypothesis,
                reason=queued_reason,
                pipeline_continuation=continuation,
                queue_stage=stage,
            )
        if result.live_search_state != LiveSearchState.LIVE_SEARCH_RATE_LIMITED:
            return None

        registry = shared_policy_registry()
        wait = max(registry.seconds_until_safe(SEARCH), registry.seconds_until_safe(FETCH))
        diagnostics = result.diagnostics
        if diagnostics is not None and diagnostics.rate_limit_retry_after:
            wait = max(wait, float(diagnostics.rate_limit_retry_after))
        if wait <= 0 or wait > self.MAX_QUEUED_REFRESH_SECONDS:
            return None

        queued_hypothesis = getattr(result, "pending_hypothesis", None) or hypothesis
        queued_reason = "discovery" if getattr(result, "pending_hypothesis", None) is not None else ""
        queue_stage = STAGE_FETCH if registry.seconds_until_safe(FETCH) > registry.seconds_until_safe(SEARCH) else "search"
        return self._queue_live_refresh(
            request_id,
            text=text,
            anchor=anchor,
            wait_seconds=wait,
            neighbourhood=self._neighbourhood_for(text, league, hypothesis=queued_hypothesis),
            hypothesis=queued_hypothesis,
            reason=queued_reason,
            queue_stage=queue_stage,
        )

    def _price_check_source_diagnostics(self, result) -> dict[str, Any]:
        """MARKET-01B11 section 24 — where each price came from and what it cost."""
        from poe2value.price_check.market_session import shared_market_session
        from poe2value.price_check.rate_policy import FETCH, SEARCH, shared_policy_registry

        diagnostics = result.diagnostics
        registry = shared_policy_registry()
        search_wait = registry.seconds_until_safe(SEARCH)
        return {
            "price_source": result.provider_id,
            "market_status": result.market_status,
            "live_cache_age_seconds": (
                round(result.cache_age_seconds, 1) if result.cache_age_seconds is not None else None
            ),
            "cached_comparable_count": result.comparable_count,
            "search_allowed_now": search_wait <= 0,
            "next_search_safe_in_ms": int(search_wait * 1000),
            "next_fetch_safe_in_ms": int(registry.seconds_until_safe(FETCH) * 1000),
            "search_requests": getattr(diagnostics, "search_requests", 0) if diagnostics else 0,
            "fetch_requests": getattr(diagnostics, "fetch_requests", 0) if diagnostics else 0,
            "http_status": getattr(diagnostics, "http_status", None) if diagnostics else None,
            "market_session": shared_market_session().snapshot(),
        }

    # ------------------------------------------------------------ queued live refresh

    # Anything longer than this is a real penalty, not ordinary pacing; the user is told
    # rather than left waiting.
    MAX_QUEUED_REFRESH_SECONDS = 90.0

    def _queue_live_refresh(
        self,
        request_id: int,
        *,
        text: str,
        anchor: tuple[int, int] | None,
        wait_seconds: float,
        neighbourhood: str,
        cached_age: float | None = None,
        cached_count: int = 0,
        hypothesis=None,
        reason: str = "",
        pipeline_continuation=None,
        queue_stage: str = "search",
    ) -> int:
        """Tell the user we are waiting, then retry by ourselves when policy allows.

        MARKET-01B11 section 14: pending work is coalesced by market neighbourhood, so
        checking five rings while one search is permitted schedules **one** refresh, not
        five.
        """
        self._queued_refreshes[neighbourhood] = (
            text,
            request_id,
            anchor,
            hypothesis,
            pipeline_continuation,
        )

        presentation = build_price_check_queued(
            seconds_until_refresh=wait_seconds,
            cached_age_seconds=cached_age,
            cached_comparable_count=cached_count,
            reason=reason,
            stage=queue_stage,
        )
        payload = {
            "price_check": {
                "queued_live_refresh": True,
                "request_id": request_id,
                "queued_seconds": round(wait_seconds, 1),
                "neighbourhood": neighbourhood,
            },
            "presentation": presentation,
            "request_meta": {
                "request_id": request_id,
                "kind": "price_check",
                "copy_anchor_screen_px": {"x": anchor[0], "y": anchor[1]} if anchor else None,
            },
        }
        if isinstance(hypothesis, CompiledPriceCheckRequest):
            queued_result = self._paced_result(hypothesis, wait_seconds)
            payload["panel_model"] = self._panel_model_for(queued_result, presentation, generation=hypothesis.generation)
            payload["request_meta"]["generation"] = hypothesis.generation
        self._emit_price_check_finished(request_id, payload)

        existing = self._queued_timers.pop(neighbourhood, None)
        if existing is not None:
            existing.stop()
            existing.deleteLater()
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: self._run_queued_refresh(neighbourhood))
        timer.start(int(max(0.2, wait_seconds) * 1000))
        self._queued_timers[neighbourhood] = timer
        logger.info(
            "price_check_queued neighbourhood=%s wait=%.1fs request_id=%s",
            neighbourhood[:12],
            wait_seconds,
            request_id,
        )
        return request_id

    def _run_queued_refresh(self, neighbourhood: str) -> None:
        pending = self._queued_refreshes.pop(neighbourhood, None)
        timer = self._queued_timers.pop(neighbourhood, None)
        if timer is not None:
            timer.deleteLater()
        if not pending:
            return
        text, _original_id, anchor, hypothesis, pipeline_continuation = pending
        if isinstance(hypothesis, CompiledPriceCheckRequest):
            self.submit_price_check(text, copy_anchor_screen_px=anchor,
                                    compiled_request=hypothesis, pipeline_continuation=pipeline_continuation)
            return
        if hypothesis is not None:
            logger.info(
                "price_check_queued resuming refined neighbourhood=%s",
                neighbourhood[:12],
            )
            self.submit_refined_price_check(hypothesis)
            return
        self._request_id += 1
        request_id = self._request_id
        logger.info(
            "price_check_queued resuming neighbourhood=%s request_id=%s continuation=%s",
            neighbourhood[:12],
            request_id,
            getattr(pipeline_continuation, "stage", None),
        )
        self.begin_price_check_request(request_id=request_id, anchor_screen_px=anchor)
        self.submit_price_check(
            text,
            copy_anchor_screen_px=anchor,
            request_id=request_id,
            pipeline_continuation=pipeline_continuation,
        )

    def _neighbourhood_for(self, item_raw: str, league: str | None, *, hypothesis=None) -> str:
        if isinstance(hypothesis, CompiledPriceCheckRequest):
            return f"compiled:{league}:{hypothesis.compiled_query.query_fingerprint}"
        from poe2value.price_check.comparable_query import build_search_query
        from poe2value.price_check.market_drivers import neighbourhood_identity
        from poe2value.price_check.market_session import neighbourhood_fingerprint

        try:
            if hypothesis is not None:
                return neighbourhood_identity(hypothesis)
            return neighbourhood_fingerprint(
                build_search_query(item_raw, league=league), league=league
            )
        except Exception:  # noqa: BLE001 - never break a price check over a cache key
            return "unknown"

    def _emit_league_required(
        self,
        request_id: int,
        resolution: LeagueResolution,
        *,
        text: str,
        anchor: tuple[int, int] | None,
    ) -> int:
        """Show an actionable prompt and remember the request so it can resume."""
        self._pending_league_request = (text, request_id, anchor)
        leagues = list(self.league_catalog.selectable_leagues())
        presentation = build_price_check_league_required(
            failure_code=resolution.failure_code or "league_required",
            stale_league=resolution.stale_league,
            selecting=True,
        )
        payload = {
            "price_check": {
                "league_required": True,
                "request_id": request_id,
                "failure_code": resolution.failure_code,
                "stale_league": resolution.stale_league,
            },
            "presentation": presentation,
            "request_meta": {
                "request_id": request_id,
                "kind": "price_check",
                "copy_anchor_screen_px": {"x": anchor[0], "y": anchor[1]} if anchor else None,
            },
        }
        self._emit_price_check_finished(request_id, payload)
        self.league_selection_required.emit(
            request_id,
            leagues,
            str(resolution.failure_code or ""),
            str(resolution.stale_league or ""),
        )
        return request_id

    def begin_price_check_request(
        self,
        *,
        request_id: int,
        anchor_screen_px: tuple[int, int] | None = None,
    ) -> int:
        """New Shift+C request — clear prior presentation and supersede in-flight capture."""
        if not self.settings.price_check_enabled:
            return request_id
        if request_id > self._request_id:
            self._request_id = request_id
        self._latest_price_check_id = request_id
        self._active_price_check_id = request_id
        self._price_check_inflight = True
        if anchor_screen_px is not None and not (anchor_screen_px[0] == 0 and anchor_screen_px[1] == 0):
            self._request_anchors[request_id] = anchor_screen_px
        if self.price_check_capture.has_pending_session:
            self.price_check_capture.cancel()
        log_capture_phase(CapturePhase.HOTKEY_RECEIVED, capture_id=request_id)
        self.price_check_started.emit(request_id)
        return request_id

    @property
    def active_price_check_id(self) -> int | None:
        return self._active_price_check_id

    def begin_price_check_capture(
        self,
        anchor_screen_px: tuple[int, int],
        *,
        request_id: int | None = None,
    ) -> int | None:
        """Begin the owned Shift+C capture used exclusively by Item Check."""
        return self.price_check_capture.begin_capture(anchor_screen_px, request_id=request_id)

    def notify_app_deactivated(self) -> None:
        """Reset price-check capture state when overlay app loses activation."""
        self.price_check_hotkey.notify_app_deactivated()
        self.price_check_capture.cancel()

    def route_price_check_clipboard(
        self,
        *,
        text: str,
        sequence: int | None,
        anchor_screen_px: tuple[int, int],
    ) -> bool:
        return self.price_check_capture.route_clipboard_event(
            text=text,
            sequence=sequence,
            anchor_screen_px=anchor_screen_px,
        )

    def should_suppress_gameplay_for_price_capture(self, sequence: int | None) -> bool:
        return self.price_check_capture.should_suppress_gameplay(sequence)

    def try_external_clipboard_item_check(
        self,
        text: str,
        *,
        sequence: int | None,
        content_hash: str,
        copy_anchor_screen_px: tuple[int, int],
        cursor_position: QPoint | None = None,
        copy_timestamp: float | None = None,
    ) -> bool:
        """Analyze PoE2 market clipboard copies when guards pass. Returns True if handled."""
        decision, _recognition = self._external_clipboard_router.evaluate(
            ExternalClipboardCandidate(
                text=text,
                sequence=sequence,
                content_hash=content_hash,
                copy_anchor_screen_px=copy_anchor_screen_px,
            ),
            previous_sequence=self._last_clipboard_sequence,
            hotkey_owns_sequence=self.price_check_capture.is_hotkey_owned_sequence,
        )
        decision_key = decision.value
        self._external_clipboard_counts[decision_key] = self._external_clipboard_counts.get(decision_key, 0) + 1
        self._last_external_clipboard_decision = f"{decision_key} sequence={sequence}"
        if decision in {
            ExternalClipboardDecision.SUPPRESSED_HOTKEY,
            ExternalClipboardDecision.IGNORED_FOREIGN_CTRL_C,
            ExternalClipboardDecision.IGNORED_FOREGROUND,
            ExternalClipboardDecision.IGNORED_NOT_ITEM,
            ExternalClipboardDecision.IGNORED_DUPLICATE,
        }:
            return decision == ExternalClipboardDecision.SUPPRESSED_HOTKEY
        if decision != ExternalClipboardDecision.ACCEPTED:
            return False
        self.submit_clipboard_text(
            text,
            cursor_position=cursor_position,
            copy_anchor_screen_px=copy_anchor_screen_px,
            copy_timestamp=copy_timestamp,
            content_hash=content_hash or None,
            clipboard_sequence=sequence,
        )
        return True

    def _on_price_check_capture_started(self, request_id: int) -> None:
        anchor = self.price_check_capture.active_session
        if anchor is not None:
            self._request_anchors[request_id] = anchor.anchor_screen_px

    def _on_price_check_capture_ready(
        self,
        request_id: int,
        text: str,
        anchor: object,
        sequence: object,
    ) -> None:
        physical_anchor = anchor if isinstance(anchor, tuple) else None
        try:
            # Shift+C owns one game-side copy for Item Check. Market/Price Check is a
            # separate consumer and must never start implicitly from this payload.
            self.submit_clipboard_text(
                text,
                copy_anchor_screen_px=physical_anchor,
                clipboard_sequence=sequence if isinstance(sequence, int) else None,
            )
        except Exception as exc:  # noqa: BLE001 - a Qt slot must not raise
            logger.exception("owned Item Check capture routing failed")
            self._on_price_check_capture_failed(
                request_id,
                f"Could not analyze hovered item: {exc}",
            )

    def _on_price_check_capture_failed(self, request_id: int, message: str) -> None:
        """Surface owned Shift+C acquisition failures through Item Check only."""
        if request_id > self._request_id:
            self._request_id = request_id
        self._latest_request_id = max(self._latest_request_id, request_id)
        self._begin_eval_feedback(request_id)
        self._emit_item_check_error(request_id, message)

    def _emit_price_check_finished(self, request_id: int, payload: dict[str, Any]) -> None:
        presentation = payload.get("presentation") or {}
        log_capture_phase(
            CapturePhase.PRICE_CHECK_RESULT_READY,
            capture_id=request_id,
            kind=(payload.get("request_meta") or {}).get("kind"),
            latest_capture_id=self._latest_price_check_id,
        )
        log_capture_phase(
            CapturePhase.PRESENTATION_BUILT,
            capture_id=request_id,
            has_presentation=bool(presentation),
            title=presentation.get("title"),
            source_label=presentation.get("source_label"),
            currency_band_count=len(presentation.get("currency_bands") or []),
        )
        if request_id < self._latest_price_check_id:
            log_capture_phase(
                CapturePhase.SESSION_STALE,
                capture_id=request_id,
                active_capture_id=self._latest_price_check_id,
                stage="price_check_finished",
            )
            return
        self.price_check_finished.emit(request_id, payload)
        if self._active_price_check_id == request_id:
            self._active_price_check_id = None
        self._price_check_inflight = False

    def submit_price_check_failure(
        self,
        message: str,
        *,
        request_id: int | None = None,
        emit_started: bool = True,
    ) -> int | None:
        if not self.settings.price_check_enabled:
            return None
        if request_id is None:
            self._request_id += 1
            request_id = self._request_id
        if emit_started:
            self.begin_price_check_request(request_id=request_id)
        elif request_id >= self._latest_price_check_id:
            self._latest_price_check_id = request_id
        anchor = self._request_anchors.get(request_id) or get_cursor_pos_physical()
        if anchor is not None and not (anchor[0] == 0 and anchor[1] == 0):
            self._request_anchors[request_id] = anchor
        presentation = build_price_check_acquisition_failure(message)
        payload = {
            "price_check": {
                "acquisition_failed": True,
                "request_id": request_id,
                "message": message,
            },
            "presentation": presentation,
            "request_meta": {
                "request_id": request_id,
                "kind": "price_check",
                "copy_anchor_screen_px": {"x": anchor[0], "y": anchor[1]} if anchor else None,
            },
        }
        self._emit_price_check_finished(request_id, payload)
        return request_id

    def submit_capture_test_result(
        self,
        text: str,
        *,
        copy_anchor_screen_px: tuple[int, int] | None = None,
        request_id: int | None = None,
        sequence: int | None = None,
        sequence_before: int | None = None,
    ) -> int | None:
        """CAPTURE-ONLY diagnostic — show acquisition proof without market pipeline."""
        if request_id is None:
            self._request_id += 1
            request_id = self._request_id
        anchor = copy_anchor_screen_px or get_cursor_pos_physical()
        if anchor is not None and not (anchor[0] == 0 and anchor[1] == 0):
            self._request_anchors[request_id] = anchor
        session = self.price_check_capture.active_session
        start_sequence = sequence_before
        if start_sequence is None:
            stored = self.price_check_capture.completed_sequences.get(request_id)
            if stored is not None:
                start_sequence, stored_after = stored
                if sequence is None:
                    sequence = stored_after
        if start_sequence is None:
            start_sequence = 0
        foreground = evaluate_poe_foreground_match()
        presentation = build_capture_test_presentation(
            item_raw=text or "",
            capture_id=request_id,
            sequence_before=int(start_sequence),
            sequence_after=sequence,
            foreground_info=foreground,
        )
        payload = {
            "price_check": {
                "capture_test": True,
                "request_id": request_id,
                "capture_id": request_id,
            },
            "presentation": presentation,
            "request_meta": {
                "request_id": request_id,
                "kind": "capture_test",
                "copy_anchor_screen_px": {"x": anchor[0], "y": anchor[1]} if anchor else None,
            },
        }
        log_capture_phase(
            CapturePhase.PRICE_CHECK_SUBMITTED,
            capture_id=request_id,
            diagnostic_mode="capture_only",
            sequence_before=start_sequence,
            sequence_after=sequence,
            **{
                key: foreground.get(key)
                for key in (
                    "current_hwnd",
                    "current_pid",
                    "current_process_name",
                    "current_window_title",
                    "poe_match_result",
                )
            },
        )
        self._emit_price_check_finished(request_id, payload)
        return request_id

    def submit_market_only_diagnostic(
        self,
        *,
        fixture_text: str | None = None,
        request_id: int | None = None,
    ) -> int | None:
        """MARKET-ONLY diagnostic — run live pipeline on saved fixture without capture."""
        if request_id is None:
            self._request_id += 1
            request_id = self._request_id
        self._latest_price_check_id = request_id
        self._active_price_check_id = request_id
        self._price_check_inflight = True
        self.price_check_started.emit(request_id)
        try:
            item_raw = fixture_text or load_market_fixture_text()
            raw = RawItemInput.from_text(item_raw)
            resolution = self.resolve_price_check_league()
            domain_request = DomainPriceCheckRequest(
                item_raw=item_raw,
                content_hash=raw.content_hash,
                league=resolution.context,
                request_id=request_id,
                league_source=resolution.source,
            )
            result = self._market_only_service.check(domain_request)
            presentation = build_market_only_presentation(
                result,
                debug=bool(self.settings.debug),
            )
            payload = {
                "price_check": result.to_dict(),
                "presentation": presentation,
                "request_meta": {
                    "request_id": request_id,
                    "kind": "market_only",
                },
            }
            self._emit_price_check_finished(request_id, payload)
            return request_id
        except Exception as exc:  # noqa: BLE001 - diagnostic must never fail silently
            return self._emit_price_check_pipeline_error(request_id, exc)
        finally:
            if self._active_price_check_id == request_id:
                self._active_price_check_id = None
            self._price_check_inflight = False

    def submit_price_check(
        self,
        text: str,
        *,
        copy_anchor_screen_px: tuple[int, int] | None = None,
        request_id: int | None = None,
        pipeline_continuation=None,
        compiled_request=None,
    ) -> int | None:
        """Run the retained Price Check engine for an explicit or resumed request."""
        if not self.settings.price_check_enabled:
            return None
        if compiled_request is not None and not self._price_check_session.accepts(compiled_request.generation):
            logger.info("price_check_stale_compiled_retry_dropped generation=%s", compiled_request.generation)
            return None

        if request_id is None:
            self._request_id += 1
            request_id = self._request_id
            self.begin_price_check_request(request_id=request_id, anchor_screen_px=copy_anchor_screen_px)
        elif request_id > self._request_id:
            self._request_id = request_id
        if request_id >= self._latest_price_check_id:
            self._latest_price_check_id = request_id

        anchor = copy_anchor_screen_px or get_cursor_pos_physical()
        if anchor is not None and not (anchor[0] == 0 and anchor[1] == 0):
            self._request_anchors[request_id] = anchor
            self._last_copy_anchor_physical = anchor

        try:
            raw = RawItemInput.from_text(text or "")
            resolution = self.resolve_price_check_league()
            if not resolution.resolved:
                # MARKET-01B10: never a dead end. Park the request, ask once, resume.
                return self._emit_league_required(
                    request_id, resolution, text=text or "", anchor=anchor
                )
            if compiled_request is None:
                generation = self._begin_price_check_session(
                    request_id=request_id, item_raw=text or "", anchor=anchor
                )
                session = self._price_check_session
                if session.plan is None or session.compiled is None:
                    raise ValueError("Could not compile the market search plan")
                domain_request = CompiledPriceCheckRequest(
                    item_raw=text or "", content_hash=raw.content_hash, league=resolution.context,
                    request_id=request_id, league_source=resolution.source,
                    pipeline_continuation=pipeline_continuation,
                    plan=session.plan, compiled_query=session.compiled, generation=generation,
                    user_refined=session.user_refined,
                )
            else:
                from dataclasses import replace
                if not self._price_check_session.accepts(compiled_request.generation):
                    return None
                generation = compiled_request.generation
                domain_request = replace(compiled_request, request_id=request_id,
                                         pipeline_continuation=pipeline_continuation)
            result = self._check_price_within_budget(domain_request)

            queued = self._maybe_queue_live_refresh(
                result,
                request_id,
                text=text or "",
                anchor=anchor,
                league=resolution.context.league,
            )
            if queued is not None:
                return queued

            presentation = self._price_check_service.presentation_for(
                result,
                debug=bool(self.settings.debug),
            )
            self._remember_price_check(text or "", result, presentation)
            payload = {
                "price_check": result.to_dict(),
                "presentation": presentation,
                "panel_model": self._panel_model_for(result, presentation, generation=generation),
                "request_meta": {
                    "request_id": request_id,
                    "kind": "price_check",
                    "generation": generation,
                    "copy_anchor_screen_px": {"x": anchor[0], "y": anchor[1]} if anchor else None,
                },
            }
            log_capture_phase(
                CapturePhase.PRICE_CHECK_SUBMITTED,
                capture_id=request_id,
                **self._price_check_source_diagnostics(result),
            )
            self._emit_price_check_finished(request_id, payload)
            return request_id
        except Exception as exc:  # noqa: BLE001 - never leave Shift+C without a window
            # MARKET-01B9: an unhandled pipeline error used to escape into the Qt slot,
            # so price_check_finished was never emitted and no overlay ever appeared.
            return self._emit_price_check_pipeline_error(request_id, exc, anchor=anchor)
        finally:
            if self._active_price_check_id == request_id:
                self._active_price_check_id = None
            self._price_check_inflight = False

    def _emit_price_check_pipeline_error(
        self,
        request_id: int,
        exc: BaseException,
        *,
        anchor: tuple[int, int] | None = None,
    ) -> int:
        """Turn any unexpected price-check failure into a visible overlay."""
        logger.exception("price_check_pipeline_error request_id=%s", request_id)
        message = f"Price check failed: {type(exc).__name__}: {exc}"
        presentation = build_price_check_acquisition_failure(
            message,
            failure_code="pipeline_error",
        )
        presentation["title"] = "PRICE CHECK FAILED"
        presentation["disclaimer"] = "Unexpected error in the price check pipeline."
        payload = {
            "price_check": {
                "pipeline_error": True,
                "request_id": request_id,
                "message": message,
                "error_type": type(exc).__name__,
            },
            "presentation": presentation,
            "request_meta": {
                "request_id": request_id,
                "kind": "price_check",
                "copy_anchor_screen_px": {"x": anchor[0], "y": anchor[1]} if anchor else None,
            },
        }
        log_capture_phase(
            CapturePhase.PRICE_CHECK_SUBMITTED,
            capture_id=request_id,
            pipeline_error=type(exc).__name__,
        )
        self._emit_price_check_finished(request_id, payload)
        return request_id

    @property
    def price_check_session(self) -> PriceCheckSession:
        return self._price_check_session

    def _begin_price_check_session(
        self, *, request_id: int, item_raw: str, anchor: tuple[int, int] | None
    ) -> int:
        """Claim the session, plan the search, and tell the UI immediately.

        The plan is built here rather than after the network so the panel can show the
        item's real filters while the market is still being asked. A planning failure must
        not cost the user the acknowledgement, so it degrades to name-and-base only.
        """
        from poe2value.items.metadata import parse_lightweight_metadata
        from poe2value.price_check.market_plan import compile_plan, plan_for_item

        raw = RawItemInput.from_text(item_raw)
        meta = parse_lightweight_metadata(raw)
        base_parts = [str(meta.base_type or ""), str(meta.rarity or "").title()]
        if meta.ilvl is not None:
            base_parts.append(f"ilvl {meta.ilvl}")
        generation = self._price_check_session.begin(
            request_id=request_id,
            item_raw=item_raw,
            item_name=str(meta.name or meta.base_type or "Item"),
            base_line=" · ".join(part for part in base_parts if part),
            anchor=anchor,
        )
        try:
            plan = plan_for_item(
                item_raw,
                category=meta.category,
                base_type=meta.base_type,
                rarity=meta.rarity,
                item_level=meta.ilvl,
                quality=meta.quality,
                corrupted=meta.corrupted,
            )
            self._price_check_session.adopt_plan(plan, compile_plan(plan))
        except Exception:  # noqa: BLE001 - the acknowledgement matters more than the plan
            logger.exception("price_check_plan_failed request_id=%s", request_id)
        self.price_check_captured.emit(
            request_id,
            {
                "generation": generation,
                "item_name": self._price_check_session.item_name,
                "base_line": self._price_check_session.base_line,
                "anchor": anchor,
            },
        )
        return generation

    def _panel_model_for(
        self, result: Any, presentation: dict[str, Any], *, generation: int
    ) -> Any:
        """The MARKET-03 view model for this result, or None when planning failed."""
        from poe2value.price_check.panel_model import panel_model_for_result

        session = self._price_check_session
        if session.plan is None or not session.accepts(generation):
            return None
        bound_request = getattr(result, "request", None)
        plan = bound_request.plan if isinstance(bound_request, CompiledPriceCheckRequest) else session.plan
        compiled = bound_request.compiled_query if isinstance(bound_request, CompiledPriceCheckRequest) else session.compiled
        trust = None
        discovery = getattr(result, "discovery", None)
        if isinstance(discovery, dict):
            trust = discovery.get("price_trust") or discovery.get("price_trust_assessment") or None
        try:
            return panel_model_for_result(
                item_name=session.item_name,
                plan=plan,
                compiled=compiled,
                result=result,
                presentation=presentation,
                trust=trust,
                user_refined=session.user_refined,
            )
        except Exception:  # noqa: BLE001 - a view model failure must not lose the result
            logger.exception("price_check_panel_model_failed generation=%s", generation)
            return None

    def submit_panel_refresh(self, edits: dict[str, Any]) -> dict[str, Any] | None:
        """A user edit from the panel. Marks the plan theirs and re-runs the same item.

        Edits patch the logical plan and compile it before entering the canonical service.
        """
        session = self._price_check_session
        if not session.has_item:
            return None
        generation = int(edits.get("generation") or 0)
        if not session.accepts(generation):
            logger.info(
                "price_check_panel_stale_refresh_dropped incoming_generation=%s "
                "current_generation=%s",
                generation,
                session.generation,
            )
            return None
        from poe2value.price_check.panel_edits import apply_plan_edits
        from poe2value.price_check.market_plan import compile_plan
        if session.plan is None:
            return None
        try:
            plan = apply_plan_edits(session.plan, edits)
            compiled = compile_plan(plan)
        except (ValueError, AssertionError) as exc:
            from dataclasses import replace
            from poe2value.price_check.panel_model import PanelState
            message = f"Search unchanged: {exc}"
            self.state_message.emit(message)
            model = self._panel_model_for(session.last_result, session.last_presentation,
                                          generation=session.generation)
            if model is not None:
                self._emit_price_check_finished(self._latest_price_check_id, {
                    "presentation": session.last_presentation,
                    "panel_model": replace(model, state=PanelState.ERROR, state_text=message),
                    "request_meta": {"request_id": self._latest_price_check_id,
                                     "kind": "price_check", "generation": session.generation},
                })
            return None
        session.adopt_plan(plan, compiled)
        session.mark_user_refined()
        session.generation += 1
        raw = RawItemInput.from_text(session.item_raw)
        resolution = self.resolve_price_check_league()
        if not resolution.resolved:
            return None
        request = CompiledPriceCheckRequest(
            item_raw=session.item_raw, content_hash=raw.content_hash, league=resolution.context,
            league_source=resolution.source, plan=plan, compiled_query=compiled,
            generation=session.generation, user_refined=True,
        )
        self.submit_price_check(session.item_raw, copy_anchor_screen_px=session.anchor, compiled_request=request)
        return self.last_price_check_presentation()

    def _remember_price_check(self, item_raw: str, result: Any, presentation: dict[str, Any]) -> None:
        self._last_price_check_item_raw = str(item_raw or "")
        self._last_price_check_result = result
        self._last_price_check_presentation = dict(presentation or {})
        self._price_check_session.remember_result(result, presentation)

    def has_last_price_check(self) -> bool:
        return bool(str(self._last_price_check_item_raw or "").strip())

    def last_price_check_hypothesis(self):
        result = self._last_price_check_result
        if result is None:
            return None
        return getattr(result, "hypothesis", None)

    def last_price_check_presentation(self) -> dict[str, Any]:
        return dict(self._last_price_check_presentation)

    def request_refine_last_price_check(self) -> bool:
        if not self.has_last_price_check():
            self.state_message.emit("No Price Check session is available to refine.")
            return False
        self.refine_last_price_requested.emit()
        return True

    def submit_refined_price_check(self, hypothesis) -> dict[str, Any] | None:
        """Refresh the last captured item with an edited hypothesis. No recapture."""
        text = self._last_price_check_item_raw
        if not str(text or "").strip():
            self.state_message.emit("No Price Check session is available to refine.")
            return None
        from poe2value.platform.windows.cursor import get_cursor_pos_physical

        self._request_id += 1
        request_id = self._request_id
        self.begin_price_check_request(request_id=request_id)
        anchor = get_cursor_pos_physical()
        try:
            raw = RawItemInput.from_text(text)
            resolution = self.resolve_price_check_league()
            if not resolution.resolved:
                return None
            domain_request = DomainPriceCheckRequest(
                item_raw=text,
                content_hash=raw.content_hash,
                league=resolution.context,
                request_id=request_id,
                league_source=resolution.source,
                hypothesis=hypothesis,
            )
            result = self._check_price_within_budget(domain_request)
            queued = self._maybe_queue_live_refresh(
                result,
                request_id,
                text=text,
                anchor=anchor,
                league=resolution.context.league,
                hypothesis=hypothesis,
            )
            if queued is not None:
                from poe2value.price_check.rate_policy import SEARCH, shared_policy_registry

                wait = shared_policy_registry().seconds_until_safe(SEARCH)
                reason = "discovery" if getattr(hypothesis, "hypothesis_source", None) and str(getattr(hypothesis.hypothesis_source, "value", "")) == "AUTO_RECOVERY" else ""
                presentation = build_price_check_queued(
                    seconds_until_refresh=max(wait, 0.2),
                    reason=reason,
                )
                presentation["queued_live_refresh"] = True
                presentation["request_id"] = queued
                return presentation
            presentation = self._price_check_service.presentation_for(
                result,
                debug=bool(self.settings.debug),
            )
            self._remember_price_check(text, result, presentation)
            payload = {
                "price_check": result.to_dict(),
                "presentation": presentation,
                "request_meta": {
                    "request_id": request_id,
                    "kind": "price_check",
                    "copy_anchor_screen_px": {"x": anchor[0], "y": anchor[1]} if anchor else None,
                },
            }
            self._emit_price_check_finished(request_id, payload)
            return presentation
        except Exception as exc:  # noqa: BLE001
            self._emit_price_check_pipeline_error(request_id, exc, anchor=anchor)
            return None

    def submit_market_search(
        self,
        *,
        slot: str,
        budget_amount: float | None = None,
        budget_currency: str | None = None,
        depth: str = "BALANCED",
        source: str = "fixture",
        import_path: str | None = None,
        fixture_corpus: str | None = None,
    ) -> int | None:
        if not self._require_module(FeatureModule.MARKET, message="Market module is disabled in current module preset."):
            return None
        if not self.build_info.is_ready:
            self.state_message.emit("No build loaded — select a build from the tray menu.")
            return None
        self._request_id += 1
        request_id = self._request_id
        self._market_cancelled = False
        request = MarketSearchRequest(
            request_id=request_id,
            slot=slot,
            profile=self.settings.value_profile,
            budget_amount=budget_amount,
            budget_currency=budget_currency,
            depth=depth,
            source=source,
            import_path=import_path,
            fixture_corpus=fixture_corpus,
            search_intent=self.search_intent_for_slot(slot),
            baseline_generation=self._baseline_generation,
        )
        self.market_started.emit(request_id)
        self._track_progress("market", module="MARKET", title="Market Search", request_id=request_id)
        self._scheduler.submit(request)
        return request_id

    def cancel_market_search(self) -> None:
        self._market_cancelled = True
        self._worker.request_yield()

    def _on_market_finished(self, request_id: int, payload: object, error: Exception | None) -> None:
        active = self._scheduler.active
        if active is not None and getattr(active, "request_id", None) == request_id:
            self._scheduler.complete(active)
        else:
            self._scheduler.complete_by_id(request_id)

        if error is not None:
            self.market_error.emit(str(error))
            self._finish_progress("market", status=OperationStatus.FAILED, detail=str(error))
            return
        if not isinstance(payload, dict):
            return
        if payload.get("status") == "yielded":
            if self._market_cancelled:
                self._market_cancelled = False
                self.market_error.emit("Market search cancelled")
                self._finish_progress("market", status=OperationStatus.CANCELLED)
            return
        meta = payload.get("request_meta") or {}
        if meta.get("baseline_generation", self._baseline_generation) != self._baseline_generation:
            self.market_stale.emit()
            return
        if payload.get("stale"):
            self.market_stale.emit()
            return
        self._last_market_result = payload
        fingerprint = self.baseline_state.fingerprint or self._equipment_fingerprint
        payload["baseline_fingerprint"] = fingerprint
        payload["baseline_generation"] = self._baseline_generation
        self.pool_registry.register_from_search_result(payload)
        self._finish_progress("market", status=OperationStatus.COMPLETE)
        self.market_finished.emit(payload)

    def submit_gear_optimization(
        self,
        *,
        budget_amount: float,
        budget_currency: str,
        search_preset: str = "BALANCED",
        enabled_slots: tuple[str, ...],
        max_purchases: int | None = None,
        min_dps_floor: float | None = None,
        min_max_hit_floor: float | None = None,
    ) -> int | None:
        if not self._require_module(FeatureModule.GEAR_OPTIMIZER, message="Gear Optimizer is disabled in current module preset."):
            return None
        if not self.build_info.is_ready:
            self.state_message.emit("No build loaded — select a build from the tray menu.")
            return None
        self._request_id += 1
        request_id = self._request_id
        self._gear_cancelled = False
        request = GearOptimizationRequest(
            request_id=request_id,
            budget_amount=budget_amount,
            budget_currency=budget_currency,
            profile=self.settings.value_profile,
            search_preset=search_preset,
            enabled_slots=enabled_slots,
            max_purchases=max_purchases,
            min_dps_floor=min_dps_floor,
            min_max_hit_floor=min_max_hit_floor,
            baseline_generation=self._baseline_generation,
        )
        self.gear_started.emit(request_id)
        self._track_progress("gear", module="GEAR_OPTIMIZER", title="Gear Optimization", request_id=request_id)
        self._scheduler.submit(request)
        return request_id

    def cancel_gear_optimization(self) -> None:
        self._gear_cancelled = True
        self._worker.request_yield()

    @property
    def last_gear_result(self) -> dict[str, Any] | None:
        return self._last_gear_result

    def _on_gear_finished(self, request_id: int, payload: object, error: Exception | None) -> None:
        active = self._scheduler.active
        if active is not None and getattr(active, "request_id", None) == request_id:
            self._scheduler.complete(active)
        else:
            self._scheduler.complete_by_id(request_id)

        if error is not None:
            self.gear_error.emit(str(error))
            self._finish_progress("gear", status=OperationStatus.FAILED, detail=str(error))
            return
        if not isinstance(payload, dict):
            return
        if payload.get("status") == "yielded":
            if self._gear_cancelled:
                self._gear_cancelled = False
                self.gear_error.emit("Gear optimization cancelled")
                self._finish_progress("gear", status=OperationStatus.CANCELLED)
            return
        meta = payload.get("request_meta") or {}
        if meta.get("baseline_generation", self._baseline_generation) != self._baseline_generation:
            self.gear_stale.emit()
            return
        if payload.get("stale"):
            self.gear_stale.emit()
            return
        self._last_gear_result = payload
        self._finish_progress("gear", status=OperationStatus.COMPLETE)
        self.gear_finished.emit(payload)

    def _begin_eval_feedback(self, request_id: int) -> None:
        timer = self._analyzing_timers.pop(request_id, None)
        if timer:
            timer.stop()
        self.evaluation_started.emit(request_id)
        self._item_check_lifecycle.advance(request_id, ItemCheckPhase.EVAL_STARTED)
        cold = self.build_info.state in {BuildState.LOADING, BuildState.RELOADING}
        if cold:
            self._paint_warming(request_id)
        else:
            self._paint_analyzing(request_id)
            self._start_item_check_user_timeout(request_id)
        self._start_item_check_watchdog(request_id)

    def _paint_warming(self, request_id: int) -> None:
        if request_id != self._latest_request_id:
            return
        self._item_check_lifecycle.advance(request_id, ItemCheckPhase.FIRST_PAINT)
        self.evaluation_warming.emit(request_id)

    def retry_last_item_check(self) -> int | None:
        """Re-run the last captured item. No second hover or clipboard copy."""
        request = self._retry_request
        if request is None or not str(request.raw_text or "").strip():
            return None
        return self.submit_clipboard_text(
            request.raw_text,
            cursor_position=request.cursor_position,
            copy_anchor_screen_px=request.copy_anchor_screen_px,
            copy_timestamp=request.copy_timestamp,
            content_hash=request.content_hash,
        )

    def _note_successful_item_check(self) -> None:
        if not bool(getattr(self.settings, "show_hotkey_hints", True)):
            return
        if bool(getattr(self.settings, "hotkey_hints_dismissed", False)):
            return
        count = int(getattr(self.settings, "hotkey_hints_success_count", 0) or 0) + 1
        self.settings.hotkey_hints_success_count = count
        if count >= 5:
            self.settings.show_hotkey_hints = False
        save_settings(self.settings)

    def _paint_analyzing(self, request_id: int) -> None:
        if request_id != self._latest_request_id:
            return
        self._item_check_lifecycle.advance(request_id, ItemCheckPhase.FIRST_PAINT)
        self.analyzing.emit(request_id)

    def _emit_analyzing(self, request_id: int) -> None:
        """Re-show analyzing for deferred builds; respects presentation invalidation."""
        if request_id != self._latest_request_id:
            return
        if self._scheduler.active is None:
            deferred = self._deferred_evaluation
            if deferred is not None and deferred.request_id == request_id:
                if deferred.presentation_generation != self._presentation_generation:
                    return
                self._paint_analyzing(request_id)
            return
        active = self._scheduler.active
        if active.request_id != request_id:
            return
        if active.presentation_generation != self._presentation_generation:
            return
        self._paint_analyzing(request_id)

    def _start_item_check_watchdog(self, request_id: int) -> None:
        timer = self._item_check_watchdogs.pop(request_id, None)
        if timer:
            timer.stop()
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda rid=request_id: self._on_item_check_watchdog(rid))
        timer.start(ITEM_CHECK_WATCHDOG_MS)
        self._item_check_watchdogs[request_id] = timer

    def _stop_item_check_watchdog(self, request_id: int) -> None:
        timer = self._item_check_watchdogs.pop(request_id, None)
        if timer:
            timer.stop()
        self._stop_item_check_user_timeout(request_id)

    def _start_item_check_user_timeout(self, request_id: int) -> None:
        timer = self._item_check_user_timeouts.pop(request_id, None)
        if timer:
            timer.stop()
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda rid=request_id: self._on_item_check_user_timeout(rid))
        timer.start(ITEM_CHECK_USER_TIMEOUT_MS)
        self._item_check_user_timeouts[request_id] = timer

    def _stop_item_check_user_timeout(self, request_id: int) -> None:
        timer = self._item_check_user_timeouts.pop(request_id, None)
        if timer:
            timer.stop()

    def _on_item_check_user_timeout(self, request_id: int) -> None:
        if self._item_check_lifecycle.is_terminal(request_id):
            return
        if request_id != self._latest_request_id:
            return
        # Four seconds is feedback, not cancellation: the real PoB result may still
        # arrive (multi-slot items often take longer on a cold worker).
        self._item_check_lifecycle.advance(request_id, ItemCheckPhase.SLOW)
        self.evaluation_timeout.emit(request_id)

    def _on_item_check_watchdog(self, request_id: int) -> None:
        if self._item_check_lifecycle.is_terminal(request_id):
            return
        if request_id != self._latest_request_id:
            return
        track = self._item_check_lifecycle.track(request_id)
        phase = track.phase.value if track else "unknown"
        message = "Analysis timed out — PoB evaluation did not finish in time."
        self._item_check_lifecycle.advance(
            request_id,
            ItemCheckPhase.WATCHDOG,
            phase_reached=phase,
            worker_state="pending" if self._pending_request_id == request_id else "idle",
        )
        self._emit_item_check_error(request_id, message)

    def _emit_item_check_error(
        self,
        request_id: int,
        message: str,
        *,
        presentation_generation: int | None = None,
        title: str = "",
        **extra: Any,
    ) -> None:
        if request_id != self._latest_request_id:
            self._item_check_lifecycle.advance(request_id, ItemCheckPhase.SUPERSEDED, **extra)
            return
        if (
            presentation_generation is not None
            and presentation_generation != self._presentation_generation
        ):
            self._item_check_lifecycle.advance(request_id, ItemCheckPhase.SUPERSEDED, **extra)
            return
        self._stop_item_check_watchdog(request_id)
        self._item_check_lifecycle.mark_error(request_id, message, **extra)
        if title:
            self.evaluation_titled_error.emit(request_id, title, message)
        else:
            self.evaluation_error.emit(request_id, message)

    def _on_worker_finished(self, request_id: int, payload: object, error: Exception | None) -> None:
        timer = self._analyzing_timers.pop(request_id, None)
        if timer:
            timer.stop()

        active = self._scheduler.active
        finishing = None
        if active is not None and active.request_id == request_id:
            finishing = active
        elif self._scheduler.pending is not None and self._scheduler.pending.request_id == request_id:
            finishing = self._scheduler.pending
        request_gen = finishing.presentation_generation if finishing is not None else None
        is_latest = request_id == self._latest_request_id

        recovery_error: WorkerUnhealthy | None = error if isinstance(error, WorkerUnhealthy) else None
        try:
            if is_latest:
                if error is not None:
                    message = error.message if isinstance(error, EngineError) else str(error)
                    error_title = ""
                    extra_fields: dict[str, Any] = {}
                    if isinstance(error, UnsupportedGameLanguage):
                        # Typed, not string-sniffed: the UI never has to parse a message.
                        error_title = UNSUPPORTED_LANGUAGE_TITLE
                        extra_fields = {
                            "stage": "unsupported_item_language",
                            "detected_language": error.language_code or "unknown",
                            "confidence": error.confidence,
                        }
                    self._emit_item_check_error(
                        request_id,
                        message,
                        presentation_generation=request_gen,
                        title=error_title,
                        **extra_fields,
                    )
                elif payload is None:
                    self._emit_item_check_error(request_id, "Could not analyze this item.", presentation_generation=request_gen)
                else:
                    result, timing = payload
                    self._item_check_lifecycle.advance(request_id, ItemCheckPhase.EVAL_FINISHED)
                    try:
                        self._deliver_evaluation_result(request_id, result, timing, from_cache=False)
                    except Exception as exc:  # noqa: BLE001 - delivery must not strand the queue
                        logger.exception("item_check_delivery_failed request_id=%s", request_id)
                        self._emit_item_check_error(request_id, f"Could not display item analysis: {exc}")
            else:
                self._item_check_lifecycle.advance(request_id, ItemCheckPhase.SUPERSEDED)
        finally:
            if recovery_error is not None:
                for queued in self._scheduler.queued:
                    queued_id = int(getattr(queued, "request_id", 0) or 0)
                    if queued_id:
                        self._stop_item_check_watchdog(queued_id)
                        self._item_check_lifecycle.mark_error(
                            queued_id, "PoB worker restarted before this analysis could run.", stage="worker_recovery"
                        )
                        if queued_id == self._latest_request_id:
                            self.evaluation_error.emit(queued_id, "PoB worker restarted — try Item Check again.")
                self._scheduler.discard_pending()
            if finishing is not None and finishing.request_id == request_id:
                self._scheduler.complete(finishing)
            else:
                self._scheduler.complete_by_id(request_id)
            self._heartbeat_state.note_eval_finished(request_id)
            pending = self._scheduler.pending
            self._heartbeat_state.note_pending(pending.request_id if pending else None)
            if pending is None and self._scheduler.active is None:
                self._pending_request_id = None
            elif pending is not None:
                self._pending_request_id = pending.request_id
            elif self._scheduler.active is not None:
                self._pending_request_id = self._scheduler.active.request_id

        if recovery_error is not None:
            self._attempt_recovery(recovery_error)

        if not is_latest:
            return

        if (
            request_gen is not None
            and request_gen != self._presentation_generation
            and request_id != self._latest_request_id
        ):
            return

    def _deliver_evaluation_result(
        self,
        request_id: int,
        result: dict[str, Any],
        timing: EvaluationTiming,
        *,
        from_cache: bool,
    ) -> None:
        meta = result.get("request_meta") or {}
        if request_id != self._latest_request_id:
            self._item_check_lifecycle.advance(request_id, ItemCheckPhase.SUPERSEDED)
            return
        track = self._item_check_lifecycle.track(request_id)
        if track and track.phase in {ItemCheckPhase.ERROR, ItemCheckPhase.WATCHDOG}:
            return
        if not from_cache:
            active = self._scheduler.active
            active_id = getattr(active, "request_id", None) if active is not None else None
            if active_id is not None and active_id != request_id:
                return
        if meta.get("baseline_generation", self._baseline_generation) != self._baseline_generation:
            self._emit_item_check_error(request_id, "Build changed during evaluation — copy the item again.")
            return
        expected_context = self._current_evaluation_identity().token
        produced_context = str(meta.get("evaluation_context_identity") or "")
        if produced_context and produced_context != expected_context:
            self._emit_item_check_error(request_id, "Evaluation context changed — copy the item again.")
            return
        produced_candidate = str(meta.get("candidate_fingerprint") or "")
        actual_candidate = str((result.get("raw_input") or {}).get("content_hash") or "")
        if not from_cache and produced_candidate and actual_candidate and produced_candidate != actual_candidate:
            self._emit_item_check_error(request_id, "Candidate identity changed during evaluation.")
            return
        worker_revision = str(meta.get("worker_source_revision") or result.get("source_revision") or "")
        expected_revision = self._current_evaluation_identity().source_revision
        if worker_revision and expected_revision and worker_revision != expected_revision:
            self._emit_item_check_error(request_id, "Build revision changed during evaluation — copy the item again.")
            return
        if (
            meta.get("presentation_generation", self._presentation_generation) != self._presentation_generation
            and request_id != self._latest_request_id
        ):
            self._item_check_lifecycle.advance(request_id, ItemCheckPhase.SUPERSEDED)
            return

        timing.ui_updated_ms = time.perf_counter() * 1000
        self._stop_item_check_watchdog(request_id)
        identity = baseline_identity(
            fingerprint=str(((result.get("recommendation") or {}).get("baseline") or {}).get("fingerprint_hash") or ""),
            source_identity=self.build_info.source_ref.key if self.build_info.source_ref else self.build_info.path,
            loadout=self._active_loadout,
            item_set=self._active_item_set_id,
            context=self.build_info.context,
            generation=self._baseline_generation,
        )
        content_hash = str((result.get("raw_input") or {}).get("content_hash") or meta.get("content_hash") or "")
        stored_price = self._prices.get((content_hash, identity))
        if stored_price is not None:
            result = rescore_evaluation(
                result,
                profile=self.settings.value_profile,
                price=stored_price,
                build_name=self.build_info.name,
                loadout_name=self._active_loadout,
                item_set_name=self._active_item_set_name or self._active_item_set_id,
                context=self.build_info.context,
                item_check_pro=self.settings.item_check_pro,
            )
        result.setdefault("request_meta", meta)
        result["request_meta"]["loadout_name"] = self._active_loadout
        result["request_meta"]["item_set_name"] = self._active_item_set_name or self._active_item_set_id
        result["request_meta"]["build_name"] = self.build_info.name
        result["request_meta"]["context"] = self.build_info.context
        result["request_meta"]["cache_hit"] = bool(from_cache or meta.get("cache_hit"))
        result["request_meta"]["evaluation_context_identity"] = expected_context
        result["request_meta"]["candidate_fingerprint"] = content_hash
        result["evaluation_context"] = self._current_evaluation_identity().to_dict()
        slots = tuple(sorted(
            str(row.get("pob_slot"))
            for row in result.get("compatible_slots") or []
            if row.get("pob_slot")
        ))
        result["evaluation_identity"] = EvaluationIdentity(
            context_identity=expected_context,
            candidate_fingerprint=content_hash,
            slot_context=slots,
        ).to_dict()
        if not from_cache:
            self._store_evaluation_cache(content_hash, result)
        self._last_timing = timing
        rec = result.get("recommendation") or {}
        fp = str(((rec.get("baseline") or {}).get("fingerprint_hash")) or "")
        if fp:
            self._equipment_fingerprint = fp
        pro = self.item_check_settings()
        result = self._apply_optional_presentation_enrichment(result, pro, request_id=request_id)
        self._last_result = result
        slot = str(((result.get("recommendation") or {}).get("pob_slot")) or "")
        self._item_check_lifecycle.advance(request_id, ItemCheckPhase.PRESENTATION_BUILT, slot=slot)
        self.evaluation_finished.emit(request_id, result)
        # PERF-01: user-visible result first, persistence second. Recording history is
        # a JSON serialise plus a full-file write on the UI thread (~0.6 ms p50, 2-3 ms
        # p95); it used to run before the paint. Both recorders read only fields the
        # overlay never touches (content hash, display name, verdict, best slot,
        # upgrade-path hint), so the stored content and ordering are unchanged.
        # Exceptions are deliberately not swallowed here: the caller still turns a
        # failure into a terminal item-check error, it just no longer costs the paint.
        if pro.history_enabled:
            self._history.record(result, identity=identity, current=True)
        if self._loot_review.active and pro.loot_review_enabled:
            self._loot_review.record(result, baseline_identity=identity)
        self._pob_warm = True
        self._note_successful_item_check()
        self._item_check_lifecycle.advance(request_id, ItemCheckPhase.TERMINAL_PAINT, slot=slot)
        self._maybe_schedule_upgrade_path(request_id, result, pro)
        self._maybe_schedule_build_decomp(request_id, result)
        if self._analysis_resume is not None and self._scheduler.active is None:
            resume = self._analysis_resume
            if resume.baseline_generation == self._baseline_generation:
                self._scheduler.submit(resume)

    def set_value_profile(self, profile: str) -> dict[str, Any] | None:
        self.settings.value_profile = profile
        self._configure_worker()
        self.tree_view_model.rescore_profile(profile)
        if self._last_analysis and self._analysis_generation == self._baseline_generation:
            if self._last_analysis.get("kind") == "tree":
                from poe2value.tree.ranking import rescore_tree_results

                self._last_analysis = rescore_tree_results(self._last_analysis, profile)
            else:
                self._last_analysis = rescore_analysis(self._last_analysis, profile)
            self.analysis_finished.emit(self._last_analysis)
        if not self._last_result:
            return None
        content_hash = str((self._last_result.get("raw_input") or {}).get("content_hash") or "")
        price = self._prices.get((content_hash, self._baseline_identity()))
        if price is None and self._last_result.get("manual_price"):
            try:
                stored = self._last_result["manual_price"]
                price = parse_manual_price(stored.get("amount"), stored.get("currency"))
            except (ManualPriceError, TypeError, ValueError):
                price = None
        rescored = rescore_evaluation(
            self._last_result,
            profile=profile,
            price=price,
            build_name=self.build_info.name,
            loadout_name=self._active_loadout,
            item_set_name=self._active_item_set_name or self._active_item_set_id,
            context=self.build_info.context,
            item_check_pro=self.settings.item_check_pro,
        )
        if self._last_result.get("request_meta"):
            rescored["request_meta"] = self._last_result["request_meta"]
        self._last_result = rescored
        self.last_result_rescored.emit(rescored)
        return rescored

    def select_value_profile(self, profile: str) -> dict[str, Any] | None:
        from poe2value.items.value_profiles import ValueProfile

        try:
            selected = ValueProfile(str(profile)).value
        except ValueError:
            return None
        self.settings.value_profile = selected
        save_settings(self.settings)
        result = self.set_value_profile(selected)
        self.value_profile_changed.emit(selected)
        return result

    def apply_manual_price(self, amount: float, currency: str) -> dict[str, Any]:
        if not self._last_result:
            raise ManualPriceError("no last item to price")
        price = parse_manual_price(amount, currency)
        content_hash = str((self._last_result.get("raw_input") or {}).get("content_hash") or "")
        identity = self._baseline_identity()
        self._prices[(content_hash, identity)] = price
        rescored = rescore_evaluation(
            self._last_result,
            profile=self.settings.value_profile,
            price=price,
            build_name=self.build_info.name,
            loadout_name=self._active_loadout,
            item_set_name=self._active_item_set_name or self._active_item_set_id,
            context=self.build_info.context,
            item_check_pro=self.settings.item_check_pro,
        )
        if self._last_result.get("request_meta"):
            rescored["request_meta"] = self._last_result["request_meta"]
        self._last_result = rescored
        self.last_result_rescored.emit(rescored)
        return rescored

    def pin_last_result(self) -> dict[str, Any] | None:
        if not self._last_result:
            return None
        entry = self._pin_compare.pin(
            str((self._last_result.get("raw_input") or {}).get("content_hash") or "item"),
            self._last_result,
            baseline_identity=self._baseline_identity(),
        )
        if entry is None:
            return None
        self._sync_compare_summary()
        self._spawn_pinned_overlay(entry)
        self.pin_compare_changed.emit()
        return entry.to_dict()

    def unpin_entry(self, entry_id: str) -> None:
        self._close_pinned_window(entry_id)
        self._pin_compare.unpin(entry_id)
        self.settings.pinned_overlays.pop(str(entry_id), None)
        from poe2value.app.settings import save_settings

        save_settings(self.settings)
        self._sync_compare_summary()
        self.pin_compare_changed.emit()

    def can_pin_more(self) -> bool:
        return self._pin_compare.can_pin_more()

    def pin_from_overlay(self) -> bool:
        entry_dict = self.pin_last_result()
        return entry_dict is not None

    def _spawn_pinned_overlay(self, entry) -> None:
        from poe2value.ui.pinned_item_overlay import PinnedItemOverlay

        existing = self._pinned_windows.get(entry.entry_id)
        if existing is not None:
            existing.update_result(
                entry.result,
                stale_reason=entry.stale_reason if entry.stale else "",
            )
            existing.show()
            existing.raise_()
            return
        window = PinnedItemOverlay(
            self.settings,
            entry_id=entry.entry_id,
            pin_label=entry.pin_label,
            result=entry.result,
            on_unpin=self._pinned_window_requested_unpin,
        )
        saved = self.settings.pinned_overlays.get(str(entry.entry_id))
        if saved:
            window.restore_saved_geometry(saved)
        else:
            anchor = self._last_copy_anchor_physical
            if anchor:
                from poe2value.ui.overlay_positioning import compute_overlay_placement

                placement = compute_overlay_placement(
                    window.width(),
                    window.height(),
                    copy_anchor_physical=anchor,
                    offset_px=int(self.settings.overlay_near_offset_px) + 48,
                    last_valid_anchor_physical=anchor,
                )
                window.move(placement.logical_pos)
            window.show()
        self._pinned_windows[entry.entry_id] = window
        window.show()
        window.raise_()

    def _pinned_window_requested_unpin(self, entry_id: str) -> None:
        self._pinned_windows.pop(entry_id, None)
        self._pin_compare.unpin(entry_id)
        self.settings.pinned_overlays.pop(str(entry_id), None)
        from poe2value.app.settings import save_settings

        save_settings(self.settings)
        self._sync_compare_summary()
        self.pin_compare_changed.emit()

    def _close_pinned_window(self, entry_id: str) -> None:
        window = self._pinned_windows.pop(entry_id, None)
        if window is None:
            return
        window._on_unpin = None
        window.hide()
        window.deleteLater()

    def _refresh_pinned_overlay_stale(self, reason: str) -> None:
        for entry in self._pin_compare.entries:
            if entry.pinned and not entry.is_current and entry.stale:
                window = self._pinned_windows.get(entry.entry_id)
                if window is not None:
                    window.set_stale(reason)
        self.pin_compare_changed.emit()

    def _persist_build_settings(self, path: str, context: str) -> None:
        from poe2value.app.settings import save_settings

        changed = False
        if self.settings.build_path != path:
            self.settings.build_path = path
            changed = True
        if self.settings.context != context:
            self.settings.context = context
            changed = True
        if changed:
            save_settings(self.settings)

    def compare_entries(self) -> list[dict[str, Any]]:
        return self._pin_compare.compare_table(profile=self.settings.value_profile)

    def _sync_compare_summary(self) -> dict[str, Any]:
        summary = build_compare_summary(self._pin_compare, profile=self.settings.value_profile)
        if self._last_result:
            self._last_result["compare_summary"] = summary
        for entry in self._pin_compare.entries:
            if entry.is_current:
                continue
            entry.result["compare_summary"] = summary
            window = self._pinned_windows.get(entry.entry_id)
            if window is not None:
                window.update_result(
                    entry.result,
                    stale_reason=entry.stale_reason if entry.stale else "",
                )
        return summary

    def refresh_pinned_results(self, result: dict[str, Any]) -> None:
        """Pinned snapshots stay frozen. New analyses only refresh compare chrome."""
        self._sync_compare_summary()

    def _attach_market_context(self, result: dict[str, Any]) -> dict[str, Any]:
        from poe2value.market_assist.price_parser import parse_price_note

        raw = str((result.get("raw_input") or {}).get("text") or (result.get("raw_input") or {}).get("raw_text") or "")
        parsed = parse_price_note(raw)
        session = self._market_capture_store.active_session
        ctx: dict[str, Any] = {
            "active_session": session is not None,
            "parsed_price": parsed.to_dict() if parsed.supported else None,
        }
        if session is not None and parsed.supported:
            obs_id = str(
                result.get("market_observation_id")
                or (result.get("request_meta") or {}).get("market_observation_id")
                or ""
            )
            observations = list(session.observations)
            rank = next(
                (idx + 1 for idx, obs in enumerate(observations) if obs.observation_id == obs_id),
                None,
            )
            ctx["session_rank"] = rank
            ctx["session_total"] = len(observations)
            ctx["is_best_value"] = bool(obs_id and session.best_observation_id == obs_id)
            ctx["is_new_best"] = bool(obs_id and obs_id == self._market_capture_new_best_id)
        merged = dict(result)
        merged["market_context"] = ctx
        return merged

    def _patch_presentation_price(self, result: dict[str, Any]) -> dict[str, Any]:
        from poe2value.items.presentation import _build_price_block

        presentation = dict(result.get("presentation") or {})
        power = (result.get("recommendation") or {}).get("power_per_currency") or result.get("power_per_currency")
        price_block = _build_price_block(
            result,
            power=power,
            value_profile=str(result.get("value_profile") or self.settings.value_profile),
        )
        if price_block:
            presentation["price"] = price_block
        merged = dict(result)
        merged["presentation"] = presentation
        return merged

    def history_result(self, entry_id: str) -> dict[str, Any] | None:
        for entry in self.history_entries:
            if entry.get("id") == entry_id:
                return entry.get("result")
        return None

    def is_entry_pinned(self, content_hash: str) -> bool:
        for row in self.compare_entries():
            if row.get("content_hash") == content_hash and row.get("pinned"):
                return True
        return False

    def pin_history_entry(self, entry_id: str) -> dict[str, Any] | None:
        result = self.history_result(entry_id)
        if not result:
            return None
        entry = self._pin_compare.pin(
            str(entry_id),
            result,
            baseline_identity=self._baseline_identity(),
        )
        if entry is None:
            return None
        self._sync_compare_summary()
        self._spawn_pinned_overlay(entry)
        self.pin_compare_changed.emit()
        return entry.to_dict()

    def unpin_history_entry(self, entry_id: str) -> None:
        self.unpin_entry(str(entry_id))

    def activate_history_entry(self, entry_id: str) -> dict[str, Any] | None:
        result = self.history_result(entry_id)
        if result:
            self._last_result = result
        return result

    def build_item_summary(self, result: dict[str, Any]) -> str:
        presentation = result.get("presentation") or {}
        pob = result.get("pob_parse") or {}
        rec = result.get("recommendation") or {}
        lines = [
            str(presentation.get("item_name") or pob.get("display_name") or "Item"),
            f"Verdict: {presentation.get('verdict_label') or rec.get('verdict') or '—'}",
            f"Best slot: {(result.get('best_slot') or {}).get('label') or '—'}",
            f"Decision: {(result.get('decision') or {}).get('headline') or '—'}",
        ]
        upgrade = result.get("upgrade_path") or presentation.get("upgrade_path") or {}
        if upgrade.get("summary"):
            lines.append(f"Upgrade path: {upgrade.get('summary')}")
        return "\n".join(lines)

    def start_loot_review(self) -> None:
        self.update_item_check_settings(loot_review_enabled=True)
        self._loot_review.start(baseline_identity=self._baseline_identity())

    def stop_loot_review(self) -> None:
        self._loot_review.stop()
        self.update_item_check_settings(loot_review_enabled=False)

    def loot_review_entries(self) -> list[dict[str, Any]]:
        return [entry.to_dict() for entry in self._loot_review.ranked()]

    def loot_review_by_category(self) -> dict[str, list[dict[str, Any]]]:
        return {key: [entry.to_dict() for entry in values] for key, values in self._loot_review.by_category().items()}

    def run_upgrade_potential(self) -> dict[str, Any] | None:
        if not self._last_result or not self._engine:
            return None
        if self._potential_analyzer is None:
            self._potential_analyzer = UpgradePotentialAnalyzer(self._engine)
        recommendation = self._last_result.get("recommendation") or {}
        slot = str(recommendation.get("pob_slot") or "")
        raw_text = str((self._last_result.get("raw_input") or {}).get("raw_text") or "")
        if not slot or not raw_text:
            return None
        pro = self.item_check_settings()
        op = self.progress_hub.begin(module="ITEM_CHECK", title="Upgrade path", cancellable=True)
        try:
            result = self._potential_analyzer.analyze(
                slot=slot,
                item_raw=raw_text,
                result=self._last_result,
                profile=self.settings.value_profile,
                style=pro.recommendation_style,
                deep=True,
                on_progress=lambda payload: self.progress_hub.update_from_payload(
                    op.operation_id,
                    payload,
                    module="ITEM_CHECK",
                    title="Upgrade path",
                ),
            )
            payload = result.to_dict()
            self._apply_upgrade_potential(self._last_result, payload, pro=pro)
            self.progress_hub.finish(op.operation_id)
            return payload
        except Exception as exc:
            self.progress_hub.fail(op.operation_id, detail=str(exc))
            return None

    def _cancel_upgrade_path_work(self) -> None:
        if self._potential_analyzer is not None:
            self._potential_analyzer.cancel()
        dropped = self._scheduler.discard_queued_upgrade_path()
        if dropped:
            self._upgrade_path_jobs.clear()
        self._active_upgrade_parent_id = None

    def _ensure_potential_analyzer(self) -> UpgradePotentialAnalyzer | None:
        if not self._engine:
            return None
        if self._potential_analyzer is None:
            self._potential_analyzer = UpgradePotentialAnalyzer(self._engine, cache=self._upgrade_path_cache)
        return self._potential_analyzer

    def _apply_optional_presentation_enrichment(
        self,
        result: dict[str, Any],
        pro: ItemCheckProSettings,
        *,
        request_id: int,
    ) -> dict[str, Any]:
        """Optional upgrade-path/market/price layers must never block TIER-1 tooltip delivery."""
        enriched = dict(result)
        for step, fn in (
            ("upgrade_path", lambda payload: self._prime_upgrade_path(payload, pro)),
            ("market_context", self._attach_market_context),
            ("manual_price", self._patch_presentation_price),
        ):
            try:
                enriched = fn(enriched)
            except Exception:  # noqa: BLE001 - optional enrichment only
                logger.exception(
                    "item_check optional enrichment failed request_id=%s step=%s",
                    request_id,
                    step,
                )
        return enriched

    def _prime_upgrade_path(self, result: dict[str, Any], pro: ItemCheckProSettings) -> dict[str, Any]:
        if not pro.upgrade_path_enabled():
            return result
        analyzer = self._ensure_potential_analyzer()
        if analyzer is None:
            return result
        recommendation = result.get("recommendation") or {}
        slot = str(recommendation.get("pob_slot") or "")
        raw_text = str((result.get("raw_input") or {}).get("raw_text") or "")
        if not slot or not raw_text:
            return result
        immediate = analyzer.build_immediate(
            slot=slot,
            result=result,
            profile=self.settings.value_profile,
            style=pro.recommendation_style,
            pending=False,
        )
        needs_probe = analyzer.should_auto_run(
            result,
            mode=pro.upgrade_potential,
            deep=pro.upgrade_path_deep(),
            style=pro.recommendation_style,
            market_capture_active=self.market_capture_active,
            loot_review_active=self._loot_review.active and pro.loot_review_enabled,
        )
        if immediate.status == "COMPLETE":
            result = dict(result)
            result["upgrade_potential"] = immediate.to_dict()
        elif needs_probe:
            pending = immediate.__dict__.copy()
            pending["status"] = "PENDING"
            result = dict(result)
            result["upgrade_potential"] = pending
        return attach_upgrade_path_presentation(
            result,
            pending=needs_probe and immediate.status != "COMPLETE",
            style=pro.recommendation_style,
        )

    def _apply_upgrade_potential(
        self,
        result: dict[str, Any],
        payload: dict[str, Any],
        *,
        pro: ItemCheckProSettings | None = None,
    ) -> dict[str, Any]:
        pro = pro or self.item_check_settings()
        merged = dict(result)
        merged["upgrade_potential"] = payload
        return attach_upgrade_path_presentation(merged, pending=False, style=pro.recommendation_style)

    def _maybe_schedule_upgrade_path(self, request_id: int, result: dict[str, Any], pro: ItemCheckProSettings) -> None:
        if not pro.upgrade_path_enabled() or not self._engine:
            return
        analyzer = self._ensure_potential_analyzer()
        if analyzer is None:
            return
        if not analyzer.should_auto_run(
            result,
            mode=pro.upgrade_potential,
            deep=pro.upgrade_path_deep(),
            style=pro.recommendation_style,
            market_capture_active=self.market_capture_active,
            loot_review_active=self._loot_review.active and pro.loot_review_enabled,
        ):
            return
        recommendation = result.get("recommendation") or {}
        slot = str(recommendation.get("pob_slot") or "")
        raw_text = str((result.get("raw_input") or {}).get("raw_text") or "")
        if not slot or not raw_text:
            return
        meta = result.get("request_meta") or {}
        self._request_id += 1
        upgrade_request = UpgradePathRequest(
            request_id=self._request_id,
            parent_request_id=request_id,
            content_hash=str((result.get("raw_input") or {}).get("content_hash") or meta.get("content_hash") or ""),
            item_raw=raw_text,
            slot=slot,
            result_snapshot=result,
            baseline_generation=self._baseline_generation,
            presentation_generation=int(meta.get("presentation_generation") or self._presentation_generation),
            profile=self.settings.value_profile,
            style=pro.recommendation_style,
            deep=pro.upgrade_path_deep(),
        )
        self._upgrade_path_jobs[upgrade_request.request_id] = upgrade_request
        self._active_upgrade_parent_id = request_id
        self._scheduler.submit(upgrade_request)


    def _sync_pending_request_id(self) -> None:
        pending = self._scheduler.pending
        if pending is None and self._scheduler.active is None:
            self._pending_request_id = None
        elif pending is not None:
            self._pending_request_id = pending.request_id
        elif self._scheduler.active is not None:
            self._pending_request_id = self._scheduler.active.request_id

    def _on_upgrade_path_finished(self, request_id: int, payload: object, error: Exception | None) -> None:
        self._scheduler.complete_by_id(request_id)
        self._upgrade_path_jobs.pop(request_id, None)
        self._sync_pending_request_id()
        if error is not None or payload is None:
            return
        if not isinstance(payload, dict):
            return
        parent_id = int(payload.get("parent_request_id") or 0)
        if parent_id != self._active_upgrade_parent_id:
            return
        presentation_generation = int(payload.get("presentation_generation") or 0)
        if presentation_generation != self._presentation_generation:
            return
        if payload.get("baseline_generation", self._baseline_generation) != self._baseline_generation:
            return
        if not self._last_result:
            return
        last_hash = str((self._last_result.get("raw_input") or {}).get("content_hash") or "")
        if last_hash and last_hash != str(payload.get("content_hash") or ""):
            return
        pro = self.item_check_settings()
        updated = self._apply_upgrade_potential(self._last_result, payload.get("upgrade_potential") or {}, pro=pro)
        updated["request_meta"] = dict(self._last_result.get("request_meta") or {})
        self._last_result = updated
        identity = baseline_identity(
            fingerprint=str(((updated.get("recommendation") or {}).get("baseline") or {}).get("fingerprint_hash") or ""),
            source_identity=self.build_info.source_ref.key if self.build_info.source_ref else self.build_info.path,
            loadout=self._active_loadout,
            item_set=self._active_item_set_id,
            context=self.build_info.context,
            generation=self._baseline_generation,
        )
        if pro.history_enabled:
            self._history.record(updated, identity=identity, current=True)
        self.refresh_pinned_results(updated)
        self.upgrade_path_updated.emit(parent_id, updated)
        if self._scheduler.active is None and self._analysis_resume is not None:
            resume = self._analysis_resume
            if resume.baseline_generation == self._baseline_generation:
                self._scheduler.submit(resume)

    def _maybe_schedule_build_decomp(self, request_id: int, result: dict[str, Any]) -> None:
        if not self._engine:
            return
        intel = result.get("build_comparison") or {}
        if str(intel.get("decomposition_status") or "") not in {"PENDING", ""}:
            return
        recommendation = result.get("recommendation") or {}
        slot = str(recommendation.get("pob_slot") or "")
        raw_text = str((result.get("raw_input") or {}).get("raw_text") or "")
        if not slot or not raw_text:
            return
        mods = intel.get("mods") or []
        if not mods:
            return
        meta = result.get("request_meta") or {}
        self._request_id += 1
        decomp_request = BuildDecompRequest(
            request_id=self._request_id,
            parent_request_id=request_id,
            content_hash=str((result.get("raw_input") or {}).get("content_hash") or meta.get("content_hash") or ""),
            item_raw=raw_text,
            slot=slot,
            result_snapshot=result,
            baseline_generation=self._baseline_generation,
            presentation_generation=int(meta.get("presentation_generation") or self._presentation_generation),
            profile=self.settings.value_profile,
        )
        self._scheduler.submit(decomp_request)

    def _on_build_decomp_finished(self, request_id: int, payload: object, error: Exception | None) -> None:
        self._scheduler.complete_by_id(request_id)
        self._sync_pending_request_id()
        if error is not None or payload is None or not isinstance(payload, dict):
            return
        if payload.get("baseline_generation", self._baseline_generation) != self._baseline_generation:
            return
        presentation_generation = int(payload.get("presentation_generation") or 0)
        if presentation_generation != self._presentation_generation:
            return
        if not self._last_result:
            return
        last_hash = str((self._last_result.get("raw_input") or {}).get("content_hash") or "")
        if last_hash and last_hash != str(payload.get("content_hash") or ""):
            return
        updated = attach_decomposition(self._last_result, payload.get("decomposition") or {})
        pro = self.item_check_settings()
        try:
            updated = attach_upgrade_path_presentation(
                updated,
                pending=bool((updated.get("upgrade_potential") or {}).get("status") == "PENDING"),
                style=pro.recommendation_style,
            )
        except Exception:  # noqa: BLE001 - TIER-2 enrichment must not discard TIER-1
            logger.exception("build_decomp upgrade-path presentation enrichment failed")
        from poe2value.items.intelligence import enrich_fast_result

        updated = enrich_fast_result(
            updated,
            recommendation_style=pro.recommendation_style,
            popup_density=pro.popup_density,
            multi_profile_enabled=pro.multi_profile,
            decision_enabled=pro.decision_intelligence,
            best_slot_enabled=pro.best_replacement_slot,
            build_name=self.build_info.name,
            loadout_name=self._active_loadout,
            item_set_name=self._active_item_set_name or self._active_item_set_id,
            context=self.build_info.context,
        )
        updated["request_meta"] = dict(self._last_result.get("request_meta") or {})
        self._last_result = updated
        parent_id = int(payload.get("parent_request_id") or 0)
        self.refresh_pinned_results(updated)
        self.upgrade_path_updated.emit(parent_id, updated)

    def _schedule_potential_analysis(self, result: dict[str, Any]) -> None:
        """Legacy sync hook — prefer scheduler-backed upgrade path."""
        pro = self.item_check_settings()
        request_id = int((result.get("request_meta") or {}).get("request_id") or self._latest_request_id)
        self._maybe_schedule_upgrade_path(request_id, result, pro)
        self._maybe_schedule_build_decomp(request_id, result)

    @property
    def history_entries(self) -> list[dict[str, Any]]:
        return self._history.entries()

    def _on_heartbeat(self) -> None:
        self._heartbeat_state.touch_gui()
        stall = self._heartbeat_state.detect_stall()
        self.heartbeat_updated.emit(self._heartbeat_state)
        if stall != StallKind.NONE and stall == StallKind.POB:
            # Clear analyzing overlay if PoB appears wedged but queue drained.
            if self._scheduler.active is None:
                self._pending_request_id = None

    def _attempt_recovery(self, error: Exception) -> None:
        if self._recovery_attempted:
            self.build_info = BuildInfo(
                path=self.build_info.path,
                name=self.build_info.name,
                context=self.build_info.context,
                state=BuildState.ERROR,
                error_message=str(error),
            )
            self.build_changed.emit(self.build_info)
            self.evaluation_error.emit(self._latest_request_id, "Worker unhealthy — reload build from tray.")
            return
        self._recovery_attempted = True
        try:
            self.shutdown_engine()
            self.start_engine()
            if self.build_info.path:
                self.load_build(self.build_info.path, context=self.build_info.context)
        except Exception as exc:
            self.build_info = BuildInfo(
                path=self.build_info.path,
                state=BuildState.ERROR,
                error_message=str(exc),
            )
            self.build_changed.emit(self.build_info)

    def shutdown(self) -> None:
        self._shutting_down = True
        self.item_dismiss.stop()
        self.price_check_capture.shutdown()
        self.price_check_hotkey.stop()
        for entry_id in list(self._pinned_windows):
            self._close_pinned_window(entry_id)
        self._heartbeat_timer.stop()
        self._thread.quit()
        self._thread.wait(5000)
        if self._tracked_loader is not None:
            self._tracked_loader.shutdown()
            self._tracked_loader = None
        self.shutdown_engine()

    def diagnostic_report(self) -> str:
        from poe2value.app.diagnostics import render_global_diagnostics

        return render_global_diagnostics(self)

    # --- MARKET-ASSIST-01 ---

    @property
    def market_capture_active(self) -> bool:
        return self._market_capture_store.active_session is not None

    def market_assist_runtime_settings(self) -> MarketAssistantRuntimeSettings:
        return MarketAssistantRuntimeSettings.from_dict(self.settings.market_assist)

    def market_assist_suppress_popup(self) -> bool:
        if not self.market_capture_active:
            return False
        return self.market_assist_runtime_settings().suppress_item_popup

    def market_capture_snapshot(self) -> dict[str, Any] | None:
        return self._market_capture_store.snapshot()

    def start_market_capture_session(
        self,
        *,
        slot: str,
        budget_amount: float | None = None,
        budget_currency: str | None = None,
    ) -> tuple[bool, str]:
        if not self._require_module(FeatureModule.MARKET_ASSISTANT, message="Market Assistant is disabled."):
            return False, "Market Assistant module is disabled."
        if not self.build_info.is_ready:
            return False, "No build loaded — select a build from the tray menu."
        build_path = self.build_info.path
        if not build_path:
            return False, "No build path."
        revision = read_build_revision(build_path)
        if revision is None:
            return False, "UX-01A: cannot read build revision — reload build first."

        budget = None
        if budget_amount is not None and budget_currency:
            budget = ListingPrice(amount=float(budget_amount), currency=str(budget_currency))

        session = self._market_capture_store.start_session(
            target_slot=slot,
            profile=self.settings.value_profile,
            baseline_generation=self._baseline_generation,
            baseline_fingerprint=self.baseline_state.fingerprint or self._equipment_fingerprint,
            build_path=build_path,
            budget=budget,
            search_intent=self.search_intent_for_slot(slot),
        )
        session.metadata.update(self.market_assist_runtime_settings().session_defaults())
        self._market_capture_new_best_id = None
        self.market_capture_session_changed.emit(session.to_dict())
        self.market_capture_updated.emit(session.to_dict())
        self._drain_market_capture_queue()
        return True, f"Capture session started for {slot}."

    def stop_market_capture_session(self, *, finalize: bool = True) -> dict[str, Any] | None:
        session = self._market_capture_store.stop_session()
        if session is None:
            return None
        payload = None
        if finalize:
            pool = finalize_session_to_pool(session)
            payload = pool_to_handoff_payload(pool, session)
            payload["baseline_fingerprint"] = session.baseline_fingerprint
            payload["baseline_generation"] = session.baseline_generation
            self.pool_registry.register_from_search_result(payload)
        self.market_capture_session_changed.emit(session.to_dict())
        self.market_capture_updated.emit(session.to_dict())
        return payload

    def try_market_capture_clipboard(
        self,
        text: str,
        *,
        content_hash: str | None = None,
        clipboard_sequence: int | None = None,
    ) -> tuple[bool, str]:
        if not is_enabled(FeatureModule.MARKET_ASSISTANT):
            return False, ""
        if not self.market_capture_active:
            return False, ""
        self._market_capture_store.check_baseline_frozen(
            baseline_generation=self._baseline_generation,
            baseline_fingerprint=self.baseline_state.fingerprint or self._equipment_fingerprint,
            build_path=self.build_info.path or "",
        )
        if not self.market_capture_active:
            return True, "SESSION ENDED — BUILD CHANGED"

        from poe2value.items.cache import ItemPipelineCache
        from poe2value.items.pob_parse import PobParseResult
        from poe2value.items.raw_input import RawItemInput
        from poe2value.items.recognition import recognize_input
        from poe2value.items.slots import pob_slot_to_product

        raw = RawItemInput.from_text(text, content_hash=content_hash)
        recognition = recognize_input(raw)
        if not recognition.recognized:
            return False, ""

        if is_duplicate_clipboard_event(self._last_clipboard_sequence, clipboard_sequence):
            return True, "duplicate sequence"
        if clipboard_sequence is not None:
            self._last_clipboard_sequence = clipboard_sequence

        compatible: set[str] = set()
        try:
            if self._engine is not None:
                pob_result = self._engine.parse_item(text)
                pob_parse = PobParseResult.from_engine(pob_result, raw.metadata)
                for pob_slot in pob_parse.compatible_slots:
                    compatible.add(pob_slot_to_product(pob_slot, item_type=pob_parse.item.get("type")).value)
        except Exception:
            compatible = set()

        observation, message = self._market_capture_store.capture_clipboard(
            text,
            content_hash=raw.content_hash,
            compatible_product_slots=compatible or None,
        )
        session = self._market_capture_store.active_session
        if session is not None:
            self.market_capture_updated.emit(session.to_dict())
        if observation is not None and observation.slot_match and observation.queue_state.value in {"QUEUED", "CAPTURED"}:
            self._drain_market_capture_queue()
        return True, message

    def _drain_market_capture_queue(self) -> None:
        session = self._market_capture_store.active_session
        if session is None:
            return
        for row in self._market_capture_store.pending_observations():
            self._request_id += 1
            request_id = self._request_id
            price = row.price
            request = MarketCaptureEvalRequest(
                request_id=request_id,
                observation_id=row.observation_id,
                item_raw=row.item_raw,
                product_slot=session.target_slot,
                pob_slot=session.pob_slot,
                price_amount=price.amount if price else None,
                price_currency=price.currency if price else None,
                baseline_generation=self._baseline_generation,
            )
            self._market_capture_store.mark_evaluating(row.observation_id, request_id)
            self._scheduler.submit(request)
            active_kind = str(getattr(self._scheduler.active, "kind", "gameplay"))
            if active_kind not in {"gameplay", "baseline", "market_capture"}:
                self._worker.request_yield()

    def _on_market_capture_finished(self, request_id: int, payload: object, error: Exception | None) -> None:
        active = self._scheduler.active
        if active is not None and getattr(active, "request_id", None) == request_id:
            self._scheduler.complete(active)
        else:
            self._scheduler.complete_by_id(request_id)

        if error is not None:
            self.state_message.emit(f"Market capture eval failed: {error}")
            self._drain_market_capture_queue()
            return
        if not isinstance(payload, dict):
            self._drain_market_capture_queue()
            return

        observation_id = str(payload.get("observation_id") or "")
        evaluation = payload.get("evaluation") or {}
        prior_best = self._market_capture_new_best_id
        self._market_capture_store.apply_evaluation(observation_id, evaluation)
        session = self._market_capture_store.active_session
        if session is not None:
            if session.best_observation_id and session.best_observation_id != prior_best:
                self._market_capture_new_best_id = session.best_observation_id
                self.market_capture_new_best.emit()
            self.market_capture_updated.emit(session.to_dict())
        self._drain_market_capture_queue()

    def market_capture_next_search_clipboard(self) -> str:
        session = self._market_capture_store.active_session
        if session is None:
            return ""
        return self._market_capture_guidance.clipboard_hint(session.guidance)

    def analyze_market_ideal_target(self) -> None:
        session = self._market_capture_store.active_session
        if session is None or not self._engine or not self.build_info.path:
            return
        self._track_progress("market_capture_ideal", module="MARKET_ASSISTANT", title="Ideal Target", request_id=0)

        def run() -> None:
            result = self._market_capture_ideal.analyze(
                self._engine,
                session,
                build_path=self.build_info.path,
                context=self.build_info.context,
                profile=self.settings.value_profile,
                on_progress=lambda payload: self._emit_progress(
                    "market_capture_ideal",
                    payload,
                    module="MARKET_ASSISTANT",
                    title="Ideal Target",
                ),
            )
            session.metadata["ideal_target"] = result.to_dict()
            self._finish_progress("market_capture_ideal", status=OperationStatus.COMPLETE)
            self.market_capture_updated.emit(session.to_dict())

        QTimer.singleShot(0, run)

    def handoff_market_capture_to_gear(self) -> bool:
        history = self._market_capture_store.history
        if not history:
            return False
        session = history[-1]
        pool = finalize_session_to_pool(session)
        payload = pool_to_handoff_payload(pool, session)
        payload["baseline_fingerprint"] = session.baseline_fingerprint
        payload["baseline_generation"] = session.baseline_generation
        self.pool_registry.register_from_search_result(payload)
        return True
