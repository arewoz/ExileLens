"""Tracked tree source for BUILD PATH overlay — separate from evaluation baseline."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from poe2value.tree.models import PassiveTreeSnapshot


def tracked_source_fingerprint(
    build_path: str,
    tree_set_id: str,
    snapshot: PassiveTreeSnapshot | None,
) -> str:
    parts = {
        "build_path": str(build_path or ""),
        "tree_set_id": str(tree_set_id or ""),
        "tree_fingerprint": snapshot.baseline.tree_fingerprint if snapshot else "",
        "generation": snapshot.baseline.generation if snapshot else 0,
    }
    blob = json.dumps(parts, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


@dataclass
class TrackedTreeSource:
    """Read-only passive tree used for BUILD PATH overlay and calibration anchors."""

    build_path: str
    build_name: str
    tree_set_id: str
    tree_set_name: str
    passive_tree_snapshot: PassiveTreeSnapshot
    source_fingerprint: str
    display_label: str

    @classmethod
    def from_snapshot(
        cls,
        *,
        build_path: str,
        build_name: str,
        tree_set_id: str,
        tree_set_name: str,
        snapshot: PassiveTreeSnapshot,
        generation: int = 0,
    ) -> TrackedTreeSource:
        snap = snapshot
        if generation and snap.baseline.generation != generation:
            from poe2value.tree.models import TreeBaseline

            baseline = TreeBaseline(
                build_path=snap.baseline.build_path,
                build_name=snap.baseline.build_name,
                loadout=snap.baseline.loadout,
                tree_set=snap.baseline.tree_set,
                item_set=snap.baseline.item_set,
                context=snap.baseline.context,
                profile=snap.baseline.profile,
                generation=generation,
                fingerprint=snap.baseline.fingerprint,
                tree_fingerprint=snap.baseline.tree_fingerprint,
            )
            snap = PassiveTreeSnapshot(baseline, snap.nodes, snap.edges, snap.tree_set)
        label_bits = [build_name or "Build"]
        if tree_set_name:
            label_bits.append(tree_set_name)
        display = " · ".join(bits for bits in label_bits if bits)
        fp = tracked_source_fingerprint(build_path, tree_set_id, snap)
        return cls(
            build_path=str(build_path),
            build_name=str(build_name or ""),
            tree_set_id=str(tree_set_id or ""),
            tree_set_name=str(tree_set_name or ""),
            passive_tree_snapshot=snap,
            source_fingerprint=fp,
            display_label=display,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "build_path": self.build_path,
            "build_name": self.build_name,
            "tree_set_id": self.tree_set_id,
            "tree_set_name": self.tree_set_name,
            "source_fingerprint": self.source_fingerprint,
            "display_label": self.display_label,
            "allocated_count": len(self.passive_tree_snapshot.allocated_ids()),
        }
