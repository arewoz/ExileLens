"""Visible, non-blocking degradation states (FILTER-08E).

FILTER-08D showed that every lost input degrades conservatively (the filter widens, never hides) but four of the degradations were silent.
The opportunity model records WHY it fell back while it works (``BuildOpportunityModel.diagnostics``); this module turns those records
into compact, user-facing states plus detailed diagnostic provenance. Nothing here blocks generation: partial coverage is a state, not an
error. (Incompatible DATA still blocks, via data_drift.)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

COMPACT = "Partial personalization — some item families use conservative fallback"

# code -> (short label shown in the detail list, explanation)
CODES: dict[str, tuple[str, str]] = {
    "WEAPON_REQUIREMENT_UNKNOWN": ("weapon requirement unknown",
                                   "the skill needs a weapon but no verified weapon requirement is available; weapon classes follow the curated "
                                   "skill map or every supported class"),
    "FAMILY_MAPPING_MISSING": ("stat-family mapping missing",
                               "no verified modifier pool/family mapping for these bases; they keep their build-independent quality band instead "
                               "of being judged against the build's needs"),
    "BASE_METADATA_MISSING": ("base metadata missing",
                              "the verified base properties do not cover every verified base; bases without metadata cannot be named by build rules"),
    "NO_OBSERVED_GEAR": ("no observed gear",
                         "the build's equipped bases are unknown, so equipped-class evidence and current-slot context are unavailable"),
    "SKILL_UNRESOLVED": ("main skill not resolved",
                         "the main skill could not be resolved to a damage mode, so weapon and stat evidence rests on generic fallbacks"),
}


@dataclass(frozen=True)
class Degradation:
    code: str
    label: str
    detail: str
    subjects: tuple[str, ...] = ()

    @property
    def line(self) -> str:
        shown = ", ".join(self.subjects[:3]) + (f" (+{len(self.subjects) - 3} more)" if len(self.subjects) > 3 else "")
        return f"FALLBACK: {self.label}" + (f" — {shown}" if shown else "")


def collect(diagnostics: Mapping[str, Iterable[str]]) -> tuple[Degradation, ...]:
    out = []
    for code in CODES:
        subjects = tuple(sorted(s for s in diagnostics.get(code, ()) if s))
        if code in diagnostics and (diagnostics[code] or code in ("NO_OBSERVED_GEAR",)):
            label, detail = CODES[code]
            out.append(Degradation(code, label, detail, subjects))
    return tuple(out)


def compact(degradations: Iterable[Degradation]) -> str:
    return COMPACT if any(True for _ in degradations) else ""


def lines(degradations: Iterable[Degradation]) -> list[str]:
    return [d.line for d in degradations]
