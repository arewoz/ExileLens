"""Load TrackedTreeSource via a dedicated read-only PoB worker subprocess.

Architecture decision (Phase 5A.6D):
- Item evaluation uses the primary ``EvaluationController`` worker (mutable baseline).
- BUILD PATH / calibration anchors use ``TrackedTreeLoader`` with its own
  ``Engine(use_subprocess=True)`` subprocess.
- The tracking worker may load any build and tree set; it never shares state with
  the evaluation worker, so tracked selection cannot replace the eval baseline.
- We do not parse build XML offline: PoB supplies node coordinates and edges.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from exilelens.config import PobConfig, load_config
from exilelens.engine import Engine
from exilelens.tree.models import snapshot_from_payload
from exilelens.tree.mutations import load_tree_snapshot
from exilelens.tree.tracked_source import TrackedTreeSource


class TrackedTreeLoader:
    """Dedicated subprocess PoB session for read-only tracked tree snapshots."""

    def __init__(self, config: PobConfig | None = None) -> None:
        self.config = config or load_config()
        self._engine: Engine | None = None
        self._lock = threading.Lock()
        self._ready_path: str = ""
        self._ready_tree_set: str = ""

    def _ensure_engine(self) -> Engine:
        if self._engine is None:
            self._engine = Engine(self.config, use_subprocess=True)
            self._engine.start()
        return self._engine

    def shutdown(self) -> None:
        if self._engine is not None:
            self._engine.shutdown()
            self._engine = None
        self._ready_path = ""
        self._ready_tree_set = ""

    def list_tree_sets(self, build_path: str, *, context: str = "MAP") -> list[dict[str, Any]]:
        engine = self._ensure_engine()
        resolved = str(Path(build_path).resolve())
        with self._lock:
            # ensure_build_ready re-reads the file after a PoB save (revision-keyed).
            engine.ensure_build_ready(resolved, context=context)
            if self._ready_path != resolved or engine.last_load_reloaded:
                self._ready_path = resolved
                self._ready_tree_set = ""
            payload = engine.list_tree_sets()
        return list(payload.get("tree_sets") or [])

    def load_tracked_source(
        self,
        *,
        build_path: str,
        tree_set_id: str = "",
        context: str = "MAP",
        generation: int = 0,
    ) -> TrackedTreeSource:
        engine = self._ensure_engine()
        resolved = str(Path(build_path).resolve())
        tree_set_id = str(tree_set_id or "")
        with self._lock:
            loaded = engine.ensure_build_ready(resolved, context=context)
            if self._ready_path != resolved or engine.last_load_reloaded:
                self._ready_path = resolved
                self._ready_tree_set = ""
            sets = engine.list_tree_sets()
            active_index = str(sets.get("active_index") or "1")
            if not tree_set_id:
                tree_set_id = active_index
            if tree_set_id != self._ready_tree_set:
                engine.set_active_tree_set(tree_set_id)
                self._ready_tree_set = tree_set_id
            snapshot = load_tree_snapshot(
                engine,
                build_path=resolved,
                context=context,
                profile="BALANCED",
                generation=generation,
            )
        build_blob = loaded.get("build") if isinstance(loaded.get("build"), dict) else loaded
        build_name = str((build_blob or {}).get("build_name") or (build_blob or {}).get("name") or Path(resolved).stem)
        tree_set_name = snapshot.baseline.tree_set
        for entry in sets.get("tree_sets") or []:
            if str(entry.get("id")) == tree_set_id or str(entry.get("index")) == tree_set_id:
                tree_set_name = str(entry.get("title") or tree_set_name)
                break
        return TrackedTreeSource.from_snapshot(
            build_path=resolved,
            build_name=build_name,
            tree_set_id=tree_set_id,
            tree_set_name=tree_set_name,
            snapshot=snapshot,
            generation=generation,
        )

    def snapshot_from_payload(self, payload: dict[str, Any], *, build_path: str, generation: int) -> TrackedTreeSource:
        """Test helper: build TrackedTreeSource from a graph export dict."""
        baseline_raw = dict(payload.get("baseline") or {})
        baseline_raw.setdefault("build_path", build_path)
        baseline_raw.setdefault("generation", generation)
        from exilelens.tree.models import TreeBaseline

        fields = TreeBaseline.__dataclass_fields__
        kwargs = {key: baseline_raw.get(key) for key in fields}
        baseline = TreeBaseline(**kwargs)
        snap = snapshot_from_payload(payload, baseline=baseline)
        tree_set = payload.get("tree_set") or {}
        tree_set_id = str(tree_set.get("index") or tree_set.get("id") or "")
        tree_set_name = str(tree_set.get("title") or baseline.tree_set or "")
        return TrackedTreeSource.from_snapshot(
            build_path=build_path,
            build_name=baseline.build_name,
            tree_set_id=tree_set_id,
            tree_set_name=tree_set_name,
            snapshot=snap,
            generation=generation,
        )
