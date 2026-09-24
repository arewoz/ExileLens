"""Pipeline-level network withhold — pacing is not a market failure.

MARKET-02F2A: when the next pipeline stage (search, fetch, exchange) is unsafe,
park the check and resume from the same stage. A proactive withhold never spends an
HTTP request and never surfaces as HTTP 429.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from exilelens.price_check.rate_policy import EXCHANGE, FETCH, LEAGUES, SEARCH

STAGE_SEARCH = "search"
STAGE_FETCH = "fetch"
STAGE_EXCHANGE = "exchange"
STAGE_LEAGUES = "leagues"

_ENDPOINT_FOR_STAGE = {
    STAGE_SEARCH: SEARCH,
    STAGE_FETCH: FETCH,
    STAGE_EXCHANGE: EXCHANGE,
    STAGE_LEAGUES: LEAGUES,
}


@dataclass(frozen=True)
class FetchContinuation:
    """Resume fetch after search succeeded — do not rerun search."""

    query_id: str
    result_ids: tuple[str, ...]
    fetch_offset: int = 0
    pass_index: int = 0
    relaxation_tier: int = 0
    search_http_status: int = 200
    search_total: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_id": self.query_id,
            "result_ids": list(self.result_ids),
            "fetch_offset": self.fetch_offset,
            "pass_index": self.pass_index,
            "relaxation_tier": self.relaxation_tier,
            "search_http_status": self.search_http_status,
            "search_total": self.search_total,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> FetchContinuation | None:
        if not isinstance(raw, dict):
            return None
        try:
            return cls(
                query_id=str(raw["query_id"]),
                result_ids=tuple(str(row) for row in raw.get("result_ids") or ()),
                fetch_offset=int(raw.get("fetch_offset") or 0),
                pass_index=int(raw.get("pass_index") or 0),
                relaxation_tier=int(raw.get("relaxation_tier") or 0),
                search_http_status=int(raw.get("search_http_status") or 200),
                search_total=int(raw.get("search_total") or 0),
            )
        except (KeyError, TypeError, ValueError):
            return None


@dataclass(frozen=True)
class PipelineContinuation:
    """Where to resume after a withhold expires."""

    stage: str
    fetch: FetchContinuation | None = None
    generation_id: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "fetch": self.fetch.to_dict() if self.fetch is not None else None,
            "generation_id": self.generation_id,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> PipelineContinuation | None:
        if not isinstance(raw, dict):
            return None
        stage = str(raw.get("stage") or "").strip()
        if not stage:
            return None
        fetch = FetchContinuation.from_dict(raw.get("fetch"))
        try:
            generation_id = int(raw.get("generation_id") or 0)
        except (TypeError, ValueError):
            generation_id = 0
        return cls(stage=stage, fetch=fetch, generation_id=generation_id)


@dataclass(frozen=True)
class NetworkWithhold:
    """A scheduled wait before the next HTTP dispatch on this price-check path."""

    endpoint: str
    wait_seconds: float
    continuation_stage: str
    request_id: int = 0
    continuation: PipelineContinuation | None = None
    reason: str = ""
    proactive: bool = True
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @property
    def is_fetch_stage(self) -> bool:
        return self.continuation_stage == STAGE_FETCH

    @property
    def is_search_stage(self) -> bool:
        return self.continuation_stage == STAGE_SEARCH

    def to_dict(self) -> dict[str, Any]:
        return {
            "endpoint": self.endpoint,
            "wait_seconds": round(float(self.wait_seconds), 3),
            "continuation_stage": self.continuation_stage,
            "request_id": self.request_id,
            "continuation": self.continuation.to_dict() if self.continuation is not None else None,
            "reason": self.reason,
            "proactive": self.proactive,
            "diagnostics": dict(self.diagnostics),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> NetworkWithhold | None:
        if not isinstance(raw, dict):
            return None
        try:
            return cls(
                endpoint=str(raw.get("endpoint") or ""),
                wait_seconds=float(raw.get("wait_seconds") or 0.0),
                continuation_stage=str(raw.get("continuation_stage") or ""),
                request_id=int(raw.get("request_id") or 0),
                continuation=PipelineContinuation.from_dict(raw.get("continuation")),
                reason=str(raw.get("reason") or ""),
                proactive=bool(raw.get("proactive", True)),
                diagnostics=dict(raw.get("diagnostics") or {}),
            )
        except (TypeError, ValueError):
            return None


def endpoint_for_stage(stage: str) -> str:
    return _ENDPOINT_FOR_STAGE.get(stage, stage)


def build_fetch_withhold(
    *,
    wait_seconds: float,
    request_id: int,
    fetch: FetchContinuation,
    proactive: bool = True,
    reason: str = "fetch_pacing",
) -> NetworkWithhold:
    return NetworkWithhold(
        endpoint=FETCH,
        wait_seconds=wait_seconds,
        continuation_stage=STAGE_FETCH,
        request_id=request_id,
        continuation=PipelineContinuation(stage=STAGE_FETCH, fetch=fetch, generation_id=request_id),
        reason=reason,
        proactive=proactive,
    )


def build_search_withhold(
    *,
    wait_seconds: float,
    request_id: int,
    proactive: bool = True,
    reason: str = "search_pacing",
) -> NetworkWithhold:
    return NetworkWithhold(
        endpoint=SEARCH,
        wait_seconds=wait_seconds,
        continuation_stage=STAGE_SEARCH,
        request_id=request_id,
        continuation=PipelineContinuation(stage=STAGE_SEARCH, generation_id=request_id),
        reason=reason,
        proactive=proactive,
    )
