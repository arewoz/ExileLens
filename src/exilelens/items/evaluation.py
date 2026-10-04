from __future__ import annotations

import copy
import logging
import time
from dataclasses import dataclass, field, replace
from typing import Any

from exilelens.errors import (
    BaselineItemUnresolved,
    EngineError,
    EvaluationInvalidBuildState,
    ItemUnsupported,
    NoCompatibleSlot,
    NotPoe2Item,
    RestoreFailed,
    SlotInvalid,
    SlotResolutionFailed,
    UnsupportedGameLanguage,
)
from exilelens.baseline import display_item_set_name
from exilelens.items.baseline_item import resolve_baseline_item, resolve_candidate_item, unmodeled_item_transform
from exilelens.items.cache import ItemPipelineCache
from exilelens.items.comparison_trace import build_comparison_trace
from exilelens.items.evaluation_outcome import failed_outcome
from exilelens.items.equipability import build_equipability
from exilelens.items.pob_parse import PobParseResult
from exilelens.items.intelligence import enrich_fast_result
from exilelens.items.language_detect import detect_poe_item_language, unsupported_language_body
from exilelens.items.native_metric_discovery import (
    MAX_REPORT_GROUPS,
    candidate_keys,
    compare_native_components,
    select_baseline_components,
    should_discover_components,
)
from exilelens.items.ailment_intel import ailment_breakdown
from exilelens.items.main_skill_diagnostics import build_main_skill_diagnostic, selected_skill_has_no_offense
from exilelens.items.primary_metric import DamageOwner, DamageQuantity, MetricScope, resolve_primary_metric
from exilelens.items.offense_coverage import OffenseCoverageAuditor, infer_offense_coverage
from exilelens.items.ranking import rank_slot_comparisons
from exilelens.items.raw_input import ItemInputSource, RawItemInput
from exilelens.items.recognition import ItemClassification
from exilelens.items.slots import ProductSlot, WEAPON_TYPES, pob_slot_to_product
from exilelens.items.socket_normalize import strip_socketed_modifiers
from exilelens.items.stonefist_integration import (
    TransformResult,
    effective_item,
    equipped_gloves_transform,
    safe_transform,
    stonefist_applies,
    transform_report,
    unresolved_reasons,
)
from exilelens.items.value_layer import parse_profile

logger = logging.getLogger(__name__)


def weapon_layout_refusal_message(reason: str | None) -> str:
    """What the player reads (the engine message is shown as-is) when PoB says the item cannot be worn with the build's weapons.

    The bridge reasons are developer wording ("off-hand item is not compatible with the current weapon layout"). The refusal is
    correct (PoB's own IsItemValidForSlot decides, and ExileLens does not evaluate the two-step change of also swapping the weapon);
    the message says what it means and what to do. The reason may be a two-handed main hand or a main hand the off-hand type needs
    something else from (a quiver needs a bow), so it does not guess which."""
    text = str(reason or "")
    if text.startswith("off-hand item"):
        return ("This off-hand item can't be equipped with the main-hand weapon in your Path of Building build, so there is nothing "
                "to compare it with. Change the weapon in Path of Building to check it.")
    if text.startswith("two-hand weapon"):
        return "This two-handed weapon can't be equipped with the weapon layout in your Path of Building build."
    return text or "unsupported equipment layout"


def jewel_no_compatible_slot(allocated_count: int, excluded_count: int) -> NoCompatibleSlot:
    """The truthful refusal when a jewel candidate has no evaluable socket (M1.3, R4).

    Three different causes must not collapse into one message (`allocated_count` comes straight from PoB's allocated-socket
    enumeration, bridge.lua `allocated_jewel_socket_slots`, and includes `excluded_count`):
    no allocated socket at all; every allocated socket was left out because the jewel in it makes other passives'
    allocation depend on its presence (a swap-and-restore of that socket is not provably restorable, bridge.lua
    `jewel_socket_is_connectivity_risky`) -- the sockets exist and may well accept this jewel, so "not compatible" would be
    false; or the evaluable sockets do not accept this jewel family.
    """
    details = {"allocated_jewel_socket_count": allocated_count, "excluded_connectivity_risky_socket_count": excluded_count}
    if allocated_count == 0:
        return NoCompatibleSlot("this build has no allocated jewel sockets", details)
    if excluded_count >= allocated_count:
        return NoCompatibleSlot(
            "this build's allocated jewel sockets cannot be evaluated safely: the jewel socketed in each changes which "
            "passives can be allocated, so replacing it cannot be checked and restored reliably",
            details,
        )
    if excluded_count:
        return NoCompatibleSlot(
            "this jewel is not compatible with any jewel socket that can be evaluated safely in this build "
            f"({excluded_count} socket(s) were skipped because their jewel changes passive connectivity)",
            details,
        )
    return NoCompatibleSlot("this jewel is not compatible with any allocated jewel socket in this build", details)


def _product_slot_value(pob_slot: str, item_type: str | None) -> str:
    """`pob_slot_to_product` as a plain string, for both fixed equipment slots
    (a `ProductSlot` member) and dynamic jewel sockets (already a plain
    "Jewel <nodeId>" string) -- see `exilelens.items.slots` for why jewel
    sockets are not `ProductSlot` members."""
    result = pob_slot_to_product(pob_slot, item_type=item_type)
    return result.value if isinstance(result, ProductSlot) else result


@dataclass
class EvaluationContext:
    build_path: str
    context: str = "MAP"
    debug: bool = False


