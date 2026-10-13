"""PERF-01: pay the first Item Check's one-time PoB diagnostic pass while the lane is idle after a build load.

For a multi-skill build the first Item Check on a loaded build runs one native ``get_skill_report`` pass (about 0.1 s
on a small build, 1.3 s on a heavy one) whose result is then cached for every later check. Nothing about it depends on
the candidate item, so it can be read right after the build is loaded, as a low-priority lane job that any Item Check,
build load or analysis outranks. It fills exactly the cache Item Check reads (same key, same function), so a check that
arrives early still gets the same answer; one that arrives while the pass is running waits no longer than it would have
paid for the same pass inline.
"""

from __future__ import annotations

from typing import Any

from exilelens.items.evaluation import cached_native_component_report
from exilelens.items.native_metric_discovery import should_discover_components
from exilelens.items.primary_metric import resolve_primary_metric


def prewarm_native_report(engine: Any, *, context: str) -> bool:
    """Fill the native component report cache for the engine's current baseline. ``False`` when it has no use here
    (single-skill build, or an engine without the raw call)."""
    if not hasattr(engine, "_call") or not hasattr(engine, "get_build_info"):
        return False
    loaded = engine.get_build_info()
    build_info = loaded.get("build") or {}
    primary_metric = resolve_primary_metric(build_info, loaded.get("metrics"))
    if not should_discover_components(build_info, primary_metric):
        return False
    cached_native_component_report(
        engine,
        build_info=build_info,
        primary_metric=primary_metric,
        baseline_fingerprint=loaded.get("fingerprint_hash"),
        context=context,
    )
    return True
