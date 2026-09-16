"""Passive PoE2 market clipboard capture for Item Check.

External clipboard updates (e.g. PoE2 Market "Copy Item") converge on the same
``submit_clipboard_text`` pipeline as owned Shift+C capture. Invalid or
out-of-context clipboard payloads are ignored silently.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from poe2value.items.raw_input import ItemInputSource, RawItemInput
from poe2value.items.language_detect import detect_poe_item_language
from poe2value.items.recognition import RecognitionResult, recognize_input
from poe2value.platform.windows.clipboard_identity import is_duplicate_clipboard_event
from poe2value.platform.windows.foreground_info import is_poe_foreground
from poe2value.platform.windows.user_clipboard_copy import (
    last_foreign_ctrl_c_source,
    should_suppress_passive_item_clipboard,
)

logger = logging.getLogger(__name__)


class ExternalClipboardDecision(str, Enum):
    ACCEPTED = "accepted"
    IGNORED_FOREGROUND = "foreground_not_poe"
    IGNORED_NOT_ITEM = "not_item"
    IGNORED_DUPLICATE = "duplicate"
    SUPPRESSED_HOTKEY = "hotkey_owned"
    # A Ctrl+C ExileLens does not own: the player's own, or one injected by
    # another overlay (Scalpel and friends copy the hovered item with SendInput).
    IGNORED_FOREIGN_CTRL_C = "foreign_ctrl_c"
    IGNORED_PHYSICAL_CTRL_C = "foreign_ctrl_c"  # historical alias


@dataclass
class ExternalClipboardCandidate:
    text: str
    sequence: int | None
    content_hash: str
    copy_anchor_screen_px: tuple[int, int] | None = None


@dataclass(frozen=True)
class ExternalClipboardRouter:
    """Stateless guards for passive market clipboard capture."""

    def evaluate(
        self,
        candidate: ExternalClipboardCandidate,
        *,
        previous_sequence: int | None,
        hotkey_owns_sequence: Callable[[int | None], bool],
        poe_foreground: Callable[[], bool] | None = None,
    ) -> tuple[ExternalClipboardDecision, RecognitionResult | None]:
        sequence = candidate.sequence
        logger.info(
            "clipboard_update sequence=%s len=%s",
            sequence,
            len(candidate.text or ""),
        )

        if hotkey_owns_sequence(sequence):
            logger.info("clipboard_candidate suppressed reason=hotkey_owned sequence=%s", sequence)
            return ExternalClipboardDecision.SUPPRESSED_HOTKEY, None

        if should_suppress_passive_item_clipboard():
            logger.info(
                "clipboard_candidate ignored reason=foreign_ctrl_c source=%s sequence=%s",
                last_foreign_ctrl_c_source() or "unknown",
                sequence,
            )
            return ExternalClipboardDecision.IGNORED_FOREIGN_CTRL_C, None

        foreground_fn = poe_foreground or is_poe_foreground
        try:
            poe_active = bool(foreground_fn())
        except Exception:
            poe_active = False
        if not poe_active:
            logger.info("clipboard_candidate ignored reason=foreground_not_poe sequence=%s", sequence)
            return ExternalClipboardDecision.IGNORED_FOREGROUND, None

        logger.info("clipboard_candidate source=external sequence=%s", sequence)

        if is_duplicate_clipboard_event(previous_sequence, sequence):
            logger.info("clipboard_candidate ignored reason=duplicate sequence=%s", sequence)
            return ExternalClipboardDecision.IGNORED_DUPLICATE, None

        raw = RawItemInput.from_text(
            candidate.text,
            source=ItemInputSource.CLIPBOARD,
            content_hash=candidate.content_hash or None,
        )
        recognition = recognize_input(raw)
        if not recognition.recognized:
            # LANG-01 diagnostic only: passive capture still stays silent (it must not
            # pop a tooltip for arbitrary clipboard text), but a localized item copied
            # here is worth a log line so support can explain the silence.
            detection = detect_poe_item_language(candidate.text or "")
            logger.info(
                "clipboard_candidate ignored reason=not_item sequence=%s detail=%s detected_language=%s",
                sequence,
                recognition.reason,
                detection.language.value if detection.is_confident_non_english else "",
            )
            return ExternalClipboardDecision.IGNORED_NOT_ITEM, recognition

        base_type = ""
        slot_hint = ""
        for line in candidate.text.replace("\r\n", "\n").split("\n"):
            if line.startswith("Item Class:"):
                slot_hint = line.split(":", 1)[1].strip()
            elif not base_type and line.strip() and not line.startswith(("Rarity:", "Item Class:", "--------")):
                base_type = line.strip()
                break
        logger.info(
            "clipboard_item accepted base_type=%s slot=%s sequence=%s",
            base_type or "unknown",
            slot_hint or "unknown",
            sequence,
        )
        logger.info("comparison_started source=market_clipboard sequence=%s", sequence)
        return ExternalClipboardDecision.ACCEPTED, recognition
