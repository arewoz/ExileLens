"""MARKET-03 — the one explicit Price Check session the controller owns.

The session holds the requested item, the MARKET-03 plan and
compiled query sent by the service, and the generation every async
completion is measured against.

The generation is the important part. It is *not* the overlay's request id: those ids are
minted per pipeline request and a pinned panel outlives them. A completion carrying an
older generation is dropped and said out loud — never returned from silently, which is
the failure this product has already shipped once.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from exilelens.price_check.market_plan import CompiledTradeQuery, MarketSearchPlan


@dataclass
class PriceCheckSession:
    """What the current Price Check is, and which updates still belong to it."""

    generation: int = 0
    request_id: int = 0
    item_raw: str = ""
    item_name: str = ""
    base_line: str = ""
    anchor: tuple[int, int] | None = None
    plan: MarketSearchPlan | None = None
    compiled: CompiledTradeQuery | None = None
    #: Compatibility metadata for the explicit legacy refine dialog only.
    hypothesis: Any = None
    user_refined: bool = False
    last_presentation: dict[str, Any] = field(default_factory=dict)
    last_result: Any = None

    @property
    def has_item(self) -> bool:
        return bool(self.item_raw.strip())

    def begin(
        self,
        *,
        request_id: int,
        item_raw: str,
        item_name: str,
        base_line: str,
        anchor: tuple[int, int] | None,
    ) -> int:
        """Claim the session for a fresh capture and return the new generation."""
        self.generation += 1
        self.request_id = request_id
        self.item_raw = item_raw
        self.item_name = item_name
        self.base_line = base_line
        self.anchor = anchor
        self.plan = None
        self.compiled = None
        self.hypothesis = None
        self.user_refined = False
        self.last_presentation = {}
        self.last_result = None
        return self.generation

    def accepts(self, generation: int) -> bool:
        """Whether an update belongs to the current capture."""
        return generation == self.generation

    def adopt_plan(self, plan: MarketSearchPlan, compiled: CompiledTradeQuery | None) -> None:
        self.plan = plan
        self.compiled = compiled

    def mark_user_refined(self) -> None:
        """An explicit edit. Automatic re-planning stops here (brief section 9)."""
        self.user_refined = True

    def remember_result(self, result: Any, presentation: dict[str, Any]) -> None:
        self.last_result = result
        self.last_presentation = dict(presentation or {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "generation": self.generation,
            "request_id": self.request_id,
            "item_name": self.item_name,
            "base_line": self.base_line,
            "has_plan": self.plan is not None,
            "user_refined": self.user_refined,
        }
