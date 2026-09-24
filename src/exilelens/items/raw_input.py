from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from exilelens.items.evaluation_identity import candidate_fingerprint


class ItemInputSource(str, Enum):
    FILE = "file"
    STDIN = "stdin"
    CLIPBOARD = "clipboard"
    TEST = "test"
    UNKNOWN = "unknown"


class DetectedFormat(str, Enum):
    POE2_CLIPBOARD = "poe2_clipboard"
    UNKNOWN = "unknown"
    EMPTY = "empty"


@dataclass(frozen=True)
class RawItemInput:
    raw_text: str
    source: ItemInputSource = ItemInputSource.UNKNOWN
    detected_format: DetectedFormat = DetectedFormat.UNKNOWN
    normalized_line_endings: bool = False
    content_hash: str = ""

    @classmethod
    def from_text(
        cls,
        raw_text: str,
        *,
        source: ItemInputSource = ItemInputSource.UNKNOWN,
        detected_format: DetectedFormat | None = None,
        content_hash: str | None = None,
    ) -> RawItemInput:
        from exilelens.items.clipboard_locale import normalize_clipboard_text

        normalized = "\r\n" in raw_text or ("\r" in raw_text and "\n" in raw_text.replace("\r\n", ""))
        text, _locale = normalize_clipboard_text(raw_text)
        if detected_format is None:
            if not text.strip():
                detected_format = DetectedFormat.EMPTY
            elif text.lstrip().startswith("Rarity:") or text.lstrip().startswith("Item Class:"):
                detected_format = DetectedFormat.POE2_CLIPBOARD
            else:
                detected_format = DetectedFormat.UNKNOWN
        if content_hash is None:
            content_hash = candidate_fingerprint(text)
        return cls(
            raw_text=text,
            source=source,
            detected_format=detected_format,
            normalized_line_endings=not normalized,
            content_hash=content_hash,
        )
