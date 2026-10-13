"""Probe policy for FILTER (research): production Build Intelligence plus global Armour/Evasion probes.

Production's global (sensitivity) stage runs ``ProbeCatalog.global_ids()``, which omits ARMOUR and EVASION: they exist in the
catalog but only run per slot. Without them a filter cannot tell an armour build from an evasion build. Rather than build a
second sensitivity engine, FILTER passes a catalog subclass through the existing ``analyze_build(catalog=...)`` contract: the
same probe engine, restore checks, caching, confidence and Build Priorities lanes handle the two extra probes. Nothing else
about the catalog (magnitudes, gating of minion/poison/ignite/crit probes by observed PoB facts) is changed.
"""
from __future__ import annotations

from exilelens.analysis.catalog import ProbeCatalog

DEFENCE_PROBE_IDS = ("ARMOUR", "EVASION")


class FilterProbeCatalog(ProbeCatalog):
    def global_ids(self, **kwargs) -> tuple[str, ...]:
        return tuple(dict.fromkeys((*super().global_ids(**kwargs), *(p for p in DEFENCE_PROBE_IDS if p in self._probes))))
