from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable

from poe2value.price_check.models import PriceCheckRequest, PriceCheckResult
from poe2value.price_check.rate_limit import RateLimiter
from poe2value.price_check.service import PriceCheckService


class ComparableLookupWorker:
    """Async comparable lookup with rate limiting and shared cache."""

    def __init__(
        self,
        service: PriceCheckService,
        *,
        max_workers: int = 1,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self._service = service
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="price-check")
        self._rate_limiter = rate_limiter or RateLimiter()

    def submit(self, request: PriceCheckRequest) -> Future[PriceCheckResult]:
        return self._executor.submit(self._run, request)

    def _run(self, request: PriceCheckRequest) -> PriceCheckResult:
        if not self._rate_limiter.acquire():
            result = self._service.check(request)
            return PriceCheckResult(
                request=result.request,
                estimate=result.estimate,
                provider_id=result.provider_id,
                important_mods=result.important_mods,
                message="Rate limited — showing cached or fallback result.",
                no_item_text=result.no_item_text,
                cache_hit=result.cache_hit,
                comparable_count=result.comparable_count,
                search_basis=result.search_basis,
                search_relaxation_tier=result.search_relaxation_tier,
            )
        return self._service.check(request)

    def shutdown(self, *, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=not wait)
