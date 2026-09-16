"""Finalize capture session observations into a Phase 5B MarketCandidatePool."""

from __future__ import annotations

import hashlib
from typing import Any

from poe2value.market.categories import assign_categories
from poe2value.market.models import (
    CandidateEvaluation,
    CandidateIdentity,
    CandidateListing,
    MarketCandidatePool,
    MarketCandidateResult,
)
from poe2value.market.pareto import compute_pareto_frontier
from poe2value.market_assist.models import CaptureQueueState, MarketCaptureSession


def finalize_session_to_pool(session: MarketCaptureSession) -> MarketCandidatePool:
    candidates: list[MarketCandidateResult] = []
    for row in session.observations:
        if row.queue_state is not CaptureQueueState.EVALUATED or not row.evaluation or not row.slot_match:
            continue
        ev = row.evaluation
        listing_id = hashlib.sha256(row.observation_key.encode("utf-8")).hexdigest()[:16]
        listing = CandidateListing(
            identity=CandidateIdentity(
                listing_id=listing_id,
                content_hash=row.content_hash,
                source="MARKET_CAPTURE",
            ),
            slot=session.target_slot,
            pob_slot=session.pob_slot,
            item_raw=row.item_raw,
            price=row.price,
            metadata={
                "capture_index": row.capture_index,
                "seen_count": row.seen_count,
                "raw_price_note": row.price_note_raw,
                "session_id": session.session_id,
            },
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
        candidates.append(MarketCandidateResult(evaluation=evaluation, categories=[]))

    assign_categories(candidates)
    eval_rows = [row.evaluation for row in candidates]
    pareto = compute_pareto_frontier(eval_rows)
    frontier_set = set(pareto.candidate_ids)
    for row in candidates:
        lid = row.evaluation.listing.identity.listing_id
        if lid in frontier_set:
            row.on_frontier = True
            row.pareto_rank = pareto.candidate_ids.index(lid) + 1

    category_map: dict[str, str] = {}
    for row in candidates:
        if row.categories:
            category_map[row.evaluation.listing.identity.listing_id] = row.categories[0]

    return MarketCandidatePool(
        slot=session.target_slot,
        pob_slot=session.pob_slot,
        profile=session.profile,
        candidates=candidates,
        pareto=pareto,
        categories=category_map,
    )


def pool_to_handoff_payload(pool: MarketCandidatePool, session: MarketCaptureSession) -> dict[str, Any]:
    return {
        "contract_version": 1,
        "kind": "MarketSearchResult",
        "source": "MARKET_CAPTURE",
        "pool": pool.to_dict(),
        "request": {
            "slot": session.target_slot,
            "profile": session.profile,
            "source": "MARKET_CAPTURE",
            "baseline_generation": session.baseline_generation,
        },
        "provider_status": "MARKET_CAPTURE_SESSION",
        "network": False,
        "live_market": False,
    }
