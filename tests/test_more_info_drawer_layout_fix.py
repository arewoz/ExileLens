"""More Info drawer whitespace bug: regression coverage.

Root cause: `DetailAnalysisDrawer._add_section_title()` used
`QLayout.addSpacing()` to add breathing room between sections. That call
inserts a raw `QSpacerItem` with no handle to remove later, but
`_clear_body()` only ever removed and deleted tracked `QWidget`s
(`self._section_widgets`) -- so every spacer added this way was orphaned in
`_line_layout` and survived every subsequent `set_content()`/`clear()`.
Across repeated Item Check results (every Shift+C, every pinned-overlay
refresh reusing the same drawer instance) they accumulated indefinitely at
the front of the layout, pushing real content further down each time --
observed in a packaged build as a large blank area above the first visible
section (e.g. VERDICT) in an otherwise-sparse result.

Fix: spacers are now small fixed-height `QWidget`s added through the same
tracked-widget path as every other section widget, so `_clear_body()`
cleans them up exactly like a label.

These tests need a real (offscreen) `QApplication` and widget geometry after
a layout pass -- there is no meaningful way to assert this purely from data
structures, since the bug was specifically about Qt layout item lifecycle,
not About the section payload. Follows the same `QT_QPA_PLATFORM=offscreen`
pattern as `public_tests/test_pob_path_state_consistency.py` and
`tests/test_p1_1c_more_info_hierarchy.py`.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from exilelens.items.more_info import build_more_info

pytestmark = pytest.mark.itemcheck


def _make_app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _block(*, dense: bool, item_name: str):
    resistances = (
        [{"element": "chaos", "state": "BELOW_CAP_WORSENED", "severity": "high", "current": 15, "candidate": 0}]
        if dense
        else []
    )
    score_contributors = [{"key": "res_flex", "contribution": -0.5}] if dense else []
    outcome = {
        "verdict": "MEANINGFUL_DOWNGRADE",
        "verdict_label": "MEANINGFUL DOWNGRADE",
        "final_score": 22.0,
        "evaluation_quality": "FULL",
        "quality_label": "",
        "verdict_reason": "Net score -28.0 against the current item.",
        "guardrails_applied": [],
        "critical_tradeoffs": [],
        "resistances": resistances,
        "all_deltas": [
            {
                "key": "primary_offense",
                "label": "Damage",
                "current": 1000,
                "candidate": 950.9,
                "percent_delta": -4.9,
                "direction": "negative",
            }
        ],
        "score_contributors": score_contributors,
        "unsupported_or_unmodeled": [],
        "evaluation_quality_reasons": [],
    }
    model = {
        "item_name": item_name,
        "impact_rows": [],
        "evaluation_outcome": outcome,
        "primary_metric": {},
        "native_damage_discovery": {},
    }
    return build_more_info(model, outcome=outcome), model


def _layout_widgets(layout):
    widgets = []
    for i in range(layout.count()):
        w = layout.itemAt(i).widget()
        if w is not None:
            widgets.append(w)
    return widgets


def _leading_orphan_spacer_run(layout) -> int:
    """Count layout items at the very front that are not widgets at all --
    the exact shape of the bug: raw QSpacerItems with no owning widget."""
    count = 0
    for i in range(layout.count()):
        if layout.itemAt(i).widget() is None:
            count += 1
        else:
            break
    return count


def test_content_starts_at_top_after_switching_from_dense_to_sparse() -> None:
    """The reported bug: Dragon Brow (dense, Advanced expanded) followed by
    Bushwhack (sparse) must not leave blank space above the first section."""
    _make_app()
    from exilelens.ui.overlay_detail_drawer import DetailAnalysisDrawer

    drawer = DetailAnalysisDrawer()
    drawer.set_target_width(350)
    drawer.show()
    drawer.resize(350, 700)

    dense_block, dense_model = _block(dense=True, item_name="Dragon Brow")
    drawer.set_content(dense_block, model=dense_model)
    if drawer._advanced_toggle is not None:
        drawer._advanced_toggle.click()

    sparse_block, sparse_model = _block(dense=False, item_name="Bushwhack, Lizardscale Boots")
    drawer.set_content(sparse_block, model=sparse_model)

    assert _leading_orphan_spacer_run(drawer._line_layout) == 0
    widgets = _layout_widgets(drawer._line_layout)
    assert widgets, "sparse result must still render its normal sections"
    assert widgets[0].geometry().y() == 0, "first content widget must sit at the very top of the drawer"


def test_repeated_dense_sparse_cycling_never_accumulates_orphaned_spacers() -> None:
    """The bug compounded with every render (every Shift+C reusing the same
    drawer instance) -- stress-cycle several results and confirm the layout
    item count stays bounded rather than growing without limit."""
    _make_app()
    from exilelens.ui.overlay_detail_drawer import DetailAnalysisDrawer

    drawer = DetailAnalysisDrawer()
    drawer.set_target_width(350)
    drawer.show()
    drawer.resize(350, 700)

    item_counts_after_sparse: list[int] = []
    for _ in range(5):
        dense_block, dense_model = _block(dense=True, item_name="Dragon Brow")
        drawer.set_content(dense_block, model=dense_model)
        if drawer._advanced_toggle is not None:
            drawer._advanced_toggle.click()

        sparse_block, sparse_model = _block(dense=False, item_name="Bushwhack, Lizardscale Boots")
        drawer.set_content(sparse_block, model=sparse_model)
        item_counts_after_sparse.append(drawer._line_layout.count())

    # Identical sparse content rendered from an identical starting sequence
    # each cycle -- the resulting item count must be constant, not growing.
    assert len(set(item_counts_after_sparse)) == 1, item_counts_after_sparse
    assert _leading_orphan_spacer_run(drawer._line_layout) == 0
    widgets = _layout_widgets(drawer._line_layout)
    assert widgets[0].geometry().y() == 0


def test_clear_body_removes_every_gap_spacer_it_added() -> None:
    """Direct unit check on the fix: every widget _add_gap() adds must be in
    the tracked widget list _clear_body() cleans up -- no bare QSpacerItem
    left for the layout to keep forever."""
    _make_app()
    from exilelens.ui.overlay_detail_drawer import DetailAnalysisDrawer

    drawer = DetailAnalysisDrawer()
    dense_block, dense_model = _block(dense=True, item_name="Dragon Brow")
    drawer.set_content(dense_block, model=dense_model)
    assert drawer._line_layout.count() > 0

    drawer._clear_body()
    assert drawer._line_layout.count() == 0, "every widget (including gap spacers) must be removed"


def test_jewel_multi_slot_result_also_starts_at_top() -> None:
    """Manual-review companion case: a 2-socket Jewel comparison after a
    dense normal result must not inherit any leftover spacer offset either."""
    _make_app()
    from exilelens.ui.overlay_detail_drawer import DetailAnalysisDrawer

    drawer = DetailAnalysisDrawer()
    drawer.set_target_width(350)
    drawer.show()
    drawer.resize(350, 700)

    dense_block, dense_model = _block(dense=True, item_name="Dragon Brow")
    drawer.set_content(dense_block, model=dense_model)
    if drawer._advanced_toggle is not None:
        drawer._advanced_toggle.click()

    def outcome_for(node_id: int, score: float) -> dict[str, object]:
        return {
            "verdict": "SIDEGRADE",
            "verdict_label": "SIDEGRADE",
            "final_score": score,
            "evaluation_quality": "FULL",
            "quality_label": "",
            "verdict_reason": f"Net score test {node_id}.",
            "guardrails_applied": [],
            "critical_tradeoffs": [],
            "resistances": [],
            "all_deltas": [],
            "score_contributors": [],
            "unsupported_or_unmodeled": [],
            "evaluation_quality_reasons": [],
            "replacement_slot": f"Jewel {node_id}",
        }

    choices = [
        {"slot": "Jewel 7960", "selected": True, "best": True, "replacing_item": "Foe Joy, Sapphire", "verdict_label": "MEANINGFUL UPGRADE", "verdict": "MEANINGFUL_UPGRADE", "final_score": 71, "evaluation_outcome": outcome_for(7960, 71)},
        {"slot": "Jewel 21984", "replacing_item": "Apocalypse Stone, Sapphire", "verdict_label": "SIDEGRADE", "verdict": "SIDEGRADE", "final_score": 50, "evaluation_outcome": outcome_for(21984, 50)},
    ]
    jewel_model = {
        "item_name": "Test Jewel",
        "replacement_choices": choices,
        "evaluation_outcome": choices[0]["evaluation_outcome"],
        "primary_metric": {},
        "native_damage_discovery": {},
    }
    jewel_block = build_more_info(jewel_model, outcome=choices[0]["evaluation_outcome"])
    jewel_block["replacement_choices"] = choices

    drawer.set_content(jewel_block, model=jewel_model)
    assert _leading_orphan_spacer_run(drawer._line_layout) == 0
    widgets = _layout_widgets(drawer._line_layout)
    assert widgets and widgets[0].geometry().y() == 0

    drawer.select_choice(1)
    assert _leading_orphan_spacer_run(drawer._line_layout) == 0
