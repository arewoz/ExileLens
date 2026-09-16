from __future__ import annotations

from typing import Any

from poe2value.gear.models import PoolState, SlotPoolEntry
from poe2value.gear.slots import GEAR_OPTIMIZER_SLOTS, GEAR_SLOT_LABELS, pob_slot_for_product
from poe2value.market.models import MarketCandidatePool


class CandidatePoolRegistry:
    """Tracks Phase 5B candidate pools per gear slot."""

    def __init__(self) -> None:
        self._pools: dict[str, MarketCandidatePool] = {}
        self._meta: dict[str, dict[str, Any]] = {}

    def register(
        self,
        pool: MarketCandidatePool,
        *,
        baseline_fingerprint: str,
        baseline_generation: int,
        profile: str,
    ) -> None:
        slot = pool.slot
        self._pools[slot] = pool
        self._meta[slot] = {
            "baseline_fingerprint": baseline_fingerprint,
            "baseline_generation": baseline_generation,
            "profile": profile,
        }

    def register_from_search_result(self, result: dict[str, Any]) -> None:
        pool_payload = result.get("pool") or {}
        slot = str(pool_payload.get("slot") or result.get("request", {}).get("slot") or "")
        if not slot:
            return
        candidates = pool_payload.get("candidates") or []
        from poe2value.market.models import MarketCandidateResult, CandidateEvaluation, CandidateListing, CandidateIdentity

        parsed_candidates = []
        for row in candidates:
            ev = row.get("evaluation") or {}
            listing_payload = ev.get("listing") or {}
            ident_payload = listing_payload.get("identity") or {}
            listing = CandidateListing.from_dict(listing_payload)
            if not listing.identity.listing_id:
                listing.identity = CandidateIdentity(
                    listing_id=str(ident_payload.get("listing_id") or listing.identity.content_hash),
                    content_hash=listing.identity.content_hash,
                    source=listing.identity.source,
                )
            evaluation = CandidateEvaluation(
                listing=listing,
                comparison=ev.get("comparison") or {},
                build_value_delta=float(ev.get("build_value_delta") or 0.0),
                offense_delta=float(ev.get("offense_delta") or 0.0),
                defense_delta=float(ev.get("defense_delta") or 0.0),
                verdict=str(ev.get("verdict") or "UNRESOLVED"),
                power_per_currency=ev.get("power_per_currency"),
                restore_pass=bool(ev.get("restore_pass", True)),
                cache_hit=bool(ev.get("cache_hit", False)),
                status=str(ev.get("status") or "ok"),
                error=ev.get("error"),
            )
            parsed_candidates.append(
                MarketCandidateResult(
                    evaluation=evaluation,
                    categories=list(row.get("categories") or []),
                    pareto_rank=row.get("pareto_rank"),
                    on_frontier=bool(row.get("on_frontier", False)),
                )
            )
        pool = MarketCandidatePool(
            slot=slot,
            pob_slot=str(pool_payload.get("pob_slot") or ""),
            profile=str(pool_payload.get("profile") or "BALANCED"),
            candidates=parsed_candidates,
        )
        meta = result.get("request_meta") or {}
        self.register(
            pool,
            baseline_fingerprint=str(result.get("baseline_fingerprint") or meta.get("baseline_fingerprint") or ""),
            baseline_generation=int(meta.get("baseline_generation") or result.get("baseline_generation") or 0),
            profile=str(pool.profile),
        )

    def clear(self) -> None:
        self._pools.clear()
        self._meta.clear()

    def get_pool(self, product_slot: str) -> MarketCandidatePool | None:
        return self._pools.get(product_slot)

    def status(
        self,
        *,
        baseline_fingerprint: str,
        baseline_generation: int,
        profile: str,
        enabled_slots: tuple[str, ...] | None = None,
    ) -> list[SlotPoolEntry]:
        slots = enabled_slots or tuple(slot.value for slot in GEAR_OPTIMIZER_SLOTS)
        rows: list[SlotPoolEntry] = []
        for product_slot in slots:
            pob_slot = pob_slot_for_product(product_slot)
            pool = self._pools.get(product_slot)
            meta = self._meta.get(product_slot) or {}
            if pool is None:
                rows.append(
                    SlotPoolEntry(
                        product_slot=product_slot,
                        pob_slot=pob_slot,
                        state=PoolState.MISSING,
                        message="Run Market search for this slot",
                    )
                )
                continue
            if meta.get("baseline_generation") != baseline_generation:
                rows.append(
                    SlotPoolEntry(
                        product_slot=product_slot,
                        pob_slot=pob_slot,
                        state=PoolState.STALE,
                        pool=pool,
                        candidate_count=len(pool.candidates),
                        baseline_fingerprint=str(meta.get("baseline_fingerprint") or ""),
                        baseline_generation=int(meta.get("baseline_generation") or 0),
                        profile=str(meta.get("profile") or profile),
                        message="Baseline generation changed — refresh Market search",
                    )
                )
                continue
            if meta.get("baseline_fingerprint") and meta.get("baseline_fingerprint") != baseline_fingerprint:
                rows.append(
                    SlotPoolEntry(
                        product_slot=product_slot,
                        pob_slot=pob_slot,
                        state=PoolState.STALE,
                        pool=pool,
                        candidate_count=len(pool.candidates),
                        baseline_fingerprint=str(meta.get("baseline_fingerprint") or ""),
                        baseline_generation=int(meta.get("baseline_generation") or 0),
                        profile=str(meta.get("profile") or profile),
                        message="Build fingerprint changed — refresh Market search",
                    )
                )
                continue
            if meta.get("profile") and meta.get("profile") != profile:
                rows.append(
                    SlotPoolEntry(
                        product_slot=product_slot,
                        pob_slot=pob_slot,
                        state=PoolState.INCOMPATIBLE,
                        pool=pool,
                        candidate_count=len(pool.candidates),
                        baseline_fingerprint=str(meta.get("baseline_fingerprint") or ""),
                        baseline_generation=int(meta.get("baseline_generation") or 0),
                        profile=str(meta.get("profile") or profile),
                        message=f"Pool profile {meta.get('profile')} != optimizer profile {profile}",
                    )
                )
                continue
            ok_candidates = [row for row in pool.candidates if row.evaluation.status == "ok" and row.evaluation.restore_pass]
            if not ok_candidates:
                rows.append(
                    SlotPoolEntry(
                        product_slot=product_slot,
                        pob_slot=pob_slot,
                        state=PoolState.EMPTY,
                        pool=pool,
                        candidate_count=0,
                        baseline_fingerprint=str(meta.get("baseline_fingerprint") or baseline_fingerprint),
                        baseline_generation=int(meta.get("baseline_generation") or baseline_generation),
                        profile=str(meta.get("profile") or profile),
                        message="No viable candidates in pool",
                    )
                )
                continue
            rows.append(
                SlotPoolEntry(
                    product_slot=product_slot,
                    pob_slot=pob_slot,
                    state=PoolState.READY,
                    pool=pool,
                    candidate_count=len(ok_candidates),
                    baseline_fingerprint=str(meta.get("baseline_fingerprint") or baseline_fingerprint),
                    baseline_generation=int(meta.get("baseline_generation") or baseline_generation),
                    profile=str(meta.get("profile") or profile),
                    message=f"{len(ok_candidates)} candidates ready",
                )
            )
        return rows

    def ready_pools(
        self,
        *,
        baseline_fingerprint: str,
        baseline_generation: int,
        profile: str,
        enabled_slots: tuple[str, ...],
    ) -> dict[str, MarketCandidatePool]:
        ready: dict[str, MarketCandidatePool] = {}
        for row in self.status(
            baseline_fingerprint=baseline_fingerprint,
            baseline_generation=baseline_generation,
            profile=profile,
            enabled_slots=enabled_slots,
        ):
            if row.state == PoolState.READY and row.pool is not None:
                ready[row.product_slot] = row.pool
        return ready

    def slot_labels(self) -> dict[str, str]:
        return dict(GEAR_SLOT_LABELS)
