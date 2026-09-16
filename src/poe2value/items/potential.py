"""Lazy upgrade potential analysis via bounded blocker-first PoB probes."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from poe2value.analysis.catalog import ProbeCatalog
from poe2value.analysis.probes import ProbeEngine, clone_item_with_mods, detect_breakpoints, score_probe_metrics
from poe2value.items.blocker_solver import (
    RepairVector,
    UpgradePathResultKind,
    analyze_blockers,
    blocker_why_lines,
    build_repair_vector,
    format_not_close_reason,
)
from poe2value.items.decision import RecommendationStyle
from poe2value.items.item_check_settings import UpgradePotentialMode
from poe2value.items.upgrade_path import (
    UpgradePathState,
    build_why_not_upgrade,
    classify_upgrade_path_state,
)
from poe2value.items.offense_coverage import PotentialDimensionEvidence, dimension_eligible
from poe2value.items.value_layer import parse_profile
from poe2value.items.value_profiles import ValueProfile


ANALYZER_VERSION = 4
MAX_SECONDARY_DIMENSIONS = 3
MAX_SECONDARY_STEPS = 5
MAX_TOTAL_PROBES_AUTO = 20
MAX_TOTAL_PROBES_DEEP = 26
NEAR_MISS_RATING_GAP = 8.0
_UPGRADE_VERDICTS = frozenset({"STRONG_UPGRADE", "CLEAR_UPGRADE", "OFFENSE_UPGRADE", "DEFENSE_UPGRADE"})
_NEAR_MISS_RATING_LOW = 42.0


@dataclass
class UpgradePotentialResult:
    status: str
    slot: str
    product_state: str = UpgradePathState.PENDING.value
    solver_kind: str = ""
    probes_run: int = 0
    pob_recalcs: int = 0
    paths_tested: int = 0
    repair_targets: list[dict[str, Any]] = field(default_factory=list)
    thresholds: list[dict[str, Any]] = field(default_factory=list)
    paths: list[dict[str, Any]] = field(default_factory=list)
    tested_dimensions: list[dict[str, Any]] = field(default_factory=list)
    blockers: list[dict[str, Any]] = field(default_factory=list)
    repair_vector: list[dict[str, Any]] = field(default_factory=list)
    repaired_rating: float | None = None
    repaired_verdict: str = ""
    secondary_attempted: list[str] = field(default_factory=list)
    not_close_reason: str = ""
    why_not_upgrade: list[dict[str, Any]] = field(default_factory=list)
    craft_legality_verified: bool = False
    near_miss: bool = False
    message: str = ""
    progress_phase: str = ""
    elapsed_ms: float = 0.0
    analyzer_version: int = ANALYZER_VERSION
    dimension_eligibility: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "slot": self.slot,
            "product_state": self.product_state,
            "solver_kind": self.solver_kind,
            "probes_run": self.probes_run,
            "pob_recalcs": self.pob_recalcs,
            "paths_tested": self.paths_tested,
            "repair_targets": self.repair_targets,
            "thresholds": self.thresholds,
            "paths": self.paths,
            "tested_dimensions": self.tested_dimensions,
            "blockers": self.blockers,
            "repair_vector": self.repair_vector,
            "repaired_rating": self.repaired_rating,
            "repaired_verdict": self.repaired_verdict,
            "secondary_attempted": self.secondary_attempted,
            "not_close_reason": self.not_close_reason,
            "why_not_upgrade": self.why_not_upgrade,
            "craft_legality_verified": self.craft_legality_verified,
            "near_miss": self.near_miss,
            "message": self.message,
            "progress_phase": self.progress_phase,
            "elapsed_ms": round(self.elapsed_ms, 2),
            "analyzer_version": self.analyzer_version,
            "dimension_eligibility": self.dimension_eligibility,
        }


class UpgradePotentialAnalyzer:
    def __init__(self, engine: Any, *, catalog: ProbeCatalog | None = None, cache: dict[str, dict[str, Any]] | None = None) -> None:
        self.engine = engine
        self.catalog = catalog or ProbeCatalog()
        self.probe_engine = ProbeEngine(engine, catalog=self.catalog)
        self._cache = cache if cache is not None else {}
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def reset_cancel(self) -> None:
        self._cancelled = False

    def _cache_key(
        self,
        *,
        slot: str,
        item_raw: str,
        fingerprint: str,
        profile: str,
        style: str,
    ) -> str:
        return f"{fingerprint}|{slot}|{hash(item_raw)}|{profile}|{style}|v{ANALYZER_VERSION}"

    def should_auto_run(
        self,
        result: dict[str, Any],
        *,
        mode: str = UpgradePotentialMode.AUTO.value,
        deep: bool = False,
        style: str = RecommendationStyle.BALANCED.value,
        market_capture_active: bool = False,
        loot_review_active: bool = False,
    ) -> bool:
        normalized = str(mode or UpgradePotentialMode.AUTO.value).upper()
        if normalized in {UpgradePotentialMode.OFF.value, UpgradePotentialMode.MANUAL.value}:
            return False
        if market_capture_active:
            return False
        immediate = classify_upgrade_path_state(result, style=style)
        if immediate in {UpgradePathState.ALREADY_UPGRADE.value, UpgradePathState.BUILD_REPAIR.value}:
            return False
        if loot_review_active and immediate not in {
            UpgradePathState.NEAR_MISS.value,
            UpgradePathState.TRADEOFF.value,
            UpgradePathState.REPAIRABLE_DOWNGRADE.value,
        }:
            return False
        if immediate == UpgradePathState.NOT_CLOSE.value and not deep and normalized != UpgradePotentialMode.AUTO_DEEP.value:
            return False
        return True

    def build_immediate(
        self,
        *,
        slot: str,
        result: dict[str, Any],
        profile: str = "BALANCED",
        style: str = RecommendationStyle.BALANCED.value,
        pending: bool = False,
    ) -> UpgradePotentialResult:
        recommendation = result.get("recommendation") or {}
        fingerprint = str(((recommendation.get("baseline") or {}).get("fingerprint_hash")) or "")
        raw_text = str((result.get("raw_input") or {}).get("raw_text") or "")
        selected = parse_profile(profile)
        cache_key = self._cache_key(slot=slot, item_raw=raw_text, fingerprint=fingerprint, profile=selected.value, style=style)
        cached = self._cache.get(cache_key)
        if cached is not None and not pending:
            return UpgradePotentialResult(**cached)

        product_state = classify_upgrade_path_state(result, style=style)
        why_not = build_why_not_upgrade(result)
        if product_state == UpgradePathState.ALREADY_UPGRADE.value:
            return UpgradePotentialResult(
                status="COMPLETE",
                slot=slot,
                product_state=product_state,
                solver_kind=UpgradePathResultKind.ALREADY_UPGRADE.value,
                why_not_upgrade=why_not,
                message="Already an upgrade. No repair required.",
                craft_legality_verified=False,
            )
        if product_state == UpgradePathState.BUILD_REPAIR.value:
            return UpgradePotentialResult(
                status="COMPLETE",
                slot=slot,
                product_state=product_state,
                why_not_upgrade=why_not,
                message="Already fixes build constraint.",
                craft_legality_verified=False,
            )
        if product_state == UpgradePathState.NOT_CLOSE.value and not pending:
            return UpgradePotentialResult(
                status="COMPLETE",
                slot=slot,
                product_state=product_state,
                solver_kind=UpgradePathResultKind.NOT_CLOSE.value,
                why_not_upgrade=why_not,
                not_close_reason="Not close within tested bounds.",
                message="Not close within tested bounds.",
                craft_legality_verified=False,
            )
        return UpgradePotentialResult(
            status="PENDING" if pending else "QUEUED",
            slot=slot,
            product_state=UpgradePathState.PENDING.value,
            why_not_upgrade=why_not,
            message="Analyzing main blocker...",
            progress_phase="identify_blockers",
            craft_legality_verified=False,
        )

    def analyze(
        self,
        *,
        slot: str,
        item_raw: str,
        result: dict[str, Any],
        profile: str = "BALANCED",
        style: str = RecommendationStyle.BALANCED.value,
        deep: bool = False,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> UpgradePotentialResult:
        started = time.perf_counter()
        self.reset_cancel()
        recommendation = result.get("recommendation") or {}
        offense_coverage = result.get("offense_coverage") or recommendation.get("offense_coverage") or {}
        baseline_raw = ((recommendation.get("baseline") or {}).get("metrics")) or {}
        candidate_raw = ((recommendation.get("candidate") or {}).get("metrics")) or {}
        fingerprint = str(((recommendation.get("baseline") or {}).get("fingerprint_hash")) or "")
        selected = parse_profile(profile)
        cache_key = self._cache_key(slot=slot, item_raw=item_raw, fingerprint=fingerprint, profile=selected.value, style=style)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return UpgradePotentialResult(**cached)

        immediate = self.build_immediate(slot=slot, result=result, profile=profile, style=style, pending=False)
        if immediate.status == "COMPLETE" and immediate.product_state in {
            UpgradePathState.ALREADY_UPGRADE.value,
            UpgradePathState.BUILD_REPAIR.value,
            UpgradePathState.NOT_CLOSE.value,
        }:
            self._cache[cache_key] = immediate.__dict__
            return immediate

        slot_label = str((result.get("best_slot") or {}).get("label") or recommendation.get("pob_slot") or slot)
        why_not = build_why_not_upgrade(result)
        blockers = analyze_blockers(recommendation, baseline_raw, candidate_raw)
        why_not = _merge_why_not(why_not, blocker_why_lines(blockers, slot_label=slot_label))
        repair_vector = build_repair_vector(blockers, catalog=self.catalog)
        repair_targets = [item.to_dict() for item in blockers if item.repairable and item.repair_target > 0]
        max_total = MAX_TOTAL_PROBES_DEEP if deep else MAX_TOTAL_PROBES_AUTO
        probes_run = 0
        paths: list[dict[str, Any]] = []
        solver_kind = UpgradePathResultKind.UNSUPPORTED.value
        repaired_rating: float | None = None
        repaired_verdict = ""
        secondary_attempted: list[str] = []
        remaining_losses = _remaining_loss_labels(blockers, repair_vector)
        dimension_eligibility: list[dict[str, Any]] = []

        if on_progress:
            on_progress({"phase": "identify_blockers", "blockers": len(blockers), "completed": 0, "total": max_total})

        if not repair_vector.repairs:
            payload = UpgradePotentialResult(
                status="COMPLETE",
                slot=slot,
                product_state=UpgradePathState.NOT_CLOSE.value,
                solver_kind=UpgradePathResultKind.UNSUPPORTED.value,
                blockers=[item.to_dict() for item in blockers],
                repair_targets=repair_targets,
                why_not_upgrade=why_not,
                not_close_reason="No supported repair dimension detected.",
                message="No supported repair dimension detected",
                craft_legality_verified=False,
                elapsed_ms=(time.perf_counter() - started) * 1000,
            )
            self._cache[cache_key] = payload.__dict__
            return payload

        if on_progress:
            on_progress(
                {
                    "phase": "verify_repair",
                    "message": "Testing resistance repair...",
                    "completed": probes_run,
                    "total": max_total,
                }
            )
        repair_sample = self._run_vector_probe(
            slot,
            item_raw,
            repair_vector,
            baseline_raw,
            selected,
            style=style,
        )
        probes_run += 1
        paths_tested = 1
        if repair_sample.get("status") == "ok":
            repaired_rating = float(repair_sample.get("rating") or 0)
            repaired_verdict = str(repair_sample.get("verdict") or "")
            if repaired_verdict in _UPGRADE_VERDICTS:
                solver_kind = (
                    UpgradePathResultKind.MULTI_BLOCKER_REPAIR_UPGRADE.value
                    if len(repair_vector.repairs) > 1
                    else UpgradePathResultKind.SINGLE_REPAIR_UPGRADE.value
                )
                paths = _finalize_paths(repair_vector, repair_sample, secondary=None)
            else:
                secondary_dims = _select_secondary_dimensions(
                    recommendation,
                    baseline_raw,
                    candidate_raw,
                    repair_vector,
                    blockers,
                    max_dims=MAX_SECONDARY_DIMENSIONS,
                    offense_coverage=offense_coverage,
                )
                dimension_eligibility = list(secondary_dims.get("eligibility") or [])
                best_combined = None
                for target in secondary_dims.get("targets") or []:
                    if self._cancelled or probes_run >= max_total:
                        break
                    probe_id = str(target.get("probe_id") or "")
                    definition = self.catalog.get(probe_id)
                    if definition is None:
                        continue
                    secondary_attempted.append(str(target.get("label") or probe_id))
                    low = 0.0
                    high = float(target.get("needed") or definition.default_magnitude)
                    high = min(high, 60.0)
                    steps = 0
                    while steps < MAX_SECONDARY_STEPS and high - low > 1.0 and probes_run < max_total:
                        if self._cancelled:
                            break
                        mid = round((low + high) / 2.0, 1)
                        probes_run += 1
                        paths_tested += 1
                        if on_progress:
                            on_progress(
                                {
                                    "phase": "secondary_search",
                                    "probe_id": probe_id,
                                    "magnitude": mid,
                                    "completed": probes_run,
                                    "total": max_total,
                                }
                            )
                        sample = self._run_vector_probe(
                            slot,
                            item_raw,
                            repair_vector,
                            baseline_raw,
                            selected,
                            style=style,
                            secondary_probe_id=probe_id,
                            secondary_magnitude=mid,
                        )
                        if sample.get("status") != "ok":
                            break
                        if sample.get("verdict") in _UPGRADE_VERDICTS:
                            best_combined = {
                                "probe_id": probe_id,
                                "label": definition.label,
                                "unit": definition.unit,
                                "magnitude": mid,
                                "score_delta": sample.get("score_delta"),
                                "result_rating": sample.get("rating"),
                                "consequence": sample.get("consequence"),
                                "craft_legality_verified": False,
                            }
                            high = mid
                        else:
                            low = mid
                        steps += 1
                    if best_combined:
                        solver_kind = UpgradePathResultKind.REPAIR_PLUS_SECONDARY.value
                        paths = _finalize_paths(repair_vector, repair_sample, secondary=best_combined)
                        break

        rating = float(((recommendation.get("value") or {}).get("rating")) or 0)
        near_miss = _NEAR_MISS_RATING_LOW <= rating < 50 + NEAR_MISS_RATING_GAP
        if paths:
            product_state = UpgradePathState.NEAR_MISS.value if near_miss else UpgradePathState.TRADEOFF.value
            message = "Threshold probes complete"
        else:
            product_state = UpgradePathState.NOT_CLOSE.value
            solver_kind = UpgradePathResultKind.NOT_CLOSE.value
            message = format_not_close_reason(
                repair_vector=repair_vector,
                repaired_rating=repaired_rating,
                repaired_verdict=repaired_verdict or None,
                secondary_attempted=secondary_attempted,
                remaining_losses=remaining_losses,
            )

        payload = UpgradePotentialResult(
            status="COMPLETE",
            slot=slot,
            product_state=product_state,
            solver_kind=solver_kind,
            probes_run=probes_run,
            pob_recalcs=self.probe_engine.pob_recalcs,
            paths_tested=paths_tested,
            repair_targets=repair_targets,
            thresholds=paths,
            paths=paths,
            tested_dimensions=repair_vector.repairs,
            blockers=[item.to_dict() for item in blockers],
            repair_vector=repair_vector.repairs,
            repaired_rating=repaired_rating,
            repaired_verdict=repaired_verdict,
            secondary_attempted=secondary_attempted,
            not_close_reason=message if product_state == UpgradePathState.NOT_CLOSE.value else "",
            craft_legality_verified=False,
            near_miss=near_miss,
            why_not_upgrade=why_not,
            message=message,
            elapsed_ms=(time.perf_counter() - started) * 1000,
            dimension_eligibility=dimension_eligibility,
        )
        self._cache[cache_key] = payload.__dict__
        return payload

    def _run_vector_probe(
        self,
        slot: str,
        item_raw: str,
        repair_vector: RepairVector,
        baseline_raw: dict[str, Any],
        profile: ValueProfile,
        *,
        style: str = RecommendationStyle.BALANCED.value,
        secondary_probe_id: str | None = None,
        secondary_magnitude: float | None = None,
    ) -> dict[str, Any]:
        lines = repair_vector.mod_lines(self.catalog)
        secondary_probe = None
        if secondary_probe_id and secondary_magnitude is not None:
            secondary_probe = self.catalog.get(secondary_probe_id)
            if secondary_probe is not None:
                lines.append(secondary_probe.line(float(secondary_magnitude)))
        if not lines:
            return {"status": "REJECTED", "message": "empty repair vector"}
        probed_raw_item = clone_item_with_mods(item_raw, lines)
        try:
            evaluation = self.engine.evaluate_candidate(slot, probed_raw_item)
        except Exception as exc:
            return {"status": "REJECTED", "message": str(exc)}
        self.probe_engine.pob_recalcs += 1
        restore = evaluation.get("restore") or {}
        if not restore.get("pass"):
            return {"status": "RESTORE_FAILED", "restore": restore}
        scored = score_probe_metrics(
            evaluation["baseline"]["metrics"],
            evaluation["candidate"]["metrics"],
            profile,
        )
        probe_id = secondary_probe_id or (repair_vector.repairs[0]["probe_id"] if repair_vector.repairs else "")
        verdict = str(scored.get("verdict") or "")
        rating = float((scored.get("value") or {}).get("rating") or 0)
        consequence = _probe_consequence(scored.get("resist_caps") or {}, str(probe_id), verdict)
        return {
            "status": "ok",
            "probe_id": probe_id,
            "score_delta": scored["value"]["score_delta"],
            "rating": rating,
            "verdict": verdict,
            "resist_caps": scored["resist_caps"],
            "breakpoints": detect_breakpoints(scored["resist_caps"], str(probe_id)),
            "consequence": consequence,
        }


def _finalize_paths(
    repair_vector: RepairVector,
    repair_sample: dict[str, Any],
    *,
    secondary: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    paths = repair_vector.path_entries()
    for entry in paths:
        entry["result_rating"] = repair_sample.get("rating")
        entry["consequence"] = repair_sample.get("consequence") or "blocker repaired"
    if secondary:
        secondary_entry = dict(secondary)
        secondary_entry["step"] = 2
        secondary_entry["kind"] = "secondary"
        paths.append(secondary_entry)
    return paths


def _merge_why_not(base: list[dict[str, Any]], extra: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = list(base)
    seen = {str(item.get("explanation") or "") for item in base}
    for item in extra:
        key = str(item.get("explanation") or "")
        if key and key not in seen:
            merged.append(item)
            seen.add(key)
    return merged[:4]


def _remaining_loss_labels(blockers: list[Any], repair_vector: RepairVector) -> list[str]:
    repaired_metrics = {str(item.get("probe_id") or "") for item in repair_vector.repairs}
    labels: list[str] = []
    for blocker in blockers:
        if blocker.repairable and blocker.probe_id in repaired_metrics:
            continue
        if blocker.blocker_type in {
            "EHP_REGRESSION",
            "MAX_HIT_REGRESSION",
            "LIFE_REGRESSION",
            "ENERGY_SHIELD_REGRESSION",
            "RESOURCE_REGRESSION",
        }:
            labels.append(blocker.label or blocker.metric)
    return labels[:4]


def _select_secondary_dimensions(
    recommendation: dict[str, Any],
    baseline_raw: dict[str, Any],
    candidate_raw: dict[str, Any],
    repair_vector: RepairVector,
    blockers: list[Any],
    *,
    max_dims: int,
    offense_coverage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    repaired_ids = {str(item.get("probe_id") or "") for item in repair_vector.repairs}
    blocker_by_probe = {
        str(item.probe_id): item for item in blockers if getattr(item, "probe_id", None) and item.repairable
    }
    targets: list[dict[str, Any]] = []
    eligibility: list[dict[str, Any]] = []
    mapping = [
        ("Life", "LIFE", "Maximum Life", 8.0),
        ("EnergyShield", "ENERGY_SHIELD", "Energy Shield", 8.0),
        ("Mana", "MANA", "Mana", 15.0),
    ]
    for field, probe_id, label, min_loss in mapping:
        evidence = str((offense_coverage or {}).get("dimension_evidence", {}).get(probe_id) or PotentialDimensionEvidence.SUPPORTED.value)
        eligibility.append({"probe_id": probe_id, "evidence": evidence, "reason": ""})
        if probe_id in repaired_ids:
            continue
        before = float(baseline_raw.get(field) or 0)
        after = float(candidate_raw.get(field) or 0)
        loss = before - after
        blocker = blocker_by_probe.get(probe_id)
        if loss >= min_loss and blocker is not None:
            targets.append(
                {
                    "probe_id": probe_id,
                    "label": label,
                    "needed": loss,
                    "priority": 0,
                    "blocker": blocker.to_dict(),
                }
            )
    cast_eligible, cast_reason = dimension_eligible(offense_coverage, "CAST_SPEED")
    cast_evidence = str((offense_coverage or {}).get("dimension_evidence", {}).get("CAST_SPEED") or PotentialDimensionEvidence.SUPPORTED.value)
    eligibility.append({"probe_id": "CAST_SPEED", "evidence": cast_evidence, "reason": cast_reason})
    metrics = recommendation.get("normalized_metrics") or recommendation.get("metric_profile") or {}
    offense = metrics.get("primary_offense") or {}
    if cast_eligible and "CAST_SPEED" not in repaired_ids:
        needed = 12.0 if float(offense.get("absolute_delta") or 0) < 0 else 10.0
        priority = 1 if float(offense.get("absolute_delta") or 0) < 0 else 2
        targets.append({"probe_id": "CAST_SPEED", "label": "Cast Speed", "needed": needed, "priority": priority})
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in sorted(targets, key=lambda row: row.get("priority", 50)):
        probe_id = str(item.get("probe_id") or "")
        if not probe_id or probe_id in seen:
            continue
        seen.add(probe_id)
        deduped.append(item)
        if len(deduped) >= max_dims:
            break
    return {"targets": deduped, "eligibility": eligibility}


def _probe_consequence(resist: dict[str, Any], probe_id: str, verdict: str) -> str:
    if probe_id.endswith("_RES"):
        element = probe_id.replace("_RES", "").lower()
        info = (resist.get("elements") or {}).get(element) or {}
        state = info.get("state")
        if state in {"CAP_REACHED", "CAPPED_STAYS_CAPPED", "CAP_GAINED"}:
            return f"{element.title()} cap restored"
        if state in {"BELOW_CAP_IMPROVED", "BELOW_CAP_UNCHANGED"}:
            return f"{element.title()} restored vs current"
    if verdict in _UPGRADE_VERDICTS:
        return "clean upgrade"
    return ""
