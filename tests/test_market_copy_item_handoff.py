"""MKT-UX-01 regression: Market "Copy Item" -> Item Check handoff guards.

PoE2 Market "Copy Item" writes full item text to the clipboard with no Ctrl+C
keystroke. ExileLens ingests it passively through the stateless
``ExternalClipboardRouter`` into the normal ``submit_clipboard_text`` Item
Check pipeline. These tests lock the handoff guards with mocks (no Qt, no PoB,
no clipboard):

- a genuine market copy is ACCEPTED for Item Check,
- the same OS sequence repeated is IGNORED_DUPLICATE (never re-evaluated),
- the same item text under a *new* sequence is ACCEPTED again (identical text
  is not duplication -- see ``clipboard_event_decision``),
- owned hotkey copies, foreign Ctrl+C copies, background-window copies, and
  non-item text are all dropped silently (no tooltip, no evaluation),
- raw clipboard content never reaches the logs (CS-001).

Downstream behavior once accepted (build readiness, PoB parse, coverage,
restore, presentation) is the ordinary Item Check pipeline and is covered by
its own suites; controller/Qt wiring is intentionally out of scope here.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from poe2value.app.external_clipboard_capture import (
    ExternalClipboardCandidate,
    ExternalClipboardDecision,
    ExternalClipboardRouter,
)
from poe2value.platform.windows.user_clipboard_copy import (
    note_foreign_ctrl_c_copy,
    reset_user_ctrl_c_copy_state,
)

pytestmark = pytest.mark.itemcheck

ITEMS = Path(__file__).resolve().parents[1] / "fixtures" / "items"


@pytest.fixture(autouse=True)
def _isolated_foreign_copy_state():
    reset_user_ctrl_c_copy_state()
    yield
    reset_user_ctrl_c_copy_state()


def _candidate(text: str, sequence: int | None) -> ExternalClipboardCandidate:
    return ExternalClipboardCandidate(
        text=text,
        sequence=sequence,
        content_hash=f"hash-{sequence}",
    )


def _evaluate(text: str, sequence: int | None, *, previous_sequence: int | None = None, **kwargs):
    router = ExternalClipboardRouter()
    return router.evaluate(
        _candidate(text, sequence),
        previous_sequence=previous_sequence,
        hotkey_owns_sequence=kwargs.get("hotkey_owns_sequence", lambda _seq: False),
        poe_foreground=kwargs.get("poe_foreground", lambda: True),
    )


def _market_ring_text() -> str:
    return (ITEMS / "core04_offense_ring.txt").read_text(encoding="utf-8")


def test_market_copy_item_is_accepted_for_item_check() -> None:
    decision, recognition = _evaluate(_market_ring_text(), 41)

    assert decision is ExternalClipboardDecision.ACCEPTED
    assert recognition is not None
    assert recognition.recognized


def test_same_sequence_repeated_is_ignored_as_duplicate() -> None:
    text = _market_ring_text()
    first, _ = _evaluate(text, 41, previous_sequence=None)
    assert first is ExternalClipboardDecision.ACCEPTED

    # The controller passes the consumed sequence back as previous_sequence;
    # the identical OS event must never start a second evaluation.
    second, recognition = _evaluate(text, 41, previous_sequence=41)
    assert second is ExternalClipboardDecision.IGNORED_DUPLICATE
    assert recognition is None


def test_same_item_under_new_sequence_is_evaluated_again() -> None:
    text = _market_ring_text()
    first, _ = _evaluate(text, 41, previous_sequence=None)
    second, recognition = _evaluate(text, 42, previous_sequence=41)

    assert first is ExternalClipboardDecision.ACCEPTED
    assert second is ExternalClipboardDecision.ACCEPTED
    assert recognition is not None and recognition.recognized


def test_owned_hotkey_copy_is_suppressed() -> None:
    decision, recognition = _evaluate(
        _market_ring_text(), 41, hotkey_owns_sequence=lambda _seq: True
    )

    assert decision is ExternalClipboardDecision.SUPPRESSED_HOTKEY
    assert recognition is None


def test_foreign_ctrl_c_copy_is_ignored() -> None:
    # Another overlay (or the player's own Ctrl+C) copied via keystroke just
    # before this clipboard event: the passive path must stay silent.
    note_foreign_ctrl_c_copy("injected-overlay")

    decision, recognition = _evaluate(_market_ring_text(), 41)

    assert decision is ExternalClipboardDecision.IGNORED_FOREIGN_CTRL_C
    assert recognition is None


def test_background_window_copy_is_ignored() -> None:
    decision, recognition = _evaluate(
        _market_ring_text(), 41, poe_foreground=lambda: False
    )

    assert decision is ExternalClipboardDecision.IGNORED_FOREGROUND
    assert recognition is None


@pytest.mark.parametrize("text", ["hello world", "", "   \n  "])
def test_non_item_text_is_ignored_silently(text: str) -> None:
    decision, recognition = _evaluate(text, 41)

    assert decision is ExternalClipboardDecision.IGNORED_NOT_ITEM
    # Returned for diagnostics only; the caller must not pop a tooltip.
    assert recognition is not None
    assert not recognition.recognized


def test_raw_clipboard_content_never_reaches_logs(caplog: pytest.LogRecord) -> None:
    text = _market_ring_text()
    probe = max(text.splitlines(), key=len)
    assert len(probe) > 20  # a real mod line, not a header

    with caplog.at_level(logging.INFO, logger="poe2value.app.external_clipboard_capture"):
        decision, _ = _evaluate(text, 41)

    assert decision is ExternalClipboardDecision.ACCEPTED
    assert probe not in caplog.text
    assert text not in caplog.text
