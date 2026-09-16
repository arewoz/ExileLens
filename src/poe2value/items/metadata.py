from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from poe2value.items.raw_input import RawItemInput


_SECTION_BREAK = re.compile(r"^-{4,}$")
_RARITY_RE = re.compile(r"^Rarity:\s*(\w+)", re.I)
_QUALITY_RE = re.compile(r"^Quality:\s*(\d+)", re.I)
_ILVL_RE = re.compile(r"^Item Level:\s*(\d+)", re.I)
_LEVEL_REQ_RE = re.compile(r"^LevelReq:\s*(\d+)", re.I)
_IMPLICITS_RE = re.compile(r"^Implicits:\s*(\d+)", re.I)
_REQ_RE = re.compile(r"^Requirements:\s*(.+)$", re.I)


@dataclass
class LightweightItemMetadata:
    rarity: str | None = None
    name: str | None = None
    base_type: str | None = None
    category: str | None = None
    quality: int | None = None
    requirements: dict[str, Any] = field(default_factory=dict)
    ilvl: int | None = None
    identified: bool = True
    corrupted: bool = False
    raw_sections: list[list[str]] = field(default_factory=list)


def parse_lightweight_metadata(raw: RawItemInput) -> LightweightItemMetadata:
    text = raw.raw_text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    meta = LightweightItemMetadata()
    current_section: list[str] = []
    body_started = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        rarity_match = _RARITY_RE.match(stripped)
        if rarity_match:
            meta.rarity = rarity_match.group(1).upper()
            continue
        quality_match = _QUALITY_RE.match(stripped)
        if quality_match:
            meta.quality = int(quality_match.group(1))
            continue
        ilvl_match = _ILVL_RE.match(stripped)
        if ilvl_match:
            meta.ilvl = int(ilvl_match.group(1))
            continue
        level_req_match = _LEVEL_REQ_RE.match(stripped)
        if level_req_match:
            meta.requirements["level"] = int(level_req_match.group(1))
            continue
        req_match = _REQ_RE.match(stripped)
        if req_match:
            meta.requirements["text"] = req_match.group(1)
            continue
        implicits_match = _IMPLICITS_RE.match(stripped)
        if implicits_match:
            meta.requirements["implicits"] = int(implicits_match.group(1))
            continue
        if stripped.lower() == "unidentified":
            meta.identified = False
            continue
        if stripped.lower() == "corrupted":
            meta.corrupted = True
            continue
        if _SECTION_BREAK.match(stripped):
            if current_section:
                meta.raw_sections.append(current_section)
                current_section = []
            continue

        if not body_started and meta.rarity:
            if meta.name is None:
                meta.name = stripped
                continue
            if meta.base_type is None:
                meta.base_type = stripped
                meta.category = stripped
                body_started = True
                continue
        current_section.append(stripped)

    if current_section:
        meta.raw_sections.append(current_section)
    return meta
