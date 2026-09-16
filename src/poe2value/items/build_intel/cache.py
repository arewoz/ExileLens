"""Build-intelligence cache keys. Baseline reload must drop these entries."""

from __future__ import annotations

import hashlib


def _hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def decomposition_cache_key(
    *,
    slot: str,
    item_raw: str,
    profile: str,
    fingerprint: str = "",
    generation: int = 0,
) -> str:
    return "|".join(
        [
            "bdecomp",
            str(generation),
            str(fingerprint or ""),
            str(slot or ""),
            str(profile or ""),
            _hash(item_raw),
        ]
    )


def threshold_cache_key(
    *,
    fingerprint: str,
    slot: str,
    content_hash: str,
    generation: int = 0,
) -> str:
    return f"bthresh|{generation}|{fingerprint}|{slot}|{content_hash}"
