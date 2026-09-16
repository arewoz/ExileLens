from __future__ import annotations

from dataclasses import dataclass, field

from poe2value.gear.models import GearPlanEvaluation


@dataclass
class GearPlanEvalCache:
    entries: dict[str, GearPlanEvaluation] = field(default_factory=dict)
    hits: int = 0
    misses: int = 0

    def make_key(self, *, baseline_fingerprint: str, context: str, canonical_id: str, profile: str) -> str:
        return f"{baseline_fingerprint}|{context}|{profile}|{canonical_id}"

    def get(self, key: str) -> GearPlanEvaluation | None:
        row = self.entries.get(key)
        if row is None:
            self.misses += 1
            return None
        self.hits += 1
        cached = GearPlanEvaluation(
            plan=row.plan,
            baseline_metrics=dict(row.baseline_metrics),
            final_metrics=dict(row.final_metrics),
            baseline_fingerprint=row.baseline_fingerprint,
            final_fingerprint=row.final_fingerprint,
            comparison=dict(row.comparison),
            build_value_delta=row.build_value_delta,
            offense_delta=row.offense_delta,
            defense_delta=row.defense_delta,
            verdict=row.verdict,
            warnings=list(row.warnings),
            constraint_violations=list(row.constraint_violations),
            restore_pass=row.restore_pass,
            cache_hit=True,
            status=row.status,
            error=row.error,
            total_price=row.total_price,
            price_currency=row.price_currency,
        )
        return cached

    def put(self, key: str, evaluation: GearPlanEvaluation) -> None:
        self.entries[key] = evaluation

    def stats(self) -> dict[str, int]:
        return {"entries": len(self.entries), "hits": self.hits, "misses": self.misses}

    def clear(self) -> None:
        self.entries.clear()
        self.hits = 0
        self.misses = 0
