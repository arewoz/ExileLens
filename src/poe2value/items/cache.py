from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from poe2value.items.metadata import LightweightItemMetadata, parse_lightweight_metadata
from poe2value.items.raw_input import RawItemInput
from poe2value.items.recognition import RecognitionResult, recognize_input


@dataclass
class ItemPipelineCache:
    recognition: dict[str, RecognitionResult] = field(default_factory=dict)
    metadata: dict[str, LightweightItemMetadata] = field(default_factory=dict)
    # PoB's compatible_slots are build/loadout dependent, unlike recognition.
    pob_parse: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)

    def get_recognition(self, raw: RawItemInput) -> RecognitionResult:
        if raw.content_hash not in self.recognition:
            self.recognition[raw.content_hash] = recognize_input(raw)
        return self.recognition[raw.content_hash]

    def get_metadata(self, raw: RawItemInput) -> LightweightItemMetadata:
        if raw.content_hash not in self.metadata:
            self.metadata[raw.content_hash] = parse_lightweight_metadata(raw)
        return self.metadata[raw.content_hash]

    def get_pob_parse(self, raw: RawItemInput, loader, *, build_fingerprint: str = "") -> dict[str, Any]:
        key = (raw.content_hash, build_fingerprint)
        if key not in self.pob_parse:
            self.pob_parse[key] = loader(raw.raw_text)
        return self.pob_parse[key]

    def invalidate(self) -> None:
        self.recognition.clear()
        self.metadata.clear()
        self.pob_parse.clear()
