from __future__ import annotations

import itertools
import time
from dataclasses import dataclass
from typing import Any, Callable

from poe2value.gear.budget_curve import build_budget_curve
from poe2value.gear.cache import GearPlanEvalCache
from poe2value.gear.categories import assign_plan_categories
from poe2value.gear.constraints import check_plan_constraints, safe_partial_prune
from poe2value.gear.models import (
    GEAR_SEARCH_LIMITS,
    KEEP_CURRENT_ID,
    GearPlan,
    GearPlanEvaluation,
    GearPlanReplacement,
    GearSearchPreset,
)
from poe2value.gear.pareto import compute_plan_pareto_frontier
from poe2value.gear.transaction import evaluate_gear_plan, normalized_listing_price
from poe2value.market.currency import CurrencyRateTable
from poe2value.market.models import CandidateIdentity, CandidateListing, ListingPrice, MarketCandidatePool


YieldFn = Callable[[], bool]
ProgressFn = Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class SlotChoice:
    product_slot: str
    pob_slot: str
    listing: CandidateListing | None
    item_raw: str
    price: ListingPrice | None
    keep_current: bool
    heuristic_score: float = 0.0


def _keep_choice(product_slot: str, pob_slot: str, baseline_raw: str) -> SlotChoice:
    return SlotChoice(
        product_slot=product_slot,
        pob_slot=pob_slot,
        listing=None,
        item_raw=baseline_raw,
        price=None,
        keep_current=True,
        heuristic_score=0.0,
    )


from poe2value.market.models import MarketCandidateResult


