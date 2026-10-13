"""PERF-01: the engine-bound half of a build (re)load, kept apart from controller state.

``EvaluationController.load_build`` used to interleave PoB round trips with controller field updates, all on
the Qt UI thread, so every load froze the application for as long as PoB needed (about 1.5 s on a small build,
4+ s on a heavy one) -- at startup, with the tray already visible, and on every build switch.

The round trips are collected here into one function that touches **no** controller state: it takes plain
inputs, talks to the engine only, and returns a plain :class:`BaselineCapture`. The controller runs it either
inline (the synchronous API, unchanged) or on the PoB lane (the interactive paths) and then applies the capture
on the UI thread behind a baseline-generation check, so a result for a build that has since been replaced is
dropped instead of shown.

The call sequence and the exception behaviour below are exactly those of the former
``_refresh_loadout_catalog`` / ``_apply_loadout_selection`` / ``_capture_ready_baseline``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from exilelens.baseline import canonical_item_set_id, resolve_item_set


@dataclass(frozen=True)
class CaptureInputs:
    """Everything the capture needs from controller and settings, read on the UI thread when it is requested."""

    path: str
    context: str
    generation: int
    value_profile: str
    selected_loadout: str
    item_set_follow_loadout: bool
    selected_item_set_id: str
    # Controller values that survive a catalog read that fails (the original left them unchanged).
    previous_loadouts: tuple[dict[str, Any], ...] = ()
    previous_item_sets: tuple[dict[str, Any], ...] = ()
    previous_active_loadout: str = ""
    previous_active_item_set_id: str = ""
    previous_active_item_set_name: str = ""


@dataclass
class BaselineCapture:
    loadouts: list[dict[str, Any]] = field(default_factory=list)
    item_sets: list[dict[str, Any]] = field(default_factory=list)
    #: Values as of the catalog read (what ``loadouts_changed`` announces).
    catalog_active_loadout: str = ""
    catalog_active_item_set_id: str = ""
    catalog_active_item_set_name: str = ""
    catalog_failed: bool = False
    #: Values after the stored selection was applied to the engine.
    active_loadout: str = ""
    active_item_set_id: str = ""
    active_item_set_name: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    equipment: dict[str, Any] = field(default_factory=dict)
    equipment_fingerprint: str = ""
    tree_fingerprint_fallback: str = ""
    snapshot: Any = None
    graph: Any = None
    #: The pure half of ingesting ``graph`` into the tree view model, computed off the UI thread.
    tree_ingest: Any = None
    build_info: dict[str, Any] = field(default_factory=dict)
    #: What the engine reported as loaded, read at capture time (the engine may be loading something else later).
    source_ref: Any = None
    loaded_revision: Any = None
    loaded_source: Any = None


def capture_baseline(engine: Any, inputs: CaptureInputs) -> BaselineCapture:
    """Run the engine round trips of a ready-baseline capture. Never touches controller state."""
    from exilelens.config import fingerprint_hash
    from exilelens.tree.fingerprint import tree_fingerprint_from_components
    from exilelens.tree.mutations import load_tree_snapshot

    capture = BaselineCapture(
        loadouts=list(inputs.previous_loadouts),
        item_sets=list(inputs.previous_item_sets),
        catalog_active_loadout=inputs.previous_active_loadout,
        catalog_active_item_set_id=inputs.previous_active_item_set_id,
        catalog_active_item_set_name=inputs.previous_active_item_set_name,
    )
    # --- loadout / item-set catalog (was _refresh_loadout_catalog) -----------------------------------
    try:
        loadout_info = engine.list_loadouts()
        item_set_info = engine.list_item_sets()
        capture.loadouts = list(loadout_info.get("loadouts") or [])
        capture.item_sets = list(item_set_info.get("item_sets") or [])
        capture.catalog_active_loadout = str(loadout_info.get("active") or "")
        resolved = resolve_item_set(capture.item_sets, item_set_info.get("active_id"))
        capture.catalog_active_item_set_id = resolved.id
        capture.catalog_active_item_set_name = resolved.name
    except Exception:  # noqa: BLE001 - identical to the original: a failed catalog read leaves empty lists
        capture.catalog_failed = True
        capture.loadouts = []
        capture.item_sets = []
    capture.active_loadout = capture.catalog_active_loadout
    capture.active_item_set_id = capture.catalog_active_item_set_id
    capture.active_item_set_name = capture.catalog_active_item_set_name

    # --- stored selection (was _apply_loadout_selection) ---------------------------------------------
    selected = inputs.selected_loadout.strip()
    if selected:
        names = {entry.get("name") for entry in capture.loadouts}
        if selected in names:
            engine.set_active_loadout(selected)
            capture.active_loadout = selected
    if not inputs.item_set_follow_loadout:
        item_set_id = inputs.selected_item_set_id.strip()
        if item_set_id:
            known = {canonical_item_set_id(entry.get("id")) for entry in capture.item_sets}
            canonical = canonical_item_set_id(item_set_id)
            if canonical in known:
                engine.set_active_item_set(canonical)
                resolved = resolve_item_set(capture.item_sets, canonical)
                capture.active_item_set_id = resolved.id
                capture.active_item_set_name = resolved.name

    # --- metrics / equipment / tree snapshot / build info (was _capture_ready_baseline) ----------------
    metrics = engine.get_metrics(context=inputs.context)
    capture.metrics = metrics
    equipment: dict[str, Any] = {}
    try:
        equipment = engine.get_equipment() or {}
    except Exception:  # noqa: BLE001
        equipment = {}
    capture.equipment = equipment
    capture.equipment_fingerprint = fingerprint_hash(
        equipment if isinstance(equipment, dict) else {"equipment": equipment}
    )
    capture.tree_fingerprint_fallback = tree_fingerprint_from_components(metrics.get("fingerprint") or {})
    snapshot = load_tree_snapshot(
        engine,
        build_path=inputs.path,
        context=inputs.context,
        profile=inputs.value_profile,
        generation=inputs.generation,
        loadout=capture.active_loadout,
        item_set=capture.active_item_set_id,
    )
    capture.snapshot = snapshot
    # Built here so the UI thread only applies it (pure functions of the snapshot: the graph export, the
    # snapshot rebuilt from it, its geometry, the frontier shortest paths and the reachable target sets).
    capture.graph = snapshot.to_graph_export()
    from exilelens.tree.view_model import prepare_graph_payload

    capture.tree_ingest = prepare_graph_payload(capture.graph, default_profile=inputs.value_profile)
    info = engine.get_build_info() if hasattr(engine, "get_build_info") else {}
    capture.build_info = info if isinstance(info, dict) else {}
    capture.source_ref = getattr(engine, "loaded_source_ref", None)
    capture.loaded_revision = getattr(engine, "loaded_revision", None)
    capture.loaded_source = getattr(engine, "loaded_source", None)
    return capture
