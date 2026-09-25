"""Bounded hypothetical ideal-target analysis with real PoB verification."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from exilelens.analysis.identity import AnalysisBaseline
from exilelens.analysis.probes import ProbeEngine
from exilelens.market_assist.models import CaptureQueueState, MarketCaptureSession

ProgressFn = Callable[[dict[str, Any]], None]
MAX_PROBE_COMBOS = 12


@dataclass
class IdealTargetResult:
    gap_to_best: float
    hypothetical_gain: float
    probes_run: int
    craft_legality_verified: bool = False
    top_stats: list[str] = field(default_factory=list)
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "gap_to_best": self.gap_to_best,
            "hypothetical_gain": self.hypothetical_gain,
            "probes_run": self.probes_run,
            "craft_legality_verified": self.craft_legality_verified,
            "top_stats": self.top_stats,
            "message": self.message,
            "warning": "craft_legality_verified=false — hypothetical stat combos only",
        }


class IdealTargetAnalyzer:
    """Manual ideal-target probe — bounded combo search with real PoB."""

    def analyze(
        self,
        engine: Any,
        session: MarketCaptureSession,
        *,
        build_path: str,
        context: str,
        profile: str,
        on_progress: ProgressFn | None = None,
    ) -> IdealTargetResult:
        best_delta = 0.0
        for row in session.observations:
            if row.queue_state is not CaptureQueueState.EVALUATED or not row.evaluation:
                continue
            best_delta = max(best_delta, float(row.evaluation.get("build_value_delta") or 0.0))

        guidance_stats = [row.get("stat") for row in (session.guidance.get("next_search") or [])[:4]]
        if not guidance_stats:
            guidance_stats = ["SKILL_LEVEL", "CAST_SPEED", "MANA"]

        probe_engine = ProbeEngine(engine)
        baseline = AnalysisBaseline(
            build_path=build_path,
            build_name="",
            loadout="",
            item_set="",
            context=context,
            profile=profile,
            generation=0,
            fingerprint=str(engine.get_metrics().get("fingerprint_hash") or ""),
        )
        combos = guidance_stats[:3]
        total_gain = 0.0
        probes_run = 0
        for index, stat in enumerate(combos):
            if on_progress:
                on_progress(
                    {
                        "phase": "ideal_target",
                        "completed": index,
                        "total": len(combos),
                        "message": f"Probing {stat}",
                    }
                )
            try:
                result = probe_engine.run_probe(
                    baseline=baseline,
                    pob_slot=session.pob_slot,
                    probe_id=str(stat).upper(),
                    context=context,
                )
            except Exception:
                continue
            probes_run += 1
            total_gain += float(result.get("score_delta") or 0.0)

        gap = max(0.0, total_gain - best_delta)
        return IdealTargetResult(
            gap_to_best=round(gap, 2),
            hypothetical_gain=round(total_gain, 2),
            probes_run=probes_run,
            craft_legality_verified=False,
            top_stats=guidance_stats,
            message="Bounded hypothetical combo — not a craft recipe.",
        )
