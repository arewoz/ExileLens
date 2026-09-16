from __future__ import annotations

import time
from typing import Any, Callable

from poe2value.analysis.audit import BuildNeed, BuildStateAudit, build_state_audit
from poe2value.analysis.cache import ProbeCache
from poe2value.analysis.catalog import ProbeCatalog
from poe2value.analysis.identity import AnalysisBaseline
from poe2value.analysis.opportunity import (
    SAFE_CONTRIBUTION_SLOTS,
    WEAPON_PRODUCT_SLOTS,
    score_slot_opportunity,
)
from poe2value.analysis.probes import ProbeEngine
from poe2value.analysis.search_intent import build_search_intent
from poe2value.analysis.slot_compat import load_slot_compat, slot_compatibility
from poe2value.errors import EngineError
from poe2value.items.primary_metric import resolve_primary_metric
from poe2value.items.slots import EVALUABLE_POB_SLOTS, pob_slot_to_product
from poe2value.items.value_profiles import ValueProfile

YieldFn = Callable[[], bool]
ProgressFn = Callable[[dict[str, Any]], None]


def _equipment_map(equipment_payload: Any) -> dict[str, dict[str, Any]]:
    if isinstance(equipment_payload, dict):
        rows = equipment_payload.get("equipment") or equipment_payload.get("slots") or []
    else:
        rows = equipment_payload or []
    mapping: dict[str, dict[str, Any]] = {}
    for row in rows:
        if isinstance(row, dict) and row.get("slot"):
            mapping[str(row["slot"])] = row
    return mapping


def _strip_explicits(item_raw: str) -> str:
    lines = item_raw.replace("\r\n", "\n").split("\n")
    implicits = 0
    implicit_index = None
    for idx, line in enumerate(lines):
        if line.startswith("Implicits:"):
            try:
                implicits = int(line.split(":", 1)[1].strip() or "0")
            except ValueError:
                implicits = 0
            implicit_index = idx
            break
    if implicit_index is None:
        return "\n".join(lines[:4]) + "\n"
    end = implicit_index + 1 + implicits
    return "\n".join(lines[:end]).rstrip() + "\n"


def _compat_sets(pob_path: str) -> dict[str, set[str]]:
    table = load_slot_compat(pob_path)
    return {probe_id: set(info.get("slots") or []) for probe_id, info in table.items()}


def _carrier(equipment: dict[str, dict[str, Any]]) -> tuple[str, str] | None:
    for slot in ("Ring 1", "Ring 2", "Amulet", "Belt", "Helmet", "Gloves", "Boots", "Body Armour"):
        row = equipment.get(slot)
        raw = (row or {}).get("raw") or ""
        if row and row.get("equipped") and raw.strip():
            return slot, raw
    return None


def _product_for_pob(pob_slot: str, item_type: str | None) -> str:
    try:
        return pob_slot_to_product(pob_slot, item_type=item_type).value
    except KeyError:
        return pob_slot.upper().replace(" ", "_")


class AnalysisYielded(Exception):
    def __init__(self, state: dict[str, Any]):
        super().__init__("analysis yielded to gameplay")
        self.state = state


