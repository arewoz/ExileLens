"""Deterministic stress of the Diagnostics responsive layout on ONE window instance.

Rows stack their action under the value below a width threshold. These checks assert that after any sequence of
resizes, state changes, navigation and rail mode changes the layout mode matches the available width and no geometry
is stale, overlapping or clipped.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="the dashboard harness uses Windows-only capture helpers")
_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def harness(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(_ROOT / "scripts"))
    monkeypatch.syspath_prepend(str(_ROOT))
    qa = importlib.import_module("ui_visual_qa")
    states = importlib.import_module("qa_states")
    original = os.environ.get("LOCALAPPDATA")
    instance = qa.Harness(tmp_path)
    instance.states = states.STATE_REGISTRY
    yield instance
    instance.controller.shutdown()
    instance.window.close()
    if original is None:
        os.environ.pop("LOCALAPPDATA", None)
    else:
        os.environ["LOCALAPPDATA"] = original


def _settle(h, n: int = 30) -> None:
    for _ in range(n):
        h.app.processEvents()


def _go(h, state: str | None = None, size: tuple[int, int] | None = None) -> None:
    if state:
        h.states[state](h)
    if size:
        h.window.resize(*size)
    _settle(h)


def _rows(h):
    page = h.window._diagnostics
    return page, [row for row in page._health_rows.values() if row.isVisibleTo(page)]


def _geometry(h):
    page, rows = _rows(h)
    out = []
    for row in rows:
        origin = row.mapTo(page, row.rect().topLeft())
        action = row.action_button()
        a = action.mapTo(page, action.rect().topLeft()) if action is not None and action.isVisibleTo(row) else None
        out.append((row.width(), row.height(), origin.y(), row._stacked, (a.x(), a.y(), action.width()) if a else None))
    return out, page.scroll.verticalScrollBar().isVisible() or page.scroll.verticalScrollBar().maximum() > 0, h.window._rail.width()


def check_layout(h) -> None:
    from PySide6.QtWidgets import QLabel

    from exilelens.ui import theme

    page, rows = _rows(h)
    assert rows
    for row in rows:
        needed = theme.scaled_px(row.LABEL_WIDTH) + 16 + 28 + theme.scaled_px(110) + 220
        expected = row.width() < max(row.NARROW, needed)
        assert row._stacked == expected, (row.label(), row.width(), row._stacked)
        want = "TopToBottom" if expected else "LeftToRight"
        assert row._outer.direction().name == want
        action = row.action_button()
        if action is not None and action.isVisibleTo(row):
            a = action.geometry()
            host = row._action_host.geometry()
            inside = row.rect()
            assert inside.contains(row._action_host.geometry().adjusted(0, 0, -1, -1)), "action outside the row"
            text = row._text_host.geometry()
            if expected:
                assert host.top() >= text.bottom() - 1, "stacked action overlaps the text"
            else:
                assert host.left() >= text.right() - 1, "side action overlaps the text"
            assert a.width() > 0
        for label in row.findChildren(QLabel):
            if label.isVisibleTo(row) and label.text() and label.wordWrap():
                assert label.height() >= label.heightForWidth(label.width()) - 1, f"clipped: {label.text()[:30]}"
    # every row must fit inside the page's viewport horizontally
    viewport = page.scroll.viewport().width()
    for row in rows:
        right = row.mapTo(page.scroll.viewport(), row.rect().topRight()).x()
        assert right <= viewport + 1


def _stable(h) -> None:
    """The layout must not change when given more time: nothing is stale."""
    before = _geometry(h)
    _settle(h, 60)
    assert _geometry(h) == before


HEALTHY, DEGRADED = "diagnostics-healthy", "diagnostics-degraded"
FULL, COMPACT = (980, 720), (720, 560)

SEQUENCES = {
    "A": [(HEALTHY, FULL), (DEGRADED, COMPACT), (DEGRADED, FULL), (HEALTHY, COMPACT)],
    "B": [(HEALTHY, FULL), (DEGRADED, COMPACT), (HEALTHY, FULL), (DEGRADED, COMPACT)],
    "D": [(DEGRADED, COMPACT), (HEALTHY, None), (DEGRADED, None), (HEALTHY, None), (DEGRADED, None)],
}


@pytest.mark.parametrize("name", sorted(SEQUENCES))
def test_transition_sequences_keep_the_layout_consistent(harness, name) -> None:
    steps = 0
    for _ in range(3):  # repeated passes over the same instance
        for state, size in SEQUENCES[name]:
            _go(harness, state, size)
            check_layout(harness)
            _stable(harness)
            steps += 1
    assert steps >= 12


def test_rapid_resizes_while_degraded(harness) -> None:
    _go(harness, DEGRADED, FULL)
    for _ in range(12):
        for size in (COMPACT, FULL):
            harness.window.resize(*size)  # no settling between resizes
    _settle(harness)
    check_layout(harness)
    _stable(harness)
    harness.window.resize(*COMPACT)
    _settle(harness)
    check_layout(harness)


def test_navigating_away_and_back_across_a_compact_transition(harness) -> None:
    _go(harness, DEGRADED, FULL)
    for _ in range(4):
        harness.window.navigate("settings")
        harness.window.resize(*COMPACT)
        _settle(harness)
        harness.window.navigate("diagnostics")
        _settle(harness)
        check_layout(harness)
        harness.window.navigate("overview")
        harness.window.resize(*FULL)
        _settle(harness)
        harness.window.navigate("diagnostics")
        _settle(harness)
        check_layout(harness)
    _stable(harness)


def test_rail_full_compact_full_while_degraded(harness) -> None:
    _go(harness, DEGRADED, FULL)
    widths = []
    for size in (COMPACT, FULL, COMPACT, FULL, (840, 640), (839, 640), (841, 640), COMPACT):
        _go(harness, None, size)
        check_layout(harness)
        widths.append(harness.window._rail.width())
    assert widths[0] == widths[2] == widths[-1] and widths[1] == widths[3]


def test_identical_final_state_gives_identical_geometry(harness) -> None:
    """Whatever route led there, 720x560 degraded is the same layout."""
    _go(harness, DEGRADED, COMPACT)
    reference = _geometry(harness)
    routes = [
        [(HEALTHY, FULL), (DEGRADED, COMPACT)],
        [(DEGRADED, FULL), (HEALTHY, COMPACT), (DEGRADED, COMPACT)],
        [(HEALTHY, COMPACT), (DEGRADED, FULL), (DEGRADED, COMPACT)],
    ]
    for _ in range(4):
        for route in routes:
            for state, size in route:
                _go(harness, state, size)
            assert _geometry(harness) == reference