@dataclass
class EvaluationTimings:
    recognition_ms: float = 0.0
    metadata_ms: float = 0.0
    pob_parse_ms: float = 0.0
    slot_resolution_ms: float = 0.0
    per_slot_eval_ms: dict[str, float] = field(default_factory=dict)
    total_ms: float = 0.0
    # TOOLTIP-PERF (diagnostic): Lua-side stage breakdown per evaluated slot,
    # populated only while EXILELENS_TOOLTIP_PERF is set.
    per_slot_pob_ms: dict[str, dict[str, float]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        slot_values = list(self.per_slot_eval_ms.values())
        slot_values.sort()
        median = slot_values[len(slot_values) // 2] if slot_values else 0.0
        p95 = slot_values[int(len(slot_values) * 0.95)] if slot_values else 0.0
        return {
            "recognition_ms": self.recognition_ms,
            "metadata_ms": self.metadata_ms,
            "pob_parse_ms": self.pob_parse_ms,
            "slot_resolution_ms": self.slot_resolution_ms,
            "per_slot_eval_median_ms": median,
            "per_slot_eval_p95_ms": p95,
            "total_ms": self.total_ms,
            "per_slot_eval_ms": self.per_slot_eval_ms,
            "per_slot_pob_ms": self.per_slot_pob_ms,
        }


def _log_pob_baseline(
    *,
    build_path: str,
    build_info: dict[str, Any],
    baseline_fingerprint: str | None,
    metrics: dict[str, Any],
) -> None:
    """Bounded INFO log so owners can confirm stale vs proof-script baseline."""
    lines = [
        "POB BASELINE",
        f"build_path={build_path}",
        f"build_name={build_info.get('build_name') or build_info.get('name') or ''}",
        f"baseline_fingerprint={baseline_fingerprint or ''}",
        (
            "Fire effective="
            f"{metrics.get('FireResist')} "
            f"uncapped={metrics.get('FireResistTotal')} "
            f"cap={metrics.get('FireResistMax')} "
            f"overcap={metrics.get('FireResistOverCap')}"
        ),
    ]
    logger.info("\n".join(lines))


def _fingerprint_mismatch(
    baseline_fp: dict[str, Any] | None, restored_fp: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    """Every top-level fingerprint field that differs between baseline and restored.

    Used only to explain a restore that the worker itself reported as OK but whose
    fingerprint hash does not match the baseline's -- so a future failure names the
    exact field(s) that did not come back (item set, loadout, primary-skill identity,
    tree, equipment, ...) instead of only the fact that *something* differed.
    """
    baseline_fp = baseline_fp or {}
    restored_fp = restored_fp or {}
    keys = set(baseline_fp) | set(restored_fp)
    return {
        key: {"baseline": baseline_fp.get(key), "restored": restored_fp.get(key)}
        for key in sorted(keys)
        if baseline_fp.get(key) != restored_fp.get(key)
    }


@dataclass(frozen=True)
class _MeasurementRequest:
    """The one PoB transaction an item evaluation needs, handed to its driver.

    ``stonefist`` is the candidate's Way of the Stonefist transform report (None when
    the build has no item-base transform), so a driver can see whether this candidate
    is exact before anything is measured.
    """

    slots: tuple[str, ...]
    item_raw: str
    context: str
    component_keys: tuple[str, ...] | None
    baseline_overrides: tuple[tuple[str, str], ...] | None
    defer_restore: bool
    stonefist: dict[str, Any] | None

    def batch_key(self) -> tuple[Any, ...]:
        """Requests with equal keys can be measured as variants of one transaction."""
        return (self.slots, self.context, self.component_keys, self.baseline_overrides)

    def measure(self, engine) -> dict[str, Any]:
        return engine.evaluate_item_slots(
            list(self.slots),
            self.item_raw,
            context=self.context,
            component_keys=list(self.component_keys) if self.component_keys else None,
            defer_restore=self.defer_restore,
            baseline_overrides=dict(self.baseline_overrides) if self.baseline_overrides else None,
        )


def _resume_evaluation(steps, measure) -> dict[str, Any]:
    """Hand an evaluation suspended at its measurement its PoB result (or failure)."""
    try:
        batch = measure()
    except Exception as exc:  # the evaluation's own handlers classify it
        steps.throw(exc)
        raise RuntimeError("item evaluation ignored a measurement failure") from exc
    try:
        steps.send(batch)
    except StopIteration as stop:
        return stop.value
    raise RuntimeError("item evaluation requested a second measurement")


def _evaluate_item_impl(raw_text: str, engine, **kwargs: Any) -> dict[str, Any]:
    steps = _evaluate_item_steps(raw_text, engine, **kwargs)
    request = next(steps)
    return _resume_evaluation(steps, lambda: request.measure(engine))


def _evaluate_item_steps(
    raw_text: str,
    engine,
    *,
    build_path: str = "",
    build_source=None,
    context: str = "MAP",
    source: ItemInputSource = ItemInputSource.UNKNOWN,
    cache: ItemPipelineCache | None = None,
    debug: bool = False,
    value_profile: str = "BALANCED",
    loadout: str = "",
    item_set: str = "",
    item_check_pro: dict[str, Any] | None = None,
    offense_coverage: dict[str, Any] | None = None,
    defer_restore: bool = False,
    stonefist_bound: str = "none",
    stonefist_unresolved: str = "",
    stonefist_alternative: int | None = None,
):
    """Evaluate one item; suspends once, yielding the PoB measurement it needs.

    The driver sends back the ``evaluate_item_slots``-shaped result for that request
    (or throws its failure in). Splitting at the measurement lets several roll
    configurations of one Stonefist candidate be measured in a single transaction
    while each is still scored by exactly this code.
    """
    started = time.perf_counter()
    timings = EvaluationTimings()
    cache = cache or ItemPipelineCache()
    raw = RawItemInput.from_text(raw_text, source=source)

    # ITEM-CHECK-SOCKET-NORM: "Ignore socketed modifiers in Item Check" strips
    # rune/soul-core-granted lines from the candidate before it reaches PoB --
    # ``engine_raw`` is the text PoB actually parses/measures and the text the
    # pob-parse cache keys on, so a toggle of this setting can never reuse a cache
    # entry built under the other setting. ``raw`` (recognition, metadata, the
    # displayed candidate item and the reported raw_input) stays the true,
    # unmodified clipboard text throughout: this setting changes what is MEASURED,
    # never what is truthfully shown to have been on the item. The symmetric half
    # -- normalizing the currently equipped item -- happens further below, once
    # the compatible slots (and thus which equipped items are being compared) are
    # known.
    ignore_socketed_mods = bool((item_check_pro or {}).get("ignore_socketed_mods"))
    candidate_normalization = None
    engine_raw = raw
    if ignore_socketed_mods:
        candidate_normalization = strip_socketed_modifiers(raw.raw_text)
        if candidate_normalization.changed:
            engine_raw = RawItemInput.from_text(
                candidate_normalization.text,
                source=raw.source,
                detected_format=raw.detected_format,
            )

    t0 = time.perf_counter()
    recognition = cache.get_recognition(raw)
    timings.recognition_ms = (time.perf_counter() - t0) * 1000
    if not recognition.recognized:
        raise NotPoe2Item(recognition.reason, {"confidence": recognition.confidence.value})
    if recognition.classification == ItemClassification.FLASK:
        raise ItemUnsupported("flask items are not supported for equipment evaluation")

    t0 = time.perf_counter()
    metadata = cache.get_metadata(raw)
    timings.metadata_ms = (time.perf_counter() - t0) * 1000

    loaded = (
        engine.ensure_source_ready(build_source, context=context)
        if build_source is not None else engine.ensure_build_ready(build_path, context=context)
    )
    from exilelens.baseline import apply_engine_identity

    # The requested loadout / item set must be active (and PoB settled) BEFORE the
    # primary skill, metric and baseline fingerprint are read from the build.
    if loadout or item_set:
        apply_engine_identity(engine, loadout=loadout, item_set=item_set)
        loaded = engine.get_build_info()
    build_info = loaded.get("build") or {}
    baseline_fingerprint = loaded.get("fingerprint_hash")
    baseline_metrics = dict(loaded.get("metrics") or {})
    _log_pob_baseline(
        build_path=build_source.ref.key if build_source is not None else build_path,
        build_info=build_info,
        baseline_fingerprint=str(baseline_fingerprint or "") or None,
        metrics=baseline_metrics,
    )
    primary_metric = resolve_primary_metric(build_info, loaded.get("metrics"))
    selected_profile = parse_profile(value_profile)
    if offense_coverage is not None:
        coverage_payload = dict(offense_coverage)
    elif primary_metric.damage_owner == DamageOwner.MINION or primary_metric.semantic_quantity == DamageQuantity.AILMENT_DPS:
        # The actor table and number establish provenance, not responsiveness.  The
        # first comparison on this baseline proves the minion signal with PoB probes;
        # subsequent items reuse that fingerprint/context/field-specific evidence.
        audit_cache = getattr(engine, "_actor_ailment_offense_coverage_cache", None)
        if audit_cache is None:
            audit_cache = {}
            setattr(engine, "_actor_ailment_offense_coverage_cache", audit_cache)
        coverage_payload = OffenseCoverageAuditor(engine, cache=audit_cache).ensure(
            build_info=build_info,
            baseline_metrics=loaded.get("metrics") or {},
            fingerprint=str(baseline_fingerprint or ""),
            context=context,
        ).to_dict()
    else:
        coverage_payload = infer_offense_coverage(primary_metric, loaded.get("metrics")).to_dict()
        coverage_payload["audit_skipped"] = True

    # CORPUS-02C: Way of the Stonefist transforms equipped gloves in game. PoB
    # measures the transformed item the character would actually equip; the
    # displayed candidate (``raw``) stays the item the player copied.
    stonefist_active = stonefist_applies(build_info)
    candidate_transform: TransformResult | None = None
    if stonefist_active:
        candidate_transform = safe_transform(engine, engine_raw.raw_text, stonefist_bound, stonefist_alternative)
        if stonefist_unresolved and candidate_transform.ok and (candidate_transform.bounded or candidate_transform.alternatives > 1):
            candidate_transform = TransformResult(ok=False, unresolved=[stonefist_unresolved])
        if candidate_transform.ok and not candidate_transform.already_transformed:
            engine_raw = RawItemInput.from_text(
                candidate_transform.item_raw, source=raw.source, detected_format=raw.detected_format,
            )

    t0 = time.perf_counter()
    pob_engine_result = cache.get_pob_parse(
        engine_raw, engine.parse_item, build_fingerprint=str(baseline_fingerprint or ""),
    )
    pob_parse = PobParseResult.from_engine(pob_engine_result, metadata)
    timings.pob_parse_ms = (time.perf_counter() - t0) * 1000
    if not pob_parse.parse_ok:
        raise ItemUnsupported("PoB could not parse item")
    is_jewel_candidate = pob_parse.item.get("type") == "Jewel"

    t0 = time.perf_counter()
    compatible_slots = list(pob_parse.compatible_slots)
    timings.slot_resolution_ms = (time.perf_counter() - t0) * 1000

    if pob_parse.weapon_layout == "UNSUPPORTED_EQUIPMENT_LAYOUT":
        raise SlotResolutionFailed(
            weapon_layout_refusal_message(pob_parse.weapon_layout_reason),
            {"weapon_layout": pob_parse.weapon_layout},
        )
    if not compatible_slots:
        if is_jewel_candidate:
            raise jewel_no_compatible_slot(
                pob_parse.allocated_jewel_socket_count or 0,
                pob_parse.excluded_connectivity_risky_socket_count or 0,
            )
        raise NoCompatibleSlot("item has no compatible replacement slots in the loaded build")
    # Detect two-hand weapon candidate that would auto-clear an equipped offhand.
    # This is a paired-slot change: equipping a two-hander in Weapon 1 removes
    # the offhand from Weapon 2. Ordinary Item Check only evaluates Weapon 1,
    # but the comparison delta includes the offhand loss. We flag this so the
    # presentation layer can disclose the full scope of the change.
    paired_offhand_cleared = False
    paired_offhand_slot = ""
    paired_offhand_name = ""
    paired_offhand_physical_slot = ""
    paired_offhand_raw = ""
    item_type = pob_parse.item.get("type")
    is_two_hand = pob_parse.item.get("two_hand") or (item_type in WEAPON_TYPES and "twohand" in str(pob_parse.item.get("base_tags") or "").lower())
    # Check for two-hand via base tags more reliably
    base_tags = pob_parse.item.get("base_tags") or {}
    if base_tags.get("twohand"):
        is_two_hand = True
    if is_two_hand and "Weapon 1" in compatible_slots:
        # Read current equipment to see if an offhand is equipped in Weapon 2
        try:
            equipment_payload = engine.get_equipment() or {}
        except Exception:
            equipment_payload = {}
        equipment_by_slot = {
            str(entry.get("slot")): entry
            for entry in (equipment_payload.get("equipment") or [])
            if isinstance(entry, dict)
        }
        weapon2_entry = equipment_by_slot.get("Weapon 2")
        if weapon2_entry and weapon2_entry.get("equipped"):
            offhand_type = weapon2_entry.get("type") or ""
            if offhand_type in ("Shield", "Focus", "Quiver"):
                # The logical Weapon 2 entry may be backed by Weapon 2 Swap.
                # Keep that physical source so the measured candidate fingerprint
                # can prove this exact active offhand was actually cleared.
                paired_offhand_slot = "Weapon 2"
                paired_offhand_physical_slot = str(weapon2_entry.get("physical_slot") or "Weapon 2")
                paired_offhand_name = str(
                    weapon2_entry.get("name") or weapon2_entry.get("base_name") or ""
                ).strip()
                paired_offhand_raw = str(weapon2_entry.get("raw") or "")

    if pob_parse.weapon_layout == "AMBIGUOUS_WEAPON_LAYOUT" and len([s for s in compatible_slots if s.startswith("Weapon")]) > 1:
        # Evaluate all weapon-compatible slots rather than failing.
        pass

    components: list[dict[str, Any]] = []
    if should_discover_components(build_info, primary_metric) and hasattr(engine, "_call"):
        # PoB's normal output has only the selected group. For an explicitly
        # multi-skill build, one cached diagnostic pass reads other native PoB
        # outputs; only the selected components are recalculated per item.
        report_cache = getattr(engine, "_native_component_report_cache", None)
        if report_cache is None:
            report_cache = {}
            setattr(engine, "_native_component_report_cache", report_cache)
        # PoB's cheap hit/minion flags narrow most reports. Skill-DoT and
        # ailments need the full enabled list: some native DoT stat sets have
        # no hit/dot hint until that group itself is calculated.
        broad_dot = primary_metric.semantic_quantity in {DamageQuantity.SKILL_DOT, DamageQuantity.AILMENT_DPS}
        report_indices = None if broad_dot else build_info.get("native_damage_group_indices") or []
        report_key = (baseline_fingerprint, context, build_info.get("main_socket_group"),
                      build_info.get("weapon_set", 1), str(build_info.get("active_skill_set_id") or ""),
                      tuple(report_indices or ()))
        try:
            report = report_cache.get(report_key)
            if report is None:
                report = engine._call("get_skill_report", {"indices": report_indices} if report_indices else {})
                report_cache[report_key] = report
            reported_primary = (report.get("metrics") or {}).get(primary_metric.pob_field)
            original_primary = baseline_metrics.get(primary_metric.pob_field)
            if reported_primary is not None and original_primary is not None and abs(
                float(reported_primary) - float(original_primary)
            ) <= max(0.5, abs(float(original_primary)) * 0.000001):
                components = select_baseline_components(build_info, primary_metric, baseline_metrics, report)
        except Exception:
            logger.exception("PoB native component discovery unavailable; primary comparison retained")

    # MAIN-SKILL-01: a selected main skill with no calculated offense gets an
    # actionable diagnostic (identity, why, PoB-calculated alternatives, recovery).
    # Baseline-only, so it is read once and shared by every slot comparison.
    main_skill_diagnostic: dict[str, Any] | None = None
    if selected_skill_has_no_offense(primary_metric, baseline_metrics):
        skill_group_count = int(build_info.get("skill_group_count") or 0)
        diagnostic_report: dict[str, Any] | None = None
        if hasattr(engine, "_call") and 0 < skill_group_count <= MAX_REPORT_GROUPS:
            diag_cache = getattr(engine, "_native_component_report_cache", None)
            if diag_cache is None:
                diag_cache = {}
                setattr(engine, "_native_component_report_cache", diag_cache)
            diagnostic_key = ("main-skill-diagnostic", baseline_fingerprint, context, build_info.get("main_socket_group"),
                              build_info.get("weapon_set", 1), str(build_info.get("active_skill_set_id") or ""))
            try:
                diagnostic_report = diag_cache.get(diagnostic_key)
                if diagnostic_report is None:
                    diagnostic_report = engine._call("get_skill_report", {})
                    diag_cache[diagnostic_key] = diagnostic_report
            except Exception:
                logger.exception("PoB skill report unavailable; main-skill diagnostic lists no alternatives")
                diagnostic_report = None
        main_skill_diagnostic = build_main_skill_diagnostic(
            primary_metric, baseline_metrics, diagnostic_report,
            context=context, skill_group_count=skill_group_count,
            effect_catalog=build_info.get("effect_catalog"),
        )

    comparisons: list[dict[str, Any]] = []
    failed_slot_outcomes: list[dict[str, Any]] = []
    recovery_used = False
    debug_payload: dict[str, Any] = {"slots": [], "restores": []}

    # ITEM-CHECK-SOCKET-NORM (symmetric half): the currently equipped item in each
    # compatible slot is read and normalized the same way the candidate was above,
    # so the PoB baseline measurement itself -- not just the displayed text -- is
    # recalculated with socketed-item modifiers removed. Never one-sided: a slot is
    # only overridden when its own equipped item actually has something to strip.
    baseline_overrides: dict[str, str] = {}
    baseline_normalization_diagnostics: dict[str, int] = {}
    if ignore_socketed_mods:
        try:
            equipment_payload = engine.get_equipment() or {}
        except Exception:
            logger.exception("could not read live equipment for socket-modifier normalization")
            equipment_payload = {}
        equipment_by_slot = {
            str(entry.get("slot")): entry
            for entry in (equipment_payload.get("equipment") or [])
            if isinstance(entry, dict)
        }
        for slot in compatible_slots:
            entry = equipment_by_slot.get(slot)
            if not entry or not entry.get("equipped"):
                continue
            current_raw = str(entry.get("raw") or "")
            if not current_raw:
                continue
            normalized = strip_socketed_modifiers(current_raw)
            if normalized.changed:
                baseline_overrides[slot] = normalized.text
                baseline_normalization_diagnostics[slot] = len(normalized.removed_lines)

    # CORPUS-02C: a build whose equipped gloves are still ordinary (e.g. built by
    # hand in PoB) is measured with its gloves transformed as in game, for every
    # slot, in memory only -- the transaction restores the true build afterwards.
    transform_overrides: dict[str, str] = {}
    baseline_transform: TransformResult | None = None
    if stonefist_active:
        baseline_transform = equipped_gloves_transform(engine, baseline_overrides.get("Gloves"))
        if baseline_transform is not None and baseline_transform.ok and not baseline_transform.already_transformed:
            transform_overrides["Gloves"] = baseline_transform.item_raw
    engine_overrides = {**baseline_overrides, **transform_overrides}

    # PERF-02: every compatible slot for this item is measured inside one PoB
    # transaction -- one baseline, N candidate frames, one restore -- instead of N
    # transactions costing 2N frames. The restore and its verification are shared by
    # every slot because there is one transaction; `restore.status` says whether they
    # have run yet.
    t_batch = time.perf_counter()
    batch_keys = candidate_keys(components) if components else None
    request = _MeasurementRequest(
        slots=tuple(compatible_slots),
        item_raw=engine_raw.raw_text,
        context=context,
        component_keys=tuple(batch_keys) if batch_keys else None,
        baseline_overrides=tuple(sorted(engine_overrides.items())) if engine_overrides else None,
        defer_restore=defer_restore,
        stonefist=(transform_report("Gloves", candidate_transform, None) or {}).get("candidate")
        if stonefist_active and "Gloves" in compatible_slots else None,
    )
    try:
        batch = yield request
    except SlotInvalid as exc:
        raise BaselineItemUnresolved(
            "PoB baseline item could not be resolved for this item",
            {"slots": list(compatible_slots)},
        ) from exc
    except RestoreFailed as exc:
        # The worker build no longer matches the baseline. Nothing from this
        # transaction is delivered, and the engine is invalidated so the next
        # evaluation reloads a known-good baseline before measuring anything.
        recovery_used = True
        engine.invalidate_build()
        raise EvaluationInvalidBuildState(
            "Path of Building could not restore the build after this comparison",
            {"slots": list(compatible_slots), "details": getattr(exc, "details", None)},
        ) from exc

    batch_restore = batch.get("restore") or {}
    batch_restored = batch.get("restored")
    batch_baseline = batch["baseline"]
    measured_slots = batch.get("slots") or []
    batch_ms = (time.perf_counter() - t_batch) * 1000

    # Disclosure is based on PoB's measured candidate equipment, not on a
    # guessed incompatibility. A two-hander only reports a paired removal when
    # it actually cleared the classified active offhand in this transaction.
    if paired_offhand_slot and paired_offhand_raw:
        weapon1_measurement = next(
            (
                entry
                for entry in measured_slots
                if entry.get("slot") == "Weapon 1" and not entry.get("error")
            ),
            None,
        )
        candidate_equipment = (
            (weapon1_measurement or {}).get("candidate", {}).get("equipment") or {}
        )
        if not str(candidate_equipment.get(paired_offhand_physical_slot) or "").strip():
            paired_offhand_cleared = True
    if not paired_offhand_cleared:
        paired_offhand_slot = ""
        paired_offhand_name = ""
    slot_perf = batch.get("perf")
    if isinstance(slot_perf, dict):
        timings.per_slot_pob_ms["__transaction__"] = {
            key: (round(float(value), 2) if isinstance(value, (int, float)) else value)
            for key, value in slot_perf.items()
            if isinstance(value, (int, float, list, dict))
        }

    # A restore that already ran and did not pass invalidates the whole transaction.
    # This is caught independently of the RESTORE_FAILED exception above: the worker's
    # own equipment/semantic/metrics checks (tx_finish) can report success while the
    # broader per-field fingerprint comparison here (equipment, item set, loadout, tree,
    # and primary-skill identity together) still disagrees. Either signal means the
    # build can no longer be trusted for the next comparison, so both take the same
    # fail-closed path: mark recovery used, invalidate the loaded build so the next
    # evaluation reloads a known-good baseline, and report exactly which fields did not
    # come back instead of a bare "restore failed".
    if batch_restore.get("status") == "OK" and not batch_restore.get("pass"):
        recovery_used = True
        engine.invalidate_build()
        restored_fp = (batch_restored or {}).get("fingerprint") or {}
        mismatch = _fingerprint_mismatch(batch_baseline.get("fingerprint"), restored_fp)
        raise EvaluationInvalidBuildState(
            "restore failed after evaluating this item",
            {
                "slots": list(compatible_slots),
                "restore": batch_restore,
                "mismatched_fields": mismatch,
                "restored_item_set": str(restored_fp.get("active_item_set_id") or ""),
                "restored_loadout": str(restored_fp.get("active_loadout") or ""),
                "restored_primary_identity": {
                    key: value for key, value in restored_fp.items() if key.startswith("main_")
                },
            },
        )

    for entry in measured_slots:
        pob_slot = entry["slot"]
        product_slot = _product_slot_value(pob_slot, pob_parse.item.get("type"))
        failure = entry.get("error")
        if failure is not None:
            debug_payload["slots"].append({"slot": pob_slot, "error": failure.get("message"), "details": failure.get("details")})
            # A legal slot whose measurement raised is a FAILED outcome, not a silent drop.
            failed_slot_outcomes.append(
                failed_outcome(
                    "SLOT_EVALUATION_FAILED",
                    f"Path of Building failed while evaluating {pob_slot}",
                    source_slot=product_slot,
                    replacement_slot=pob_slot,
                ).to_dict()
            )
            continue

        # Each slot is one measurement inside the shared transaction, so the per-slot
        # figure is the batch cost spread over the slots that actually produced one.
        timings.per_slot_eval_ms[pob_slot] = batch_ms / max(1, len(measured_slots))
        baseline_block = dict(batch_baseline)
        baseline_block["slot_item"] = entry.get("slot_item")
        comparison = {
            "product_slot": product_slot,
            "pob_slot": pob_slot,
            "baseline": baseline_block,
            "candidate": entry["candidate"],
            "restored": batch_restored,
            "restore": batch_restore,
            "delta": entry["delta"],
            "primary_metric_field": primary_metric.pob_field,
            "baseline_primary_metric": primary_metric.to_dict(),
            "candidate_primary_metric": resolve_primary_metric(
                {
                    "main_skill_identity": (entry.get("candidate") or {}).get("primary_skill") or {},
                    "full_dps_skills": ((entry.get("candidate") or {}).get("semantic") or {}).get("full_dps") or [],
                    "offense_metric_scope": (
                        MetricScope.FULL_DPS_AGGREGATE.value
                        if primary_metric.pob_field == "FullDPS"
                        else MetricScope.PRIMARY_SKILL.value
                    ),
                },
                (entry.get("candidate") or {}).get("metrics") or {},
            ).to_dict(),
            "eval_ms": timings.per_slot_eval_ms[pob_slot],
        }
        comparison["equipability"] = build_equipability(
            pob_parse.item, baseline_block.get("metrics"), (entry.get("candidate") or {}).get("metrics")
        )
        comparison["native_damage_discovery"] = compare_native_components(primary_metric, components, comparison)
        if main_skill_diagnostic is not None:
            comparison["main_skill_diagnostic"] = main_skill_diagnostic
        breakdown = ailment_breakdown(
            comparison["baseline_primary_metric"],
            baseline_block.get("metrics"),
            (entry.get("candidate") or {}).get("metrics"),
        )
        if breakdown is not None:
            comparison["ailment_breakdown"] = breakdown
        item_set_id = str(item_set or build_info.get("active_item_set_id") or "")
        item_set_name = display_item_set_name(build_info.get("active_item_set_name"), item_set_id)
        loadout_id = str(loadout or build_info.get("active_loadout") or "")
        try:
            baseline_item = resolve_baseline_item(
                pob_slot=pob_slot,
                product_slot=product_slot,
                baseline=baseline_block,
                item_set_id=item_set_id,
                item_set_name=item_set_name,
                loadout_id=loadout_id,
                loadout_name=loadout_id,
                fingerprint=str(baseline_block.get("fingerprint_hash") or baseline_fingerprint or ""),
            )
        except BaselineItemUnresolved:
            raise
        comparison["baseline_item"] = baseline_item.to_dict()
        comparison["candidate_item"] = resolve_candidate_item(
            metadata=metadata,
            pob_parse=pob_parse.__dict__,
            product_slot=product_slot,
            pob_slot=pob_slot,
            raw_text=raw.raw_text,
        ).to_dict()
        comparison["item_transform"] = transform_report(pob_slot, candidate_transform, baseline_transform)
        if pob_slot != "Gloves" and baseline_transform is not None and not baseline_transform.ok:
            # Ordinary equipped gloves whose transformation is not exact stay untransformed
            # in PoB's baseline; disclose it instead of silently comparing against it.
            comparison["stonefist_baseline_note"] = (
                "The equipped gloves are ordinary gloves in this Path of Building build, but Way of the "
                "Stonefist transforms them in game and their transformed rolls are unknown, so this comparison "
                "cannot be trusted as measured; import the character from the game for exact gloves"
            )
        comparison["unmodeled_item_transform"] = unmodeled_item_transform(
            build_info.get("item_base_transforms"),
            pob_slot,
            effective_item(comparison["baseline_item"], baseline_transform if pob_slot == "Gloves" else None),
            effective_item(comparison["candidate_item"], candidate_transform if pob_slot == "Gloves" else None),
            unresolved=unresolved_reasons(candidate_transform, baseline_transform),
        )
        comparisons.append(comparison)
        debug_payload["slots"].append(
            {
                "product_slot": product_slot,
                "pob_slot": pob_slot,
                "restore_status": batch_restore.get("status"),
                "restore_pass": batch_restore.get("pass"),
                "fingerprint": {
                    "baseline": baseline_block.get("fingerprint_hash"),
                    "restored": (batch_restored or {}).get("fingerprint_hash"),
                },
            }
        )
    if not comparisons:
        raise SlotResolutionFailed("no slot evaluations succeeded")

    ranking = rank_slot_comparisons(
        comparisons,
        profile=selected_profile,
        primary_field=primary_metric.pob_field,
        primary_confidence=primary_metric.confidence.value,
        offense_coverage=coverage_payload,
    )
    # PERF-02: this post-check is a weaker restatement of the transaction verification
    # (equipment + semantic calc state + metrics within tolerance) that tx_finish already
    # performed. When the restore was deferred it has not run yet, and asking the worker
    # for metrics here would drain it back onto the path this change exists to clear --
    # so the check is skipped and the verification is the deferred restore itself.
    # A driver may measure a deferred-requested evaluation in a transaction that
    # restored immediately (Stonefist configuration batches); the check then runs.
    final_metrics: dict[str, Any] = {}
    if not defer_restore or batch_restore.get("status") == "OK":
        final_metrics = engine.get_metrics(context=context)
        if baseline_fingerprint and final_metrics.get("fingerprint_hash") != baseline_fingerprint:
            raise EvaluationInvalidBuildState(
                "build fingerprint changed after evaluation sequence",
                {
                    "baseline": baseline_fingerprint,
                    "final": final_metrics.get("fingerprint_hash"),
                },
            )

    timings.total_ms = (time.perf_counter() - started) * 1000
    payload = {
        "ok": True,
        "source_identity": (
            build_source.ref.key if build_source is not None
            else getattr(getattr(engine, "loaded_source_ref", None), "key", "")
        ),
        "source_revision": getattr(getattr(engine, "loaded_revision", None), "token", ""),
        "source_generation": getattr(engine, "source_generation", 0),
        "raw_input": {
            "content_hash": raw.content_hash,
            "source": raw.source.value,
            "detected_format": raw.detected_format.value,
            "normalized_line_endings": raw.normalized_line_endings,
            "raw_text": raw.raw_text,
        },
        "recognition": {
            "recognized": recognition.recognized,
            "confidence": recognition.confidence.value,
            "reason": recognition.reason,
            "classification": recognition.classification.value,
        },
        "metadata": metadata.__dict__,
        "pob_parse": pob_parse.__dict__,
        "primary_metric": primary_metric.to_dict(),
        "effect_catalog": build_info.get("effect_catalog") or {},
        "native_damage_discovery": (ranking["recommendation"] or {}).get("native_damage_discovery") or {},
        "main_skill_diagnostic": main_skill_diagnostic or {},
        "damage_claim": (ranking["recommendation"] or {}).get("damage_claim") or {},
        "offense_coverage": coverage_payload,
        "value_profile": selected_profile.value,
        "value": (ranking["recommendation"] or {}).get("value"),
        "compatible_slots": [
            {
                "product_slot": _product_slot_value(slot, pob_parse.item.get("type")),
                "pob_slot": slot,
            }
            for slot in compatible_slots
        ],
        "paired_offhand_cleared": paired_offhand_cleared,
        "paired_offhand_slot": paired_offhand_slot,
        "paired_offhand_name": paired_offhand_name if paired_offhand_cleared else "",
        "slot_comparisons": ranking["slot_comparisons"],
        "failed_slot_outcomes": failed_slot_outcomes,
        "recommendation": ranking["recommendation"],
        "pareto": ranking["pareto"],
        "build": build_info,
        "timings": timings.to_dict(),
        "state_integrity": {
            "recovery_used": recovery_used,
            "loadout": str(build_info.get("active_loadout") or ""),
            "item_set": str(build_info.get("active_item_set_id") or ""),
        },
        # Privacy-safe: counts and slot names only, never the removed mod text --
        # see items/diagnostics.py's allowlist serializer, which surfaces this block.
        "socket_normalization": {
            "enabled": ignore_socketed_mods,
            "candidate_normalized": bool(candidate_normalization and candidate_normalization.changed),
            "candidate_removed_count": len(candidate_normalization.removed_lines) if candidate_normalization else 0,
            "baseline_normalized_slots": sorted(baseline_overrides.keys()),
            "baseline_removed_counts": dict(baseline_normalization_diagnostics),
        },
    }
    if is_jewel_candidate:
        # M1.3: truthful note about sockets this evaluation could not safely
        # consider at all -- see bridge.lua's `jewel_socket_is_connectivity_risky`.
        # Zero for the overwhelming majority of builds; non-zero only when a
        # currently-equipped jewel (e.g. "From Nothing") makes other allocated
        # passives reachable without a connected path, which the ordinary
        # swap-and-restore transaction cannot safely round-trip.
        payload["jewel_socket_diagnostics"] = {
            "allocated_jewel_socket_count": pob_parse.allocated_jewel_socket_count or 0,
            "excluded_connectivity_risky_socket_count": pob_parse.excluded_connectivity_risky_socket_count or 0,
        }
    payload["comparison_trace"] = build_comparison_trace(payload)
    pro = item_check_pro or {}
    payload = enrich_fast_result(
        payload,
        recommendation_style=str(pro.get("recommendation_style") or "BALANCED"),
        popup_density=str(pro.get("popup_density") or "COMPACT"),
        multi_profile_enabled=bool(pro.get("multi_profile", True)),
        decision_enabled=bool(pro.get("decision_intelligence", True)),
        best_slot_enabled=bool(pro.get("best_replacement_slot", True)),
        build_name=str(build_info.get("build_name") or build_info.get("name") or ""),
        loadout_name=str(build_info.get("active_loadout") or loadout or ""),
        item_set_name=str(build_info.get("active_item_set_name") or item_set or ""),
        context=context,
    )
    if debug:
        payload["debug"] = {
            **debug_payload,
            "initial_fingerprint": baseline_fingerprint,
            "final_fingerprint": final_metrics.get("fingerprint_hash"),
            "ranking": ranking["pareto"],
            "comparison_trace": payload["comparison_trace"],
        }
    return payload


# --------------------------------------------------------------------------- #
# LANG-01 failure classifier
#
# The clipboard -> recognition -> PoB parse chain is unchanged. Only *after* it has
# already failed, and only for the failure codes a localized client actually
# produces, do we ask whether the raw clipboard text was non-English. An English
# item that fails (say, an unknown new base type) keeps its original error, so real
# parser bugs stay visible instead of hiding behind "unsupported language".
# --------------------------------------------------------------------------- #

# Codes a localized clipboard can plausibly produce: recognition found no PoE2
# headers, PoB refused the text, or PoB resolved no base type
# (runtime/lua/bridge.lua -> "item base type could not be resolved").
_LOCALIZATION_SUSPECT_CODES = frozenset({"NOT_POE2_ITEM", "ITEM_PARSE_FAILED", "ITEM_UNSUPPORTED"})

# ITEM_UNSUPPORTED is also how we reject flasks and jewels. Those are correct
# English outcomes and must never be re-labelled.
_NEVER_RECLASSIFY = (
    "flask items are not supported",
    "jewel items are not supported",
)


def _classify_localization_failure(raw_text: str, error: EngineError) -> EngineError:
    """Return an UnsupportedGameLanguage error, or the original error untouched.

    LOCALIZATION-01 extension point: when a canonical localization layer exists,
    this is the one place that changes -- a confident non-English detection would
    canonicalize and re-run the analyzer here instead of raising.
    """
    if error.code not in _LOCALIZATION_SUSPECT_CODES:
        return error
    message = (error.message or "").lower()
    if any(marker in message for marker in _NEVER_RECLASSIFY):
        return error

    detection = detect_poe_item_language(raw_text)
    if not detection.is_confident_non_english:
        logger.debug(
            "item_language_check inconclusive detected_language=%s confidence=%.2f "
            "item_like=%s original_error=%s",
            detection.language.value,
            detection.confidence,
            detection.item_like,
            error.code,
        )
        return error

    logger.warning(
        "unsupported_item_language detected_language=%s confidence=%.2f evidence=%s "
        "original_error=%s original_message=%s",
        detection.language.value,
        detection.confidence,
        list(detection.evidence),
        error.code,
        error.message,
    )
    return UnsupportedGameLanguage(
        unsupported_language_body(detection),
        {
            "detected_language": detection.display_name,
            "language_code": detection.language.value,
            "confidence": round(detection.confidence, 2),
            "evidence": list(detection.evidence),
            "original_error": {"code": error.code, "message": error.message},
        },
    )


def evaluate_item(raw_text: str, engine, **kwargs: Any) -> dict[str, Any]:
    """Evaluate a clipboard item; English behaviour is byte-for-byte unchanged.

    The only addition is that an already-failed parse is re-classified as
    :class:`UnsupportedGameLanguage` when the raw clipboard text is confidently
    non-English.
    """
    try:
        return _evaluate_with_stonefist_bounds(raw_text, engine, **kwargs)
    except EngineError as exc:
        raise _classify_localization_failure(raw_text, exc) from exc


#: PoB outputs Item Check scores from, all "higher is better" for the character.
#: A roll-dependent candidate is only reported when each of them is ordered
#: worst <= middle <= best across the three measured roll configurations.
_MONOTONE_FIELDS = (
    "TotalEHP", "Life", "EnergyShield", "Mana", "Evasion", "Armour", "Ward",
    "FireResist", "ColdResist", "LightningResist", "ChaosResist", "BlockChance", "SpellBlockChance",
    "PhysicalMaximumHitTaken", "FireMaximumHitTaken", "ColdMaximumHitTaken",
    "LightningMaximumHitTaken", "ChaosMaximumHitTaken",
)


def _verdict_structure(row: dict[str, Any]) -> tuple[Any, ...]:
    """Everything besides the score that decides the public verdict."""
    outcome = row.get("evaluation_outcome") or {}
    impact = outcome.get("item_impact") or {}
    axes = tuple(sorted(
        (name, str(axis.get("direction")), bool(axis.get("significant")),
         bool(axis.get("material_positive")), bool(axis.get("material_negative")))
        for name, axis in (impact.get("axes") or {}).items()
    ))
    guardrails = tuple(sorted(str(g.get("code")) for g in outcome.get("guardrails_applied") or []))
    # SCORING-01a: whether a material two-sided conflict exists (not just the descriptive pattern) is
    # what lets the score be replaced by the canonical sidegrade, so it is part of the verdict structure.
    conflict = str((impact.get("conflict") or {}).get("kind"))
    return (str(outcome.get("verdict")), str(outcome.get("evaluation_quality")), str(impact.get("pattern")), conflict,
            axes, guardrails)


def _roll_monotone_violations(rows: list[dict[str, Any]]) -> list[str]:
    """Fields whose value is not ordered worst <= middle <= best."""
    worst, middle, best = rows
    fields = list(_MONOTONE_FIELDS)
    primary = str(worst.get("primary_metric_field") or "")
    if primary:
        fields.insert(0, primary)
    violations: list[str] = []
    for field_name in fields:
        values = []
        for row in (worst, middle, best):
            value = ((row.get("candidate") or {}).get("metrics") or {}).get(field_name)
            try:
                values.append(float(value))
            except (TypeError, ValueError):
                values = []
                break
        if len(values) != 3:
            continue
        tolerance = max(1e-6, abs(values[2]) * 1e-9)
        if values[0] > values[1] + tolerance or values[1] > values[2] + tolerance:
            violations.append(field_name)
    return violations


#: At most this many different transformed items are evaluated for one candidate.
_MAX_TRANSFORM_ALTERNATIVES = 4


def _measure_configurations(engine, pending: list[tuple[Any, _MeasurementRequest]]) -> list[dict[str, Any]]:
    """Measure evaluations suspended at their PoB measurement; return their results in order.

    Requests that measure the same slots against the same baseline are variants of
    one item: PoB measures them in one transaction (one baseline read, one frame per
    variant, one verified restore) and every evaluation receives its own variant's
    result. Anything else -- or an engine without variant batches -- is measured on
    its own, never deferred. A failed batch is handed to the first evaluation that
    needs it, whose normal failure handling applies (invalidating the build when the
    restore failed); the remaining evaluations are then abandoned by the caller.
    """
    results: list[dict[str, Any] | None] = [None] * len(pending)
    groups: dict[tuple[Any, ...], list[int]] = {}
    for index, (_, request) in enumerate(pending):
        groups.setdefault(request.batch_key(), []).append(index)
    batched = hasattr(engine, "evaluate_item_variants")
    for indices in groups.values():
        if len(indices) == 1 or not batched:
            for index in indices:
                steps, request = pending[index]
                single = replace(request, defer_restore=False)
                results[index] = _resume_evaluation(steps, lambda single=single: single.measure(engine))
            continue
        head = pending[indices[0]][1]
        raws = list(dict.fromkeys(pending[index][1].item_raw for index in indices))
        by_raw: dict[str, dict[str, Any]] = {}

        def variant(request: _MeasurementRequest, head=head, raws=raws, by_raw=by_raw) -> dict[str, Any]:
            if not by_raw:
                measured = engine.evaluate_item_variants(
                    list(head.slots),
                    raws,
                    context=head.context,
                    component_keys=list(head.component_keys) if head.component_keys else None,
                    baseline_overrides=dict(head.baseline_overrides) if head.baseline_overrides else None,
                )
                if len(measured) != len(raws):
                    raise EngineError(
                        "EVALUATION_FAILED", "PoB returned a different number of item variants than requested",
                    )
                by_raw.update(zip(raws, measured))
            return copy.deepcopy(by_raw[request.item_raw])

        for index in indices:
            steps, request = pending[index]
            results[index] = _resume_evaluation(steps, lambda request=request: variant(request))
    return results  # type: ignore[return-value]


#: One-at-a-time roll probes: each ranged transformed line alone at its best roll, the
#: others at their worst. Each probe is one more PoB recalculation in the candidate's
#: transaction (~0.3 s), so they are measured only for alternatives with 2..8 ranged
#: lines (with one, the probe is the best configuration) and only while the whole
#: candidate stays within 8 configurations -- e.g. one alternative with up to 5 ranged
#: lines. Otherwise none are measured and the worst <= middle <= best check stands alone.
_MAX_FLIPPED_LINES = 8
_MAX_CONFIGURATIONS = 8


def _flip_plan(configurations: list[tuple[int, str, Any, _MeasurementRequest]]) -> list[tuple[int, str]]:
    plan: list[tuple[int, str]] = []
    for alternative, bound, _steps, request in configurations:
        if bound != "worst":
            continue
        ranged = list((request.stonefist or {}).get("ranged_lines") or [])
        if 2 <= len(ranged) <= _MAX_FLIPPED_LINES:
            plan.extend((alternative, f"flip:{template}") for template in ranged)
    if len(configurations) + len(plan) > _MAX_CONFIGURATIONS:
        return []
    return plan


def _evaluate_with_stonefist_bounds(raw_text: str, engine, **kwargs: Any) -> dict[str, Any]:
    """CORPUS-02C: a Stonefist glove candidate whose transformed item is not unique.

    Two things can leave several possible transformed items: the game rolls ranged
    transformed modifiers independently when the gloves are equipped, and the
    displayed lines may fit more than one modifier combination. PoB measures every
    possible combination ("alternative") and, for each, the worst, middle and best
    rolls. A verdict is reported only when

    * every scored PoB output of each alternative is ordered worst <= middle <= best
      (the outcome is monotone in the rolls, so these bound every other roll), and
    * every measured configuration gives the same public verdict.

    Otherwise the comparison stays UNSUPPORTED with the reason. The reported numbers
    are a verified range over all configurations, never one assumed roll.
    """
    first = _evaluate_item_steps(raw_text, engine, stonefist_bound="worst", stonefist_alternative=0, **kwargs)
    first_request = next(first)
    transform = first_request.stonefist or {}
    alternatives = int(transform.get("alternatives") or 1) if transform.get("ok") else 1
    if not transform.get("ok") or (not transform.get("bounded") and alternatives <= 1):
        return _resume_evaluation(first, lambda: first_request.measure(engine))

    def refuse(reason: str) -> dict[str, Any]:
        return _evaluate_item_impl(
            raw_text, engine, stonefist_bound="worst", stonefist_alternative=0, stonefist_unresolved=reason, **kwargs,
        )

    if alternatives > _MAX_TRANSFORM_ALTERNATIVES:
        first.close()
        return refuse(f"its displayed modifiers fit {alternatives} different glove modifier combinations")
    # Every configuration is prepared up to its PoB measurement, all of them are
    # measured together (one transaction for those that share slots and baseline),
    # and each is then scored by the ordinary item evaluation.
    plain = {**kwargs, "defer_restore": False}
    configurations: list[tuple[int, str, Any, _MeasurementRequest]] = []
    try:
        for alternative in range(alternatives):
            if alternative == 0:
                steps, request = first, first_request
            else:
                steps = _evaluate_item_steps(
                    raw_text, engine, stonefist_bound="worst", stonefist_alternative=alternative, **plain,
                )
                request = next(steps)
            configurations.append((alternative, "worst", steps, request))
            if (request.stonefist or {}).get("bounded"):
                for bound in ("middle", "best"):
                    steps = _evaluate_item_steps(
                        raw_text, engine, stonefist_bound=bound, stonefist_alternative=alternative, **plain,
                    )
                    configurations.append((alternative, bound, steps, next(steps)))
        for alternative, bound in _flip_plan(configurations):
            steps = _evaluate_item_steps(
                raw_text, engine, stonefist_bound=bound, stonefist_alternative=alternative, **plain,
            )
            configurations.append((alternative, bound, steps, next(steps)))
        results = _measure_configurations(engine, [(steps, request) for _, _, steps, request in configurations])
    finally:
        first.close()
        for _, _, steps, _ in configurations:
            steps.close()
    runs: list[dict[str, Any]] = [  # each: {"alternative", "bound", "result"}
        {"alternative": alternative, "bound": bound, "result": result}
        for (alternative, bound, _, _), result in zip(configurations, results)
    ]

    slots = [row.get("pob_slot") for row in runs[0]["result"].get("slot_comparisons") or [] if (row.get("item_transform") or {}).get("candidate")]
    for slot in slots:
        rows = []
        for run in runs:
            row = next((r for r in run["result"].get("slot_comparisons") or [] if r.get("pob_slot") == slot), None)
            if row is None or not ((row.get("item_transform") or {}).get("candidate") or {}).get("ok"):
                return refuse("its possible transformed items could not all be measured")
            rows.append((run, row))
        verdicts = {str((row.get("evaluation_outcome") or {}).get("verdict") or "") for _, row in rows}
        if len(verdicts) > 1:
            low = str((rows[0][1].get("evaluation_outcome") or {}).get("verdict") or "")
            other = next(v for v in verdicts if v != low)
            cause = (
                "its transformed modifier rolls are only decided when equipped"
                if alternatives <= 1 else
                "its displayed modifiers fit several glove modifier combinations and its transformed rolls are only decided when equipped"
            )
            return refuse(f"{cause}, and across the possibilities the verdict changes ({low} and {other})")
        for alternative in range(alternatives):
            measured = [(run["bound"], row) for run, row in rows if run["alternative"] == alternative]
            by_bound = dict(measured)
            trio = [by_bound[bound] for bound in ("worst", "middle", "best") if bound in by_bound]
            # The verdict policy is not order-preserving on its own (e.g. a TRADEOFF
            # pattern forces SIDEGRADE regardless of score), so matching verdicts at
            # the ends prove nothing unless the verdict's whole structure -- pattern,
            # per-axis direction/significance, applied guardrails, quality -- is also
            # identical at every measured roll. With outputs monotone in the rolls,
            # every intermediate roll then shares that structure and verdict.
            if len({_verdict_structure(row) for _, row in measured}) > 1:
                return refuse(
                    "its transformed modifier rolls are only decided when equipped, and across their range "
                    "the comparison changes character (impact pattern or guardrails), so no single verdict "
                    "holds for every roll"
                )
            if len(trio) == 3:
                violations = _roll_monotone_violations(trio)
                if violations:
                    return refuse(
                        "its transformed modifier rolls are only decided when equipped, and Path of Building's "
                        "results are not ordered across the roll range (" + ", ".join(violations[:3]) + "), so no "
                        "verdict can be guaranteed for every roll"
                    )
                for bound, row in measured:
                    if not bound.startswith("flip:"):
                        continue
                    violations = _roll_monotone_violations([trio[0], row, trio[2]])
                    if violations:
                        return refuse(
                            "its transformed modifier rolls are only decided when equipped, and Path of Building's "
                            "results are not ordered when only \"" + bound[len("flip:"):] + "\" changes ("
                            + ", ".join(violations[:3]) + "), so no verdict can be guaranteed for every roll"
                        )
    # Report on the lowest-damage configuration, with the verified range over all of them.
    def primary_pct(result: dict[str, Any]) -> float:
        row = next((r for r in result.get("slot_comparisons") or [] if r.get("pob_slot") in slots), {})
        value = ((row.get("metric_profile") or {}).get("primary_offense") or {}).get("percent_delta")
        return float(value) if value is not None else 0.0

    base = min((run["result"] for run in runs), key=primary_pct)
    flips = sum(1 for run in runs if run["bound"].startswith("flip:"))
    _attach_stonefist_bounds(base, [run["result"] for run in runs], alternatives, flips)
    return base


_UPGRADE_VERDICTS = frozenset({"MINOR_UPGRADE", "MEANINGFUL_UPGRADE", "MAJOR_UPGRADE"})
_DOWNGRADE_VERDICTS = frozenset({"MINOR_DOWNGRADE", "MEANINGFUL_DOWNGRADE", "MAJOR_DOWNGRADE", "STRONG_DOWNGRADE"})


def _pct_text(value: Any) -> str:
    try:
        return f"{float(value):+.1f}%"
    except (TypeError, ValueError):
        return "n/a"


def _attach_stonefist_bounds(
    base: dict[str, Any], results: list[dict[str, Any]], alternatives: int = 1, flips: int = 0,
) -> None:
    """Report a verified impact range over every measured configuration."""
    bounds_by_slot: dict[str, Any] = {}
    presentation = base.get("presentation") or {}
    for row in base.get("slot_comparisons") or []:
        if not ((row.get("item_transform") or {}).get("candidate") or {}).get("ok"):
            continue
        slot = row.get("pob_slot")
        others = [
            r for result in results for r in result.get("slot_comparisons") or [] if r.get("pob_slot") == slot
        ]
        outcome = row.get("evaluation_outcome") or {}
        verdict = str(outcome.get("verdict") or "")
        ranges: dict[str, dict[str, Any]] = {}
        for delta in outcome.get("all_deltas") or []:
            key = str(delta.get("key") or "")
            points = []
            for other in others:
                match = next((d for d in ((other.get("evaluation_outcome") or {}).get("all_deltas") or []) if str(d.get("key")) == key), None)
                if match is not None and match.get("percent_delta") is not None:
                    points.append((float(match["percent_delta"]), match.get("candidate")))
            if not points:
                continue
            low, high = min(points), max(points)
            ranges[key] = {"label": delta.get("label") or key, "worst_pct": low[0], "best_pct": high[0],
                           "worst": low[1], "best": high[1]}
            if abs(high[0] - low[0]) > 1e-9:
                delta["percent_delta_range"] = [low[0], high[0]]
                delta["label"] = f"{delta.get('label') or key} [measured {_pct_text(low[0])} to {_pct_text(high[0])}]"
        offense = ranges.get("primary_offense") or {}
        ehp = ranges.get("ehp") or {}
        parts = []
        if offense:
            parts.append(f"{offense['label']} {_pct_text(offense['worst_pct'])} to {_pct_text(offense['best_pct'])}")
        if ehp:
            parts.append(f"EHP {_pct_text(ehp['worst_pct'])} to {_pct_text(ehp['best_pct'])}")
        guarantee = (
            "an upgrade at each measured roll" if verdict in _UPGRADE_VERDICTS
            else "a downgrade at each measured roll" if verdict in _DOWNGRADE_VERDICTS
            else f"{verdict.replace('_', ' ').lower()} at each measured roll"
        )
        cause = "rolls this glove's transformed modifiers when it is equipped"
        if alternatives > 1:
            cause = f"turns this glove into one of {alternatives} possible items (its lines fit several modifier combinations) and rolls their transformed modifiers when equipped"
        summary = (
            f"Way of the Stonefist {cause}. Path of Building measured the lowest, middle and highest possible rolls"
            + (" of each" if alternatives > 1 else "")
            + (", and each ranged modifier alone at its highest roll" if flips else "")
            + ": " + ("; ".join(parts) or "the listed changes")
            + f". The verdict was {guarantee}; rolls in between were not measured individually."
        )
        note = {"code": "STONEFIST_ROLL_DEPENDENT", "detail": summary}
        bounds = {
            "verdict": verdict,
            "guarantee": guarantee,
            "summary": summary,
            "ranges": ranges,
            "alternatives": alternatives,
            "verified_configurations": len(others),
            "single_roll_probes": flips,
        }
        row["stonefist_roll_bounds"] = bounds
        bounds_by_slot[str(slot)] = bounds
        for target in (outcome, presentation.get("evaluation_outcome")):
            if isinstance(target, dict):
                notes = [r for r in (target.get("unsupported_or_unmodeled") or []) if r.get("code") != note["code"]]
                target["unsupported_or_unmodeled"] = notes + [dict(note)]
        if isinstance(presentation.get("evaluation_outcome"), dict):
            presentation["evaluation_outcome"]["all_deltas"] = outcome.get("all_deltas")
    if bounds_by_slot:
        base["stonefist_roll_bounds"] = bounds_by_slot
        slot_bounds = bounds_by_slot.get(str((base.get("recommendation") or {}).get("pob_slot"))) or next(iter(bounds_by_slot.values()))
        presentation["roll_dependent"] = True
        presentation["stonefist_roll_bounds"] = slot_bounds
        explanation = str(presentation.get("verdict_explanation") or "")
        presentation["verdict_explanation"] = f"{slot_bounds['summary']} {explanation}".strip()
        for impact in presentation.get("impact_rows") or []:
            match = slot_bounds["ranges"].get(str(impact.get("key") or ""))
            if match and abs(float(match["worst_pct"]) - float(match["best_pct"])) > 1e-9:
                impact["delta_text"] = f"{_pct_text(match['worst_pct'])} to {_pct_text(match['best_pct'])}"


# Public name for the classifier: the controller applies it at the recognition
# boundary too, where a localized clipboard is rejected before PoB is ever asked.
classify_localization_failure = _classify_localization_failure
