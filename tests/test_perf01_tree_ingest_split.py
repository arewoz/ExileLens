"""PERF-01: the tree view model's graph ingest is split into a pure half (run off the UI thread) and a cheap apply.

The pure half is the expensive part of a build load's UI work (snapshot rebuild, geometry, one shortest-path search
per frontier node). These tests pin that the split produces exactly the state ``ingest_graph_payload`` always did and
that staleness handling stays with the stateful half.
"""

from __future__ import annotations

import pytest

from exilelens.tree.graph import get_frontier_nodes, unallocated_costs
from exilelens.tree.models import EvalStatus, NodeType, PassiveTreeSnapshot, TreeBaseline, snapshot_from_payload
from exilelens.tree.view_model import (
    TreeCoachViewModel,
    prepare_graph_ingest,
    prepare_graph_payload,
)

pytestmark = pytest.mark.itemcheck


def _node(node_id: int, kind: str, *, allocated: bool, neighbors: list[int], x: float) -> dict:
    return {
        "id": node_id, "name": f"n{node_id}", "type": kind, "allocated": allocated, "neighbors": neighbors,
        "x": x, "y": 0.0, "support": "SUPPORTED",
    }


def _payload(*, fingerprint: str = "fp-1") -> dict:
    # class start(allocated) - small(allocated) - small - notable - notable
    return {
        "baseline": {
            "build_path": "b.xml", "build_name": "b", "loadout": "Default", "tree_set": "Default", "item_set": "1",
            "context": "MAP", "profile": "BALANCED", "generation": 4, "fingerprint": fingerprint,
            "tree_fingerprint": "tree-1",
        },
        "nodes": [
            _node(1, "CLASS_START", allocated=True, neighbors=[2], x=0.0),
            _node(2, "SMALL", allocated=True, neighbors=[1, 3], x=1.0),
            _node(3, "SMALL", allocated=False, neighbors=[2, 4], x=2.0),
            _node(4, "NOTABLE", allocated=False, neighbors=[3, 5], x=3.0),
            _node(5, "NOTABLE", allocated=False, neighbors=[4], x=4.0),
        ],
        "edges": [[1, 2], [2, 3], [3, 4], [4, 5]],
        "tree_set": {"index": 0, "title": "Default"},
    }


def test_prepare_then_apply_equals_the_state_derived_from_the_snapshot() -> None:
    payload = _payload()
    prepared = prepare_graph_payload(payload, default_profile="BALANCED")
    assert prepared is not None

    model = TreeCoachViewModel(profile="BALANCED")
    model.apply_prepared_graph(prepared)

    snapshot = prepared.snapshot
    frontier = get_frontier_nodes(snapshot)
    costs = unallocated_costs(snapshot)
    assert model.snapshot is snapshot
    assert model._frontier_ids == {int(r["node_id"]) for r in frontier}
    assert model._frontier_valid == {int(r["node_id"]) for r in frontier if r.get("status") == EvalStatus.VALID.value}
    expected3 = {n.id for n in snapshot.nodes.values() if n.type in {NodeType.NOTABLE, NodeType.KEYSTONE}
                 and not n.allocated and 0 < costs.get(n.id, 0) <= 3}
    expected5 = {n.id for n in snapshot.nodes.values() if n.type in {NodeType.NOTABLE, NodeType.KEYSTONE}
                 and not n.allocated and 0 < costs.get(n.id, 0) <= 5}
    assert model._targets3 == expected3 and expected3        # the fixture really has reachable targets
    assert model._targets5 == expected5
    assert set(model.geometry) == set(snapshot.nodes)


def test_ingest_graph_payload_is_the_same_two_steps() -> None:
    direct = TreeCoachViewModel(profile="BALANCED")
    direct.ingest_graph_payload(_payload())
    split = TreeCoachViewModel(profile="BALANCED")
    prepared = prepare_graph_payload(_payload(), default_profile="BALANCED")
    assert prepared is not None
    split.apply_prepared_graph(prepared)
    for attr in ("_frontier_ids", "_frontier_valid", "_targets3", "_targets5", "geometry", "profile"):
        assert getattr(direct, attr) == getattr(split, attr), attr
    assert direct.snapshot.baseline == split.snapshot.baseline


def test_a_payload_without_a_baseline_ingests_nothing() -> None:
    assert prepare_graph_payload({"nodes": [], "edges": []}, default_profile="BALANCED") is None
    model = TreeCoachViewModel(profile="BALANCED")
    model.ingest_graph_payload({"nodes": [], "edges": []})
    assert model.snapshot is None


def test_staleness_is_decided_by_the_apply_half_against_the_previous_snapshot() -> None:
    model = TreeCoachViewModel(profile="BALANCED")
    first = prepare_graph_payload(_payload(fingerprint="fp-1"), default_profile="BALANCED")
    assert first is not None
    model.apply_prepared_graph(first)
    model.evaluations[3] = {"node_id": 3}
    model.analyzed_scopes.add("frontier")
    model.pending_ids.add(4)

    same = prepare_graph_payload(_payload(fingerprint="fp-1"), default_profile="BALANCED")
    model.apply_prepared_graph(same)
    assert model.evaluations and model.analyzed_scopes and model.pending_ids   # same baseline: kept

    changed = prepare_graph_payload(_payload(fingerprint="fp-2"), default_profile="BALANCED")
    model.apply_prepared_graph(changed)
    assert not model.evaluations and not model.analyzed_scopes and not model.pending_ids


def test_prepare_graph_ingest_does_not_touch_any_view_model() -> None:
    baseline = TreeBaseline(
        build_path="", build_name="", loadout="", tree_set="Default", item_set="", context="MAP", profile="BALANCED",
        generation=0, fingerprint="f", tree_fingerprint="t",
    )
    snapshot = snapshot_from_payload(_payload(), baseline=baseline)
    assert isinstance(snapshot, PassiveTreeSnapshot)
    prepared = prepare_graph_ingest(snapshot)
    assert prepared.snapshot is snapshot
