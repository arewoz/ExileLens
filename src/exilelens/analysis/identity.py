from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class AnalysisBaseline:
    """Exact baseline identity for a Phase 5A analysis."""

    build_path: str
    build_name: str
    loadout: str
    item_set: str
    context: str
    profile: str
    generation: int
    fingerprint: str

    def identity_key(self) -> str:
        return "|".join(
            [
                self.fingerprint,
                self.build_path,
                self.loadout,
                self.item_set,
                self.context,
                str(self.generation),
            ]
        )

    def probe_cache_prefix(self) -> str:
        """Raw PoB probes are valid across profile-only changes."""
        return "|".join(
            [
                self.fingerprint,
                self.build_path,
                self.loadout,
                self.item_set,
                self.context,
                str(self.generation),
            ]
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def baseline_fingerprint_key(
    *,
    fingerprint: str,
    generation: int,
    probe_id: str,
    magnitude: float,
    context: str,
) -> str:
        return f"{fingerprint}|{generation}|{probe_id}|{float(magnitude)}|{context}"


def is_stale(result_baseline: AnalysisBaseline | dict[str, Any], current: AnalysisBaseline) -> bool:
    if isinstance(result_baseline, dict):
        result_baseline = AnalysisBaseline(**{k: result_baseline[k] for k in AnalysisBaseline.__dataclass_fields__})
    return (
        result_baseline.fingerprint != current.fingerprint
        or result_baseline.generation != current.generation
        or result_baseline.context != current.context
        or result_baseline.build_path != current.build_path
        or result_baseline.loadout != current.loadout
        or result_baseline.item_set != current.item_set
    )