def analyze_build(
    engine: Any,
    *,
    build_path: str,
    context: str = "MAP",
    profile: str | ValueProfile = ValueProfile.BALANCED,
    generation: int = 0,
    loadout: str = "",
    item_set: str = "",
    pob_path: str = "",
    cache: ProbeCache | None = None,
    catalog: ProbeCatalog | None = None,
    should_yield: YieldFn | None = None,
    on_progress: ProgressFn | None = None,
    slot_filter: str | None = None,
    resume: dict[str, Any] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    selected = profile if isinstance(profile, ValueProfile) else ValueProfile(str(profile).upper())
    catalog = catalog or ProbeCatalog()
    cache = cache or ProbeCache()
    probes = ProbeEngine(engine, catalog=catalog, cache=cache)

    if hasattr(engine, "ensure_build_ready"):
        loaded = engine.ensure_build_ready(build_path, context=context)
    else:
        loaded = engine.load_build(build_path, context=context)
    from poe2value.baseline import apply_engine_identity

    apply_engine_identity(engine, loadout=loadout, item_set=item_set)
    metrics = engine.get_metrics(context)
    equipment = _equipment_map(engine.get_equipment())
    fingerprint = str(metrics.get("fingerprint_hash") or loaded.get("fingerprint_hash") or "")
    raw = metrics.get("raw") or metrics.get("metrics") or {}
    if not raw and "CombinedDPS" in metrics:
        raw = metrics
    build_info = {}
    if hasattr(engine, "get_build_info"):
        try:
            build_info = engine.get_build_info() or {}
        except Exception:
            build_info = loaded.get("build") or {}
    build_blob = build_info.get("build") if isinstance(build_info.get("build"), dict) else build_info
    build_name = str(build_blob.get("name") or build_blob.get("build_name") or loaded.get("build", {}).get("name") or loaded.get("build", {}).get("build_name") or "")
    primary = resolve_primary_metric(build_blob, raw)
    audit = build_state_audit(
        raw,
        primary_field=primary.pob_field,
        primary_confidence=primary.confidence.value,
    )
    baseline = AnalysisBaseline(
        build_path=str(build_path),
        build_name=build_name,
        loadout=loadout,
        item_set=item_set,
        context=context,
        profile=selected.value,
        generation=generation,
        fingerprint=fingerprint,
    )
    carrier = _carrier(equipment)
    skipped: list[dict[str, Any]] = []
    global_probes: list[dict[str, Any]] = []
    compat_sets = _compat_sets(pob_path) if pob_path else {}

    def progress(stage: str, **extra: Any) -> None:
        if on_progress:
            on_progress({"stage": stage, **extra})

    def check_yield(state: dict[str, Any]) -> None:
        if should_yield and should_yield():
            raise AnalysisYielded(state)

    progress("audit")
    state = resume or {"stage": "stage2", "global_probes": [], "slot_results": {}}

    if carrier:
        carrier_slot, carrier_raw = carrier
        # Stage 2: generic high-value families on a jewellery/armour carrier.
        for probe_id in catalog.stage2_ids():
            check_yield({"stage": "stage2", "global_probes": global_probes})
            definition = catalog.get(probe_id)
            if definition is None:
                skipped.append({"probe_id": probe_id, "reason": "unknown"})
                continue
            result = probes.run_probe(
                slot=carrier_slot,
                item_raw=carrier_raw,
                probe_id=probe_id,
                magnitude=definition.default_magnitude,
                baseline=baseline,
                profile=selected,
                primary_field=audit.primary_field,
                primary_confidence=audit.primary_confidence,
                context=context,
            )
            global_probes.append(result)
            progress("probe", probe_id=probe_id, slot=carrier_slot)

        # Exact deficit resistance probes.
        for need in audit.needs:
            if need.code not in {"RES_CAP_MISSING", "LOW_CHAOS_RES"} or not need.deficit:
                continue
            probe_id = {
                "fire_res": "FIRE_RES",
                "cold_res": "COLD_RES",
                "lightning_res": "LIGHTNING_RES",
                "chaos_res": "CHAOS_RES",
            }.get(need.metric)
            if not probe_id:
                continue
            mag = round(float(need.deficit))
            if mag <= 0:
                continue
            check_yield({"stage": "breakpoint", "global_probes": global_probes})
            result = probes.run_probe(
                slot=carrier_slot,
                item_raw=carrier_raw,
                probe_id=probe_id,
                magnitude=mag,
                baseline=baseline,
                profile=selected,
                primary_field=audit.primary_field,
                primary_confidence=audit.primary_confidence,
                context=context,
            )
            result["breakpoint_exact"] = True
            result["CAP_REACHED_AT"] = mag
            global_probes.append(result)

        # Selective nonlinearity for the strongest offense family.
        offense_ranked = sorted(
            [p for p in global_probes if p.get("family") == "offense" and p.get("status") == "ok"],
            key=lambda row: abs(float(row.get("score_delta") or 0)),
            reverse=True,
        )
        if offense_ranked:
            top = offense_ranked[0]["probe_id"]
            definition = catalog.get(top)
            if definition and definition.nonlinear_sampling:
                check_yield({"stage": "nonlinear", "global_probes": global_probes})
                curve = probes.sample_nonlinear(
                    slot=carrier_slot,
                    item_raw=carrier_raw,
                    probe_id=top,
                    baseline=baseline,
                    profile=selected,
                    should_yield=should_yield,
                    primary_field=audit.primary_field,
                    primary_confidence=audit.primary_confidence,
                    context=context,
                )
                for sample in curve["samples"]:
                    if sample not in global_probes and sample.get("magnitude") != catalog.require(top).default_magnitude:
                        global_probes.append({**sample, "nonlinear_sample": True})
                global_probes.append({"probe_id": top, "status": "curve", "linearity": curve["linearity"], "samples": curve["samples"]})
    else:
        skipped.append({"probe_id": "*", "reason": "no_safe_carrier"})

    if not carrier:
        # Attach MOVEMENT/OFFENSE needs only when probes exist.
        pass
    else:
        move = next((p for p in global_probes if p.get("probe_id") == "MOVEMENT_SPEED" and p.get("status") == "ok"), None)
        if move and float(move.get("score_delta") or 0) >= 4:
            audit.needs.append(
                BuildNeed(
                    code="MOVEMENT_OPPORTUNITY",
                    severity="medium",
                    metric="movement_speed",
                    current=audit.utility.get("movement_speed"),
                    target=None,
                    deficit=None,
                    explanation="Movement speed has meaningful mapping value on this baseline.",
                    confidence="medium",
                )
            )
        offense_probe = next((p for p in global_probes if p.get("family") == "offense" and float(p.get("score_delta") or 0) >= 6), None)
        if offense_probe:
            audit.needs.append(
                BuildNeed(
                    code="OFFENSE_OPPORTUNITY",
                    severity="medium",
                    metric=str(offense_probe.get("probe_id")),
                    current=audit.offense.get("primary"),
                    target=None,
                    deficit=None,
                    explanation=f"{offense_probe.get('display_name')} has high marginal value.",
                    confidence=str(offense_probe.get("confidence") or "medium").lower(),
                )
            )

    slot_results: list[dict[str, Any]] = []
    equipped_slots = [
        (pob_slot, row)
        for pob_slot, row in equipment.items()
        if pob_slot in EVALUABLE_POB_SLOTS and row.get("equipped") and (row.get("raw") or "").strip()
    ]

    for pob_slot, row in equipped_slots:
        product_slot = _product_for_pob(pob_slot, row.get("base_name") or row.get("type"))
        if slot_filter and slot_filter not in {product_slot, pob_slot}:
            skipped.append({"slot": product_slot, "reason": "filtered"})
            continue
        limited = product_slot in WEAPON_PRODUCT_SLOTS
        contribution = None
        slot_probe_rows: list[dict[str, Any]] = []
        per_probe_compat: dict[str, dict[str, Any]] = {}

        if limited:
            opportunity = score_slot_opportunity(
                product_slot=product_slot,
                needs=audit.needs,
                slot_probes=[],
                contribution=None,
                compat=compat_sets,
                analysis_limited=True,
            )
            intent = {
                "contract_version": 1,
                "kind": "SearchIntent",
                "slot": product_slot,
                "required": [],
                "high_value": [],
                "useful": [],
                "low_value": [],
                "avoid": [],
                "analysis_limited": True,
                "note": "WEAPON ANALYSIS LIMITED",
                "price": None,
                "network": False,
            }
            slot_results.append(
                {
                    "product_slot": product_slot,
                    "pob_slot": pob_slot,
                    "current_item": {"name": row.get("name"), "base_name": row.get("base_name"), "raw": row.get("raw")},
                    "analysis_limited": True,
                    "contribution": None,
                    "probes": [],
                    "opportunity": opportunity,
                    "search_intent": intent,
                }
            )
            progress("slot", slot=product_slot)
            continue

        item_raw = str(row.get("raw") or "")
        # Stage 3: slot-compatible probes (reuse cache when same carrier/global already ran).
        for definition in catalog.all():
            check_yield({"stage": "slot", "slot": product_slot, "global_probes": global_probes})
            compat = (
                slot_compatibility(definition.probe_id, product_slot, pob_path=pob_path)
                if pob_path
                else {"compatible": True, "confidence": "low"}
            )
            per_probe_compat[definition.probe_id] = compat
            if not compat.get("compatible"):
                skipped.append({"probe_id": definition.probe_id, "slot": product_slot, "reason": "slot_incompatible"})
                continue
            existing = next(
                (
                    p
                    for p in global_probes
                    if p.get("probe_id") == definition.probe_id and p.get("magnitude") == definition.default_magnitude and p.get("status") in {"ok", "NO_SIGNAL", "REJECTED", "UNSUPPORTED_PROBE"}
                ),
                None,
            )
            if existing and existing.get("status") in {"ok", "NO_SIGNAL"}:
                row_probe = {**existing, "slot_compatible": True, "measured_on": existing.get("slot")}
            else:
                row_probe = probes.run_probe(
                    slot=pob_slot,
                    item_raw=item_raw,
                    probe_id=definition.probe_id,
                    magnitude=definition.default_magnitude,
                    baseline=baseline,
                    profile=selected,
                    primary_field=audit.primary_field,
                    primary_confidence=audit.primary_confidence,
                    context=context,
                )
                row_probe["slot_compatible"] = True
            slot_probe_rows.append(row_probe)

        if product_slot in SAFE_CONTRIBUTION_SLOTS:
            try:
                stripped = _strip_explicits(item_raw)
                if stripped.strip() != item_raw.strip():
                    evaluation = engine.evaluate_candidate(pob_slot, stripped, context=context)
                    probes.pob_recalcs += 1
                    from poe2value.analysis.probes import score_probe_metrics

                    scored = score_probe_metrics(
                        evaluation["baseline"]["metrics"],
                        evaluation["candidate"]["metrics"],
                        selected,
                        primary_field=audit.primary_field,
                        primary_confidence=audit.primary_confidence,
                    )
                    warnings = scored.get("warnings") or []
                    if any(w.get("code") == "MAIN_SKILL_INVALID" for w in warnings):
                        contribution = {"status": "invalid", "reason": "neutralized item invalidated skills"}
                    else:
                        offense = (scored["metric_profile"].get("primary_offense") or {}).get("percent_delta")
                        contribution = {
                            "status": "ok",
                            "method": "strip_explicits",
                            "offense_percent": offense,
                            "ehp_percent": (scored["metric_profile"].get("ehp") or {}).get("percent_delta"),
                            "restore": evaluation.get("restore"),
                        }
            except EngineError:
                contribution = {"status": "skipped", "reason": "contribution_failed"}

        opportunity = score_slot_opportunity(
            product_slot=product_slot,
            needs=audit.needs,
            slot_probes=slot_probe_rows,
            contribution=contribution,
            compat=compat_sets,
        )
        intent = build_search_intent(
            baseline=baseline,
            product_slot=product_slot,
            pob_slot=pob_slot,
            needs=audit.needs,
            probes=slot_probe_rows,
            opportunity=opportunity,
            profile=selected,
            slot_compat=per_probe_compat,
        )
        slot_results.append(
            {
                "product_slot": product_slot,
                "pob_slot": pob_slot,
                "current_item": {
                    "name": row.get("name"),
                    "base_name": row.get("base_name"),
                    "raw": row.get("raw"),
                },
                "analysis_limited": False,
                "contribution": contribution,
                "probes": slot_probe_rows,
                "opportunity": opportunity,
                "search_intent": intent,
            }
        )
        progress("slot", slot=product_slot)

    ranked = sorted(
        slot_results,
        key=lambda row: (
            0 if row["opportunity"].get("score") is None else 1,
            -(row["opportunity"].get("score") or -1),
        ),
        reverse=True,
    )
    # sort: limited last, high scores first
    ranked.sort(key=lambda row: (row.get("analysis_limited") is True, -(row["opportunity"].get("score") or -1)))

    elapsed_ms = (time.perf_counter() - started) * 1000
    avg_probe = sum(probes.probe_times_ms) / len(probes.probe_times_ms) if probes.probe_times_ms else 0.0
    result = {
        "baseline": baseline.to_dict(),
        "audit": audit.to_dict(),
        "needs": [need.to_dict() if hasattr(need, "to_dict") else need for need in audit.needs],
        "global_probes": global_probes,
        "slots": ranked,
        "skipped": skipped,
        "performance": {
            "elapsed_ms": elapsed_ms,
            "pob_recalcs": probes.pob_recalcs,
            "probe_count": len(probes.probe_times_ms),
            "average_probe_ms": avg_probe,
            "cache": cache.stats(),
        },
        "stale": False,
        "market": False,
        "network": False,
    }
    return result


def analyze_slot(engine: Any, **kwargs: Any) -> dict[str, Any]:
    slot = kwargs.pop("slot")
    result = analyze_build(engine, slot_filter=slot, **kwargs)
    matches = [row for row in result["slots"] if row["product_slot"] == slot or row["pob_slot"] == slot]
    result["slot"] = matches[0] if matches else None
    return result


def search_intent_for_slot(engine: Any, **kwargs: Any) -> dict[str, Any]:
    result = analyze_slot(engine, **kwargs)
    slot = result.get("slot") or {}
    return slot.get("search_intent") or {"error": "slot_not_found", "network": False, "price": None}


def rescore_analysis(result: dict[str, Any], profile: str | ValueProfile) -> dict[str, Any]:
    """Reuse raw probe metrics; do not call PoB."""
    from poe2value.analysis.probes import score_probe_metrics

    selected = profile if isinstance(profile, ValueProfile) else ValueProfile(str(profile).upper())
    primary_field = (result.get("audit") or {}).get("primary_field") or "CombinedDPS"
    primary_confidence = (result.get("audit") or {}).get("primary_confidence") or "high"

    def _rescore_probe(probe: dict[str, Any]) -> dict[str, Any]:
        if "metric_profile" in probe and "value" in probe and probe.get("status") in {"ok", "NO_SIGNAL"}:
            # Reconstruct from stored metric_profile currents/candidates via existing value? Safer: keep raw if present.
            pass
        if probe.get("baseline_raw") and probe.get("probed_raw"):
            scored = score_probe_metrics(
                probe["baseline_raw"],
                probe["probed_raw"],
                selected,
                primary_field=primary_field,
                primary_confidence=primary_confidence,
            )
            probe = {**probe, **scored, "cache_hit": True}
        elif probe.get("metric_profile") and probe.get("resist_caps") is not None:
            from poe2value.items.value_profiles import score_profile

            probe = dict(probe)
            probe["value"] = score_profile(
                probe["metric_profile"],
                probe.get("resist_caps") or {},
                probe.get("warnings") or [],
                selected,
            )
            probe["score_delta"] = probe["value"]["score_delta"]
        return probe

    updated = dict(result)
    updated["global_probes"] = [_rescore_probe(dict(p)) for p in result.get("global_probes") or []]
    slots = []
    baseline = AnalysisBaseline(**result["baseline"])
    baseline = AnalysisBaseline(**{**baseline.to_dict(), "profile": selected.value})
    from poe2value.analysis.audit import BuildNeed

    needs = [BuildNeed(**need) if isinstance(need, dict) else need for need in result.get("needs") or []]
    pob_path = ""
    for slot in result.get("slots") or []:
        slot = dict(slot)
        slot["probes"] = [_rescore_probe(dict(p)) for p in slot.get("probes") or []]
        if slot.get("analysis_limited"):
            slots.append(slot)
            continue
        compat = {p["probe_id"]: {"compatible": p.get("slot_compatible", False)} for p in slot["probes"] if p.get("probe_id")}
        slot["opportunity"] = score_slot_opportunity(
            product_slot=slot["product_slot"],
            needs=needs,
            slot_probes=slot["probes"],
            contribution=slot.get("contribution"),
            compat={k: {slot["product_slot"]} if v.get("compatible") else set() for k, v in compat.items()},
        )
        slot["search_intent"] = build_search_intent(
            baseline=baseline,
            product_slot=slot["product_slot"],
            pob_slot=slot["pob_slot"],
            needs=needs,
            probes=slot["probes"],
            opportunity=slot["opportunity"],
            profile=selected,
            slot_compat=compat,
        )
        slots.append(slot)
    updated["slots"] = slots
    updated["baseline"] = baseline.to_dict()
    return updated