def _diversity_shortlist(pool: MarketCandidatePool, shortlist: int) -> list[MarketCandidateResult]:
    ok = [row for row in pool.candidates if row.evaluation.status == "ok" and row.evaluation.restore_pass]
    if not ok:
        return []
    by_value = sorted(ok, key=lambda r: r.evaluation.build_value_delta, reverse=True)
    by_offense = sorted(ok, key=lambda r: r.evaluation.offense_delta, reverse=True)
    by_defense = sorted(ok, key=lambda r: r.evaluation.defense_delta, reverse=True)
    priced = [row for row in ok if row.evaluation.listing.price is not None]
    by_price = sorted(priced, key=lambda r: float(r.evaluation.listing.price.amount)) if priced else []

    picked: list[Any] = []
    seen: set[str] = set()

    def add(row: Any) -> None:
        lid = row.evaluation.listing.identity.listing_id
        if lid in seen:
            return
        seen.add(lid)
        picked.append(row)

    per_bucket = max(1, shortlist // 4)
    for bucket in (by_value, by_offense, by_defense, by_price):
        for row in bucket[:per_bucket]:
            add(row)
            if len(picked) >= shortlist:
                return picked[:shortlist]
    for row in by_value:
        add(row)
        if len(picked) >= shortlist:
            break
    return picked[:shortlist]


def build_slot_choices(
    pools: dict[str, MarketCandidatePool],
    *,
    baseline_equipment: dict[str, str],
    shortlist: int,
    budget_currency: str,
    rates: CurrencyRateTable | None,
) -> dict[str, list[SlotChoice]]:
    choices: dict[str, list[SlotChoice]] = {}
    for product_slot, pool in pools.items():
        pob_slot = pool.pob_slot or product_slot
        baseline_raw = baseline_equipment.get(pob_slot, "")
        slot_choices = [_keep_choice(product_slot, pool.pob_slot, baseline_raw)]
        for row in _diversity_shortlist(pool, shortlist):
            listing = row.evaluation.listing
            price = normalized_listing_price(listing, budget_currency, rates)
            if listing.price is not None and price is None:
                continue
            normalized = ListingPrice(amount=float(price.amount if price else 0.0), currency=budget_currency) if price else None
            slot_choices.append(
                SlotChoice(
                    product_slot=product_slot,
                    pob_slot=pool.pob_slot,
                    listing=listing,
                    item_raw=listing.item_raw,
                    price=normalized,
                    keep_current=False,
                    heuristic_score=float(row.evaluation.build_value_delta or 0.0),
                )
            )
        choices[product_slot] = slot_choices
    return choices


def choices_to_plan(
    picked: dict[str, SlotChoice],
    *,
    enabled_slots: tuple[str, ...],
) -> GearPlan:
    replacements: list[GearPlanReplacement] = []
    for product_slot in enabled_slots:
        choice = picked.get(product_slot)
        if choice is None:
            continue
        identity = None
        listing = None
        if not choice.keep_current and choice.listing is not None:
            identity = choice.listing.identity
            listing = choice.listing
        elif choice.keep_current:
            identity = CandidateIdentity(KEEP_CURRENT_ID, KEEP_CURRENT_ID, "baseline")
        replacements.append(
            GearPlanReplacement(
                product_slot=product_slot,
                pob_slot=choice.pob_slot,
                identity=identity,
                listing=listing,
                item_raw=choice.item_raw,
                price=choice.price,
                keep_current=choice.keep_current,
            )
        )
    return GearPlan(replacements=tuple(replacements))


def _plan_price_and_ids(plan: GearPlan) -> tuple[float, set[str]]:
    listing_ids: set[str] = set()
    total = 0.0
    for row in plan.replacements:
        if row.keep_current:
            continue
        if row.identity and row.identity.listing_id:
            listing_ids.add(row.identity.listing_id)
        if row.price is not None:
            total += float(row.price.amount)
    return total, listing_ids


def _heuristic_score(picked: dict[str, SlotChoice]) -> float:
    return sum(choice.heuristic_score for choice in picked.values())


def generate_candidate_plans(
    slot_choices: dict[str, list[SlotChoice]],
    *,
    enabled_slots: tuple[str, ...],
    budget: float,
    max_purchases: int | None,
    beam_width: int,
    exhaustive: bool,
) -> list[tuple[dict[str, SlotChoice], float]]:
    slot_list = [slot for slot in enabled_slots if slot in slot_choices]
    option_lists = [slot_choices[slot] for slot in slot_list]
    if not option_lists:
        return []

    if exhaustive:
        combos: list[tuple[dict[str, SlotChoice], float]] = []
        for product in itertools.product(*option_lists):
            picked = dict(zip(slot_list, product))
            plan = choices_to_plan(picked, enabled_slots=enabled_slots)
            total, listing_ids = _plan_price_and_ids(plan)
            if safe_partial_prune(
                total_price=total,
                budget=budget,
                listing_ids=listing_ids,
                canonical_id=plan.canonical_id,
                seen_canonical=set(),
                purchase_count=plan.purchase_count,
                max_purchases=max_purchases,
            ):
                continue
            combos.append((picked, _heuristic_score(picked)))
        combos.sort(key=lambda row: row[1], reverse=True)
        return combos

    beams: list[tuple[dict[str, SlotChoice], float]] = [({}, 0.0)]
    for slot in slot_list:
        next_beams: list[tuple[dict[str, SlotChoice], float]] = []
        for partial, score in beams:
            for choice in slot_choices[slot]:
                picked = dict(partial)
                picked[slot] = choice
                plan = choices_to_plan(picked, enabled_slots=enabled_slots)
                total, listing_ids = _plan_price_and_ids(plan)
                if safe_partial_prune(
                    total_price=total,
                    budget=budget,
                    listing_ids=listing_ids,
                    canonical_id=plan.canonical_id,
                    seen_canonical=set(),
                    purchase_count=plan.purchase_count,
                    max_purchases=max_purchases,
                ):
                    continue
                next_beams.append((picked, score + choice.heuristic_score))
        next_beams.sort(key=lambda row: row[1], reverse=True)
        beams = next_beams[:beam_width] if next_beams else beams
    return beams


def optimize_plans(
    engine: Any,
    *,
    build_path: str,
    context: str,
    profile: str,
    pools: dict[str, MarketCandidatePool],
    enabled_slots: tuple[str, ...],
    budget_amount: float,
    budget_currency: str,
    preset: GearSearchPreset,
    constraints: tuple[Any, ...],
    max_purchases: int | None,
    min_dps_floor: float | None,
    min_max_hit_floor: float | None,
    baseline_equipment: dict[str, str],
    cache: GearPlanEvalCache | None = None,
    currency_rates: CurrencyRateTable | None = None,
    should_yield: YieldFn | None = None,
    on_progress: ProgressFn | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    should_yield = should_yield or (lambda: False)
    limits = GEAR_SEARCH_LIMITS[preset]
    shortlist = int(limits["shortlist"])
    beam_width = int(limits["beam_width"])
    max_evaluations = int(limits["max_evaluations"])
    exhaustive_threshold = int(limits["exhaustive_threshold"])

    slot_choices = build_slot_choices(
        pools,
        baseline_equipment=baseline_equipment,
        shortlist=shortlist,
        budget_currency=budget_currency,
        rates=currency_rates,
    )
    space_size = 1
    for slot in enabled_slots:
        space_size *= max(1, len(slot_choices.get(slot, [])))
    exhaustive = space_size <= exhaustive_threshold
    search_mode = "GLOBAL OPTIMUM — EXHAUSTIVE" if exhaustive else f"BOUNDED — {preset.value}"

    candidates = generate_candidate_plans(
        slot_choices,
        enabled_slots=enabled_slots,
        budget=budget_amount,
        max_purchases=max_purchases,
        beam_width=beam_width,
        exhaustive=exhaustive,
    )
    if not exhaustive:
        candidates = candidates[: max(max_evaluations * 3, beam_width)]

    evaluated: list[GearPlanEvaluation] = []
    seen_canonical: set[str] = set()
    pob_recalcs = 0
    best_value: float | None = None

    def progress(phase: str, message: str, **extra: Any) -> None:
        if on_progress:
            on_progress({"phase": phase, "message": message, **extra})

    progress("search", f"Planning {len(candidates)} candidate gear plans", candidates_considered=len(candidates))

    for idx, (picked, _score) in enumerate(candidates):
        if should_yield():
            progress("yielded", "Yielded to gameplay evaluation")
            break
        if len(evaluated) >= max_evaluations and not exhaustive:
            break
        plan = choices_to_plan(picked, enabled_slots=enabled_slots)
        total, listing_ids = _plan_price_and_ids(plan)
        prune_reason = safe_partial_prune(
            total_price=total,
            budget=budget_amount,
            listing_ids=listing_ids,
            canonical_id=plan.canonical_id,
            seen_canonical=seen_canonical,
            purchase_count=plan.purchase_count,
            max_purchases=max_purchases,
        )
        if prune_reason:
            continue
        seen_canonical.add(plan.canonical_id)
        evaluation = evaluate_gear_plan(
            engine,
            plan,
            build_path=build_path,
            context=context,
            profile=profile,
            budget_currency=budget_currency,
            currency_rates=currency_rates,
            cache=cache,
        )
        if not evaluation.cache_hit:
            pob_recalcs += 1
        if not evaluation.restore_pass:
            return {
                "evaluated": evaluated,
                "search_mode": search_mode,
                "restore_failed": True,
                "error": evaluation.error or "RESTORE_FAILED",
                "performance": {"pob_recalcs": pob_recalcs},
            }
        check_plan_constraints(
            evaluation,
            constraints=constraints,
            min_dps_floor=min_dps_floor,
            min_max_hit_floor=min_max_hit_floor,
            max_purchases=max_purchases,
        )
        evaluated.append(evaluation)
        if evaluation.constraint_violations:
            continue
        if best_value is None or evaluation.build_value_delta > best_value:
            best_value = evaluation.build_value_delta
        progress(
            "evaluate",
            f"Evaluated {len(evaluated)} plans",
            evaluated=len(evaluated),
            total=min(len(candidates), max_evaluations),
            best_build_value=best_value,
        )

    valid = [row for row in evaluated if not row.constraint_violations]
    valid.sort(key=lambda r: r.build_value_delta, reverse=True)
    frontier = compute_plan_pareto_frontier(valid)
    categories = assign_plan_categories(valid)
    curve = build_budget_curve(valid)
    best_single = max(
        (row for row in valid if row.plan.purchase_count == 1),
        key=lambda r: r.build_value_delta,
        default=None,
    )
    best_plan = valid[0] if valid else None
    opportunity = None
    if best_plan and best_single and best_plan.plan.canonical_id != best_single.plan.canonical_id:
        opportunity = {
            "best_single_build_value_delta": best_single.build_value_delta,
            "best_plan_build_value_delta": best_plan.build_value_delta,
            "multi_gain_over_single": best_plan.build_value_delta - best_single.build_value_delta,
            "single_price": best_single.total_price,
            "plan_price": best_plan.total_price,
        }

    elapsed_ms = (time.perf_counter() - started) * 1000
    return {
        "evaluated": evaluated,
        "valid": valid,
        "best_plan": best_plan,
        "alternatives": valid[1:8],
        "pareto_frontier": frontier,
        "categories": categories,
        "budget_curve": curve,
        "best_single_purchase": best_single,
        "opportunity_cost": opportunity,
        "search_mode": search_mode,
        "restore_failed": False,
        "performance": {
            "elapsed_ms": elapsed_ms,
            "pob_recalcs": pob_recalcs,
            "space_size": space_size,
            "exhaustive": exhaustive,
            "cache": (cache.stats() if cache else {}),
        },
    }
