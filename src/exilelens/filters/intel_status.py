"""Build Intelligence freshness and coverage state for the dashboard (FILTER-08C). Pure logic, no Qt, no PoB.

Reuses the production contract instead of inventing one: an analysis result carries ``baseline`` (build path, generation,
fingerprint); the controller bumps ``baseline_generation`` and emits ``analysis_stale`` whenever the loaded build changes. An
analysis is therefore current exactly when its baseline generation and build path equal the controller's.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping

from exilelens.filters.build_needs import BuildNeedsSnapshot, Coverage
from exilelens.filters.probe_policy import DEFENCE_PROBE_IDS


class IntelState(str, Enum):
    NOT_ANALYZED = "NOT_ANALYZED"
    ANALYZING = "ANALYZING"
    CURRENT = "CURRENT"
    STALE = "STALE"
    FAILED = "FAILED"


@dataclass(frozen=True)
class IntelStatus:
    state: IntelState
    coverage: Coverage | None
    headline: str
    detail: str
    needs_analysis: bool

    @property
    def text(self) -> str:
        return f"{self.headline}\n{self.detail}" if self.detail else self.headline


def is_build_analysis(payload: Any) -> bool:
    """A full build analysis (not a tree/slot result) that carries the production Build Intelligence outputs."""
    return (isinstance(payload, Mapping) and bool(payload.get("build_sensitivity")) and bool(payload.get("build_priorities"))
            and str(payload.get("kind") or "") not in {"tree", "tree_snapshot"} and not payload.get("nodes"))


def is_current(payload: Mapping[str, Any], *, generation: int, build_path: str) -> bool:
    baseline = payload.get("baseline") or {}
    return (int(baseline.get("generation", -1)) == int(generation)
            and _norm(baseline.get("build_path")) == _norm(build_path))


def _norm(path: Any) -> str:
    return str(path or "").replace("\\", "/").rstrip("/").casefold()


def defence_measured(needs: BuildNeedsSnapshot) -> bool:
    """True when production tested BOTH Armour and Evasion for this build (otherwise the defence direction is unknown)."""
    return all(needs.signal(pid) is not None and needs.signal(pid).status in ("MEASURED", "NO_SIGNAL")
               for pid in DEFENCE_PROBE_IDS)


def age_text(measured_at: str, now: datetime | None = None) -> str:
    if not measured_at:
        return "time unknown"
    try:
        then = datetime.fromisoformat(measured_at.replace("Z", "+00:00"))
    except ValueError:
        return "time unknown"
    seconds = max(0, int(((now or datetime.now(timezone.utc)) - then).total_seconds()))
    if seconds < 45:
        return "just now"
    if seconds < 3600:
        return f"{max(1, round(seconds / 60))} min ago"
    if seconds < 86400:
        return f"{round(seconds / 3600)} h ago"
    return f"{round(seconds / 86400)} d ago"


def fallback_reasons(needs: BuildNeedsSnapshot | None) -> list[str]:
    """Short, visible reasons a decision still rests on fallback evidence (from the snapshot's own coverage reasoning)."""
    if needs is None:
        return ["build not analyzed"]
    if not needs.has_measurement:
        return ["no Build Intelligence measurement"]
    if needs.coverage == Coverage.MEASURED:
        return []
    return list(needs.coverage_reasons)


def degraded_notes(needs: BuildNeedsSnapshot | None, data_status: Any = None, degradations: Any = ()) -> list[str]:
    """Visible reasons the filter is deliberately more permissive than the evidence alone would make it (FILTER-08D)."""
    notes: list[str] = []
    if data_status is not None and getattr(data_status, "state", None) is not None and data_status.state.value != "CURRENT":
        notes.append(data_status.headline + (" · filter widened" if getattr(data_status, "widen", False) else ""))
    if needs is not None and needs.has_measurement and not needs.evidence_complete:
        notes.append("Evidence incomplete (standard probe set not fully tested or confidence low): measurements may add visibility but never hide items.")
    if degradations:
        from exilelens.filters import degradation
        notes.append(degradation.COMPACT)
        notes.extend(degradation.lines(degradations))
    return notes


GENERAL_HEADLINE = "General filter"
GENERAL_DETAIL = "Connect a PoB build for personalized item opportunities."


def describe(needs: BuildNeedsSnapshot | None, *, state: IntelState, now: datetime | None = None,
             error: str = "", data_status: Any = None, degradations: Any = (), build_connected: bool = True) -> IntelStatus:
    if not build_connected:
        # No build is a product mode, not an error: every generic lane (currency, CRAFT, protected, progression) is complete without one.
        return IntelStatus(IntelState.NOT_ANALYZED, None, GENERAL_HEADLINE, GENERAL_DETAIL, False)
    if state == IntelState.ANALYZING:
        return IntelStatus(state, None, "Build Intelligence · analyzing…",
                           "Measuring your build with controlled PoB probes; the filter below is the conservative fallback until it finishes.", False)
    if state == IntelState.FAILED:
        return IntelStatus(state, Coverage.FALLBACK, "Analysis failed · conservative fallback",
                           (error or "unknown error") + " — nothing is presented as personalized.", True)
    if state == IntelState.STALE:
        return IntelStatus(state, Coverage.FALLBACK, "Build changed · re-analysis required",
                           "The previous measurement no longer describes this build; the filter is the conservative fallback.", True)
    if needs is None or not needs.has_measurement:
        return IntelStatus(IntelState.NOT_ANALYZED, Coverage.FALLBACK, "General filter · build not analyzed",
                           "Click Analyze Build to add personalized opportunities. The general filter is complete without it: base tiers come "
                           "from verified data, nothing is personalized.", True)
    reasons = fallback_reasons(needs)
    ago = age_text(needs.measured_at, now)
    coverage = needs.coverage
    label = {Coverage.MEASURED: "Measured", Coverage.PARTIAL: "Partial personalization",
             Coverage.FALLBACK: "Conservative fallback", Coverage.UNSUPPORTED: "Unsupported / unknown"}[coverage]
    detail = "; ".join(reasons) if reasons else "offense and defence measured"
    notes = degraded_notes(needs, data_status, degradations)
    if notes:
        detail += "\n" + "\n".join(notes)
    return IntelStatus(IntelState.CURRENT, coverage, f"Build Intelligence · {label} · analyzed {ago}", detail, False)
