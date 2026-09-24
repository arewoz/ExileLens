from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from exilelens.items.raw_input import DetectedFormat, RawItemInput

# PoE2 item clipboard blocks are small; character panel / bulk copies are much larger.
MAX_CLIPBOARD_CHARS = 16_384
MAX_CLIPBOARD_LINES = 80
MAX_ITEM_HEADER_COUNT = 1


class RecognitionConfidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


class ItemClassification(str, Enum):
    EQUIPMENT = "equipment"
    JEWEL = "jewel"
    FLASK = "flask"
    UNKNOWN = "unknown"
    NON_ITEM = "non_item"


@dataclass(frozen=True)
class RecognitionResult:
    recognized: bool
    confidence: RecognitionConfidence
    reason: str
    classification: ItemClassification


_URL_RE = re.compile(r"^https?://", re.I)
_POB_CODE_RE = re.compile(r"^(eN|dN)[A-Za-z0-9+/=]{20,}")
_CHAT_RE = re.compile(r"^(?:@\S+|\[\S+\]:)")


def is_probable_poe2_item(text: str) -> RecognitionResult:
    stripped = text.strip()
    if not stripped:
        return RecognitionResult(False, RecognitionConfidence.NONE, "empty input", ItemClassification.NON_ITEM)
    if len(text) > MAX_CLIPBOARD_CHARS:
        return RecognitionResult(
            False,
            RecognitionConfidence.HIGH,
            f"clipboard too large ({len(text)} chars)",
            ItemClassification.NON_ITEM,
        )
    line_count = text.count("\n") + 1
    if line_count > MAX_CLIPBOARD_LINES:
        return RecognitionResult(
            False,
            RecognitionConfidence.HIGH,
            f"too many lines ({line_count})",
            ItemClassification.NON_ITEM,
        )
    rarity_count = len(re.findall(r"(?m)^Rarity:\s*\S+", text))
    item_class_count = len(re.findall(r"(?m)^Item Class:\s*\S+", text))
    header_count = max(rarity_count, item_class_count)
    if header_count > MAX_ITEM_HEADER_COUNT:
        return RecognitionResult(
            False,
            RecognitionConfidence.HIGH,
            "multiple item headers (bulk or character panel copy)",
            ItemClassification.NON_ITEM,
        )
    if _URL_RE.match(stripped):
        return RecognitionResult(False, RecognitionConfidence.HIGH, "looks like a URL", ItemClassification.NON_ITEM)
    if _POB_CODE_RE.match(stripped):
        return RecognitionResult(False, RecognitionConfidence.HIGH, "looks like a PoB import code", ItemClassification.NON_ITEM)
    if _CHAT_RE.match(stripped):
        return RecognitionResult(False, RecognitionConfidence.HIGH, "looks like chat text", ItemClassification.NON_ITEM)
    if stripped.startswith("```") or stripped.startswith("def ") or stripped.startswith("class "):
        return RecognitionResult(False, RecognitionConfidence.MEDIUM, "looks like code", ItemClassification.NON_ITEM)

    lines = [line.strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n") if line.strip()]
    if not lines:
        return RecognitionResult(False, RecognitionConfidence.NONE, "empty input", ItemClassification.NON_ITEM)

    first = lines[0]
    if first.startswith("Item Class:"):
        return _classify_equipment(lines, "item class header present")
    if first.startswith("Rarity:"):
        rarity = first.split(":", 1)[1].strip().upper()
        if rarity not in {"NORMAL", "MAGIC", "RARE", "UNIQUE", "RELIC"}:
            return RecognitionResult(False, RecognitionConfidence.LOW, "unknown rarity label", ItemClassification.UNKNOWN)
        return _classify_equipment(lines, f"rarity header: {rarity}")

    return RecognitionResult(False, RecognitionConfidence.LOW, "missing PoE2 item headers", ItemClassification.UNKNOWN)


def recognize_input(raw: RawItemInput) -> RecognitionResult:
    return is_probable_poe2_item(raw.raw_text)


def _classify_equipment(lines: list[str], reason: str) -> RecognitionResult:
    body = "\n".join(lines).lower()
    if "flask" in body and "quality:" in body and len(lines) <= 6:
        return RecognitionResult(True, RecognitionConfidence.MEDIUM, reason, ItemClassification.FLASK)
    if any("jewel" in line.lower() for line in lines[1:4]):
        return RecognitionResult(True, RecognitionConfidence.MEDIUM, reason, ItemClassification.JEWEL)
    return RecognitionResult(True, RecognitionConfidence.HIGH, reason, ItemClassification.EQUIPMENT)
